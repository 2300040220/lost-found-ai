"""SQLite connection helper and automatic database initialisation."""
import sqlite3
from contextlib import contextmanager

from werkzeug.security import generate_password_hash

from config import cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    phone         TEXT DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lost_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_name   TEXT NOT NULL,
    category    TEXT NOT NULL,
    description TEXT NOT NULL,
    lost_date   TEXT NOT NULL,
    location    TEXT NOT NULL,
    color       TEXT DEFAULT '',
    brand       TEXT DEFAULT '',
    image_path  TEXT,
    contact     TEXT NOT NULL,
    search_text TEXT DEFAULT '',
    keywords    TEXT DEFAULT '',
    detected_objects TEXT DEFAULT '',   -- YOLO detections as JSON
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','returned')),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS found_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_name      TEXT NOT NULL,
    category       TEXT NOT NULL,
    description    TEXT NOT NULL,
    found_date     TEXT NOT NULL,
    location       TEXT NOT NULL,
    color          TEXT DEFAULT '',
    brand          TEXT DEFAULT '',
    image_path     TEXT,
    contact        TEXT NOT NULL,
    secret_details TEXT DEFAULT '',   -- finder's private identifying detail, never shown to claimants
    search_text    TEXT DEFAULT '',
    keywords       TEXT DEFAULT '',
    detected_objects TEXT DEFAULT '',   -- YOLO detections as JSON
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','returned')),
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS matches (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    lost_id        INTEGER NOT NULL REFERENCES lost_items(id)  ON DELETE CASCADE,
    found_id       INTEGER NOT NULL REFERENCES found_items(id) ON DELETE CASCADE,
    text_score     REAL NOT NULL DEFAULT 0,
    meta_score     REAL NOT NULL DEFAULT 0,
    image_score    REAL,                      -- NULL when one of the items has no image
    combined_score REAL NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'potential'
                   CHECK (status IN ('potential','claim_pending','returned','closed')),
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lost_id, found_id)
);

CREATE TABLE IF NOT EXISTS claims (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id           INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    claimant_id        INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    answers            TEXT NOT NULL,
    verification_score REAL NOT NULL DEFAULT 0,   -- advisory only
    verification_notes TEXT DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    admin_note         TEXT DEFAULT '',
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at        TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    match_id   INTEGER REFERENCES matches(id)          ON DELETE SET NULL,
    message    TEXT NOT NULL,
    link       TEXT DEFAULT '/notifications',
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent      TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lost_status  ON lost_items(status);
CREATE INDEX IF NOT EXISTS idx_found_status ON found_items(status);
CREATE INDEX IF NOT EXISTS idx_notif_user   ON notifications(user_id, is_read);
"""


@contextmanager
def db():
    """Open a connection, commit on success, roll back on error, always close.
    Foreign keys must be switched on for every SQLite connection."""
    conn = sqlite3.connect(cfg("DATABASE"), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate(conn):
    """Add columns introduced after the first release to databases that already exist."""
    for table in ("lost_items", "found_items"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "detected_objects" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN detected_objects TEXT DEFAULT ''")


def init_db():
    """Create all tables and the default admin account. Safe to run repeatedly."""
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        exists = conn.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()
        if not exists:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?, 'admin')",
                (cfg("ADMIN_NAME"), cfg("ADMIN_EMAIL"), generate_password_hash(cfg("ADMIN_PASSWORD"))),
            )
            conn.execute("INSERT INTO admin (user_id) VALUES (?)", (cur.lastrowid,))


if __name__ == "__main__":
    init_db()
    print("Database initialised at", cfg("DATABASE"))
