# Design and Development of Agentic Edge AI Based Real-Time Item Lost-Found System

A Flask web app where users report lost and found items. Four cooperating AI agents validate reports,
find likely matches (text + image), notify both people instantly, and manage ownership verification.
An administrator always makes the final decision. All AI runs **locally** (scikit-learn + OpenCV).
No paid APIs, no cloud AI.

## 1. Install on Windows 11 (VS Code)

1. Install **Python 3.11 or 3.12** from python.org. Tick **"Add python.exe to PATH"**.
2. Unzip the project and open the `lost_found_ai` folder in VS Code (File > Open Folder).
3. Open a terminal (Ctrl + `) and run:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope Process Bypass`, then activate again.

4. (Optional) load demo data: `python seed_demo.py`
5. Start the app: `python app.py`
6. Open **http://127.0.0.1:5000**

The SQLite database (`lost_found.db`) is created automatically on first start.

**Default admin:** `admin@lostfound.local` / `Admin@123` (change in `config.py` before your demo or deployment).
**Demo users** (after `seed_demo.py`): `owner@demo.com` and `finder@demo.com`, password `Demo@1234`.

> Bootstrap, the font and the Socket.IO client load from CDNs, so the *browser* needs internet the first time.
> The AI itself never uses the internet. For a fully offline demo, download `bootstrap.min.css/js` and
> `socket.io.min.js` into `static/vendor/` and change the three `<script>/<link>` tags in `templates/base.html`.

## 2. Try the full workflow (two browsers)

1. Browser A (normal window): log in as `owner@demo.com`. Browser B (private window): log in as `finder@demo.com`.
2. A: **Report lost** > "Black Samsung phone", Phone, black, Samsung, "cracked screen, blue case", upload a photo.
3. B: **Report found** > "Samsung mobile", Phone, black, "black Samsung phone with cracked screen near library". Add a private detail (e.g. "golden retriever lock screen").
4. Both windows show a **live toast, bell badge and dashboard counters** with no refresh.
5. A: **Matches** > see text / details / image / combined score > **This may be mine** > answer the questions.
6. Log in as admin (third browser): **Admin > Claims** > read the advisory score > **Approve**.
7. Both users now see each other's contact details in **Claims**. Dashboard shows "Returned to owners: 1" live.

## 3. YOLO object detection (optional but recommended)

YOLO tells the system *what* is in each photo (phone, backpack, umbrella...). It crops the object before comparing
photos, mixes "same object class" into the image score, and warns when the chosen category does not fit the photo.

```powershell
pip install ultralytics          # only needed for this one-time export
python export_yolo_onnx.py       # creates ai_models/yolov8n.onnx (about 12 MB)
```
The app runs the `.onnx` file with OpenCV (no PyTorch at run time). If the file is missing, or `YOLO_ENABLED=0`,
the app silently falls back to colour + ORB image matching. The standard model knows 80 everyday objects (COCO):
it has no "wallet", "keys", "documents" or "jewellery" class, and people are ignored on purpose.

> If you installed an earlier version: run `pip uninstall -y opencv-python` before `pip install -r requirements.txt`,
> because the project now uses `opencv-python-headless` (needed on cloud servers).

## 4. Hosting on the internet

See `docs/DEPLOY_RENDER.md`. Set `LF_ENV=production`, `SECRET_KEY` and `ADMIN_PASSWORD`; the app refuses to start
publicly with the default secrets. `/healthz` reports whether YOLO is loaded.

## 5. Run the tests

```powershell
python -m unittest discover -v
```
35 tests cover all 12 required scenarios plus YOLO decoding and hosting settings (see `docs/TESTING.md`).

## 6. Project structure

```
lost_found_ai/
├── app.py                  Flask routes, security (CSRF, RBAC), Socket.IO events
├── config.py               All settings (weights, threshold, admin account, categories)
├── database.py             SQLite schema + automatic initialisation
├── utils.py                Secure image upload validation
├── seed_demo.py            Optional demo data
├── agents/
│   ├── intake_agent.py         validate, clean, normalise, extract keywords
│   ├── matching_agent.py       TF-IDF + cosine + metadata + image => ranked matches
│   ├── verification_agent.py   claim questions + advisory answer check + admin decision
│   ├── notification_agent.py   save + push real-time notifications, broadcast stats
│   └── agent_coordinator.py    the hub that runs the workflow and logs every hand-over
├── models/database_models.py   every SQL query (privacy rules for claims live here)
├── services/
│   ├── image_matching.py       OpenCV colour histogram + ORB keypoints (on the YOLO-cropped object)
│   ├── object_detection.py     YOLO (ONNX) detection, decoding, class agreement
│   └── notification_service.py shared Socket.IO object and room helpers
├── templates/  static/  uploads/  tests/  docs/
```

## 7. How it works (short version)

* **Edge AI here** means all inference runs on the user's own computer: TF-IDF/cosine (scikit-learn) and
  colour/ORB analysis (OpenCV). Reports and photos never leave the machine. This is *local* AI on a
  PC. It does **not** use dedicated edge hardware (no Jetson/Raspberry Pi/TPU) and we do not claim it does.
* **Agents** do not call each other. The `AgentCoordinator` calls Intake, then Matching, then Notification,
  passing each result to the next one, and records every step in the `agent_logs` table (visible in Admin > Overview).
* **Score** = `0.45*text + 0.25*details + 0.30*image` (or `0.60*text + 0.40*details` when a photo is missing).
  Matches at or above `0.40` are stored. Edit the weights in `config.py`.
* **YOLO** runs inside the Intake Agent; the Matching Agent mixes its object-class agreement into the image score (30 % of it).
* **Ownership is never decided by AI.** The Verification Agent only gives an advisory score; the admin approves.
* **Image similarity is only a suggestion** (colour + shape). It cannot prove ownership.

## 8. Security features

Password hashing (Werkzeug PBKDF2) | session login, session reset on login | role-based admin routes (403 for users)
| CSRF token on every POST | extension allow-list + `secure_filename` + random prefix + real image decode check
| 5 MB upload cap | input validation in Intake Agent | Jinja auto-escaping (XSS) | parameterised SQL (no injection)
| contacts hidden until a claim is approved | finder's private clue and AI score hidden from normal users
| per-user Socket.IO rooms so notifications reach only their owner | uploads served only to logged-in users.

## 9. Limitations (be honest in your viva)

* TF-IDF matches words, not meaning (synonym map helps for common items); it will not understand "iPhone" = "mobile" unless mapped.
* Colour/ORB image matching is classical CV: good for colour and distinctive shapes, weak for plain items photographed differently.
* Development server (Werkzeug) is for demo; use a production server and HTTPS for real deployment.
* No password-reset email, rate limiting, or user deletion (easy future work).
