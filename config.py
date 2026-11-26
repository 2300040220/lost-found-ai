"""Central settings. Every other module reads its configuration from here.
Most values can be overridden with environment variables, which is how the cloud host configures the app."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DEFAULT_SECRET = "dev-only-change-this-secret-key"
DEFAULT_ADMIN_PASSWORD = "Admin@123"


def _env_bool(name, default):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


PRODUCTION = os.environ.get("LF_ENV", "").strip().lower() == "production"


class Config:
    # --- Flask / security ---
    PRODUCTION = PRODUCTION
    SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET)
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024          # reject uploads above 5 MB
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = PRODUCTION            # cookies only over HTTPS when hosted

    # --- storage (point these at a persistent disk when hosting) ---
    DATABASE = os.environ.get("LF_DATABASE", os.path.join(BASE_DIR, "lost_found.db"))
    UPLOAD_FOLDER = os.environ.get("LF_UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads"))
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}

    # --- default administrator (created automatically on first run) ---
    ADMIN_NAME = "System Admin"
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@lostfound.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    # --- AI settings ---
    MATCH_THRESHOLD = 0.40                        # minimum combined score to store a match
    MAX_MATCHES_PER_REPORT = 5
    # Combined score weights (each set sums to 1.0)
    WEIGHTS_WITH_IMAGE = {"text": 0.45, "meta": 0.25, "image": 0.30}
    WEIGHTS_NO_IMAGE = {"text": 0.60, "meta": 0.40}
    # Weights of the structured-field (metadata) score
    META_WEIGHTS = {"category": 0.30, "color": 0.20, "brand": 0.15, "date": 0.15, "location": 0.20}

    # --- YOLO object detection (YOLOv8 / YOLO11 exported to ONNX, run by OpenCV; no PyTorch needed) ---
    YOLO_ENABLED = _env_bool("YOLO_ENABLED", True)
    YOLO_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH", os.path.join(BASE_DIR, "ai_models", "yolov8n.onnx"))
    YOLO_IMG_SIZE = 640                           # must equal the imgsz used when exporting the model
    YOLO_CONF = 0.35                              # ignore detections below this confidence
    YOLO_IOU = 0.45                               # non-maximum-suppression overlap limit
    YOLO_WEIGHT = 0.30                            # share of the IMAGE score given to object-class agreement

    CATEGORIES = ["Phone", "Wallet", "Keys", "Bag", "Laptop", "Electronics", "Documents",
                  "Jewellery", "Clothing", "Books", "Others"]


def cfg(key):
    """Read a setting from the running Flask app, or from Config when no app is active
    (this lets agents run in plain scripts and unit tests)."""
    from flask import current_app, has_app_context
    if has_app_context() and key in current_app.config:
        return current_app.config[key]
    return getattr(Config, key)
