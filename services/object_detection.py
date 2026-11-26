"""Local object detection with YOLO (YOLOv8 / YOLO11 exported to ONNX) run by OpenCV's DNN module.

Why this design:
  * No PyTorch / ultralytics at run time, so it installs fast and fits on small cloud servers.
  * The model file (ai_models/yolov8n.onnx, about 12 MB) is exported once with export_yolo_onnx.py.
  * If the file is missing or YOLO_ENABLED=0, every function degrades gracefully and the app
    keeps working with the colour/ORB image matching only.

What YOLO adds to the project:
  1. It finds WHAT is in the photo (e.g. "cell phone", "backpack") and where it is.
  2. The image comparison is done on the cropped object instead of the whole photo (less background noise).
  3. Object-class agreement (both photos show a phone) is mixed into the image score.
  4. It warns the user if the chosen category does not fit the photo.

Limits: the standard model knows the 80 COCO classes. It has no class for wallet, keys, documents or
jewellery, so those items simply get no detection. People are ignored on purpose (privacy).
"""
import json
import os
import threading

import cv2
import numpy as np

from config import cfg

COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush"]

IGNORED_LABELS = {"person"}                       # never store people (privacy)

# COCO label -> category used by this app (used only to give the user a gentle hint)
CATEGORY_MAP = {
    "cell phone": "Phone", "laptop": "Laptop", "backpack": "Bag", "handbag": "Bag", "suitcase": "Bag",
    "book": "Books", "remote": "Electronics", "keyboard": "Electronics", "mouse": "Electronics",
    "tie": "Clothing", "umbrella": "Others", "bottle": "Others", "cup": "Others", "scissors": "Others",
    "clock": "Others", "teddy bear": "Others"}

_lock = threading.Lock()                          # cv2.dnn networks are not thread-safe
_nets = {}


def available():
    return bool(cfg("YOLO_ENABLED")) and os.path.isfile(cfg("YOLO_MODEL_PATH"))


def _get_net():
    path = cfg("YOLO_MODEL_PATH")
    if path not in _nets:
        _nets[path] = cv2.dnn.readNetFromONNX(path)
    return _nets[path]


def letterbox(img, size):
    """Resize keeping the aspect ratio and pad to a size x size square (grey padding, as YOLO expects)."""
    h, w = img.shape[:2]
    ratio = min(size / h, size / w)
    nw, nh = int(round(w * ratio)), int(round(h * ratio))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x, pad_y = (size - nw) // 2, (size - nh) // 2
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
    return canvas, ratio, pad_x, pad_y


def decode(output, ratio, pad_x, pad_y, orig_w, orig_h, conf_thr=0.35, iou_thr=0.45, max_items=5):
    """Turn the raw YOLOv8/YOLO11 output tensor (1 x 84 x N: 4 box values + 80 class scores)
    into a short list of detections in ORIGINAL image pixels, best first."""
    n_cols = 4 + len(COCO_CLASSES)
    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]                               # drop the batch dimension only
    if out.ndim != 2:
        return []
    if out.shape[0] == n_cols and out.shape[1] != n_cols:
        out = out.T                                # (84, N) -> (N, 84)
    if out.shape[1] != n_cols:
        return []
    scores = out[:, 4:]
    class_ids = scores.argmax(axis=1)
    confs = scores.max(axis=1)
    keep = (confs >= conf_thr) & np.array([COCO_CLASSES[c] not in IGNORED_LABELS for c in class_ids], dtype=bool)
    if not keep.any():
        return []
    out, class_ids, confs = out[keep], class_ids[keep], confs[keep]

    cx, cy, w, h = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
    x1 = np.clip((cx - w / 2 - pad_x) / ratio, 0, orig_w)
    y1 = np.clip((cy - h / 2 - pad_y) / ratio, 0, orig_h)
    x2 = np.clip((cx + w / 2 - pad_x) / ratio, 0, orig_w)
    y2 = np.clip((cy + h / 2 - pad_y) / ratio, 0, orig_h)
    boxes = [[float(a), float(b), float(c - a), float(d - b)] for a, b, c, d in zip(x1, y1, x2, y2)]
    picked = cv2.dnn.NMSBoxes(boxes, [float(c) for c in confs], float(conf_thr), float(iou_thr))
    result = []
    for i in np.array(picked).flatten().astype(int):
        if boxes[i][2] < 2 or boxes[i][3] < 2:
            continue
        result.append({"label": COCO_CLASSES[int(class_ids[i])], "conf": round(float(confs[i]), 3),
                       "box": [int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])]})
    result.sort(key=lambda d: d["conf"], reverse=True)
    return result[:max_items]


def detect(image_path):
    """Run YOLO on one image file. Returns [] when YOLO is unavailable or anything goes wrong,
    so a detection problem can never block a report from being saved."""
    if not available() or not image_path:
        return []
    try:
        img = cv2.imread(image_path)
        if img is None:
            return []
        size = int(cfg("YOLO_IMG_SIZE"))
        canvas, ratio, pad_x, pad_y = letterbox(img, size)
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (size, size), swapRB=True, crop=False)
        with _lock:
            net = _get_net()
            net.setInput(blob)
            output = net.forward()
        h, w = img.shape[:2]
        return decode(output, ratio, pad_x, pad_y, w, h, cfg("YOLO_CONF"), cfg("YOLO_IOU"))
    except Exception as exc:                       # pragma: no cover
        print("[yolo] detection failed:", exc)
        return []


# ------------------------------------------------------------------ helpers used by the agents
def dumps(dets):
    return json.dumps(dets, separators=(",", ":"))


def loads(text):
    """Parse stored detections; bad or empty data gives []."""
    try:
        data = json.loads(text) if text else []
    except (TypeError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and "label" in d and "box" in d] if isinstance(data, list) else []


def top_box(dets):
    return dets[0]["box"] if dets else None


def labels_text(value):
    """'cell phone 91%, handbag 55%' - accepts a JSON string or a list (used by templates)."""
    dets = loads(value) if isinstance(value, str) or value is None else value
    return ", ".join(f"{d['label']} {round(d['conf'] * 100)}%" for d in dets[:3])


def class_agreement(dets_a, dets_b):
    """1.0 same main object, 0.5 they share some object, 0.0 different objects, None if either has none."""
    if not dets_a or not dets_b:
        return None
    if dets_a[0]["label"] == dets_b[0]["label"]:
        return 1.0
    shared = {d["label"] for d in dets_a} & {d["label"] for d in dets_b}
    return 0.5 if shared else 0.0


def category_hint(dets):
    return CATEGORY_MAP.get(dets[0]["label"]) if dets else None
