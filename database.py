import sqlite3

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
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name, date):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, joined_date) VALUES (?, ?, ?, ?)", 
                   (str(user_id), username, first_name, date))
    conn.commit()
    conn.close()

def add_referral(referrer_id, referred_id):
    if str(referrer_id) == str(referred_id):
        return False
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
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
