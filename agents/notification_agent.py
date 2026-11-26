"""NOTIFICATION AGENT - stores notifications and pushes them live through Socket.IO."""
from models import database_models as M
from services.notification_service import emit_to_admins, emit_to_all, emit_to_user

NAME = "NotificationAgent"


def push(user_id, message, match_id=None, link="/notifications"):
    """Save a notification (unread) and send it instantly to that user's private room."""
    n = M.add_notification(user_id, message, match_id, link)
    emit_to_user(user_id, "new_notification", {
        "id": n["id"], "message": n["message"], "link": n["link"],
        "created_at": n["created_at"], "unread": M.unread_count(user_id)})
    return n


def notify_matches(matches):
    """Tell BOTH users about each NEW possible match."""
    sent = 0
    for m in matches:
        if not m["is_new"]:
            continue
        pct = round(m["combined_score"] * 100)
        push(m["lost_user_id"], f"Possible match for your lost '{m['lost_name']}': a found item "
             f"'{m['found_name']}' is {pct}% similar.", m["match_id"], "/matches")
        push(m["found_user_id"], f"The item you found, '{m['found_name']}', may belong to the owner of a lost "
             f"'{m['lost_name']}' ({pct}% similar).", m["match_id"], "/matches")
        sent += 2
    return sent


def notify_claim_submitted(claim, match):
    push(match["found_user_id"], f"Someone submitted an ownership claim for your found item "
         f"'{match['found_name']}'. An admin will review it.", match["id"], "/claims")
    push(claim["claimant_id"], f"Your claim for '{match['found_name']}' was submitted and is waiting for admin review.",
         match["id"], "/claims")
    for admin_id in M.admin_ids():
        push(admin_id, f"New claim #{claim['id']} needs review ({match['lost_name']} / {match['found_name']}).",
             match["id"], "/admin#claims")
    emit_to_admins("admin_alert", {"message": f"New claim #{claim['id']} awaiting review"})


def notify_decision(claim, match, approved, note=""):
    if approved:
        push(match["lost_user_id"], f"Claim approved. '{match['lost_name']}' will be returned. "
             "Open Claims to see the finder's contact details.", match["id"], "/claims")
        push(match["found_user_id"], f"Claim approved for '{match['found_name']}'. Open Claims to see the owner's "
             "contact details and arrange the return.", match["id"], "/claims")
    else:
        extra = f" Reason: {note}" if note else ""
        push(claim["claimant_id"], f"Your claim for '{match['found_name']}' was rejected.{extra}",
             match["id"], "/claims")
        push(match["found_user_id"], f"The claim on your found item '{match['found_name']}' was rejected by the admin.",
             match["id"], "/claims")


def broadcast_stats():
    """Dashboard counters update on every open browser without a refresh (aggregate numbers only)."""
    emit_to_all("stats_update", M.get_stats())


def broadcast_new_report(kind, item):
    """Public summary only: no contact details, no private fields."""
    emit_to_all("new_report", {"kind": kind, "id": item["id"], "item_name": item["item_name"],
                               "category": item["category"], "location": item["location"],
                               "date": item["date"], "status": item["status"]})
