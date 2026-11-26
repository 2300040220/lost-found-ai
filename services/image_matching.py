"""Local image comparison with OpenCV (no cloud, no deep-learning model download).

Two classic computer-vision signals are combined:
  1. Colour histogram (hue + brightness) -> "do the two photos have the same colours?"
  2. ORB keypoint matching -> "do the two photos share the same local shapes/textures?"

IMPORTANT: image similarity is only a suggestion. It cannot prove ownership.
"""
import os

import cv2
import numpy as np

IMAGE_DISCLAIMER = ("Image similarity is only a suggestion based on colour and shape. "
                    "It cannot prove ownership; ownership is decided after verification and admin review.")

IMG_SIZE = (256, 256)


def crop_to_box(img, box):
    """Keep only the object found by YOLO (plus a 5 % margin). Tiny boxes are ignored."""
    if not box:
        return img
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box
    mx, my = int(0.05 * (x2 - x1)), int(0.05 * (y2 - y1))
    x1, y1, x2, y2 = max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)
    return img[y1:y2, x1:x2] if (x2 - x1 >= 32 and y2 - y1 >= 32) else img


def load_and_preprocess(path, box=None):
    """Read an image, crop to the detected object (optional), resize to 256x256 and lightly blur.
    Returns None if unreadable."""
    if not path or not os.path.isfile(path):
        return None
    img = cv2.imread(path)
    if img is None:
        return None
    img = crop_to_box(img, box)
    img = cv2.resize(img, IMG_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(img, (3, 3), 0)


def color_histogram(img):
    """Colour signature that stays stable when photo noise or lighting changes a little.
    - Pixels with real colour (saturation and brightness high enough) vote into 12 HUE bins.
    - Grey / white / black pixels have no reliable hue, so they vote into 6 BRIGHTNESS bins.
    The two parts are joined and normalised, so image size does not matter."""
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
    _, s, v = cv2.split(hsv)
    chromatic = ((s >= 50) & (v >= 50)).astype(np.uint8) * 255
    hue = cv2.calcHist([hsv], [0], chromatic, [12], [0, 180]).flatten()
    grey = cv2.calcHist([hsv], [2], cv2.bitwise_not(chromatic), [6], [0, 256]).flatten()
    hist = np.concatenate([hue, grey]).astype(np.float32)
    hist /= hist.sum() or 1.0
    return hist.reshape(-1, 1)


def orb_descriptors(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=500)
    _, des = orb.detectAndCompute(gray, None)
    return des


def histogram_similarity(h1, h2):
    """1 - Bhattacharyya distance: 1.0 = identical colour distribution, 0.0 = nothing in common."""
    d = cv2.compareHist(h1, h2, cv2.HISTCMP_BHATTACHARYYA)
    return float(max(0.0, min(1.0, 1.0 - d)))


def orb_similarity(d1, d2):
    """Fraction of ORB descriptors that find a close partner in the other image."""
    if d1 is None or d2 is None or len(d1) < 5 or len(d2) < 5:
        return None                                   # not enough texture to compare
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    good = [m for m in matcher.match(d1, d2) if m.distance <= 40]
    ratio = len(good) / float(min(len(d1), len(d2)))
    return float(min(1.0, ratio * 3.0))               # different photos of one object rarely exceed ~30 %


def compare_images(path_a, path_b, box_a=None, box_b=None):
    """Return an image similarity score 0..1, or None when either image is missing/unreadable.
    box_a / box_b are optional YOLO boxes (x1, y1, x2, y2) so only the object is compared."""
    a, b = load_and_preprocess(path_a, box_a), load_and_preprocess(path_b, box_b)
    if a is None or b is None:
        return None
    hist = histogram_similarity(color_histogram(a), color_histogram(b))
    orb = orb_similarity(orb_descriptors(a), orb_descriptors(b))
    score = hist if orb is None else 0.6 * hist + 0.4 * orb
    return round(float(score), 4)
