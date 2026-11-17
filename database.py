import sqlite3
import os
from datetime import datetime

# Define the persistent directory and database path
DB_DIR = "/data"
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "bot_database.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
            status TEXT,
            product_id INTEGER
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
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            price INTEGER,
            sales_media_type TEXT,
            sales_media_file_id TEXT,
            sales_caption TEXT,
            button_text TEXT,
            success_media_type TEXT,
            success_media_file_id TEXT,
            success_caption TEXT,
            success_btn_text TEXT,
            success_btn_url TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name, date):
    conn = sqlite3.connect(DB_PATH)
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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referred_id = ?", (str(referred_id),))
    if cursor.fetchone()[0] > 0:
        conn.close()
        return False
    try:
        cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (str(referrer_id), str(referred_id)))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_referral_count(referrer_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (str(referrer_id),))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_total_users_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_seen_images(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT image_url FROM seen_images WHERE user_id = ?", (str(user_id),))
    images = [row[0] for row in cursor.fetchall()]
    conn.close()
    return images

def add_seen_image(user_id, image_url):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO seen_images (user_id, image_url) VALUES (?, ?)", (str(user_id), image_url))
    conn.commit()
    conn.close()

def reset_seen_images(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM seen_images WHERE user_id = ?", (str(user_id),))
    conn.commit()
    conn.close()

def save_order(order_id, user_id, phone, amount, status, product_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO orders (order_id, user_id, phone, amount, status, product_id) VALUES (?, ?, ?, ?, ?, ?)",
                   (order_id, str(user_id), phone, amount, status, product_id))
    conn.commit()
    conn.close()

def update_order_status(order_id, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ? WHERE order_id = ?", (status, order_id))
    conn.commit()
    conn.close()

def get_order_details(order_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, phone, amount, status, product_id FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def is_user_activated(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (str(user_id),))
    if cursor.fetchone()[0] >= 10:
        conn.close()
        return True
    cursor.execute("SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = 'completed'", (str(user_id),))
    completed = cursor.fetchone()[0]
    conn.close()
    return completed > 0

def log_broadcast_click(user_id, target_url):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO broadcast_clicks (user_id, target_url, clicked_at) VALUES (?, ?, ?)",
                   (str(user_id), target_url, str(datetime.utcnow())))
    conn.commit()
    conn.close()

def get_click_count_for_url(target_url):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM broadcast_clicks WHERE target_url = ?", (target_url,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def save_product(price, sales_media_type, sales_media_file_id, sales_caption, button_text, success_media_type, success_media_file_id, success_caption, success_btn_text, success_btn_url):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO products (price, sales_media_type, sales_media_file_id, sales_caption, button_text, success_media_type, success_media_file_id, success_caption, success_btn_text, success_btn_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (price, sales_media_type, sales_media_file_id, sales_caption, button_text, success_media_type, success_media_file_id, success_caption, success_btn_text, success_btn_url, str(datetime.utcnow())))
    prod_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return prod_id

def get_product(product_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT product_id, price, sales_media_type, sales_media_file_id, sales_caption, button_text, success_media_type, success_media_file_id, success_caption, success_btn_text, success_btn_url FROM products WHERE product_id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()
    return row
    
