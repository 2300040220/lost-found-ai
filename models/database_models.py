"""All SQL lives here, so agents and routes never write raw queries themselves."""
from database import db

TABLE = {"lost": "lost_items", "found": "found_items"}
DATE_COL = {"lost": "lost_date", "found": "found_date"}
ITEM_FIELDS = ["item_name", "category", "description", "color", "brand",
               "location", "image_path", "contact", "search_text", "keywords", "detected_objects"]


def _all(cur):
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------- users
def create_user(name, email, password_hash, phone="", role="user"):
    with db() as c:
        uid = c.execute(
            "INSERT INTO users (name,email,password_hash,phone,role) VALUES (?,?,?,?,?)",
            (name, email, password_hash, phone, role)).lastrowid
        if role == "admin":
            c.execute("INSERT INTO admin (user_id) VALUES (?)", (uid,))
    return uid


def get_user_by_email(email):
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    return dict(r) if r else None


def get_user(user_id):
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(r) if r else None


def admin_ids():
    with db() as c:
        return [r["id"] for r in c.execute("SELECT id FROM users WHERE role='admin'")]


def list_users():
    with db() as c:
        return _all(c.execute(
            """SELECT u.id,u.name,u.email,u.phone,u.role,u.created_at,
                      (SELECT COUNT(*) FROM lost_items  WHERE user_id=u.id) AS lost_count,
                      (SELECT COUNT(*) FROM found_items WHERE user_id=u.id) AS found_count
               FROM users u ORDER BY u.id"""))


# ---------------------------------------------------------------- items
def insert_item(kind, user_id, d):
    cols = ["user_id", DATE_COL[kind]] + ITEM_FIELDS
    vals = [user_id, d["date"]] + [d.get(f) for f in ITEM_FIELDS]
    if kind == "found":
        cols.append("secret_details")
        vals.append(d.get("secret_details", ""))
    sql = f"INSERT INTO {TABLE[kind]} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    with db() as c:
        return c.execute(sql, vals).lastrowid


def get_item(kind, item_id):
    with db() as c:
        r = c.execute(f"SELECT *, {DATE_COL[kind]} AS date FROM {TABLE[kind]} WHERE id=?",
                      (item_id,)).fetchone()
    return dict(r) if r else None


def list_items(kind, status=None, user_id=None, exclude_user=None):
    sql = (f"SELECT i.*, i.{DATE_COL[kind]} AS date, u.name AS owner "
           f"FROM {TABLE[kind]} i JOIN users u ON u.id=i.user_id WHERE 1=1")
    p = []
    if status:
        sql += " AND i.status=?"; p.append(status)
    if user_id:
        sql += " AND i.user_id=?"; p.append(user_id)
    if exclude_user:
        sql += " AND i.user_id<>?"; p.append(exclude_user)
    with db() as c:
        return _all(c.execute(sql + " ORDER BY i.created_at DESC, i.id DESC", p))


def delete_item(kind, item_id):
    with db() as c:
        return c.execute(f"DELETE FROM {TABLE[kind]} WHERE id=?", (item_id,)).rowcount


def recent_reports(limit=10):
    """Public summary of the newest reports (no contact data)."""
    with db() as c:
        return _all(c.execute(
            """SELECT * FROM (
                 SELECT 'lost'  AS kind, id, item_name, category, location, lost_date  AS date, status, created_at FROM lost_items
                 UNION ALL
                 SELECT 'found' AS kind, id, item_name, category, location, found_date AS date, status, created_at FROM found_items
               ) ORDER BY created_at DESC, id DESC LIMIT ?""", (limit,)))


