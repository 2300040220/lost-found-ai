"""End-to-end tests of the 12 required scenarios using Flask's test client.
Run:  python -m unittest discover -v"""
import io
import os
import tempfile
import unittest

from tests.helpers import make_image  # noqa: F401  (sets sys.path / env first)

import app as app_module
from models import database_models as M
from services.notification_service import socketio


def lost_form(**kw):
    d = {"item_name": "Black Samsung phone", "category": "Phone", "color": "black", "brand": "Samsung",
         "description": "Black Samsung mobile with a cracked screen and blue case, lock screen shows a dog",
         "date": "2026-11-20", "location": "Central library", "contact": "owner@example.com"}
    d.update(kw)
    return d


def found_form(**kw):
    d = {"item_name": "Samsung mobile", "category": "Phone", "color": "black", "brand": "Samsung",
         "description": "Found a black Samsung phone with cracked screen near the library",
         "date": "2026-11-21", "location": "Library entrance", "contact": "finder@example.com",
         "secret_details": "lock screen photo of a golden retriever dog"}
    d.update(kw)
    return d


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = app_module.create_app({"DATABASE": os.path.join(self.tmp, "t.db"),
                                          "UPLOAD_FOLDER": os.path.join(self.tmp, "up"), "TESTING": True})
        import config  # make agents (which fall back to Config outside requests) use the same temp paths
        config.Config.DATABASE = self.app.config["DATABASE"]
        config.Config.UPLOAD_FOLDER = self.app.config["UPLOAD_FOLDER"]
        self.events = []                                   # record every real-time push
        socketio.emit = lambda event, payload=None, **kw: self.events.append((event, payload, kw.get("to")))
        self.alice, self.bob, self.admin = self.app.test_client(), self.app.test_client(), self.app.test_client()

    # ---- helpers
    def token(self, c):
        with c.session_transaction() as s:
            if "_csrf" not in s:
                c.get("/login")
        with c.session_transaction() as s:
            return s["_csrf"]

    def post(self, c, url, data=None, **kw):
        data = dict(data or {})
        data["_csrf"] = self.token(c)
        return c.post(url, data=data, **kw)

    def register(self, c, name, email, pw="Passw0rd1"):
        return self.post(c, "/register", {"name": name, "email": email, "password": pw, "confirm": pw})

    def login(self, c, email, pw="Passw0rd1"):
        return self.post(c, "/login", {"email": email, "password": pw})

    def user_id(self, email):
        with self.app.app_context():
            return M.get_user_by_email(email)["id"]

    def setup_users(self):
        self.register(self.alice, "Alice", "alice@example.com"); self.login(self.alice, "alice@example.com")
        self.register(self.bob, "Bob", "bob@example.com"); self.login(self.bob, "bob@example.com")
        self.login(self.admin, "admin@lostfound.local", "Admin@123")

    def report(self, c, kind, form, image=None):
        form = dict(form)
        if image:
            form["image"] = (open(image, "rb"), os.path.basename(image))
        return self.post(c, f"/report/{kind}", form, content_type="multipart/form-data")


class TestAuth(AppTestCase):
    def test_01_register_and_login(self):                      # scenario 1
        r = self.register(self.alice, "Alice", "alice@example.com")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.register(self.alice, "Alice", "alice@example.com").status_code, 400)  # duplicate
        self.assertEqual(self.register(self.alice, "X", "bad", "short").status_code, 400)
        self.assertEqual(self.login(self.alice, "alice@example.com", "wrong").status_code, 401)
        r = self.login(self.alice, "alice@example.com")
        self.assertEqual(r.status_code, 302); self.assertTrue(r.location.endswith("/dashboard"))
        self.assertEqual(self.alice.get("/dashboard").status_code, 200)
        self.post(self.alice, "/logout")
        self.assertEqual(self.alice.get("/dashboard").status_code, 302)

    def test_password_is_hashed(self):
        self.register(self.alice, "Alice", "alice@example.com")
        with self.app.app_context():
            h = M.get_user_by_email("alice@example.com")["password_hash"]
        self.assertNotIn("Passw0rd1", h)

    def test_csrf_required(self):
        self.assertEqual(self.alice.post("/login", data={"email": "a@b.com", "password": "x"}).status_code, 400)


