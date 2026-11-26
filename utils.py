"""Small helpers: secure image upload handling."""
import os
import uuid

import cv2
from werkzeug.utils import secure_filename

from config import cfg


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in cfg("ALLOWED_EXTENSIONS")


def save_image(file_storage):
    """Validate and store an uploaded image. Returns (saved_filename | None, error | None).
    Checks: extension allow-list, safe filename, random prefix, and that OpenCV can really decode it
    (so a text file renamed to .jpg is rejected)."""
    if file_storage is None or not file_storage.filename:
        return None, None                              # the image is optional
    original = secure_filename(file_storage.filename)
    if not original or not allowed_file(original):
        return None, "Image must be one of: " + ", ".join(sorted(cfg("ALLOWED_EXTENSIONS"))) + "."
    name = f"{uuid.uuid4().hex[:12]}_{original}"
    path = os.path.join(cfg("UPLOAD_FOLDER"), name)
    os.makedirs(cfg("UPLOAD_FOLDER"), exist_ok=True)
    file_storage.save(path)
    if cv2.imread(path) is None:
        os.remove(path)
        return None, "The uploaded file is not a valid image."
    return name, None


def remove_image(filename):
    if filename:
        try:
            os.remove(os.path.join(cfg("UPLOAD_FOLDER"), filename))
        except OSError:
            pass
