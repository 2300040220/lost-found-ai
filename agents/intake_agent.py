"""INTAKE AGENT - first agent in the pipeline.
Receives raw form data, validates it, cleans it, extracts key details and returns
structured data that the other agents can trust."""
import os
import re
from datetime import date, datetime, timedelta

from config import cfg
from services import object_detection

NAME = "IntakeAgent"

# Words that mean the same thing are mapped to one canonical word so TF-IDF can match them.
SYNONYMS = {
    "mobile": "phone", "smartphone": "phone", "cellphone": "phone", "cell": "phone",
    "iphone": "phone", "android": "phone",
    "backpack": "bag", "handbag": "bag", "satchel": "bag", "rucksack": "bag",
    "purse": "wallet", "billfold": "wallet", "cardholder": "wallet",
    "keychain": "key", "keyring": "key",
    "macbook": "laptop", "notebook": "laptop",
    "earbud": "earphone", "headphone": "earphone", "airpod": "earphone", "headset": "earphone",
    "wristwatch": "watch", "smartwatch": "watch",
    "spectacle": "glasses", "eyeglass": "glasses", "sunglass": "glasses",
}
COLOR_SYNONYMS = {"grey": "gray", "navy": "blue", "maroon": "red", "golden": "gold", "violet": "purple"}
STOPWORDS = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "with", "my", "is", "was",
             "it", "its", "near", "found", "lost", "item", "has", "had", "for", "from", "this", "that"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_text(value, max_len=1000):
    """Remove control characters, collapse spaces, trim and limit the length."""
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value or "")
    return re.sub(r"\s+", " ", value).strip()[:max_len]


def tokenize(text):
    """Lower-case words, crude plural removal, then synonym mapping."""
    tokens = []
    for tok in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        tokens.append(SYNONYMS.get(tok, tok))
    return tokens


def normalize_color(color):
    words = re.findall(r"[a-z]+", (color or "").lower())
    return " ".join(COLOR_SYNONYMS.get(w, w) for w in words)


def valid_contact(contact):
    digits = re.sub(r"\D", "", contact)
    return bool(EMAIL_RE.match(contact)) or (7 <= len(digits) <= 15 and re.fullmatch(r"[+\d\s()\-]+", contact))


def build_search_text(d):
    """One canonical text per item. The item name is repeated so it weighs more in TF-IDF."""
    parts = [d["item_name"], d["item_name"], d["category"], d["description"], d["color"], d["brand"]]
    return " ".join(tokenize(" ".join(p for p in parts if p)))


def extract_keywords(d, limit=8):
    seen, out = set(), []
    for tok in tokenize(f'{d["item_name"]} {d["description"]} {d["color"]} {d["brand"]}'):
        if tok not in STOPWORDS and len(tok) > 2 and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return ", ".join(out[:limit])


def process(kind, form, image_filename=None):
    """Validate and structure one report.
    Returns {"ok": bool, "errors": [..], "data": {..}}."""
    errors = []
    d = {
        "item_name": clean_text(form.get("item_name"), 80),
        "category": clean_text(form.get("category"), 30),
        "description": clean_text(form.get("description"), 1000),
        "location": clean_text(form.get("location"), 120),
        "color": normalize_color(clean_text(form.get("color"), 30)),
        "brand": clean_text(form.get("brand"), 40),
        "contact": clean_text(form.get("contact"), 80),
        "image_path": image_filename,
        "secret_details": clean_text(form.get("secret_details"), 300) if kind == "found" else "",
    }
    if len(d["item_name"]) < 2:
        errors.append("Item name is required (at least 2 characters).")
    if d["category"] not in cfg("CATEGORIES"):
        errors.append("Please choose a valid category.")
    if len(d["description"]) < 10:
        errors.append("Description must be at least 10 characters so the AI has enough to compare.")
    if len(d["location"]) < 2:
        errors.append("Location is required.")
    if not valid_contact(d["contact"]):
        errors.append("Contact must be a valid email address or phone number.")

    raw_date = clean_text(form.get("date"), 10)
    try:
        parsed = datetime.strptime(raw_date, "%Y-%m-%d").date()
        if parsed > date.today():
            errors.append("The date cannot be in the future.")
        elif parsed < date.today() - timedelta(days=730):
            errors.append("The date is more than two years ago.")
        d["date"] = parsed.isoformat()
    except ValueError:
        errors.append("Please enter a valid date.")
        d["date"] = ""

    if errors:
        return {"ok": False, "errors": errors, "data": d, "hints": []}
    d["search_text"] = build_search_text(d)
    d["keywords"] = extract_keywords(d)

    # YOLO: what is in the photo? (skipped automatically when no photo or no model file)
    hints = []
    dets = object_detection.detect(os.path.join(cfg("UPLOAD_FOLDER"), image_filename)) if image_filename else []
    d["detected_objects"] = object_detection.dumps(dets)
    suggested = object_detection.category_hint(dets)
    if suggested and suggested != d["category"]:
        hints.append(f"The AI spotted a {dets[0]['label']} in your photo, which usually belongs to the "
                     f"'{suggested}' category, but you chose '{d['category']}'. Please double-check.")
    return {"ok": True, "errors": [], "data": d, "hints": hints}
