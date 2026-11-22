import os
import sqlite3
from datetime import datetime


def _resolve_db_path():
    env_path = (os.environ.get("DB_PATH") or "").strip()
    if env_path:
        return env_path
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/bot_database.db"
    return os.path.abspath("bot_database.db")


DB_PATH = _resolve_db_path()


def get_conn():
    parent_dir = os.path.dirname(DB_PATH)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def init_db():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TEXT,
                country TEXT,
                language TEXT DEFAULT 'sw',
                activated INTEGER DEFAULT 0
            )
        """)
        c.execute("PRAGMA table_info(users)")
        cols = {row[1] for row in c.fetchall()}
        if "activated" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN activated INTEGER DEFAULT 0")
        if "language" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'sw'")
        if "country" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN country TEXT")

        c.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id TEXT,
                referred_id TEXT PRIMARY KEY,
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS seen_images (
                user_id TEXT,
                image_url TEXT,
                PRIMARY KEY (user_id, image_url)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                target_url TEXT,
                clicked_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tracked_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                chat_id INTEGER,
                message_id INTEGER,
                sent_at REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id TEXT,
                phone TEXT,
                amount TEXT,
                status TEXT
            )
        """)
        conn.commit()


def user_exists(user_id):
    uid = str(user_id)
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,)).fetchone()
        return row is not None


def add_user(user_id, username, first_name, joined_at):
    uid = str(user_id)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, joined_at, language, activated)
            VALUES (?, ?, ?, ?, 'sw', 0)
            ON CONFLICT(user_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name)
            """,
            (uid, username, first_name, joined_at)
        )
        conn.commit()


def set_user_country(user_id, country):
    uid = str(user_id)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, country, language, activated)
            VALUES (?, ?, 'sw', 0)
            ON CONFLICT(user_id) DO UPDATE SET country = excluded.country
            """,
            (uid, country)
        )
        conn.commit()


def get_user_country(user_id):
    uid = str(user_id)
    with get_conn() as conn:
        row = conn.execute("SELECT country FROM users WHERE user_id = ?", (uid,)).fetchone()
        return row[0] if row and row[0] else None


def set_user_language(user_id, language):
    uid = str(user_id)
    lang = "en" if language == "en" else "sw"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, language, activated)
            VALUES (?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET language = excluded.language
            """,
            (uid, lang)
        )
        conn.commit()


def get_user_language(user_id):
    uid = str(user_id)
    with get_conn() as conn:
        row = conn.execute("SELECT language FROM users WHERE user_id = ?", (uid,)).fetchone()
        return row[0] if row and row[0] in ("en", "sw") else "sw"


def set_user_activated(user_id, activated=True):
    uid = str(user_id)
    val = 1 if activated else 0
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, joined_at, language, activated)
            VALUES (?, ?, 'sw', ?)
            ON CONFLICT(user_id) DO UPDATE SET activated = excluded.activated
            """,
            (uid, str(datetime.utcnow()), val)
        )
        conn.commit()


def is_user_activated(user_id):
    uid = str(user_id)
    with get_conn() as conn:
        row = conn.execute("SELECT activated FROM users WHERE user_id = ?", (uid,)).fetchone()
        return bool(row and int(row[0] or 0) == 1)


def add_referral_new_user_only(referrer_id, referred_id, existed_before):
    ref_id = str(referrer_id).strip()
    new_id = str(referred_id).strip()
    if existed_before or not ref_id or not new_id or ref_id == new_id:
        return False
    with get_conn() as conn:
        existing_ref = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (ref_id,)).fetchone()
        if not existing_ref:
            return False
        already_counted = conn.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (new_id,)).fetchone()
        if already_counted:
            return False
        conn.execute(
            "INSERT INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)",
            (ref_id, new_id, str(datetime.utcnow()))
        )
        conn.commit()
        return True


def get_referral_count(user_id):
    uid = str(user_id)
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (uid,)).fetchone()
        return int(row[0] or 0) if row else 0


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r[0] for r in rows if r and r[0]]


def get_total_users_count():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0] or 0) if row else 0


def get_users_by_country_counts():
    tracked = ["Tanzania", "Kenya", "Uganda", "Ghana", "Nigeria", "Zimbabwe", "Ethiopia"]
    counts = {name: 0 for name in tracked}
    counts["Unset"] = 0
    with get_conn() as conn:
        rows = conn.execute("SELECT country, COUNT(*) FROM users GROUP BY country").fetchall()
        for country_val, cnt in rows:
            if country_val in counts:
                counts[country_val] = int(cnt or 0)
            else:
                counts["Unset"] += int(cnt or 0)
    return counts


def get_seen_images(user_id):
    uid = str(user_id)
    with get_conn() as conn:
        rows = conn.execute("SELECT image_url FROM seen_images WHERE user_id = ?", (uid,)).fetchall()
        return {r[0] for r in rows if r and r[0]}


def add_seen_image(user_id, image_url):
    uid = str(user_id)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_images (user_id, image_url) VALUES (?, ?)",
            (uid, image_url)
        )
        conn.commit()


def reset_seen_images(user_id):
    uid = str(user_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM seen_images WHERE user_id = ?", (uid,))
        conn.commit()


def get_order_details(order_id):
    oid = str(order_id).strip()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, phone, amount, status FROM orders WHERE order_id = ?",
            (oid,)
        ).fetchone()
        return row


def log_broadcast_click(user_id, target_url):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO broadcast_clicks (user_id, target_url, clicked_at) VALUES (?, ?, ?)",
            (str(user_id), target_url, str(datetime.utcnow()))
        )
        conn.commit()


def track_user_message(user_id, chat_id, message_id, sent_at):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tracked_messages (user_id, chat_id, message_id, sent_at) VALUES (?, ?, ?, ?)",
            (str(user_id), int(chat_id), int(message_id), float(sent_at))
        )
        conn.commit()


def get_expired_messages(cutoff_ts):
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, user_id, chat_id, message_id FROM tracked_messages WHERE sent_at <= ?",
            (float(cutoff_ts),)
        ).fetchall()


def delete_tracked_messages_by_ids(row_ids):
    if not row_ids:
        return
    placeholders = ",".join("?" for _ in row_ids)
    with get_conn() as conn:
        conn.execute(f"DELETE FROM tracked_messages WHERE id IN ({placeholders})", list(row_ids))
        conn.commit()
