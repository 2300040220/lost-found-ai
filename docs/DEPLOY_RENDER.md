# Deploying to Render (reference)

The chat walks you through these one step at a time. This page is the summary.

1. **Update the project** (new zip), run `pip uninstall -y opencv-python`, then `pip install -r requirements.txt`, run `python -m unittest discover`.
2. **Create the YOLO model once:** `pip install ultralytics`, then `python export_yolo_onnx.py` (creates `ai_models/yolov8n.onnx`).
3. **Test locally** with `python app.py`: report an item with a photo; the dashboard flow should show "YOLO sees ..." on the match card.
4. **Put the project on GitHub** (private repo is fine). Commit `ai_models/yolov8n.onnx` too (about 12 MB).
5. **Create a Render Web Service** from the repo: Build `pip install -r requirements.txt`, Start `gunicorn -w 1 --threads 50 -b 0.0.0.0:$PORT app:app`.
6. **Environment variables:** `LF_ENV=production`, `SECRET_KEY` (long random), `ADMIN_PASSWORD` (your own), `PYTHON_VERSION=3.12.3`, optional `YOLO_ENABLED=0`.
7. **Open the https URL**, log in as the admin, and test with two browsers.

## Know the limits of the free plan
* **Data loss:** the disk is temporary. Every restart or redeploy deletes the SQLite database and uploaded photos
  (the admin account is recreated automatically). For permanent data use a paid instance with a disk and set
  `LF_DATABASE=/var/data/lost_found.db` and `LF_UPLOAD_FOLDER=/var/data/uploads`.
* **Sleeping:** free services sleep after inactivity; the first request wakes them (about a minute).
* **Memory:** about 512 MB. scikit-learn + OpenCV fit; YOLOv8n may be tight. If you see "out of memory",
  set `YOLO_ENABLED=0` or move to a larger instance.
* **One worker only:** Flask-SocketIO delivers real-time messages in memory, so keep `-w 1`.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Build fails on OpenCV / libGL | Make sure requirements use `opencv-python-headless` (they do) |
| App exits at start: "Production mode needs..." | Set `SECRET_KEY` and `ADMIN_PASSWORD` variables |
| Pages work but no live notifications | Open the browser console; if Socket.IO is refused set `LF_CORS_ORIGINS=https://your-app.onrender.com` |
| Logged out immediately | Use the https URL (cookies are secure-only in production) |
| `/healthz` shows `"yolo": false` | The `.onnx` file is not in the repo at `ai_models/yolov8n.onnx`, or `YOLO_ENABLED=0` |
| Out-of-memory restarts | `YOLO_ENABLED=0`, or a larger plan |

## Licence note
Ultralytics YOLO and its exported weights are AGPL-3.0. That is fine for an academic project; if you run it as a
public service for others, keep your source code available (a public GitHub repo satisfies this) or buy an Ultralytics licence.
