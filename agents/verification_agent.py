"""VERIFICATION AGENT - manages ownership claims.

It asks the claimant questions, compares the answers with what the finder recorded and
produces an ADVISORY score for the admin. It never decides ownership: only an admin can approve."""
from agents.intake_agent import clean_text, tokenize, STOPWORDS
from agents.matching_agent import text_scores
from models import database_models as M

NAME = "VerificationAgent"

BASE_QUESTIONS = [
    "Describe any unique marks, scratches, stickers or damage on the item.",
    "What was inside, attached to, or stored on the item (contents, case, keychain, wallpaper, etc.)?",
    "Where exactly and roughly when did you lose it?",
]
SECRET_QUESTION = ("The finder recorded a private identifying detail. "
                   "Describe anything only the real owner would know about this item.")


def get_questions(found_item):
    """Questions shown to the claimant. The finder's secret text itself is never revealed."""
    qs = list(BASE_QUESTIONS)
    if found_item.get("secret_details"):
        qs.append(SECRET_QUESTION)
    return qs


def evaluate_answers(answers_text, found_item):
    """Return {"score": 0..1, "notes": str}. Advisory only."""
    answers_text = clean_text(answers_text, 3000)
    reference = " ".join([found_item.get("description", ""), found_item.get("location", ""),
                          found_item.get("color", ""), found_item.get("brand", "")])
    cos_ref = text_scores(" ".join(tokenize(answers_text)), [" ".join(tokenize(reference))])[0]
    secret = found_item.get("secret_details") or ""
    notes = []
    if secret:
        s_tokens = {t for t in tokenize(secret) if t not in STOPWORDS and len(t) > 2}
        a_tokens = set(tokenize(answers_text))
        overlap = len(s_tokens & a_tokens) / len(s_tokens) if s_tokens else 0.0
        score = 0.6 * overlap + 0.4 * cos_ref
        notes.append(f"{round(overlap * 100)}% of the finder's private clue words appear in the answers.")
    else:
        score = cos_ref
        notes.append("Finder gave no private clue, so answers were compared with the public description only.")
    notes.append(f"Similarity with the found-item description: {round(cos_ref * 100)}%.")
    notes.append("Advisory score only. The admin must make the final decision.")
    return {"score": round(min(1.0, score), 4), "notes": " ".join(notes)}


def submit_claim(match_id, claimant_id, answers):
    """Validate a claim request, evaluate it and store it as PENDING.
    Returns {"ok": bool, "error": str, "claim": dict, "match": dict}."""
    match = M.get_match(match_id)
    if not match:
        return {"ok": False, "error": "Match not found."}
    if match["lost_user_id"] != claimant_id:
        return {"ok": False, "error": "Only the owner who reported the lost item can claim it."}
    if match["status"] != "potential":
        return {"ok": False, "error": "This match is not open for claims."}
    if M.claim_exists(match_id, claimant_id):
        return {"ok": False, "error": "You already have an active claim for this match."}

    questions = get_questions(M.get_item("found", match["found_id"]))
    cleaned = [clean_text(a, 500) for a in answers]
    if len(cleaned) < len(questions) or sum(1 for a in cleaned if len(a) >= 3) < 2:
        return {"ok": False, "error": "Please answer at least two questions with some detail."}

    found = M.get_item("found", match["found_id"])
    packed = "\n".join(f"Q: {q}\nA: {a}" for q, a in zip(questions, cleaned))
    result = evaluate_answers(" ".join(cleaned), found)
    claim_id = M.create_claim(match_id, claimant_id, packed, result["score"], result["notes"])
    M.set_match_status(match_id, "claim_pending")
    return {"ok": True, "claim": M.get_claim(claim_id), "match": M.get_match(match_id)}


def apply_decision(claim_id, approve, note=""):
    """Record the ADMIN's decision. On approval: items + match become 'returned'."""
    claim = M.get_claim(claim_id)
    if not claim or claim["status"] != "pending":
        return {"ok": False, "error": "Claim not found or already reviewed."}
    match = M.get_match(claim["match_id"])
    M.set_claim_decision(claim_id, "approved" if approve else "rejected", note)
    if approve:
        M.finalize_return(claim["match_id"])
    else:
        M.set_match_status(claim["match_id"], "potential")
    return {"ok": True, "claim": M.get_claim(claim_id), "match": match}
