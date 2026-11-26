"""MATCHING AGENT - scores every candidate pair and stores the good ones.

Final score = weighted mix of
   text similarity   (TF-IDF + cosine similarity)
   metadata score    (category, colour, brand, date, location)
   image similarity  (OpenCV, only when both items have a photo)
"""
import os
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from agents.intake_agent import STOPWORDS, tokenize
from config import cfg
from models import database_models as M
from services import object_detection
from services.image_matching import compare_images

NAME = "MatchingAgent"


# ------------------------------------------------------------------ scoring pieces
def item_text(item):
    """Canonical text of an item (built by the Intake Agent, rebuilt here if missing)."""
    if item.get("search_text"):
        return item["search_text"]
    raw = " ".join([item.get("item_name", "")] * 2 + [item.get("category", ""), item.get("description", ""),
                                                      item.get("color", ""), item.get("brand", "")])
    return " ".join(tokenize(raw))


def text_scores(query_text, candidate_texts):
    """TF-IDF vectors for the query + all candidates, then cosine similarity query-vs-each."""
    if not candidate_texts:
        return []
    try:
        vec = TfidfVectorizer(stop_words="english", sublinear_tf=True)
        matrix = vec.fit_transform([query_text] + list(candidate_texts))
        return [float(x) for x in cosine_similarity(matrix[0:1], matrix[1:])[0]]
    except ValueError:                                # empty vocabulary (e.g. only stop-words)
        return [0.0] * len(candidate_texts)


def _tokens(text):
    return {t for t in tokenize(text) if t not in STOPWORDS}


def _overlap(a, b):
    """Overlap coefficient |A∩B| / min(|A|,|B|); None when either side is empty."""
    a, b = _tokens(a), _tokens(b)
    if not a or not b:
        return None
    return len(a & b) / min(len(a), len(b))


def _date_score(lost_date, found_date):
    try:
        gap = (datetime.strptime(found_date, "%Y-%m-%d") - datetime.strptime(lost_date, "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None
    if gap < -1:
        return 0.0                                    # found before it was lost: very unlikely
    gap = max(gap, 0)
    for limit, score in ((3, 1.0), (7, 0.8), (14, 0.6), (30, 0.3)):
        if gap <= limit:
            return score
    return 0.1


def metadata_score(lost, found):
    """Compare structured fields. Fields that are blank on either side are skipped
    and the remaining weights are re-normalised, so missing data is not punished."""
    brand_l, brand_f = (lost.get("brand") or "").lower(), (found.get("brand") or "").lower()
    brand = None
    if brand_l and brand_f:
        brand = 1.0 if brand_l == brand_f else (0.8 if brand_l in brand_f or brand_f in brand_l else 0.0)
    parts = {
        "category": 1.0 if lost.get("category") == found.get("category") else 0.0,
        "color": _overlap(lost.get("color"), found.get("color")),
        "brand": brand,
        "date": _date_score(lost.get("date"), found.get("date")),
        "location": _overlap(lost.get("location"), found.get("location")),
    }
    weights = cfg("META_WEIGHTS")
    used = {k: v for k, v in parts.items() if v is not None}
    total = sum(weights[k] for k in used)
    return sum(weights[k] * v for k, v in used.items()) / total if total else 0.0


def combine_scores(text, meta, image):
    """Weighted final score. Without an image the image weight is dropped (weights re-balanced)."""
    if image is None:
        w = cfg("WEIGHTS_NO_IMAGE")
        return w["text"] * text + w["meta"] * meta
    w = cfg("WEIGHTS_WITH_IMAGE")
    return w["text"] * text + w["meta"] * meta + w["image"] * image


def _image_path(item):
    return os.path.join(cfg("UPLOAD_FOLDER"), item["image_path"]) if item.get("image_path") else None


def score_pair(lost, found, text=None):
    """Full scoring of one lost/found pair. `text` may be passed when already computed in a batch."""
    if text is None:
        text = text_scores(item_text(lost), [item_text(found)])[0]
    meta = metadata_score(lost, found)
    dets_l = object_detection.loads(lost.get("detected_objects"))
    dets_f = object_detection.loads(found.get("detected_objects"))
    # appearance (colour + shape) of the YOLO-cropped objects, or of the whole photos when YOLO found nothing
    image = compare_images(_image_path(lost), _image_path(found),
                           object_detection.top_box(dets_l), object_detection.top_box(dets_f))
    objects = object_detection.class_agreement(dets_l, dets_f)       # None unless both photos have a detection
    if image is not None and objects is not None:
        w = cfg("YOLO_WEIGHT")
        image = (1 - w) * image + w * objects
    return {"text": round(text, 4), "meta": round(meta, 4),
            "image": None if image is None else round(image, 4), "objects": objects,
            "combined": round(combine_scores(text, meta, image), 4)}


# ------------------------------------------------------------------ main entry point
def find_matches(kind, item_id):
    """Compare the new item with every open item of the opposite type (never its own, never the
    same user's) and store every pair that reaches the threshold. Returns the stored matches."""
    item = M.get_item(kind, item_id)
    if not item:
        return []
    other_kind = "found" if kind == "lost" else "lost"
    candidates = M.list_items(other_kind, status="open", exclude_user=item["user_id"])
    if not candidates:
        return []

    texts = text_scores(item_text(item), [item_text(c) for c in candidates])
    results = []
    for cand, t in zip(candidates, texts):
        lost, found = (item, cand) if kind == "lost" else (cand, item)
        s = score_pair(lost, found, text=t)
        if s["combined"] >= cfg("MATCH_THRESHOLD"):
            results.append((lost, found, s))
    results.sort(key=lambda r: r[2]["combined"], reverse=True)

    stored = []
    for lost, found, s in results[: cfg("MAX_MATCHES_PER_REPORT")]:
        match_id, is_new = M.upsert_match(lost["id"], found["id"], s["text"], s["meta"], s["image"], s["combined"])
        stored.append({"match_id": match_id, "is_new": is_new, "lost_id": lost["id"], "found_id": found["id"],
                       "lost_user_id": lost["user_id"], "found_user_id": found["user_id"],
                       "lost_name": lost["item_name"], "found_name": found["item_name"],
                       "text_score": s["text"], "image_score": s["image"], "combined_score": s["combined"]})
    return stored
