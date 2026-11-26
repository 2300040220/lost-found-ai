"""Tests for YOLO integration (decoder, fallback, scoring effect) and production/hosting settings.
Real YOLO inference needs the ONNX weights, so here the model output is simulated."""
import os
import sqlite3
import tempfile
import unittest

import numpy as np

from tests.helpers import make_image
from tests.test_routes import AppTestCase, found_form, lost_form

import app as app_module
import config
from agents import intake_agent
from agents.matching_agent import score_pair
from database import init_db
from services import object_detection as od
from services.image_matching import crop_to_box

PHONE, UMBRELLA, PERSON = od.COCO_CLASSES.index("cell phone"), od.COCO_CLASSES.index("umbrella"), 0


def fake_output(rows):
    """Build a YOLOv8-style tensor (1, 84, N) from (cx, cy, w, h, class_id, conf) rows."""
    t = np.zeros((1, 84, len(rows)), dtype=np.float32)
    for i, (cx, cy, w, h, cid, conf) in enumerate(rows):
        t[0, 0:4, i] = (cx, cy, w, h)
        t[0, 4 + cid, i] = conf
    return t


class TestDecoder(unittest.TestCase):
    def test_decode_maps_boxes_back_to_original_pixels(self):
        # original photo 1280x720 -> letterbox ratio 0.5, vertical padding 140
        out = fake_output([(320, 320, 100, 200, PHONE, 0.90),      # real phone
                           (322, 321, 100, 200, PHONE, 0.80),      # duplicate box (removed by NMS)
                           (100, 100, 50, 50, PERSON, 0.95),       # people are ignored
                           (500, 500, 40, 40, UMBRELLA, 0.10)])    # below confidence threshold
        dets = od.decode(out, ratio=0.5, pad_x=0, pad_y=140, orig_w=1280, orig_h=720)
        self.assertEqual(len(dets), 1)
        self.assertEqual(dets[0]["label"], "cell phone")
        self.assertEqual(dets[0]["box"], [540, 160, 740, 560])
        self.assertAlmostEqual(dets[0]["conf"], 0.9, places=2)

    def test_decode_accepts_transposed_tensor_and_bad_shapes(self):
        out = fake_output([(320, 320, 100, 200, PHONE, 0.9)])[0].T[None]       # (1, N, 84)
        self.assertEqual(len(od.decode(out, 1.0, 0, 0, 640, 640)), 1)
        self.assertEqual(od.decode(np.zeros((1, 10, 10)), 1.0, 0, 0, 640, 640), [])
        self.assertEqual(od.decode(np.zeros((1, 84, 5)), 1.0, 0, 0, 640, 640), [])   # nothing confident

    def test_letterbox_is_square(self):
        canvas, ratio, px, py = od.letterbox(np.zeros((720, 1280, 3), np.uint8), 640)
        self.assertEqual(canvas.shape, (640, 640, 3)); self.assertEqual((ratio, px, py), (0.5, 0, 140))


class TestFallbackAndHelpers(unittest.TestCase):
    def test_detect_returns_empty_without_model_or_when_disabled(self):
        self.assertEqual(od.detect("whatever.jpg"), [])
        old = (config.Config.YOLO_MODEL_PATH, config.Config.YOLO_ENABLED)
        config.Config.YOLO_MODEL_PATH, config.Config.YOLO_ENABLED = __file__, False     # file exists but disabled
        try:
            self.assertFalse(od.available()); self.assertEqual(od.detect(__file__), [])
        finally:
            config.Config.YOLO_MODEL_PATH, config.Config.YOLO_ENABLED = old

    def test_helpers(self):
        a = [{"label": "cell phone", "conf": 0.9, "box": [0, 0, 50, 50]}]
        b = [{"label": "cell phone", "conf": 0.7, "box": [0, 0, 60, 60]}]
        c = [{"label": "umbrella", "conf": 0.8, "box": [0, 0, 60, 60]}]
        d = [{"label": "umbrella", "conf": 0.6, "box": [0, 0, 5, 5]}, {"label": "cell phone", "conf": 0.5, "box": [0, 0, 5, 5]}]
        self.assertEqual((od.class_agreement(a, b), od.class_agreement(a, c), od.class_agreement(a, d)), (1.0, 0.0, 0.5))
        self.assertIsNone(od.class_agreement(a, []))
        self.assertEqual(od.category_hint(a), "Phone"); self.assertIsNone(od.category_hint([]))
        self.assertEqual(od.labels_text(od.dumps(a)), "cell phone 90%")
        self.assertEqual(od.loads("not json"), []); self.assertEqual(od.loads(None), [])

    def test_crop_to_box(self):
        img = np.zeros((200, 300, 3), np.uint8)
        self.assertEqual(crop_to_box(img, [50, 50, 150, 150]).shape[:2], (110, 110))   # 5 % margin each side
        self.assertEqual(crop_to_box(img, [50, 50, 60, 60]).shape[:2], (200, 300))     # tiny box ignored
        self.assertEqual(crop_to_box(img, None).shape[:2], (200, 300))