class TestWorkflow(AppTestCase):
    def test_02_03_report_lost_and_found(self):                # scenarios 2, 3
        self.setup_users()
        r = self.report(self.alice, "lost", lost_form())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.report(self.alice, "lost", lost_form(description="x")).status_code, 400)  # invalid
        r = self.report(self.bob, "found", found_form())
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            s = M.get_stats()
        self.assertEqual((s["total_lost"], s["total_found"]), (1, 1))

    def test_04_image_upload_validation(self):                 # scenario 4
        self.setup_users()
        img = make_image(os.path.join(self.tmp, "ok.png"), (30, 30, 30))
        self.assertEqual(self.report(self.alice, "lost", lost_form(), img).status_code, 302)
        self.assertEqual(len(os.listdir(self.app.config["UPLOAD_FOLDER"])), 1)
        bad_ext = self.post(self.alice, "/report/lost", dict(lost_form(), image=(io.BytesIO(b"MZ"), "virus.exe")),
                            content_type="multipart/form-data")
        self.assertEqual(bad_ext.status_code, 400)
        fake = self.post(self.alice, "/report/lost", dict(lost_form(), image=(io.BytesIO(b"not an image"), "fake.jpg")),
                         content_type="multipart/form-data")
        self.assertEqual(fake.status_code, 400)                # text renamed .jpg is rejected
        path_trick = self.post(self.alice, "/report/lost", dict(lost_form(), image=(io.BytesIO(b"x"), "../../evil.png")),
                               content_type="multipart/form-data")
        self.assertEqual(path_trick.status_code, 400)
        self.assertEqual(len(os.listdir(self.app.config["UPLOAD_FOLDER"])), 1)   # nothing extra was stored

    def test_05_to_08_matching_and_realtime(self):             # scenarios 5, 6, 7, 8
        self.setup_users()
        a = make_image(os.path.join(self.tmp, "a.png"), (30, 30, 30), seed=1)
        a2 = make_image(os.path.join(self.tmp, "a2.png"), (30, 30, 30), seed=1, noise=6)
        self.report(self.alice, "lost", lost_form(), a)
        self.report(self.bob, "found", found_form(), a2)
        with self.app.app_context():
            ms = M.list_matches_admin()
        self.assertEqual(len(ms), 1)
        m = ms[0]
        self.assertGreater(m["text_score"], 0.5)               # 5 text
        self.assertGreater(m["image_score"], 0.7)              # 6 image
        expected = 0.45 * m["text_score"] + 0.25 * m["meta_score"] + 0.30 * m["image_score"]
        self.assertAlmostEqual(m["combined_score"], expected, delta=0.002)   # 7 combined
        rooms = {(e, to) for e, _, to in self.events}
        self.assertIn(("new_notification", f"user_{self.user_id('alice@example.com')}"), rooms)   # 8 both users
        self.assertIn(("new_notification", f"user_{self.user_id('bob@example.com')}"), rooms)
        self.assertIn("stats_update", {e for e, _, _ in self.events})
        self.assertIn("new_report", {e for e, _, _ in self.events})
        n = self.alice.get("/api/notifications").get_json()
        self.assertEqual(n["unread"], 1)
        self.post(self.alice, "/notifications/read")
        self.assertEqual(self.alice.get("/api/notifications").get_json()["unread"], 0)

    def test_no_self_match_and_dissimilar_items(self):
        self.setup_users()
        self.report(self.alice, "lost", lost_form())
        self.report(self.alice, "found", found_form())          # same user's own found item: must not match
        self.report(self.bob, "found", found_form(item_name="Red umbrella", category="Others", color="red",
                                                   brand="", description="Big red folding umbrella in canteen",
                                                   location="Canteen"))
        with self.app.app_context():
            self.assertEqual(M.list_matches_admin(), [])

    def test_09_to_12_claim_approval_return_and_privacy(self):  # scenarios 9, 10, 11 + privacy
        self.setup_users()
        self.report(self.alice, "lost", lost_form()); self.report(self.bob, "found", found_form())
        with self.app.app_context():
            mid = M.list_matches_admin()[0]["id"]
        # the finder cannot claim; only the owner can
        self.assertEqual(self.bob.get(f"/matches/{mid}/claim").status_code, 404)
        page = self.alice.get(f"/matches/{mid}/claim")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"golden retriever", page.data)         # finder's secret never shown
        answers = {"answer_0": "cracked screen top left", "answer_1": "blue case and a dog photo on lock screen",
                   "answer_2": "library on Friday", "answer_3": "lock screen photo of a golden retriever dog"}
        r = self.post(self.alice, f"/matches/{mid}/claim", answers)
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            claim = M.claim_rows(is_admin=True)[0]
        self.assertEqual(claim["status"], "pending")             # 9: never auto-approved
        self.assertGreater(claim["verification_score"], 0.4)
        self.assertEqual(self.post(self.alice, f"/matches/{mid}/claim", answers).status_code, 400)  # no 2nd claim while one is pending
        # privacy: no contact details before approval
        for c in (self.alice, self.bob):
            html = c.get("/claims").data
            self.assertNotIn(b"owner@example.com", html); self.assertNotIn(b"finder@example.com", html)
        self.assertNotIn(b"golden retriever", self.bob.get("/claims").data)       # secret/answers hidden from finder's page
        self.assertNotIn(b"golden retriever", self.bob.get("/matches").data)
        self.assertNotIn(b"golden retriever", self.alice.get("/matches").data)
        self.assertEqual(self.bob.get("/claims").data.count(b"cracked screen top left"), 0)  # finder can't read answers
        # 10: admin approves
        r = self.post(self.admin, f"/admin/claims/{claim['id']}/approve")
        self.assertEqual(r.status_code, 302)
        with self.app.app_context():
            self.assertEqual(M.get_claim(claim["id"])["status"], "approved")
            s = M.get_stats()
            self.assertEqual(M.get_item("lost", 1)["status"], "returned")      # 11
            self.assertEqual(M.get_item("found", 1)["status"], "returned")
        self.assertEqual((s["returned_items"], s["potential_matches"]), (1, 0))
        # contacts released to both parties after approval
        self.assertIn(b"finder@example.com", self.alice.get("/claims").data)
        self.assertIn(b"owner@example.com", self.bob.get("/claims").data)
        self.assertIn("stats_update", {e for e, _, _ in self.events})

    def test_admin_reject_reopens_match(self):
        self.setup_users()
        self.report(self.alice, "lost", lost_form()); self.report(self.bob, "found", found_form())
        with self.app.app_context():
            mid = M.list_matches_admin()[0]["id"]
        self.post(self.alice, f"/matches/{mid}/claim", {"answer_0": "scratch", "answer_1": "nothing much", "answer_2": "somewhere", "answer_3": "unknown"})
        with self.app.app_context():
            cid = M.claim_rows(is_admin=True)[0]["id"]
        self.post(self.admin, f"/admin/claims/{cid}/reject", {"note": "Answers do not match"})
        with self.app.app_context():
            self.assertEqual(M.get_claim(cid)["status"], "rejected")
            self.assertEqual(M.get_match(mid)["status"], "potential")
            self.assertEqual(M.get_item("lost", 1)["status"], "open")

    def test_admin_mark_returned_and_remove_report(self):
        self.setup_users()
        self.report(self.alice, "lost", lost_form()); self.report(self.bob, "found", found_form())
        with self.app.app_context():
            mid = M.list_matches_admin()[0]["id"]
        self.post(self.admin, f"/admin/matches/{mid}/return")
        with self.app.app_context():
            self.assertEqual(M.get_stats()["returned_items"], 1)
        self.post(self.admin, "/admin/items/lost/1/delete")
        with self.app.app_context():
            self.assertEqual(M.get_stats()["total_lost"], 0)
            self.assertEqual(M.list_matches_admin(), [])         # cascade removed the match


class TestAccessControl(AppTestCase):
    def test_12_unauthorized_access(self):                      # scenario 12
        self.setup_users()
        for url in ("/dashboard", "/matches", "/claims", "/notifications", "/admin", "/report/lost"):
            r = self.app.test_client().get(url)
            self.assertEqual(r.status_code, 302, url)            # anonymous -> login
            self.assertIn("/login", r.location)
        self.assertEqual(self.app.test_client().get("/api/stats").status_code, 401)
        self.assertEqual(self.alice.get("/admin").status_code, 403)    # normal user -> forbidden
        self.assertEqual(self.post(self.alice, "/admin/claims/1/approve").status_code, 403)
        self.assertEqual(self.post(self.alice, "/admin/items/lost/1/delete").status_code, 403)
        self.assertEqual(self.app.test_client().get("/uploads/x.png").status_code, 302)
        self.assertEqual(self.admin.get("/admin").status_code, 200)    # admin allowed


if __name__ == "__main__":
    unittest.main()
