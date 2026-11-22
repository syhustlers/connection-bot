import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "/data/bot_database.db")


def get_connection():
    parent_dir = os.path.dirname(DB_PATH)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TEXT,
            country TEXT,
            language TEXT DEFAULT 'sw',
            activated INTEGER DEFAULT 0
        )
    """)

    # Safely migrate existing tables if columns are missing
    cursor.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "country" not in existing_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN country TEXT")
    if "language" not in existing_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'sw'")
    if "activated" not in existing_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN activated INTEGER DEFAULT 0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id TEXT,
            referred_id TEXT UNIQUE,
            created_at TEXT,
            UNIQUE(referrer_id, referred_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_images (
            user_id TEXT,
            image_url TEXT,
            UNIQUE(user_id, image_url)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            user_id TEXT,
            phone TEXT,
            amount INTEGER,
            status TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_clicks (
            click_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            target_url TEXT,
            clicked_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracked_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            chat_id TEXT,
            message_id INTEGER,
            created_ts REAL
        )
    """)

    conn.commit()
    conn.close()


def user_exists(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (str(user_id),))
    found = cursor.fetchone() is not None
    conn.close()
    return found


def add_user(user_id, username, first_name, date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, first_name, joined_date, language, activated)
        VALUES (?, ?, ?, ?, 'sw', 0)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, users.username),
            first_name = COALESCE(excluded.first_name, users.first_name)
    """, (str(user_id), username, first_name, str(date)))
    conn.commit()
    conn.close()


def set_user_country(user_id, country):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, country, language, activated, joined_date)
        VALUES (?, ?, 'sw', 0, ?)
        ON CONFLICT(user_id) DO UPDATE SET country = excluded.country
    """, (str(user_id), country, str(datetime.utcnow())))
    conn.commit()
    conn.close()


def get_user_country(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT country FROM users WHERE user_id = ?", (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def set_user_language(user_id, lang):
    lang_clean = "en" if str(lang).lower() in ("en", "english") else "sw"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, language, activated, joined_date)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(user_id) DO UPDATE SET language = excluded.language
    """, (str(user_id), lang_clean, str(datetime.utcnow())))
    conn.commit()
    conn.close()


def get_user_language(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] in ("sw", "en") else "sw"


def set_user_activated(user_id, status=True):
    val = 1 if status else 0
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, language, activated, joined_date)
        VALUES (?, 'sw', ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET activated = excluded.activated
    """, (str(user_id), val, str(datetime.utcnow())))
    conn.commit()
    conn.close()


def add_referral_new_user_only(referrer_id, referred_id, was_existing_user):
    # Strictly block existing users, self-referrals, and invalid IDs
    if was_existing_user:
        return False
    if not referrer_id or str(referrer_id) == str(referred_id):
        return False
    if not str(referrer_id).isdigit():
        return False

    conn = get_connection()
    cursor = conn.cursor()

    # Ensure referrer exists in users table so fake/random IDs cannot farm counts
    cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (str(referrer_id),))
    if cursor.fetchone() is None:
        conn.close()
        return False

    # Ensure referred user has never been counted before
    cursor.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (str(referred_id),))
    if cursor.fetchone() is not None:
        conn.close()
        return False

    try:
        cursor.execute(
            "INSERT INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)",
            (str(referrer_id), str(referred_id), str(datetime.utcnow()))
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_referral_count(referrer_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (str(referrer_id),))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


def get_total_users_count():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_users_by_country_counts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(country, 'Unset'), COUNT(*) FROM users GROUP BY COALESCE(country, 'Unset')")
    rows = cursor.fetchall()
    conn.close()
    counts = {"Tanzania": 0, "Kenya": 0, "Uganda": 0, "Unset": 0}
    for country_name, cnt in rows:
        key = country_name if country_name in ("Tanzania", "Kenya", "Uganda") else "Unset"
        counts[key] += cnt
    return counts


def get_seen_images(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT image_url FROM seen_images WHERE user_id = ?", (str(user_id),))
    images = [row[0] for row in cursor.fetchall()]
    conn.close()
    return images


def add_seen_image(user_id, image_url):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO seen_images (user_id, image_url) VALUES (?, ?)",
        (str(user_id), image_url)
    )
    conn.commit()
    conn.close()


def reset_seen_images(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM seen_images WHERE user_id = ?", (str(user_id),))
    conn.commit()
    conn.close()


def save_order(order_id, user_id, phone, amount, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO orders (order_id, user_id, phone, amount, status) VALUES (?, ?, ?, ?, ?)",
        (order_id, str(user_id), phone, amount, status)
    )
    conn.commit()
    conn.close()


def update_order_status(order_id, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))
    conn.commit()
    conn.close()


def get_order_details(order_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, phone, amount, status FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def is_user_activated(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT activated FROM users WHERE user_id = ?", (str(user_id),))
    u_row = cursor.fetchone()
    if u_row and int(u_row[0] or 0) == 1:
        conn.close()
        return True

    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (str(user_id),))
    ref_count = cursor.fetchone()[0]
    if ref_count >= 10:
        conn.close()
        return True

    cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'completed'", (str(user_id),))
    completed_orders = cursor.fetchone()[0]
    conn.close()
    return completed_orders > 0


def log_broadcast_click(user_id, target_url):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO broadcast_clicks (user_id, target_url, clicked_at) VALUES (?, ?, ?)",
        (str(user_id), target_url, str(datetime.utcnow()))
    )
    conn.commit()
    conn.close()


def get_click_count_for_url(target_url):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM broadcast_clicks WHERE target_url = ?", (target_url,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def track_user_message(user_id, chat_id, message_id, created_ts):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tracked_messages (user_id, chat_id, message_id, created_ts) VALUES (?, ?, ?, ?)",
        (str(user_id), str(chat_id), int(message_id), float(created_ts))
    )
    conn.commit()
    conn.close()


def get_expired_messages(cutoff_ts):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, chat_id, message_id FROM tracked_messages WHERE created_ts <= ?",
        (float(cutoff_ts),)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_tracked_messages_by_ids(row_ids):
    if not row_ids:
        return
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in row_ids)
    cursor.execute(f"DELETE FROM tracked_messages WHERE id IN ({placeholders})", row_ids)
    conn.commit()
    conn.close()
