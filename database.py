import sqlite3
from datetime import datetime

def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id TEXT,
            referred_id TEXT,
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
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name, date):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, first_name, joined_date) 
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
        username=excluded.username, 
        first_name=excluded.first_name
    """, (str(user_id), username, first_name, date))
    conn.commit()
    conn.close()

def add_referral(referrer_id, referred_id):
    if str(referrer_id) == str(referred_id):
        return False
    
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referred_id = ?", (str(referred_id),))
    already_referred = cursor.fetchone()[0]
    if already_referred > 0:
        conn.close()
        return False

    try:
        cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", 
                       (str(referrer_id), str(referred_id)))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_referral_count(referrer_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (str(referrer_id),))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_users():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_total_users_count():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_seen_images(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT image_url FROM seen_images WHERE user_id = ?", (str(user_id),))
    images = [row[0] for row in cursor.fetchall()]
    conn.close()
    return images

def add_seen_image(user_id, image_url):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO seen_images (user_id, image_url) VALUES (?, ?)", (str(user_id), image_url))
    conn.commit()
    conn.close()

def reset_seen_images(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM seen_images WHERE user_id = ?", (str(user_id),))
    conn.commit()
    conn.close()

def save_order(order_id, user_id, phone, amount, status):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO orders (order_id, user_id, phone, amount, status) VALUES (?, ?, ?, ?, ?)",
                   (order_id, str(user_id), phone, amount, status))
    conn.commit()
    conn.close()

def update_order_status(order_id, status):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))
    conn.commit()
    conn.close()

def get_order_details(order_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, phone, amount, status FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def is_user_activated(user_id):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (str(user_id),))
    ref_count = cursor.fetchone()[0]
    if ref_count >= 10:
        conn.close()
        return True
    
    cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'completed'", (str(user_id),))
    completed_orders = cursor.fetchone()[0]
    conn.close()
    if completed_orders > 0:
        return True
        
    return False

def log_broadcast_click(user_id, target_url):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO broadcast_clicks (user_id, target_url, clicked_at) VALUES (?, ?, ?)",
                   (str(user_id), target_url, str(datetime.utcnow())))
    conn.commit()
    conn.close()

def get_click_count_for_url(target_url):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM broadcast_clicks WHERE target_url = ?", (target_url,))
    count = cursor.fetchone()[0]
    conn.close()
    return count
    
