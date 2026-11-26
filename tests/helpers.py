"""Shared test helpers: temp database, synthetic images, event recorder."""
import os
import sys
import tempfile

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("LF_DATABASE", os.path.join(tempfile.mkdtemp(), "boot.db"))


def make_image(path, base_bgr, shapes=3, seed=1, noise=0):
    """Create a simple synthetic 'item photo': coloured background plus a few shapes."""
    rng = np.random.default_rng(seed)
    img = np.full((240, 240, 3), base_bgr, dtype=np.uint8)
    for _ in range(shapes):
        c = tuple(int(x) for x in rng.integers(0, 255, 3))
        cv2.circle(img, tuple(int(x) for x in rng.integers(30, 210, 2)), int(rng.integers(15, 45)), c, -1)
        cv2.rectangle(img, tuple(int(x) for x in rng.integers(10, 120, 2)),
                      tuple(int(x) for x in rng.integers(130, 230, 2)), c, 3)
    if noise:
        img = np.clip(img.astype(int) + rng.integers(-noise, noise, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(path, img)
    return path