# ---------------------------------------------------------------- matches
MATCH_SQL = """
SELECT m.id, m.lost_id, m.found_id, m.text_score, m.meta_score, m.image_score,
       m.combined_score, m.status, m.created_at,
       l.item_name AS lost_name, l.category AS lost_category, l.description AS lost_description,
       l.color AS lost_color, l.brand AS lost_brand, l.location AS lost_location,
       l.lost_date AS lost_date, l.image_path AS lost_image, l.user_id AS lost_user_id,
       f.item_name AS found_name, f.category AS found_category, f.description AS found_description,
       f.color AS found_color, f.brand AS found_brand, f.location AS found_location,
       f.found_date AS found_date, f.image_path AS found_image, f.user_id AS found_user_id,
       l.detected_objects AS lost_detected, f.detected_objects AS found_detected
       {extra}
FROM matches m
JOIN lost_items  l ON l.id = m.lost_id
JOIN found_items f ON f.id = m.found_id
JOIN users lu ON lu.id = l.user_id
JOIN users fu ON fu.id = f.user_id
{where} ORDER BY m.combined_score DESC, m.id DESC
"""
ADMIN_EXTRA = ", lu.name AS lost_user, fu.name AS found_user, l.contact AS lost_contact, f.contact AS found_contact"


def upsert_match(lost_id, found_id, text_s, meta_s, image_s, combined):
    """Insert a match or refresh its scores. Returns (match_id, is_new)."""
    with db() as c:
        ex = c.execute("SELECT id FROM matches WHERE lost_id=? AND found_id=?",
                       (lost_id, found_id)).fetchone()
        if ex:
            c.execute("""UPDATE matches SET text_score=?, meta_score=?, image_score=?, combined_score=?
                         WHERE id=? AND status='potential'""", (text_s, meta_s, image_s, combined, ex["id"]))
            return ex["id"], False
        cur = c.execute("""INSERT INTO matches (lost_id,found_id,text_score,meta_score,image_score,combined_score)
                           VALUES (?,?,?,?,?,?)""", (lost_id, found_id, text_s, meta_s, image_s, combined))
        return cur.lastrowid, True


def get_match(match_id, admin=False):
    sql = MATCH_SQL.format(extra=ADMIN_EXTRA if admin else "", where="WHERE m.id=?")
    with db() as c:
        r = c.execute(sql, (match_id,)).fetchone()
    return dict(r) if r else None


def list_matches_for_user(user_id):
    sql = MATCH_SQL.format(extra="", where="WHERE (l.user_id=? OR f.user_id=?) AND m.status<>'closed'")
    with db() as c:
        rows = _all(c.execute(sql, (user_id, user_id)))
    for r in rows:
        r["my_role"] = "owner" if r["lost_user_id"] == user_id else "finder"
    return rows


def list_matches_admin():
    with db() as c:
        return _all(c.execute(MATCH_SQL.format(extra=ADMIN_EXTRA, where="")))


def set_match_status(match_id, status):
    with db() as c:
        c.execute("UPDATE matches SET status=? WHERE id=?", (status, match_id))


# ---------------------------------------------------------------- claims
CLAIM_SQL = """
SELECT c.id, c.match_id, c.claimant_id, c.answers, c.verification_score, c.verification_notes,
       c.status, c.admin_note, c.created_at, c.reviewed_at,
       cu.name AS claimant_name, m.combined_score, m.lost_id, m.found_id,
       l.item_name AS lost_name, l.contact AS lost_contact, l.image_path AS lost_image,
       f.item_name AS found_name, f.contact AS found_contact, f.image_path AS found_image,
       f.user_id AS finder_id, f.secret_details AS secret_details, fu.name AS finder_name
FROM claims c
JOIN matches m ON m.id = c.match_id
JOIN lost_items  l ON l.id = m.lost_id
JOIN found_items f ON f.id = m.found_id
JOIN users cu ON cu.id = c.claimant_id
JOIN users fu ON fu.id = f.user_id
{where} ORDER BY c.created_at DESC, c.id DESC
"""


def claim_rows(where="", params=(), viewer_id=None, is_admin=False):
    """Fetch claims and strip anything the viewer must not see (privacy rules live here)."""
    with db() as c:
        rows = _all(c.execute(CLAIM_SQL.format(where=where), params))
    if is_admin:
        return rows
    for r in rows:
        r["secret_details"] = None                       # finder's private clue
        r["verification_score"] = None                   # AI score is for admins only
        r["verification_notes"] = None
        if r["claimant_id"] != viewer_id:
            r["answers"] = None                          # finder does not read the claimant's answers
        if r["status"] != "approved":                    # contacts are released only after approval
            r["lost_contact"] = None
            r["found_contact"] = None
    return rows


