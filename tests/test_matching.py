"""Unit tests for the AI core: text, metadata, image and combined scoring.
Run:  python -m unittest discover -v"""
import os
import tempfile
import unittest

from tests.helpers import make_image  # noqa: F401  (also sets sys.path / env)

from agents import intake_agent
from agents.matching_agent import combine_scores, metadata_score, score_pair, text_scores, item_text
from services.image_matching import compare_images

# ---- sample test data (also described in README) --------------------------------------
LOST_PHONE = {"item_name": "Black Samsung phone", "category": "Phone", "color": "black", "brand": "Samsung",
              "description": "Black Samsung mobile with a cracked screen and blue case",
              "location": "Central library", "date": "2026-11-10", "image_path": None}
FOUND_PHONE = {"item_name": "Samsung mobile", "category": "Phone", "color": "black", "brand": "Samsung",
               "description": "Found a black Samsung phone with cracked screen near the library",
               "location": "Library entrance", "date": "2026-11-11", "image_path": None}
FOUND_UMBRELLA = {"item_name": "Red umbrella", "category": "Others", "color": "red", "brand": "",
                  "description": "Large red folding umbrella left in the canteen",
                  "location": "Canteen", "date": "2026-11-11", "image_path": None}


def prep(item):
    item = dict(item)
    item["search_text"] = intake_agent.build_search_text(item)
    return item


class TestTextMatching(unittest.TestCase):
    def test_similar_items_score_high(self):
        s = score_pair(prep(LOST_PHONE), prep(FOUND_PHONE))
        self.assertGreater(s["text"], 0.5)
        self.assertGreaterEqual(s["combined"], 0.7)

    def test_different_items_score_low(self):
        s = score_pair(prep(LOST_PHONE), prep(FOUND_UMBRELLA))
        self.assertLess(s["combined"], 0.4)

    def test_synonyms_help_matching(self):
        self.assertIn("phone", item_text(prep(FOUND_PHONE)).split())
        self.assertEqual(intake_agent.tokenize("Mobile Phones"), ["phone", "phone"])

    def test_empty_candidates_and_empty_vocabulary(self):
        self.assertEqual(text_scores("phone", []), [])
        self.assertEqual(text_scores("the and of", ["the or of"]), [0.0])


class TestMetadataAndCombined(unittest.TestCase):
    def test_metadata_uses_all_fields(self):
        self.assertGreater(metadata_score(prep(LOST_PHONE) | {"date": "2026-11-10"}, prep(FOUND_PHONE) | {"date": "2026-11-11"}), 0.8)
        self.assertLess(metadata_score(prep(LOST_PHONE), prep(FOUND_UMBRELLA)), 0.3)

    def test_found_before_lost_is_penalised(self):
        early = prep(FOUND_PHONE) | {"date": "2026-10-01"}
        self.assertLess(metadata_score(prep(LOST_PHONE), early), metadata_score(prep(LOST_PHONE), prep(FOUND_PHONE)))

    def test_combined_formula(self):
        # with image: 0.45*text + 0.25*meta + 0.30*image
        self.assertAlmostEqual(combine_scores(0.8, 0.6, 0.5), 0.45 * 0.8 + 0.25 * 0.6 + 0.30 * 0.5)
        # without image: 0.60*text + 0.40*meta
        self.assertAlmostEqual(combine_scores(0.8, 0.6, None), 0.6 * 0.8 + 0.4 * 0.6)


class TestImageMatching(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        p = lambda n: os.path.join(self.dir, n)
        self.a = make_image(p("a.png"), (30, 30, 30), seed=1)
        self.a_copy = make_image(p("a2.png"), (30, 30, 30), seed=1, noise=6)   # same item, slightly different photo
        self.b = make_image(p("b.png"), (40, 200, 230), seed=9)               # different colours and shapes

    def test_same_image_scores_high(self):
        self.assertGreater(compare_images(self.a, self.a), 0.95)
        self.assertGreater(compare_images(self.a, self.a_copy), 0.7)

    def test_different_image_scores_low(self):
        self.assertLess(compare_images(self.a, self.b), 0.5)
        self.assertGreater(compare_images(self.a, self.a_copy), compare_images(self.a, self.b))

    def test_missing_image_returns_none(self):
        self.assertIsNone(compare_images(self.a, None))
        self.assertIsNone(compare_images(self.a, os.path.join(self.dir, "nope.png")))

    def test_image_raises_combined_score_for_true_match(self):
        import config
        lost, found = prep(LOST_PHONE), prep(FOUND_PHONE)
        without = score_pair(lost, found)["combined"]
        os.makedirs(self.dir, exist_ok=True)
        config.Config.UPLOAD_FOLDER, old = self.dir, config.Config.UPLOAD_FOLDER
        try:
            lost["image_path"], found["image_path"] = "a.png", "a2.png"
            s = score_pair(lost, found)
        finally:
            config.Config.UPLOAD_FOLDER = old
        self.assertIsNotNone(s["image"])
        self.assertGreaterEqual(s["combined"], without - 0.05)


class TestIntakeValidation(unittest.TestCase):
    good = {"item_name": "Blue wallet", "category": "Wallet", "description": "Blue leather wallet with cards",
            "date": "2026-11-20", "location": "Bus stand", "color": "Navy", "brand": "Fossil", "contact": "a@b.com"}

    def test_valid_report(self):
        r = intake_agent.process("lost", self.good)
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["color"], "blue")             # 'navy' normalised

    def test_invalid_reports(self):
        for change in ({"item_name": ""}, {"category": "Spaceship"}, {"description": "short"},
                       {"date": "2099-01-01"}, {"date": "not-a-date"}, {"contact": "xx"}):
            self.assertFalse(intake_agent.process("lost", self.good | change)["ok"], change)


if __name__ == "__main__":
    unittest.main()
