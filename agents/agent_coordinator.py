"""AGENT COORDINATOR - the central brain that connects the four agents.

Agents never call each other directly. Each agent receives data from the coordinator, returns a
result, and the coordinator passes that result to the next agent (a "hub-and-spoke" design).
Every hand-over is written to the agent_logs table so the workflow can be inspected in the admin panel."""
from agents import intake_agent, matching_agent, notification_agent, verification_agent
from models import database_models as M
from services import object_detection


class AgentCoordinator:
    @staticmethod
    def _log(agent, action, detail=""):
        M.log_agent(agent, action, detail)

    # ---------------------------------------------------------- new lost / found report
    def process_new_report(self, kind, user_id, form, image_filename=None):
        """Workflow: Intake -> save -> Matching -> Notification -> live dashboard update."""
        # 1. Intake Agent validates and structures the raw form
        intake = intake_agent.process(kind, form, image_filename)
        if not intake["ok"]:
            self._log(intake_agent.NAME, "rejected", "; ".join(intake["errors"]))
            return {"ok": False, "errors": intake["errors"]}
        seen = object_detection.labels_text(intake["data"].get("detected_objects"))
        self._log(intake_agent.NAME, "validated", f"{kind} report '{intake['data']['item_name']}'"
                  + (f" | YOLO saw: {seen}" if seen else ""))

        # 2. Coordinator saves the structured report
        item_id = M.insert_item(kind, user_id, intake["data"])
        item = M.get_item(kind, item_id)

        # 3. Matching Agent searches opposite-type items and stores scores
        matches = matching_agent.find_matches(kind, item_id)
        self._log(matching_agent.NAME, "searched", f"{kind} #{item_id}: {len(matches)} possible match(es)")

        # 4. Notification Agent informs both users of every NEW match
        sent = notification_agent.notify_matches(matches)
        self._log(notification_agent.NAME, "notified", f"{sent} notification(s) sent")

        # 5. Live dashboard: everyone's counters + recent-reports table update without refresh
        notification_agent.broadcast_new_report(kind, item)
        notification_agent.broadcast_stats()
        return {"ok": True, "item_id": item_id, "matches": matches, "hints": intake["hints"]}

    # ---------------------------------------------------------- ownership claim
    def submit_claim(self, match_id, claimant_id, answers):
        result = verification_agent.submit_claim(match_id, claimant_id, answers)
        if not result["ok"]:
            return result
        self._log(verification_agent.NAME, "claim_created",
                  f"claim #{result['claim']['id']} advisory score {result['claim']['verification_score']}")
        notification_agent.notify_claim_submitted(result["claim"], result["match"])
        self._log(notification_agent.NAME, "notified", "finder, claimant and admins")
        notification_agent.broadcast_stats()
        return result

    def decide_claim(self, claim_id, admin_id, approve, note=""):
        """Only an admin triggers this. The Verification Agent applies it, then users are told."""
        result = verification_agent.apply_decision(claim_id, approve, note)
        if not result["ok"]:
            return result
        verb = "approved" if approve else "rejected"
        self._log(verification_agent.NAME, f"claim_{verb}", f"claim #{claim_id} by admin #{admin_id}")
        notification_agent.notify_decision(result["claim"], result["match"], approve, note)
        notification_agent.broadcast_stats()
        return result

    def mark_returned(self, match_id, admin_id):
        """Admin override: mark a match as returned without a claim."""
        match = M.get_match(match_id)
        if not match or match["status"] == "returned":
            return {"ok": False, "error": "Match not found or already returned."}
        M.finalize_return(match_id)
        self._log("Admin", "marked_returned", f"match #{match_id} by admin #{admin_id}")
        for uid in {match["lost_user_id"], match["found_user_id"]}:
            notification_agent.push(uid, f"'{match['lost_name']}' was marked as returned by an admin.",
                                    match_id, "/matches")
        notification_agent.broadcast_stats()
        return {"ok": True}


coordinator = AgentCoordinator()
