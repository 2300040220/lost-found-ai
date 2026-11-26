"""Flask application: routes, security and Socket.IO events.
Run with:  python app.py   then open http://127.0.0.1:5000"""
import hmac
import os
import re
import secrets
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from flask_socketio import emit, join_room
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from agents import verification_agent
from agents.agent_coordinator import coordinator
from agents.intake_agent import EMAIL_RE
from config import DEFAULT_ADMIN_PASSWORD, DEFAULT_SECRET, Config
from database import init_db
from models import database_models as M
from services import object_detection
from services.image_matching import IMAGE_DISCLAIMER
from services.notification_service import socketio
from utils import remove_image, save_image


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    if app.config["PRODUCTION"]:
        # Refuse to start a public site with the well-known development secrets.
        if app.config["SECRET_KEY"] == DEFAULT_SECRET or app.config["ADMIN_PASSWORD"] == DEFAULT_ADMIN_PASSWORD:
            raise RuntimeError("Production mode needs the SECRET_KEY and ADMIN_PASSWORD environment variables "
                               "to be set to your own values.")
        # The host's load balancer terminates HTTPS; trust its forwarded headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    with app.app_context():
        init_db()                                    # database is created automatically
    socketio.init_app(app)
    register_security(app)
    register_routes(app)
    register_socket_events()
    return app


# ====================================================================== security
def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    """Role-based access control: only users whose session role is 'admin' get through."""
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if session.get("role") != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def register_security(app):
    @app.before_request
    def check_csrf():
        """Every POST must carry the per-session token (form field or X-CSRF-Token header)."""
        if request.method == "POST":
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
            expected = session.get("_csrf", "")
            if not sent or not expected or not hmac.compare_digest(sent, expected):
                abort(400, "Invalid or missing form token. Reload the page and try again.")

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "SAMEORIGIN"
        if app.config["PRODUCTION"]:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    app.jinja_env.filters["objects"] = object_detection.labels_text

    @app.context_processor
    def inject():
        unread = M.unread_count(session["user_id"]) if "user_id" in session else 0
        return {"csrf_token": csrf_token, "unread_count": unread, "categories": app.config["CATEGORIES"],
                "current_name": session.get("name"), "current_role": session.get("role"),
                "image_disclaimer": IMAGE_DISCLAIMER}

    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="That page does not exist."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message=getattr(e, "description", "Bad request.")), 400

    @app.errorhandler(413)
    def too_large(_):
        return render_template("error.html", code=413, message="The upload is larger than 5 MB."), 413