class TestScoringEffect(unittest.TestCase):
    def test_same_object_class_raises_image_score(self):
        d = tempfile.mkdtemp()
        make_image(os.path.join(d, "a.png"), (30, 30, 30), seed=1); make_image(os.path.join(d, "b.png"), (30, 30, 30), seed=1, noise=6)
        config.Config.UPLOAD_FOLDER, old = d, config.Config.UPLOAD_FOLDER
        try:
            box = [20, 20, 200, 200]
            mk = lambda img, label: {"item_name": "x", "category": "Phone", "description": "phone", "color": "", "brand": "",
                                     "location": "a", "date": "2026-11-10", "image_path": img,
                                     "search_text": "phone", "detected_objects": od.dumps([{"label": label, "conf": .9, "box": box}])}
            same = score_pair(mk("a.png", "cell phone"), mk("b.png", "cell phone"))
            different = score_pair(mk("a.png", "cell phone"), mk("b.png", "umbrella"))
        finally:
            config.Config.UPLOAD_FOLDER = old
        self.assertEqual((same["objects"], different["objects"]), (1.0, 0.0))
        self.assertGreater(same["image"], different["image"])
        self.assertGreater(same["combined"], different["combined"])


class TestIntakeAndWorkflowWithYolo(AppTestCase):
    def setUp(self):
        super().setUp()
        self._orig = od.detect
        od.detect = lambda path: [{"label": "cell phone", "conf": 0.88, "box": [10, 10, 200, 200]}]   # simulated YOLO

    def tearDown(self):
        od.detect = self._orig

    def test_intake_stores_detections_and_hints_category_mismatch(self):
        r = intake_agent.process("lost", lost_form(category="Wallet"), "photo.png")
        self.assertTrue(r["ok"]); self.assertIn("cell phone", r["data"]["detected_objects"])
        self.assertEqual(len(r["hints"]), 1); self.assertIn("Phone", r["hints"][0])
        self.assertEqual(intake_agent.process("lost", lost_form(), "photo.png")["hints"], [])     # category fits
        self.assertEqual(intake_agent.process("lost", lost_form())["data"]["detected_objects"], "[]")  # no photo

    def test_report_flow_shows_hint_and_yolo_on_match_card(self):
        self.setup_users()
        a = make_image(os.path.join(self.tmp, "a.png"), (30, 30, 30), seed=1)
        self.report(self.alice, "lost", lost_form(category="Wallet"), a)
        self.assertIn(b"double-check", self.alice.get("/matches").data)                   # hint was flashed
        self.report(self.bob, "found", found_form(category="Wallet"), make_image(os.path.join(self.tmp, "b.png"), (30, 30, 30), seed=1, noise=6))
        html = self.alice.get("/matches").data
        self.assertIn(b"YOLO sees", html); self.assertIn(b"cell phone 88%", html)
        self.assertIn("YOLO saw", self.admin.get("/admin").data.decode())                 # visible in the agent log


class TestMigrationAndHosting(unittest.TestCase):
    def test_old_database_gets_new_column(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE lost_items (id INTEGER PRIMARY KEY, user_id INTEGER, item_name TEXT, category TEXT, description TEXT,"
                    " lost_date TEXT, location TEXT, color TEXT, brand TEXT, image_path TEXT, contact TEXT, search_text TEXT,"
                    " keywords TEXT, status TEXT DEFAULT 'open', created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        con.commit(); con.close()
        old, config.Config.DATABASE = config.Config.DATABASE, path
        try:
            init_db()
            cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(lost_items)")}
            cols2 = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(found_items)")}
        finally:
            config.Config.DATABASE = old
        self.assertIn("detected_objects", cols); self.assertIn("detected_objects", cols2)

    def test_production_refuses_default_secrets_and_serves_health(self):
        tmp = tempfile.mkdtemp()
        base = {"PRODUCTION": True, "DATABASE": os.path.join(tmp, "p.db"), "UPLOAD_FOLDER": os.path.join(tmp, "u")}
        with self.assertRaises(RuntimeError):
            app_module.create_app(base)                                    # default secret + default admin password
        app = app_module.create_app(base | {"SECRET_KEY": "k" * 40, "ADMIN_PASSWORD": "Str0ng!Passw0rd"})
        r = app.test_client().get("/healthz")
        self.assertEqual((r.status_code, r.get_json()["status"]), (200, "ok"))
        self.assertIn("Strict-Transport-Security", r.headers)
        config.Config.DATABASE = app.config["DATABASE"]                    # keep later tests consistent


if __name__ == "__main__":
    unittest.main()