def get_claim(claim_id, is_admin=True):
    rows = claim_rows("WHERE c.id=?", (claim_id,), is_admin=is_admin)
    return rows[0] if rows else None


def create_claim(match_id, claimant_id, answers, score, notes):
    with db() as c:
        return c.execute(
            """INSERT INTO claims (match_id,claimant_id,answers,verification_score,verification_notes)
               VALUES (?,?,?,?,?)""", (match_id, claimant_id, answers, score, notes)).lastrowid


def claim_exists(match_id, claimant_id):
    with db() as c:
        return c.execute("SELECT 1 FROM claims WHERE match_id=? AND claimant_id=? AND status IN ('pending','approved')",
                         (match_id, claimant_id)).fetchone() is not None


def set_claim_decision(claim_id, status, note):
    with db() as c:
        c.execute("UPDATE claims SET status=?, admin_note=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
                  (status, note, claim_id))


def finalize_return(match_id):
    """Mark both items returned and close every other match that involved either item."""
    with db() as c:
        m = c.execute("SELECT lost_id, found_id FROM matches WHERE id=?", (match_id,)).fetchone()
        if not m:
            return False
        c.execute("UPDATE lost_items  SET status='returned' WHERE id=?", (m["lost_id"],))
        c.execute("UPDATE found_items SET status='returned' WHERE id=?", (m["found_id"],))
        c.execute("UPDATE matches SET status='returned' WHERE id=?", (match_id,))
        c.execute("""UPDATE matches SET status='closed'
                     WHERE id<>? AND (lost_id=? OR found_id=?) AND status IN ('potential','claim_pending')""",
                  (match_id, m["lost_id"], m["found_id"]))
        c.execute("""UPDATE claims SET status='rejected', admin_note='Item was returned through another claim',
                     reviewed_at=CURRENT_TIMESTAMP
                     WHERE status='pending' AND match_id IN (SELECT id FROM matches WHERE status='closed')""")
    return True


# ---------------------------------------------------------------- notifications
def add_notification(user_id, message, match_id=None, link="/notifications"):
    with db() as c:
        nid = c.execute("INSERT INTO notifications (user_id,match_id,message,link) VALUES (?,?,?,?)",
                        (user_id, match_id, message, link)).lastrowid
        r = c.execute("SELECT * FROM notifications WHERE id=?", (nid,)).fetchone()
    return dict(r)


def list_notifications(user_id, limit=50):
    with db() as c:
        return _all(c.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",
                              (user_id, limit)))


def unread_count(user_id):
    with db() as c:
        return c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                         (user_id,)).fetchone()[0]


def mark_read(user_id, notification_id=None):
    with db() as c:
        if notification_id:
            c.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notification_id, user_id))
        else:
            c.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------- stats + logs
def get_stats():
    with db() as c:
        r = c.execute("""SELECT
            (SELECT COUNT(*) FROM lost_items)  AS total_lost,
            (SELECT COUNT(*) FROM found_items) AS total_found,
            (SELECT COUNT(*) FROM matches WHERE status IN ('potential','claim_pending')) AS potential_matches,
            (SELECT COUNT(*) FROM matches WHERE status='returned') AS returned_items,
            (SELECT COUNT(*) FROM claims  WHERE status='pending')  AS pending_claims,
            (SELECT COUNT(*) FROM users)   AS total_users""").fetchone()
    return dict(r)


def log_agent(agent, action, detail=""):
    with db() as c:
        c.execute("INSERT INTO agent_logs (agent,action,detail) VALUES (?,?,?)", (agent, action, detail))


def list_logs(limit=60):
    with db() as c:
        return _all(c.execute("SELECT * FROM agent_logs ORDER BY id DESC LIMIT ?", (limit,)))