# ====================================================================== routes
def register_routes(app):
    @app.route("/healthz")
    def healthz():
        """Used by the hosting platform to check the app is alive (no login, no private data)."""
        return jsonify(status="ok", yolo=object_detection.available())

    # ------------------------------------------------------------ auth
    @app.route("/")
    def index():
        return redirect(url_for("dashboard" if "user_id" in session else "login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = re.sub(r"\s+", " ", request.form.get("name", "")).strip()
            email = request.form.get("email", "").strip().lower()
            phone = re.sub(r"[^\d+\s()\-]", "", request.form.get("phone", ""))[:20]
            pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
            errors = []
            if not 2 <= len(name) <= 60:
                errors.append("Name must be 2 to 60 characters.")
            if not EMAIL_RE.match(email) or len(email) > 120:
                errors.append("Enter a valid email address.")
            if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
                errors.append("Password needs at least 8 characters with a letter and a number.")
            if pw != pw2:
                errors.append("Passwords do not match.")
            if not errors and M.get_user_by_email(email):
                errors.append("That email is already registered.")
            if errors:
                for e in errors:
                    flash(e, "danger")
                return render_template("register.html", form=request.form), 400
            M.create_user(name, email, generate_password_hash(pw), phone)
            flash("Account created. You can log in now.", "success")
            return redirect(url_for("login"))
        return render_template("register.html", form={})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = M.get_user_by_email(request.form.get("email", "").strip().lower())
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear()                       # new session id on login (prevents fixation)
                session.update(user_id=user["id"], role=user["role"], name=user["name"])
                csrf_token()
                flash(f"Welcome back, {user['name']}.", "success")
                return redirect(url_for("admin_panel" if user["role"] == "admin" else "dashboard"))
            flash("Incorrect email or password.", "danger")
            return render_template("login.html"), 401
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You have been logged out.", "info")
        return redirect(url_for("login"))

    # ------------------------------------------------------------ dashboard
    @app.route("/dashboard")
    @login_required
    def dashboard():
        uid = session["user_id"]
        return render_template("dashboard.html", stats=M.get_stats(), recent=M.recent_reports(10),
                               my_lost=M.list_items("lost", user_id=uid), my_found=M.list_items("found", user_id=uid))

    @app.route("/api/stats")
    @login_required
    def api_stats():
        return jsonify(M.get_stats())

    @app.route("/api/notifications")
    @login_required
    def api_notifications():
        uid = session["user_id"]
        return jsonify(unread=M.unread_count(uid), items=M.list_notifications(uid, 20))

    # ------------------------------------------------------------ reporting
    @app.route("/report/<kind>", methods=["GET", "POST"])
    @login_required
    def report(kind):
        if kind not in ("lost", "found"):
            abort(404)
        if request.method == "POST":
            filename, upload_error = save_image(request.files.get("image"))
            if upload_error:
                flash(upload_error, "danger")
                return render_template(f"report_{kind}.html", form=request.form, kind=kind), 400
            result = coordinator.process_new_report(kind, session["user_id"], request.form, filename)
            if not result["ok"]:
                remove_image(filename)
                for e in result["errors"]:
                    flash(e, "danger")
                return render_template(f"report_{kind}.html", form=request.form, kind=kind), 400
            for hint in result.get("hints", []):
                flash(hint, "info")
            n = len(result["matches"])
            msg = f"Your {kind} report was saved."
            msg += f" The AI found {n} possible match{'es' if n != 1 else ''}." if n else " No matches yet. We will notify you instantly if one appears."
            flash(msg, "success")
            return redirect(url_for("matches" if n else "dashboard"))
        return render_template(f"report_{kind}.html", form={}, kind=kind)

    @app.route("/uploads/<path:filename>")
    @login_required
    def uploads(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    # ------------------------------------------------------------ matches + claims
    @app.route("/matches")
    @login_required
    def matches():
        return render_template("matches.html", matches=M.list_matches_for_user(session["user_id"]))

    @app.route("/matches/<int:match_id>/claim", methods=["GET", "POST"])
    @login_required
    def claim_form(match_id):
        match = M.get_match(match_id)
        if not match or match["lost_user_id"] != session["user_id"]:
            abort(404)                                # do not reveal other users' matches
        found = M.get_item("found", match["found_id"])
        questions = verification_agent.get_questions(found)
        if request.method == "POST":
            answers = [request.form.get(f"answer_{i}", "") for i in range(len(questions))]
            result = coordinator.submit_claim(match_id, session["user_id"], answers)
            if not result["ok"]:
                flash(result["error"], "danger")
                return render_template("claim_form.html", match=match, questions=questions, answers=answers), 400
            flash("Claim submitted. An admin will review it shortly.", "success")
            return redirect(url_for("claims"))
        return render_template("claim_form.html", match=match, questions=questions, answers=[])

    @app.route("/claims")
    @login_required
    def claims():
        uid = session["user_id"]
        mine = M.claim_rows("WHERE c.claimant_id=?", (uid,), viewer_id=uid)
        incoming = M.claim_rows("WHERE f.user_id=?", (uid,), viewer_id=uid)
        return render_template("claims.html", mine=mine, incoming=incoming)

    # ------------------------------------------------------------ notifications
    @app.route("/notifications")
    @login_required
    def notifications():
        return render_template("notifications.html", items=M.list_notifications(session["user_id"]))

    @app.route("/notifications/read", methods=["POST"])
    @login_required
    def notifications_read():
        raw = request.form.get("id")
        M.mark_read(session["user_id"], int(raw) if raw and raw.isdigit() else None)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(unread=M.unread_count(session["user_id"]))
        return redirect(request.form.get("next") if (request.form.get("next") or "").startswith("/") else url_for("notifications"))

    # ------------------------------------------------------------ admin
    @app.route("/admin")
    @admin_required
    def admin_panel():
        return render_template("admin.html", stats=M.get_stats(), users=M.list_users(),
                               lost=M.list_items("lost"), found=M.list_items("found"),
                               matches=M.list_matches_admin(),
                               claims=M.claim_rows(is_admin=True), logs=M.list_logs())

    @app.route("/admin/claims/<int:claim_id>/<action>", methods=["POST"])
    @admin_required
    def admin_decide(claim_id, action):
        if action not in ("approve", "reject"):
            abort(404)
        res = coordinator.decide_claim(claim_id, session["user_id"], action == "approve",
                                       request.form.get("note", "").strip()[:300])
        flash(f"Claim {action}d." if res["ok"] else res["error"], "success" if res["ok"] else "danger")
        return redirect(url_for("admin_panel") + "#claims")

    @app.route("/admin/matches/<int:match_id>/return", methods=["POST"])
    @admin_required
    def admin_return(match_id):
        res = coordinator.mark_returned(match_id, session["user_id"])
        flash("Marked as returned." if res["ok"] else res["error"], "success" if res["ok"] else "danger")
        return redirect(url_for("admin_panel") + "#matches")

    @app.route("/admin/items/<kind>/<int:item_id>/delete", methods=["POST"])
    @admin_required
    def admin_delete(kind, item_id):
        if kind not in ("lost", "found"):
            abort(404)
        item = M.get_item(kind, item_id)
        if item and M.delete_item(kind, item_id):
            remove_image(item.get("image_path"))
            M.log_agent("Admin", "removed_report", f"{kind} #{item_id} by admin #{session['user_id']}")
            from agents import notification_agent
            notification_agent.broadcast_stats()
            flash("Report removed.", "success")
        else:
            flash("Report not found.", "danger")
        return redirect(url_for("admin_panel") + "#reports")


# ====================================================================== Socket.IO
def register_socket_events():
    @socketio.on("connect")
    def on_connect():
        uid = session.get("user_id")
        if not uid:
            return False                              # anonymous browsers cannot listen
        join_room(f"user_{uid}")                      # private room: only this user's events
        if session.get("role") == "admin":
            join_room("admins")
        emit("stats_update", M.get_stats())


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    print(f"\nLost & Found AI running on port {port}\n")

    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )

