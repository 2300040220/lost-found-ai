"""Thin wrapper around Flask-SocketIO so agents can push real-time events.

One shared `socketio` object is created here and attached to the Flask app in app.py.
Each logged-in user joins a private room called "user_<id>", so a message sent to that
room reaches only that user (this is how privacy is kept in real time)."""
from flask_socketio import SocketIO

# 'threading' mode works on Windows with no extra server (eventlet/gevent not needed).
import os

# Default allows same-origin browsers only. If the host needs it, set LF_CORS_ORIGINS=https://your-app.onrender.com
socketio = SocketIO(async_mode="threading", cors_allowed_origins=os.environ.get("LF_CORS_ORIGINS") or None)


def _safe_emit(event, payload, room=None):
    """A failed push must never break saving or matching, so errors are swallowed."""
    try:
        if room:
            socketio.emit(event, payload, to=room)
        else:
            socketio.emit(event, payload)
        return True
    except Exception as exc:                          # pragma: no cover
        print("[socket] emit failed:", exc)
        return False


def emit_to_user(user_id, event, payload):
    return _safe_emit(event, payload, room=f"user_{user_id}")


def emit_to_admins(event, payload):
    return _safe_emit(event, payload, room="admins")


def emit_to_all(event, payload):
    return _safe_emit(event, payload)
