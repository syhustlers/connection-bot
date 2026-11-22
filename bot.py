import os
import re
import time
import random
import asyncio
import logging
from datetime import datetime
from urllib.parse import quote
from flask import Flask, request, redirect
from threading import Thread

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    InputMediaPhoto, InputMediaVideo
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)

from database import (
    init_db, user_exists, add_user, set_user_country, get_user_country,
    set_user_language, get_user_language, set_user_activated,
    add_referral_new_user_only, get_referral_count, get_all_users,
    get_total_users_count, get_users_by_country_counts,
    get_seen_images, add_seen_image, reset_seen_images,
    get_order_details, is_user_activated,
    log_broadcast_click,
    track_user_message, get_expired_messages, delete_tracked_messages_by_ids,
    DB_PATH
)

# --- ENVIRONMENT CONFIGS ---
MAIN_BOT_TOKEN = os.environ.get("MAIN_BOT_TOKEN", "")
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "")
ADMIN_ID = os.environ.get("ADMIN_ID", "")
ACTIVATION_SECRET_CODE = os.environ.get("ACTIVATION_SECRET_CODE", "").strip()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "connectiontzzbot").lstrip("@")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://connection-bot.onrender.com").rstrip("/")

# --- LINKS & CHANNELS ---
CPA_LINK = "https://tinyurl.com/Activebot"
PAY_LINK_TZ = "https://nexus.stanyxpro.com/pay/connection-bot-subscription-mwpyeqqj"
PAY_LINK_KE = "https://nexus.stanyxpro.com/pay/connection-bot-subscription-mwrg696v"
PAY_LINK_UG = "https://nexus.stanyxpro.com/pay/connection-bot-subscription-mwrgfhtt"
PAY_LINK_INTL = "https://nexus.stanyxpro.com/pay/connection-bot-subscription-mwrgc952"

TARGET_SITE = "https://www.tanzaniaraha.com/"
REQUIRED_CHANNEL = "@connectiontzz"

TWO_DAYS_SECONDS = 48 * 3600

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Anti-spam cooldown store
user_cooldowns = {}

# Admin pending input modes
ADMIN_MODE_ORDER = "order"
ADMIN_MODE_BROADCAST = "broadcast"

# Pending multi-media broadcast drafts per admin user: {admin_id: {"items": [...], "text": ""}}
admin_broadcast_drafts = {}


async def check_antispam(user_id):
    now = time.time()
    last_time = user_cooldowns.get(str(user_id))
    if last_time and (now - last_time) < 0.7:
        return False
    user_cooldowns[str(user_id)] = now
    return True


async def send_and_track(bot, user_id, chat_id, send_coro):
    sent = await send_coro
    if sent and getattr(sent, "message_id", None):
        track_user_message(user_id, chat_id, sent.message_id, time.time())
    return sent


# --- COUNTRY ADMINISTRATIVE REGIONS ---
REGIONS_BY_COUNTRY = {
    "Tanzania": [
        "Dar es Salaam", "Arusha", "Mwanza", "Dodoma", "Geita", "Iringa", "Kagera", "Katavi", "Kigoma",
        "Kilimanjaro", "Lindi", "Manyara", "Mara", "Mbeya", "Morogoro", "Mtwara", "Njombe", "Pwani",
        "Rukwa", "Ruvuma", "Shinyanga", "Simiyu", "Singida", "Tabora", "Tanga", "Zanzibar"
    ],
    "Kenya": [
        "Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet", "Embu", "Garissa", "Homa Bay",
        "Isiolo", "Kajiado", "Kakamega", "Kericho", "Kiambu", "Kilifi", "Kirinyaga", "Kisii",
        "Kisumu", "Kitui", "Kwale", "Laikipia", "Lamu", "Machakos", "Makueni", "Mandera",
        "Marsabit", "Meru", "Migori", "Mombasa", "Murang'a", "Nairobi", "Nakuru", "Nandi",
        "Narok", "Nyamira", "Nyandarua", "Nyeri", "Samburu", "Siaya", "Taita-Taveta", "Tana River",
        "Tharaka-Nithi", "Trans-Nzoia", "Turkana", "Uasin Gishu", "Vihiga", "Wajir", "West Pokot"
    ],
    "Uganda": [
        "Kampala", "Wakiso", "Mukono", "Jinja", "Gulu", "Mbarara", "Mbale", "Arua", "Lira", "Masaka",
        "Entebbe", "Hoima", "Fort Portal", "Kasese", "Kabale", "Soroti", "Moroto", "Tororo",
        "Iganga", "Luweero", "Mityana", "Masindi", "Bushenyi", "Rukungiri", "Ntungamo", "Kapchorwa",
        "Kitgum", "Nebbi", "Pallisa", "Kamuli", "Apac", "Adjumani", "Koboko", "Yumbe", "Mubende", "Kyenjojo"
    ]
}

ALL_REGIONS = {
    reg for region_list in REGIONS_BY_COUNTRY.values() for reg in region_list
}

SWITCH_KB_LABELS = {"🌍 Nchi / Lugha", "🌍 Country / Lang"}


def get_region_keyboard(country=None, lang="sw"):
    selected_country = country if country in REGIONS_BY_COUNTRY else "Tanzania"
    regions = REGIONS_BY_COUNTRY[selected_country]
    keyboard = []
    idx = 0
    row_pattern = [1, 2, 1, 3, 1, 2, 1, 3, 1, 2, 1, 3, 1, 2, 1, 1]
    for count in row_pattern:
        if idx >= len(regions):
            break
        row = [KeyboardButton(regions[idx + j]) for j in range(min(count, len(regions) - idx))]
        keyboard.append(row)
        idx += count
    while idx < len(regions):
        row = [KeyboardButton(regions[idx])]
        if idx + 1 < len(regions):
            row.append(KeyboardButton(regions[idx + 1]))
            idx += 2
        else:
            idx += 1
        keyboard.append(row)

    switch_label = "🌍 Country / Lang" if lang == "en" else "🌍 Nchi / Lugha"
    keyboard.append([KeyboardButton(switch_label)])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def detect_country_for_region(region_text, user_country=None):
    if user_country in REGIONS_BY_COUNTRY and region_text in REGIONS_BY_COUNTRY[user_country]:
        return user_country
    for c_name, r_list in REGIONS_BY_COUNTRY.items():
        if region_text in r_list:
            return c_name
    return user_country or "Tanzania"


NAMES = [
    "Asha", "Neema", "Amina", "Rehema", "Subira", "Zainabu", "Mariam", "Sophia", "Latifa", "Yasmin",
    "Tatu", "Zuhura", "Janet", "Vero", "Happy", "Joyce", "Stella", "Lilian", "Agnes", "Mwanahamis",
    "Fatma", "Saida", "Zakia", "Fatuma", "Jamila", "Hadija", "Mariamu", "Salma", "Mwanahawa", "Sharifa",
    "Khadija", "Mwanaidi", "Saada", "Zainab", "Mwashamba", "Mwanaisha", "Asia", "Mwamvita", "Mwamini", "Kulthum",
    "Mwatima", "Mwashiuya", "Hafsa", "Halima", "Rukia", "Mtumwa", "Muna", "Mwajuma", "Mwaka", "Siti",
    "Zulekha", "Sakina", "Mwanne", "Mwajabu", "Batuli", "Vanessa", "Sarah", "Irene", "Diana", "Natasha",
    "Linda", "Elizabeth", "Jackline", "Grace", "Naomi", "Brenda", "Judith", "Carol", "Mercy", "Ruth",
    "Catherine", "Joan", "Gloria", "Lucy", "Rose", "Florence", "Winnie", "Veronica", "Angel", "Faith",
    "Hope", "Nancy", "Sylvia", "Belinda", "Miriam", "Dorcas", "Queen", "Precious", "Rebecca", "Deborah",
    "Tina", "Aida", "Flora", "Anita", "Rashida", "Zuleha", "Magreth", "Zaina", "Glory", "Aisha",
    "Rahma", "Nuru", "Zawadi", "Imani", "Pendo", "Tumaini", "Samira", "Shamim", "Najma", "Nadia",
    "Hawa", "Asma", "Aziza", "Husna", "Inaya", "Iqra", "Jannat", "Khadra", "Laila", "Leila",
    "Marwa", "Munira", "Nabila", "Nafisa", "Nasra", "Ruqayya", "Safia", "Safa", "Samia", "Sanaa",
    "Shakira", "Shukria", "Sumaya", "Tahira", "Tamima", "Tasneem", "Uzuri", "Warda", "Yumna", "Zahara",
    "Zahra", "Zamzam", "Zarina", "Adela", "Adriana", "Alexandra", "Alice", "Amanda", "Amelia", "Amy",
    "Andrea", "Angela", "Anna", "Anne", "Ariana", "Ashley", "Audrey", "Barbara", "Bianca", "Brianna",
    "Camila", "Chantal", "Charlotte", "Cheryl", "Christina", "Claire", "Clara", "Claudia", "Danielle", "Darlene",
    "Delia", "Eleanor", "Elena", "Ella", "Emily", "Emma", "Erica", "Esther", "Eva", "Evelyn",
    "Fiona", "Gabriella", "Gemma", "Georgia", "Gillian", "Hannah", "Harriet", "Isabella", "Isabelle", "Jasmine",
    "Jennifer", "Jessica", "Jillian", "Josephine", "Julia", "Juliana", "Karen", "Kayla", "Kelly", "Kimberly",
    "Kristina", "Laura", "Lauren", "Leah", "Leslie", "Lydia", "Madeline", "Madison", "Maria", "Marina",
    "Marissa", "Martha", "Melissa", "Michelle", "Monica", "Morgan", "Natalie", "Nicole", "Olivia", "Pamela",
    "Patricia", "Paula", "Rachel", "Rachael", "Rosemary", "Samantha", "Sandra", "Savannah", "Sharon", "Sheila",
    "Sonia", "Stephanie", "Susan", "Suzanne", "Tamara", "Teresa", "Theresa", "Tracy", "Valerie", "Victoria",
    "Virginia", "Vivian", "Whitney", "Yvonne", "Zoe", "Abigail", "Adeline", "Alicia", "Alisha", "Alma",
    "Amber", "Anastasia", "Annette", "April", "Aubrey", "Beatrice", "Beth", "Bethany", "Beverly", "Bonnie",
    "Candice", "Caroline", "Cassie", "Cecilia", "Celeste", "Cynthia", "Daisy", "Dakota", "Daphne", "Destiny",
    "Elisa", "Elise", "Eliza", "Elsie", "Emilia", "Esme", "Eunice", "Felicia", "Gabrielle", "Giselle",
    "Hailey", "Heidi", "Helen", "Isabel", "Jade", "Jamie", "Janelle", "Janice", "Jenna", "Jenny",
    "Jocelyn", "Jordan", "Kaitlyn", "Katherine", "Kathleen", "Kendra", "Kiara", "Kylie", "Lara", "Lexi",
    "Lola", "Lorraine", "Lucia", "Lucille", "Maggie", "Margaret", "Mariah", "Marilyn", "Maya", "Megan",
    "Melanie", "Molly", "Monique", "Myra", "Nadine", "Natalia", "Nathalie", "Nina", "Noelle", "Olive",
    "Ophelia", "Paris", "Penelope", "Phoebe", "Priscilla", "Renee", "Rita", "Ruby", "Sabrina", "Sadie",
    "Selena", "Serena", "Shanice", "Shannon", "Skylar", "Sophie", "Stacy", "Summer", "Sydney", "Tanya",
    "Tara", "Tasha", "Taylor", "Tiffany", "Toni", "Valentina", "Violet", "Vivienne", "Wendy", "Willow",
    "Ximena", "Yvette", "Zelda", "Alina", "Amara", "Amani", "Anaya", "Ariel", "Athena", "Bella",
    "Brielle", "Carmen", "Celina", "Dalia", "Eliana", "Jada", "Jalia", "Jemima", "Jovina", "Kadija",
    "Kibibi", "Koku", "Maimuna", "Malkia", "Maryam", "Maua", "Mboni", "Mchome", "Mgeni", "Minah",
    "Mishka", "Mubarak", "Munawwar", "Mwana", "Mwanajuma", "Mwanamisi", "Mwanashujaa", "Mwanatatu", "Mwanahamisi", "Mwanasiti",
    "Mwanawema", "Najat", "Nawal", "Nazia", "Pendo", "Riziki", "Sabina", "Sada", "Sadaka", "Safina",
    "Safiya", "Salima", "Sausan", "Shanaz", "Shani", "Shukri", "Sumaiya", "Tabitha", "Talia", "Tausi",
    "Tunu", "Ummi", "Wema", "Widad", "Yasmeen", "Yasmina", "Zawiya", "Zuleika", "Zubeda"
]

IMAGES = [
    "https://i.postimg.cc/vm1M8nbg/1791854037257.jpg",
    "https://i.postimg.cc/fynkD7PG/1791906305237.jpg",
    "https://i.postimg.cc/G2s9WgXM/1791906329014.jpg",
    "https://i.postimg.cc/50FjhKs8/1791906348662.jpg",
    "https://i.postimg.cc/LsWn0F3Z/1791906353383.jpg",
    "https://i.postimg.cc/BvzXwfBn/1791906371572.jpg",
    "https://i.postimg.cc/bv5sFf9p/1791906389122.jpg",
    "https://i.postimg.cc/hGYf3Rb6/1791906398043.jpg",
    "https://i.postimg.cc/FKzYZHcn/1791906408155.jpg",
    "https://i.postimg.cc/qvjty3tQ/1791906420123.jpg",
    "https://i.postimg.cc/VkDSnCSC/1791906435675.jpg",
    "https://i.postimg.cc/MpdcVQcG/1791906509109.jpg",
    "https://i.postimg.cc/pL2hmZdH/1791906519102.jpg",
    "https://i.postimg.cc/kgn62cgZ/1791906531737.jpg",
    "https://i.postimg.cc/jd6nq9tp/1791906554920.jpg",
    "https://i.postimg.cc/Prn8jhs1/1791906567161.jpg",
    "https://i.postimg.cc/SNLYQ5kz/1791906700847.jpg",
    "https://i.postimg.cc/VsCbpvTY/1791907006897.jpg",
    "https://i.postimg.cc/KjBkMpLF/1791907063155.jpg",
    "https://i.postimg.cc/W41kHnRm/1791907077162.jpg",
    "https://i.postimg.cc/pdcFbFRm/1791907110977.jpg",
    "https://i.postimg.cc/qv0n8r1r/1791907157738.jpg",
    "https://i.postimg.cc/7PGg4mCq/1791907177809.jpg",
    "https://i.postimg.cc/TYngL1qg/1791907187355.jpg",
    "https://i.postimg.cc/nrD71h8s/1791907232480.jpg",
    "https://i.postimg.cc/BvmxSz5g/1791907255159.jpg",
    "https://i.postimg.cc/RCyLJ2ky/1791907265005.jpg",
    "https://i.postimg.cc/zD6FH9mY/1791907420672.jpg",
    "https://i.postimg.cc/k4ZSHKwX/1791907434486.jpg",
    "https://i.postimg.cc/xCqHgtvw/1791907438118.jpg",
    "https://i.postimg.cc/zfxKn9gn/1791907596816.jpg",
    "https://i.postimg.cc/DwdqzWyF/1791907641145.jpg",
    "https://i.postimg.cc/xTmvWxwz/1791910862948.jpg",
    "https://i.postimg.cc/gkhVfSCY/1791910868033.jpg",
    "https://i.postimg.cc/pT1QtgVr/1791910912470.jpg",
    "https://i.postimg.cc/T1zrKgD1/1791910946659.jpg",
    "https://i.postimg.cc/wvB5Z6pn/1791910964051.jpg",
    "https://i.postimg.cc/KjpJY1Z3/1791853362972.jpg",
    "https://i.postimg.cc/QCdfsQrD/1791853387431.jpg",
    "https://i.postimg.cc/VNXGFsRm/1791853420218.jpg",
    "https://i.postimg.cc/RF9PprsG/1791853437567.jpg",
    "https://i.postimg.cc/6QCjh6hg/1791853443814.jpg",
    "https://i.postimg.cc/RZkpfJc5/1791853514748.jpg",
    "https://i.postimg.cc/wTbGqGvZ/1791853572314.jpg",
    "https://i.postimg.cc/L60b9bXQ/1791853590912.jpg",
    "https://i.postimg.cc/XNLPhJ0G/1791853597063.jpg",
    "https://i.postimg.cc/8k4Y35VN/1791853626887.jpg",
    "https://i.postimg.cc/zvxPRdkK/1791853632479.jpg",
    "https://i.postimg.cc/vBLKG8gJ/1791853652329.jpg",
    "https://i.postimg.cc/ydz5q3dZ/1791853657412.jpg",
    "https://i.postimg.cc/7LzcQnqs/1791853668145.jpg",
    "https://i.postimg.cc/DwHHgM31/1791853710537.jpg",
    "https://i.postimg.cc/nhCNqtgZ/1791853718953.jpg",
    "https://i.postimg.cc/28js8Wxn/1791853736371.jpg",
    "https://i.postimg.cc/5NPZHt7W/1791853769688.jpg",
    "https://i.postimg.cc/sDfkDWJ7/1791853788828.jpg",
    "https://i.postimg.cc/Y2xcHRYs/1791853824076.jpg",
    "https://i.postimg.cc/vBFRQSPZ/1791853832194.jpg",
    "https://i.postimg.cc/C1TyF6vZ/1791853857553.jpg",
    "https://i.postimg.cc/QMWGZrJc/1791853862653.jpg",
    "https://i.postimg.cc/1zNh1Zrw/1791853873837.jpg",
    "https://i.postimg.cc/W4QVd44s/1791853893484.jpg",
    "https://i.postimg.cc/43rGY3xS/1791853899906.jpg",
    "https://i.postimg.cc/jjWKqft4/1791853912049.jpg",
    "https://i.postimg.cc/Gmgd1KwL/1791853917098.jpg",
    "https://i.postimg.cc/Bv8sZF4T/1791853946091.jpg",
    "https://i.postimg.cc/JzzMggFd/1791854075161.jpg",
    "https://i.postimg.cc/ZKZTP0xb/1791854086618.jpg",
    "https://i.postimg.cc/YSX4ZY8R/malay-atz-20261013-0001.webp",
    "https://i.postimg.cc/q7pMkqgW/nicklamaar-20261013-0001.jpg",
    "https://i.postimg.cc/bvLYdPtZ/tanzania-baddies-20261013-0001.webp",
    "https://i.postimg.cc/mrVZh4H4/tanzania-baddies-20261013-0002.webp",
    "https://i.postimg.cc/ZqjY0mdT/tanzania-baddies-20261013-0003.webp",
    "https://i.postimg.cc/Xv2Zmdxk/tanzanian-girls-20261013-0001.webp",
    "https://i.postimg.cc/5tPHTLpm/tanzanian-girls-20261013-0002.webp",
    "https://i.postimg.cc/VN7Spn4R/tanzanian-girls-20261013-0003.webp",
    "https://i.postimg.cc/tgRZB2dX/tanzanian-girls-20261013-0004.webp",
    "https://i.postimg.cc/HLWc6B0D/tanzanian-girls-20261013-0005.webp",
    "https://i.postimg.cc/LsMWfLDR/tanzanian-girls-20261114-0011.webp",
    "https://i.postimg.cc/MpB4vd7p/tanzanian-girls-20261114-0012.webp",
    "https://i.postimg.cc/YCFVhb62/tanzanian-girls-20261114-0013.webp",
    "https://i.postimg.cc/7Zzcfm3r/tanzanian-girls-20261114-0014.webp",
    "https://i.postimg.cc/y8R5kvmz/tanzanian-girls-20261114-0015.webp",
    "https://i.postimg.cc/vZnjc3WC/tanzanian-girls-20261114-0016.webp",
    "https://i.postimg.cc/3xG6dngq/tanzanian-girls-20261114-0017.webp",
    "https://i.postimg.cc/HkMKVBQP/tanzanian-girls-20261114-0018.webp",
    "https://i.postimg.cc/dVCXL48W/tanzanian-girls-20261114-0019.webp",
    "https://i.postimg.cc/9Q9SrJG8/tanzanian-girls-20261114-0020.webp",
    "https://i.postimg.cc/YCFVhb1x/tanzanian-girls-20261114-0021.webp",
    "https://i.postimg.cc/65ggWDGY/tanzanian-girls-20261114-0022.webp",
    "https://i.postimg.cc/gkQQzf6s/tanzanian-girls-20261114-0023.webp",
    "https://i.postimg.cc/sgW8vwp4/tanzanian-girls-20261114-0024.webp",
    "https://i.postimg.cc/yYtt1wSP/tanzanian-girls-20261114-0025.webp",
    "https://i.postimg.cc/NfSSsWr7/tanzanian-girls-20261114-0026.webp",
    "https://i.postimg.cc/kXzzJktN/tanzanian-girls-20261114-0027.webp",
    "https://i.postimg.cc/rF33Vvt5/tanzanian-girls-20261114-0028.webp",
    "https://i.postimg.cc/pX44Wgnz/tanzanian-girls-20261114-0029.webp",
    "https://i.postimg.cc/hP66DH7z/tanzanian-girls-20261114-0030.webp",
    "https://i.postimg.cc/9FKKmvq4/tanzanian-girls-20261114-0031.webp",
    "https://i.postimg.cc/qMzWdkg6/tanzanian-girls-20261114-0032.webp",
    "https://i.postimg.cc/fTppz60y/tanzanian-girls-20261114-0033.webp",
    "https://i.postimg.cc/zXV41J3J/tanzanian-girls-20261114-0034.webp",
    "https://i.postimg.cc/ncCNtHMF/tanzanian-girls-20261114-0035.webp",
    "https://i.postimg.cc/m2tKGbk0/tanzanian-girls-20261114-0036.webp",
    "https://i.postimg.cc/MKvg8WHg/tanzanian-girls-20261114-0037.webp",
    "https://i.postimg.cc/59PDGH4T/tanzanian-girls-20261114-0038.webp",
    "https://i.postimg.cc/ZYfXg9bg/tanzanian-girls-20261114-0039.webp",
    "https://i.postimg.cc/dQWgX7sS/tanzanian-girls-20261114-0040.webp",
    "https://i.postimg.cc/FFPwqfrC/tanzanian-girls-20261114-0041.webp",
    "https://i.postimg.cc/BZhRy8SC/tanzanian-girls-20261114-0042.webp",
    "https://i.postimg.cc/jq8B9Wxy/tanzanian-girls-20261114-0043.webp",
    "https://i.postimg.cc/6q1SGPby/tanzanian-girls-20261114-0044.webp",
    "https://i.postimg.cc/nrw5QWSn/tanzanian-girls-20261114-0045.webp",
    "https://i.postimg.cc/T1HSWsNw/tanzanian-girls-20261114-0046.webp",
    "https://i.postimg.cc/Y0yVmPDk/tanzanian-girls-20261114-0047.webp",
    "https://i.postimg.cc/sx08ZLHs/tanzanian-girls-20261114-0048.webp",
    "https://i.postimg.cc/mk6qFnX5/tanzanian-girls-20261114-0049.webp",
    "https://i.postimg.cc/zvPMRQt4/tanzanian-girls-20261114-0050.webp",
    "https://i.postimg.cc/PJq9JH4B/tanzanian-girls-20261114-0051.webp",
    "https://i.postimg.cc/XqvmqW8t/tanzanian-girls-20261114-0052.webp",
    "https://i.postimg.cc/Bbvkb3gV/tanzanian-girls-20261114-0053.webp",
    "https://i.postimg.cc/wMBZMzVP/tanzanian-girls-20261114-0054.webp",
    "https://i.postimg.cc/wMBZMzV4/tanzanian-girls-20261114-0055.webp",
    "https://i.postimg.cc/sx2qxzcw/tanzanian-girls-20261114-0056.webp",
    "https://i.postimg.cc/D0zH0hgQ/tanzanian-girls-20261114-0057.webp",
    "https://i.postimg.cc/FRpwhzjj/tanzanian-girls-20261114-0058.webp",
    "https://i.postimg.cc/2y5MyYw1/tanzanian-girls-20261114-0059.webp",
    "https://i.postimg.cc/pTC3PrD5/tanzanian-girls-20261114-0060.webp",
    "https://i.postimg.cc/nz2Nnrvj/tanzanian-girls-20261114-0061.webp",
    "https://i.postimg.cc/tTk89JhT/tanzanian-girls-20261114-0062.webp",
    "https://i.postimg.cc/j5cBR2z2/tanzanian-girls-20261114-0063.webp",
    "https://i.postimg.cc/ZRHXJnr5/tanzanian-girls-20261114-0064.webp",
    "https://i.postimg.cc/G2K6btkh/tanzanian-girls-20261114-0065.webp",
    "https://i.postimg.cc/9Mbsc0GV/tanzanian-girls-20261114-0066.webp",
    "https://i.postimg.cc/C179w5jg/tanzanian-girls-20261114-0067.webp",
    "https://i.postimg.cc/V6g2zvjz/tanzanian-girls-20261114-0068.webp",
    "https://i.postimg.cc/xC5B98Kr/tanzanian-girls-20261114-0069.webp",
    "https://i.postimg.cc/sXstF7ZC/tanzanian-girls-20261114-0070.webp",
    "https://i.postimg.cc/xCnWrMbf/tanzanian-girls-20261114-0071.webp",
    "https://i.postimg.cc/gJmf986m/tanzanian-girls-20261114-0072.webp",
    "https://i.postimg.cc/d1wzMrTK/tanzanian-girls-20261114-0073.webp",
    "https://i.postimg.cc/1tsLxwVj/tanzanian-girls-20261114-0074.webp"
]


# --- BILINGUAL TEXT & UI HELPERS ---
def get_rotating_profile_title(region_upper, lang):
    if lang == "en":
        options = [
            f"🔥 FRESH IN {region_upper} — ONLINE NOW",
            f"⚡ ACTIVE {region_upper} — AVAILABLE RIGHT NOW",
            f"💎 VERIFIED {region_upper} — INSTANT CONNECTION",
            f"✨ NEW TODAY {region_upper} — READY TO CONNECT"
        ]
    else:
        options = [
            f"🔥 PISI MPYA {region_upper} — ONLINE SASA",
            f"⚡ ACTIVE {region_upper} — ANAPATIKANA SASA HIVI",
            f"💎 VERIFIED {region_upper} — CONNECTION YA HARAKA",
            f"✨ MPYA LEO {region_upper} — TAYARI KUUNGANISHWA"
        ]
    return random.choice(options)


def get_verified_success_text(lang):
    if lang == "en":
        return (
            "🎉 <b>YOUR ACCOUNT IS NOW ACTIVATED!</b> ✅\n\n"
            "Congrats! Your verification is confirmed and you now have full access to VIP connections and exclusive hubs. 💃🔥\n\n"
            "🔗 <b>MAIN CONNECTION PORTAL:</b>\n"
            "👉 <a href=\"https://www.tanzaniaraha.com/\">Open Tanzania Raha</a>\n\n"
            "📢 <b>OFFICIAL VIP CHANNELS & GROUPS:</b>\n"
            "🔗 <a href=\"https://t.me/rawexotichub\">Raw Exotic Hub</a>\n"
            "🔗 <a href=\"https://t.me/hadithizamapenzi\">Hadithi za Mapenzi</a>\n"
            "🔗 <a href=\"https://t.me/hunterjay12345\">Hunter Jay Channel</a>\n"
            "🔗 <a href=\"https://t.me/+4Zp-ZGleL1tlZmU0\">VIP Group 1</a>\n"
            "🔗 <a href=\"https://t.me/+t5wPETWeNGk1NDlk\">VIP Group 2</a>\n"
            "🔗 <a href=\"https://t.me/+nLWCZ_D1zN8zNzg8\">VIP Group 3</a>\n"
            "🔗 <a href=\"https://t.me/+Mn-pvG_YXqQzNTQ0\">VIP Group 4</a>\n"
            "🔗 <a href=\"https://t.me/+xzbacOOTVwkxNjZk\">VIP Group 5</a>\n"
            "🔗 <a href=\"https://t.me/+QeTJSEa1s2xmZTJk\">VIP Group 6</a>\n"
            "🔗 <a href=\"https://t.me/joinchat/AAAAAEzFd9XDWqbcyqXiOg\">Archive & Vault</a>\n\n"
            "👇 <i>Choose an option below or return to your regions:</i>"
        )

    return (
        "🎉 <b>AKAUNTI YAKO IMEWEZESHWA KIKAMILIFU!</b> ✅\n\n"
        "Hongera! Uthibitisho wako umekubaliwa kwenye mfumo na sasa una ufikiaji kamili wa huduma zote za VIP na machapisho ya kipekee. 💃🔥\n\n"
        "🔗 <b>TOVUTI KUU YA CONNECTION:</b>\n"
        "👉 <a href=\"https://www.tanzaniaraha.com/\">Fungua Tanzania Raha</a>\n\n"
        "📢 <b>VIKOSI NA CHANNELS RASMI ZA VIP:</b>\n"
        "🔗 <a href=\"https://t.me/rawexotichub\">Raw Exotic Hub</a>\n"
        "🔗 <a href=\"https://t.me/hadithizamapenzi\">Hadithi za Mapenzi</a>\n"
        "🔗 <a href=\"https://t.me/hunterjay12345\">Hunter Jay Channel</a>\n"
        "🔗 <a href=\"https://t.me/+4Zp-ZGleL1tlZmU0\">VIP Group 1</a>\n"
        "🔗 <a href=\"https://t.me/+t5wPETWeNGk1NDlk\">VIP Group 2</a>\n"
        "🔗 <a href=\"https://t.me/+nLWCZ_D1zN8zNzg8\">VIP Group 3</a>\n"
        "🔗 <a href=\"https://t.me/+Mn-pvG_YXqQzNTQ0\">VIP Group 4</a>\n"
        "🔗 <a href=\"https://t.me/+xzbacOOTVwkxNjZk\">VIP Group 5</a>\n"
        "🔗 <a href=\"https://t.me/+QeTJSEa1s2xmZTJk\">VIP Group 6</a>\n"
        "🔗 <a href=\"https://t.me/joinchat/AAAAAEzFd9XDWqbcyqXiOg\">Archive & Vault</a>\n\n"
        "👇 <i>Chagua huduma unayotaka hapa chini au rudi kwenye mikoa:</i>"
    )


def get_verified_success_keyboard(lang):
    if lang == "en":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 OPEN CONNECTION SITE", url=TARGET_SITE)],
            [
                InlineKeyboardButton("🌍 COUNTRY", callback_data="pick_country"),
                InlineKeyboardButton("🌐 LANGUAGE", callback_data="pick_language")
            ],
            [InlineKeyboardButton("🔙 BACK TO REGIONS", callback_data="back_to_regions")]
        ])

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 FUNGUA TOVUTI YA CONNECTION", url=TARGET_SITE)],
        [
            InlineKeyboardButton("🌍 NCHI", callback_data="pick_country"),
            InlineKeyboardButton("🌐 LUGHA", callback_data="pick_language")
        ],
        [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
    ])


def get_error_403_text(lang):
    if lang == "en":
        return (
            "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\n"
            "Direct connection is temporarily locked. To protect profile privacy, complete one of the verification options below 👇"
        )
    return (
        "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\n"
        "Uunganishwaji umesitishwa kwa muda. Ili kulinda faragha ya mhusika, unahitaji kukamilisha uthibitisho wa mfumo kupitia mojawapo ya njia hapa chini 👇"
    )


def get_error_403_keyboard(lang):
    if lang == "en":
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
                InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")
            ],
            [InlineKeyboardButton("✅ ACTIVATION 3", callback_data="activation3")],
            [
                InlineKeyboardButton("🌍 COUNTRY", callback_data="pick_country"),
                InlineKeyboardButton("🌐 LANGUAGE", callback_data="pick_language")
            ],
            [InlineKeyboardButton("🔙 BACK", callback_data="back")]
        ])

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
            InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")
        ],
        [InlineKeyboardButton("✅ ACTIVATION 3", callback_data="activation3")],
        [
            InlineKeyboardButton("🌍 NCHI", callback_data="pick_country"),
            InlineKeyboardButton("🌐 LUGHA", callback_data="pick_language")
        ],
        [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
    ])


def get_country_keyboard(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇹🇿 Tanzania", callback_data="set_country_Tanzania")],
        [InlineKeyboardButton("🇰🇪 Kenya", callback_data="set_country_Kenya")],
        [InlineKeyboardButton("🇺🇬 Uganda", callback_data="set_country_Uganda")]
    ])


def get_language_keyboard():
    # Same row, two columns: Swahili | English
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇹🇿 Swahili", callback_data="set_lang_sw"),
        InlineKeyboardButton("🇬🇧 English", callback_data="set_lang_en")
    ]])


async def check_membership(bot, user_id):
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=int(user_id))
        if member.status in ["member", "administrator", "creator"]:
            return True
    except Exception:
        pass
    return False


# --- ONBOARDING & PREFERENCE PROMPTS ---
async def send_country_prompt(target_message, lang):
    if lang == "en":
        text = (
            "🌍 <b>SELECT YOUR COUNTRY</b>\n\n"
            "Choose your country below so we load the right regions and local options for you:"
        )
    else:
        text = (
            "🌍 <b>CHAGUA NCHI YAKO</b>\n\n"
            "Chagua nchi yako hapa chini ili tukuletee mikoa na maeneo sahihi ya nchi unayotaka:"
        )
    await target_message.reply_text(text, parse_mode="HTML", reply_markup=get_country_keyboard(lang))


async def send_language_prompt(target_message, lang):
    if lang == "en":
        text = (
            "🌐 <b>CHOOSE LANGUAGE / CHAGUA LUGHA</b>\n\n"
            "Select your preferred language below:"
        )
    else:
        text = (
            "🌐 <b>CHAGUA LUGHA / CHOOSE LANGUAGE</b>\n\n"
            "Chagua lugha unayopendelea kutumia kwenye bot:"
        )
    await target_message.reply_text(text, parse_mode="HTML", reply_markup=get_language_keyboard())


async def proceed_to_regions(message, user_id):
    lang = get_user_language(user_id)
    country = get_user_country(user_id) or "Tanzania"
    if lang == "en":
        welcome_text = (
            f"🍑 Welcome to <b>Tanzania Connection Bot</b> 🔞\n\n"
            f"🌍 Country: <b>{country}</b>\n"
            "📍 Pick your region/area below to browse active connections right now! 💃🔥\n"
            "🆓 Free 24/7 browsing!\n\n"
            "👇 <b>Choose a region from the menu below</b> 👇"
        )
    else:
        welcome_text = (
            f"🍑 Karibu kwenye <b>Tanzania Connection Bot</b> 🔞\n\n"
            f"🌍 Nchi: <b>{country}</b>\n"
            "📍 Chagua mkoa/eneo lako hapa chini uanze kutafuta connection sasa hivi! 💃🔥\n"
            "🆓 Huduma ni <b>BURE 100%</b> masaa 24/7!\n\n"
            "👇 <b>Chagua mkoa/eneo unalotaka kutoka kwenye orodha hapa chini</b> 👇"
        )
    await send_and_track(
        message.get_bot(),
        user_id,
        message.chat_id,
        message.reply_text(welcome_text, parse_mode="HTML", reply_markup=get_region_keyboard(country, lang))
    )


# --- MAIN BOT COMMANDS & HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    existed_before = user_exists(user_id)

    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))

    # Handle deep link payload: either fixed secret activation link or brand-new-user referral
    if context.args:
        payload_arg = context.args[0].strip()

        if ACTIVATION_SECRET_CODE and payload_arg == ACTIVATION_SECRET_CODE:
            set_user_activated(user_id, True)
            lang = get_user_language(user_id)
            success_msg = (
                "✅ <b>ACTIVATION LINK VERIFIED!</b>\n\nYour premium access is now active."
                if lang == "en"
                else "✅ <b>LINK YA ACTIVATION IMETHIBITISHWA!</b>\n\nAkaunti yako ya VIP sasa imewezeshwa kikamilifu."
            )
            await send_and_track(
                context.bot,
                user_id,
                update.effective_chat.id,
                update.message.reply_text(success_msg, parse_mode="HTML")
            )
            await send_and_track(
                context.bot,
                user_id,
                update.effective_chat.id,
                update.message.reply_text(
                    get_verified_success_text(lang),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=get_verified_success_keyboard(lang)
                )
            )
            return

        # Referral check: strictly counts ONLY if user did not exist prior to this /start
        if add_referral_new_user_only(payload_arg, user_id, existed_before):
            try:
                ref_lang = get_user_language(payload_arg)
                notify_text = (
                    "🎉 <b>New Referral Counted!</b>\n\n🔗 A brand-new user joined through your referral link!"
                    if ref_lang == "en"
                    else "🎉 <b>Taarifa ya Mwaliko Mpya!</b>\n\n🔗 Mtumiaji mpya kabisa amejiunga kupitia link yako ya mwaliko!"
                )
                await context.bot.send_message(chat_id=int(payload_arg), text=notify_text, parse_mode="HTML")
            except Exception:
                pass

    lang = get_user_language(user_id)
    age_text = (
        "🔞 <b>SYSTEM AGE VERIFICATION</b>\n\n"
        "This service is strictly for adults (18+). Please confirm your age to continue.\n\n"
        "👇 <b>Choose below:</b>"
        if lang == "en"
        else "🔞 <b>SYSTEM AGE VERIFICATION</b>\n\n"
        "Huduma hii ni maalum kwa ajili ya watu wazima pekee (18+). Tafadhali thibitisha umri wako kuendelea.\n\n"
        "👇 <b>Chagua hapa chini:</b>"
    )
    yes_label = "✅ YES, I AM 18+" if lang == "en" else "✅ NDIO, NINA 18+"
    no_label = "❌ NO" if lang == "en" else "❌ HAPANA"

    await send_and_track(
        context.bot,
        user_id,
        update.effective_chat.id,
        update.message.reply_text(
            age_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(yes_label, callback_data="age_yes"),
                 InlineKeyboardButton(no_label, callback_data="age_no")]
            ])
        )
    )


async def cmd_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lang = get_user_language(user_id)
    await send_country_prompt(update.message, lang)


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lang = get_user_language(user_id)
    await send_language_prompt(update.message, lang)


async def age_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    lang = get_user_language(user_id)
    await query.answer()

    if query.data == "age_no":
        deny_text = (
            "❌ Sorry, you cannot use this bot if you are under 18."
            if lang == "en"
            else "❌ Samahani, huwezi kutumia bot hii ikiwa una chini ya miaka 18."
        )
        await query.message.edit_text(deny_text)
        return

    is_joined = await check_membership(context.bot, query.from_user.id)
    if not is_joined:
        join_text = (
            "📢 <b>JOIN OUR OFFICIAL CHANNEL FIRST!</b>\n\n"
            "To continue using this bot, please join our official channel below:\n\n"
            "👉 <a href=\"https://t.me/connectiontzz\">Join Connection TZZ</a>\n\n"
            "Once joined, tap 'Check Membership' below:"
            if lang == "en"
            else "📢 <b>LAZIMA UJIUNGE NA CHANNEL YETU KWANZA!</b>\n\n"
            "Ili kuendelea kutumia bot hii, tafadhali jiunge na channel yetu rasmi hapa chini:\n\n"
            "👉 <a href=\"https://t.me/connectiontzz\">Jiunge na Connection TZZ</a>\n\n"
            "Baada ya kujiunga, bonyeza kitufe cha 'Kagua Uanachama' hapa chini:"
        )
        btn_join = "📢 JOIN CHANNEL" if lang == "en" else "📢 JIUNGE NA CHANNEL"
        btn_check = "✅ I HAVE JOINED, CONTINUE" if lang == "en" else "✅ NIMESHAJIUNGE, ENDELEA"

        await query.message.edit_text(
            join_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_join, url="https://t.me/connectiontzz")],
                [InlineKeyboardButton(btn_check, callback_data="check_sub")]
            ])
        )
        return

    await send_country_prompt(query.message, lang)


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    if not await check_antispam(user_id):
        return

    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))
    lang = get_user_language(user_id)
    saved_country = get_user_country(user_id)
    text = (update.message.text or "").strip()

    if text in SWITCH_KB_LABELS:
        await send_country_prompt(update.message, lang)
        return

    if text in ALL_REGIONS:
        effective_country = detect_country_for_region(text, saved_country)
        if not saved_country:
            set_user_country(user_id, effective_country)

        hide_kb = await update.message.reply_text(
            "<i>🔄 Loading area details...</i>" if lang == "en" else "<i>🔄 Inapakia taarifa za eneo lako...</i>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        await asyncio.sleep(0.5)
        try:
            await hide_kb.delete()
        except Exception:
            pass

        seen = get_seen_images(user_id)
        available_images = [img for img in IMAGES if img not in seen]
        if not available_images:
            reset_seen_images(user_id)
            available_images = IMAGES

        image_url = random.choice(available_images)
        add_seen_image(user_id, image_url)

        name = random.choice(NAMES)
        age = random.randint(18, 25)
        prefix = random.choice(["07", "06"])
        number = f"<tg-spoiler>{prefix}{random.randint(10, 99)}•••{random.randint(10, 99)}</tg-spoiler>"
        header = get_rotating_profile_title(text.upper(), lang)

        if lang == "en":
            caption = (
                f"{header}\n\n"
                f"💋 <b>NAME:</b> {name}\n"
                f"🎂 <b>AGE:</b> {age} Years\n"
                f"🌍 <b>COUNTRY:</b> {effective_country}\n"
                f"📍 <b>AREA:</b> {text}\n"
                f"📞 <b>PHONE NUMBER:</b> {number}\n"
                f"💎 <b>TYPE:</b> Verified Connection\n\n"
                "👇 <b>Tap the button below to connect immediately</b> 👇"
            )
            btn_connect = "🔗 CONNECT NOW"
            btn_country = "🌍 COUNTRY"
            btn_lang = "🌐 LANGUAGE"
            btn_back_reg = "🔙 BACK TO REGIONS"
        else:
            caption = (
                f"{header}\n\n"
                f"💋 <b>JINA:</b> {name}\n"
                f"🎂 <b>UMRI:</b> {age} Years\n"
                f"🌍 <b>NCHI:</b> {effective_country}\n"
                f"📍 <b>ENEO:</b> {text}\n"
                f"📞 <b>NAMBA YA SIMU:</b> {number}\n"
                f"💎 <b>AINA:</b> Verified Connection\n\n"
                "👇 <b>Bonyeza kitufe hapa chini kuunganishwa nae mara moja</b> 👇"
            )
            btn_connect = "🔗 KUONGANISHWA NAE"
            btn_country = "🌍 NCHI"
            btn_lang = "🌐 LUGHA"
            btn_back_reg = "🔙 RUDI KWENYE MKOA"

        await send_and_track(
            context.bot,
            user_id,
            update.effective_chat.id,
            update.message.reply_photo(
                photo=image_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(btn_connect, callback_data="get_connection")],
                    [
                        InlineKeyboardButton(btn_country, callback_data="pick_country"),
                        InlineKeyboardButton(btn_lang, callback_data="pick_language")
                    ],
                    [InlineKeyboardButton(btn_back_reg, callback_data="back_to_regions")]
                ])
            )
        )
        return

    # Any other text returns user cleanly to their active country's region keyboard
    fallback_text = (
        "📍 <b>Select your region from the menu below:</b>"
        if lang == "en"
        else "📍 <b>Chagua mkoa wako kutoka kwenye orodha hapa chini:</b>"
    )
    await send_and_track(
        context.bot,
        user_id,
        update.effective_chat.id,
        update.message.reply_text(
            fallback_text,
            parse_mode="HTML",
            reply_markup=get_region_keyboard(saved_country or "Tanzania", lang)
        )
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    if not await check_antispam(user_id):
        await query.answer("⚠️ Too fast! Please wait a moment.", show_alert=True)
        return

    await query.answer()
    lang = get_user_language(user_id)
    data = query.data

    if data == "check_sub":
        is_joined = await check_membership(context.bot, query.from_user.id)
        if not is_joined:
            await query.answer(
                "⚠️ You haven't joined the channel yet!" if lang == "en" else "⚠️ Bado hujajiunga na channel! Tafadhali jiunge kwanza.",
                show_alert=True
            )
            return
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_country_prompt(query.message, lang)
        return

    if data == "pick_country":
        await send_country_prompt(query.message, lang)
        return

    if data.startswith("set_country_"):
        chosen_country = data.replace("set_country_", "", 1)
        if chosen_country not in REGIONS_BY_COUNTRY:
            chosen_country = "Tanzania"
        set_user_country(user_id, chosen_country)
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_language_prompt(query.message, lang)
        return

    if data == "pick_language":
        await send_language_prompt(query.message, lang)
        return

    if data.startswith("set_lang_"):
        chosen_lang = "en" if data.endswith("_en") else "sw"
        set_user_language(user_id, chosen_lang)
        try:
            await query.message.delete()
        except Exception:
            pass
        await proceed_to_regions(query.message, user_id)
        return

    if data == "get_connection":
        if is_user_activated(user_id):
            await send_and_track(
                context.bot,
                user_id,
                query.message.chat_id,
                query.message.reply_text(
                    get_verified_success_text(lang),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=get_verified_success_keyboard(lang)
                )
            )
            return

        steps = (
            [
                "<i>🔍 Scanning security servers...</i>",
                "<i>🔄 Looking up profile records...</i>",
                "<i>🔐 Running verification gate...</i>",
                "<i>⚠️ Security firewall restricted direct number access...</i>"
            ]
            if lang == "en"
            else [
                "<i>🔍 Kuchunguza seva za usalama...</i>",
                "<i>🔄 Inatafuta data za mtumiaji...</i>",
                "<i>🔐 Inapitia mfumo wa uthibitisho...</i>",
                "<i>⚠️ Firewall imezuia upatikanaji wa namba...</i>"
            ]
        )
        msg = await query.message.reply_text(steps[0], parse_mode="HTML")
        for s_text in steps[1:]:
            await asyncio.sleep(0.55)
            msg = await msg.edit_text(s_text, parse_mode="HTML")
        await asyncio.sleep(0.55)
        try:
            await msg.delete()
        except Exception:
            pass

        await send_and_track(
            context.bot,
            user_id,
            query.message.chat_id,
            query.message.reply_text(
                get_error_403_text(lang),
                parse_mode="HTML",
                reply_markup=get_error_403_keyboard(lang)
            )
        )
        return

    if data == "activation1":
        if lang == "en":
            text = (
                "🔐 <b>ACTIVATION [1] — COMPLETE EXTERNAL VERIFICATION</b>\n\n"
                "This option unlocks access by completing the required step on our external page. "
                "Full instructions are shown on the page itself—open the link below, complete the step cleanly, "
                "and then return here to continue."
            )
            btn_open = "🌐 OPEN ACTIVATION PAGE"
            btn_back = "🔙 BACK"
        else:
            text = (
                "🔐 <b>ACTIVATION [1] — KAMILISHA HATUA YA TOVUTI</b>\n\n"
                "Njia hii inafungua ufikiaji wako kwa kukamilisha hatua iliyoandaliwa kwenye ukurasa wetu wa nje. "
                "Maelezo kamili yapo kwenye tovuti yenyewe—fungua link hapa chini, maliza hatua hiyo vizuri, "
                "kisha rudi hapa kuendelea."
            )
            btn_open = "🌐 FUNGUA TOVUTI YA ACTIVATION"
            btn_back = "🔙 RUDI"

        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_open, url=CPA_LINK)],
                [InlineKeyboardButton(btn_back, callback_data="back_to_error")]
            ])
        )
        return

    if data == "activation2":
        ref_count = get_referral_count(user_id)
        ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"

        if lang == "en":
            text = (
                "👥 <b>ACTIVATION [2] — 10 NEW REFERRALS (FREE UNLOCK)</b>\n\n"
                "Share your personal invite link with friends or groups. Once <b>10 brand-new users</b> "
                "(people who have never used the bot before) join through your link, your access unlocks automatically for free.\n\n"
                f"🔗 <b>Your Invite Link:</b>\n<code>{ref_link}</code>\n\n"
                f"📊 <b>Verified New Referrals:</b> <code>{ref_count}/10</code>"
            )
            btn_check = "🔄 CHECK COUNT"
            btn_back = "🔙 BACK"
        else:
            text = (
                "👥 <b>ACTIVATION [2] — WAALIKO WAPYA 10 (BURE)</b>\n\n"
                "Sambaza link yako binafsi kwa marafiki au kwenye magroup. Ukifikisha <b>watumiaji wapya 10</b> "
                "(ambao hawajawahi kutumia bot hii kabla) waliojiunga kupitia link yako, utafunguliwa moja kwa moja bure.\n\n"
                f"🔗 <b>Link yako ya Mwaliko:</b>\n<code>{ref_link}</code>\n\n"
                f"📊 <b>Waliojiunga Wapya:</b> <code>{ref_count}/10</code>"
            )
            btn_check = "🔄 CHEKI IDADI"
            btn_back = "🔙 RUDI"

        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_check, callback_data="check_refs")],
                [InlineKeyboardButton(btn_back, callback_data="back_to_error")]
            ])
        )
        return

    if data == "check_refs":
        ref_count = get_referral_count(user_id)
        if ref_count < 10:
            alert_txt = (
                f"🚫 You need 10 NEW referrals to unlock.\nCurrent count: {ref_count}/10"
                if lang == "en"
                else f"🚫 Bado hujatimiza referrals 10 mpya.\nIdadi yako: {ref_count}/10"
            )
            await query.answer(alert_txt, show_alert=True)
        else:
            await send_and_track(
                context.bot,
                user_id,
                query.message.chat_id,
                query.message.reply_text(
                    get_verified_success_text(lang),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=get_verified_success_keyboard(lang)
                )
            )
        return

    if data == "activation3":
        if lang == "en":
            text = (
                "💳 <b>ACTIVATION [3] — FAST DIRECT PAYMENT</b>\n\n"
                "Get fast activation by completing a direct payment using the option that matches your country or card:\n"
                "• <b>Tanzania:</b> TZS 4,500\n"
                "• <b>Kenya:</b> KSH 230\n"
                "• <b>Uganda:</b> UGX 7,500\n"
                "• <b>International Card:</b> USD $3\n\n"
                "After completing payment on the checkout page, open the bot activation link provided to activate your account."
            )
            btn_back = "🔙 BACK"
        else:
            text = (
                "💳 <b>ACTIVATION [3] — MALIPO YA HARAKA YA MOJA KWA MOJA</b>\n\n"
                "Pata activation ya haraka kwa kukamilisha malipo kupitia chaguo linalolingana na nchi au kadi yako:\n"
                "• <b>Tanzania:</b> TZS 4,500\n"
                "• <b>Kenya:</b> KSH 230\n"
                "• <b>Uganda:</b> UGX 7,500\n"
                "• <b>International Card:</b> USD $3\n\n"
                "Ukishamaliza kulipa kwenye ukurasa wa malipo, fungua link ya activation ya bot utayopewa ili kuwezesha akaunti yako."
            )
            btn_back = "🔙 RUDI"

        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🇹🇿 Tanzania — TZS 4,500", url=PAY_LINK_TZ)],
                [InlineKeyboardButton("🇰🇪 Kenya — KSH 230", url=PAY_LINK_KE)],
                [InlineKeyboardButton("🇺🇬 Uganda — UGX 7,500", url=PAY_LINK_UG)],
                [InlineKeyboardButton("💳 International Card — USD $3", url=PAY_LINK_INTL)],
                [InlineKeyboardButton(btn_back, callback_data="back_to_error")]
            ])
        )
        return

    if data == "back_to_error":
        await query.message.edit_text(
            get_error_403_text(lang),
            parse_mode="HTML",
            reply_markup=get_error_403_keyboard(lang)
        )
        return

    if data in ("back", "back_to_regions"):
        try:
            await query.message.delete()
        except Exception:
            pass
        await proceed_to_regions(query.message, user_id)


# --- BROADCAST FORMATTING & MULTI-BUTTON PARSER ---
def parse_broadcast_text_and_buttons(raw_text):
    """
    Supports:
    - Full Telegram HTML tags in message text (<b>, <i>, <u>, <s>, <code>, <pre>, <tg-spoiler>, <blockquote>, <a href="...">)
    - Multiple inline buttons at the end of the text:
        * One button per line: `Button Label | https://example.com`
        * Multiple buttons on the same row separated by `||`: `Btn 1 | https://a.com || Btn 2 | https://b.com`
    """
    if not raw_text:
        return "", None

    lines = raw_text.split("\n")
    body_lines = []
    url_pattern = re.compile(r"^https?://", re.IGNORECASE)

    trailing_mode = True
    reversed_button_rows = []

    for line in reversed(lines):
        stripped = line.strip()
        if trailing_mode and stripped and "|" in stripped:
            segments = [seg.strip() for seg in stripped.split("||")]
            row_buttons = []
            valid_row = True
            for seg in segments:
                if "|" not in seg:
                    valid_row = False
                    break
                label, target = seg.split("|", 1)
                label = label.strip()
                target = target.strip()
                if not label or not url_pattern.match(target):
                    valid_row = False
                    break
                tracked_url = f"{RENDER_EXTERNAL_URL}/click?url={quote(target, safe='')}"
                row_buttons.append(InlineKeyboardButton(label, url=tracked_url))
            if valid_row and row_buttons:
                reversed_button_rows.append(row_buttons)
                continue
        trailing_mode = False
        body_lines.append(line)

    body_lines.reverse()
    reversed_button_rows.reverse()

    clean_text = "\n".join(body_lines).strip()
    markup = InlineKeyboardMarkup(reversed_button_rows) if reversed_button_rows else None
    return clean_text, markup


def get_admin_home_text_and_kb():
    total_users = get_total_users_count()
    c_counts = get_users_by_country_counts()
    text = (
        "👑 <b>Tanzania Connection - Master Admin Panel</b>\n\n"
        f"👥 Total Users: <code>{total_users}</code>\n"
        f"🇹🇿 Tanzania: <code>{c_counts['Tanzania']}</code> | "
        f"🇰🇪 Kenya: <code>{c_counts['Kenya']}</code> | "
        f"🇺🇬 Uganda: <code>{c_counts['Uganda']}</code>\n"
        f"🌐 Unset: <code>{c_counts['Unset']}</code>\n\n"
        "Chagua huduma unayotaka kusimamia hapa chini:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Takwimu & Nchi", callback_data="admin_stats"),
         InlineKeyboardButton("👥 Watumiaji", callback_data="admin_users")],
        [InlineKeyboardButton("🔍 Angalia Order", callback_data="admin_check_order"),
         InlineKeyboardButton("📢 Rich Broadcast", callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("🔄 Safisha Mfumo", callback_data="admin_clean")]
    ])
    return text, kb


def get_broadcast_composer_text_and_kb(admin_id):
    draft = admin_broadcast_drafts.get(str(admin_id), {"items": [], "text": ""})
    items = draft.get("items", [])
    text_val = draft.get("text", "")

    photos_cnt = sum(1 for it in items if it["type"] == "photo")
    videos_cnt = sum(1 for it in items if it["type"] == "video")
    total_recipients = get_total_users_count()

    preview_snippet = text_val if text_val else "<i>(Hakuna maandishi bado)</i>"
    if len(preview_snippet) > 400:
        preview_snippet = preview_snippet[:400] + "..."

    msg = (
        "📢 <b>RICH MEDIA & MULTI-BUTTON BROADCAST STUDIO</b>\n\n"
        f"👥 Recipients: <b>{total_recipients}</b>\n"
        f"🖼 Photos attached: <b>{photos_cnt}</b> | 🎬 Videos attached: <b>{videos_cnt}</b>\n"
        f"📝 Text / Caption set: <b>{'Yes' if text_val else 'No'}</b>\n\n"
        "<b>Current Text / Buttons Source:</b>\n"
        f"{preview_snippet}\n\n"
        "<b>How to compose (unlimited media items):</b>\n"
        "• Send any number of <b>Photos</b> or <b>Videos</b>—each one adds to your media batch.\n"
        "• Send a <b>Text message</b> (or media caption) to set/update the message text.\n"
        "• Formatting supported: <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, <code>&lt;u&gt;</code>, "
        "<code>&lt;s&gt;</code>, <code>&lt;code&gt;</code>, <code>&lt;blockquote&gt;</code>, "
        "<code>&lt;tg-spoiler&gt;</code>.\n"
        "• Multi-button syntax at end of text:\n"
        "  <code>Button 1 | https://link1.com</code>\n"
        "  <code>Row2 BtnA | https://a.com || Row2 BtnB | https://b.com</code>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ Hakiki (Preview)", callback_data="bcast_preview"),
         InlineKeyboardButton("🗑 Futa Media/Text", callback_data="bcast_clear")],
        [InlineKeyboardButton("🚀 Tuma Sasa", callback_data="bcast_send")],
        [InlineKeyboardButton("🔙 Rudi Menyu", callback_data="admin_home")]
    ])
    return msg, kb


# --- ADMIN PANEL HANDLERS ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(ADMIN_ID):
        return
    context.user_data.pop("admin_mode", None)
    text, kb = get_admin_home_text_and_kb()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, main_app):
    query = update.callback_query
    admin_uid = str(query.from_user.id)
    if admin_uid != str(ADMIN_ID):
        return
    await query.answer()
    data = query.data

    if data == "admin_home":
        context.user_data.pop("admin_mode", None)
        text, kb = get_admin_home_text_and_kb()
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if data == "admin_stats":
        total_users = get_total_users_count()
        c_counts = get_users_by_country_counts()
        await query.message.edit_text(
            "📊 <b>SYSTEM & COUNTRY STATISTICS</b>\n\n"
            f"👥 Total Users: <code>{total_users}</code>\n"
            f"🇹🇿 Tanzania: <code>{c_counts['Tanzania']}</code>\n"
            f"🇰🇪 Kenya: <code>{c_counts['Kenya']}</code>\n"
            f"🇺🇬 Uganda: <code>{c_counts['Uganda']}</code>\n"
            f"🌐 Unset: <code>{c_counts['Unset']}</code>\n"
            "🚀 Status: <b>Online & Stable 24/7</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return

    if data == "admin_users":
        total_users = get_total_users_count()
        c_counts = get_users_by_country_counts()
        users = get_all_users()
        recent = ", ".join(users[-5:]) if users else "Hakuna"
        await query.message.edit_text(
            "👥 <b>WATUMIAJI KWA NCHI</b>\n\n"
            f"📈 Jumla Kuu: <code>{total_users}</code>\n"
            f"🇹🇿 Tanzania: <code>{c_counts['Tanzania']}</code>\n"
            f"🇰🇪 Kenya: <code>{c_counts['Kenya']}</code>\n"
            f"🇺🇬 Uganda: <code>{c_counts['Uganda']}</code>\n"
            f"🌐 Unset: <code>{c_counts['Unset']}</code>\n"
            f"🆔 ID za mwisho 5: <code>{recent}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return

    if data == "admin_check_order":
        context.user_data["admin_mode"] = ADMIN_MODE_ORDER
        await query.message.edit_text(
            "🔍 <b>ANGALIA ORDER YA MALIPO</b>\n\n"
            "Tuma Order ID / Ref kwenye chat hii kuangalia rekodi yake kwenye database:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return

    if data == "admin_broadcast_menu":
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        admin_broadcast_drafts.setdefault(admin_uid, {"items": [], "text": ""})
        msg, kb = get_broadcast_composer_text_and_kb(admin_uid)
        await query.message.edit_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    if data == "bcast_clear":
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        admin_broadcast_drafts[admin_uid] = {"items": [], "text": ""}
        msg, kb = get_broadcast_composer_text_and_kb(admin_uid)
        await query.message.edit_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    if data == "bcast_preview":
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        draft = admin_broadcast_drafts.get(admin_uid, {"items": [], "text": ""})
        items = draft.get("items", [])
        clean_text, markup = parse_broadcast_text_and_buttons(draft.get("text", ""))

        if len(items) > 1:
            media_group = []
            for idx, item in enumerate(items):
                cap = clean_text if idx == 0 and clean_text else None
                if item["type"] == "photo":
                    media_group.append(InputMediaPhoto(media=item["bytes"], caption=cap, parse_mode="HTML" if cap else None))
                else:
                    media_group.append(InputMediaVideo(media=item["bytes"], caption=cap, parse_mode="HTML" if cap else None))
            await query.message.reply_media_group(media=media_group)
            if markup or (not clean_text):
                await query.message.reply_text(
                    "👇 <b>Buttons Preview:</b>" if markup else "ℹ️ <i>Media group previewed above.</i>",
                    parse_mode="HTML",
                    reply_markup=markup
                )
        elif len(items) == 1:
            item = items[0]
            if item["type"] == "photo":
                await query.message.reply_photo(
                    photo=item["bytes"],
                    caption=clean_text or None,
                    parse_mode="HTML" if clean_text else None,
                    reply_markup=markup
                )
            else:
                await query.message.reply_video(
                    video=item["bytes"],
                    caption=clean_text or None,
                    parse_mode="HTML" if clean_text else None,
                    reply_markup=markup
                )
        else:
            await query.message.reply_text(
                clean_text or "<i>(Empty broadcast)</i>",
                parse_mode="HTML",
                reply_markup=markup
            )

        msg, kb = get_broadcast_composer_text_and_kb(admin_uid)
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    if data == "bcast_send":
        context.user_data.pop("admin_mode", None)
        draft = admin_broadcast_drafts.get(admin_uid, {"items": [], "text": ""})
        items = draft.get("items", [])
        clean_text, markup = parse_broadcast_text_and_buttons(draft.get("text", ""))

        if not items and not clean_text:
            await query.message.edit_text(
                "❌ Hakuna media wala ujumbe uliowekwa. Rudi kwenye Broadcast Studio.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_broadcast_menu")]])
            )
            return

        users = get_all_users()
        success = 0
        failed = 0
        status_msg = await query.message.edit_text(f"🚀 Inatuma broadcast kwa watumiaji {len(users)}...")

        for uid in users:
            try:
                if len(items) > 1:
                    media_group = []
                    for idx, item in enumerate(items):
                        cap = clean_text if idx == 0 and clean_text else None
                        if item["type"] == "photo":
                            media_group.append(InputMediaPhoto(media=item["bytes"], caption=cap, parse_mode="HTML" if cap else None))
                        else:
                            media_group.append(InputMediaVideo(media=item["bytes"], caption=cap, parse_mode="HTML" if cap else None))
                    await main_app.bot.send_media_group(chat_id=uid, media=media_group)
                    if markup:
                        await main_app.bot.send_message(
                            chat_id=uid,
                            text="👇" if not clean_text else "🔗",
                            reply_markup=markup
                        )
                elif len(items) == 1:
                    item = items[0]
                    if item["type"] == "photo":
                        await main_app.bot.send_photo(
                            chat_id=uid,
                            photo=item["bytes"],
                            caption=clean_text or None,
                            parse_mode="HTML" if clean_text else None,
                            reply_markup=markup
                        )
                    else:
                        await main_app.bot.send_video(
                            chat_id=uid,
                            video=item["bytes"],
                            caption=clean_text or None,
                            parse_mode="HTML" if clean_text else None,
                            reply_markup=markup
                        )
                else:
                    await main_app.bot.send_message(
                        chat_id=uid,
                        text=clean_text,
                        parse_mode="HTML",
                        reply_markup=markup
                    )
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        admin_broadcast_drafts[admin_uid] = {"items": [], "text": ""}
        await status_msg.edit_text(
            "✅ <b>BROADCAST IMEKAMILIKA!</b>\n\n"
            f"📤 Imefanikiwa: <code>{success}</code>\n"
            f"❌ Imeshindikana: <code>{failed}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KWENYE MENYU", callback_data="admin_home")]])
        )
        return

    if data == "admin_clean":
        user_cooldowns.clear()
        await query.message.edit_text(
            "🔄 <b>USAFISHAJI WA MFUMO</b>\n\n"
            "Kache za muda mfupi zimesafishwa. Mfumo upo safi na unafanya kazi.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )


async def admin_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_uid = str(update.effective_user.id)
    if admin_uid != str(ADMIN_ID):
        return

    mode = context.user_data.get("admin_mode")
    if mode == ADMIN_MODE_ORDER:
        context.user_data.pop("admin_mode", None)
        order_ref = (update.message.text or "").strip()
        order_data = get_order_details(order_ref)
        if order_data:
            uid, phone, amount, db_status = order_data
            await update.message.reply_text(
                f"📦 <b>ORDER: {order_ref}</b>\n\n"
                f"👤 User ID: <code>{uid}</code>\n"
                f"📱 Phone: <code>{phone}</code>\n"
                f"💵 Amount: <code>{amount}</code>\n"
                f"💾 Status: <code>{db_status}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
            )
        else:
            await update.message.reply_text(
                f"❌ Order <code>{order_ref}</code> haipatikani.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
            )
        return

    if mode == ADMIN_MODE_BROADCAST:
        draft = admin_broadcast_drafts.setdefault(admin_uid, {"items": [], "text": ""})
        msg = update.message

        if msg.photo:
            tg_file = await context.bot.get_file(msg.photo[-1].file_id)
            raw_bytes = bytes(await tg_file.download_as_bytearray())
            draft["items"].append({"type": "photo", "bytes": raw_bytes})
            if msg.caption:
                draft["text"] = msg.caption
        elif msg.video:
            tg_file = await context.bot.get_file(msg.video.file_id)
            raw_bytes = bytes(await tg_file.download_as_bytearray())
            draft["items"].append({"type": "video", "bytes": raw_bytes})
            if msg.caption:
                draft["text"] = msg.caption
        elif msg.text:
            draft["text"] = msg.text

        composer_msg, composer_kb = get_broadcast_composer_text_and_kb(admin_uid)
        await msg.reply_text(composer_msg, parse_mode="HTML", reply_markup=composer_kb)
        return

    text, kb = get_admin_home_text_and_kb()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


# --- FLASK WEB SERVER WITH CLICK ANALYTICS REDIRECT ---
app = Flask(__name__)


@app.route("/")
def home():
    return "Connection Bot Running 24/7!"


@app.route("/click")
def click_redirect():
    target_url = request.args.get("url", TARGET_SITE)
    if not re.match(r"^https?://", target_url, re.IGNORECASE):
        target_url = TARGET_SITE
    log_broadcast_click("user", target_url)
    return redirect(target_url)


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- BACKGROUND LOOP: 2-DAY AUTO-DELETE + REGION KEYBOARD RETURN & WEEKLY BACKUP ---
async def background_automation_loop(main_app):
    last_backup_key = None
    while True:
        await asyncio.sleep(60)
        now_ts = time.time()
        cutoff_ts = now_ts - TWO_DAYS_SECONDS

        expired_rows = get_expired_messages(cutoff_ts)
        if expired_rows:
            processed_ids = []
            notified_users = set()

            for row_id, uid, chat_id, msg_id in expired_rows:
                try:
                    await main_app.bot.delete_message(chat_id=int(chat_id), message_id=int(msg_id))
                except Exception:
                    pass
                processed_ids.append(row_id)

                if uid not in notified_users:
                    notified_users.add(uid)
                    lang = get_user_language(uid)
                    country = get_user_country(uid) or "Tanzania"
                    return_msg = (
                        "⏳ <b>Old messages were cleared after 2 days.</b>\n\n"
                        "📍 Pick your region below to continue:"
                        if lang == "en"
                        else "⏳ <b>Ujumbe wa siku 2 umefutwa kiotomatiki.</b>\n\n"
                        "📍 Chagua mkoa wako hapa chini kuendelea:"
                    )
                    try:
                        await main_app.bot.send_message(
                            chat_id=int(chat_id),
                            text=return_msg,
                            parse_mode="HTML",
                            reply_markup=get_region_keyboard(country, lang)
                        )
                    except Exception:
                        pass

            delete_tracked_messages_by_ids(processed_ids)

        # Weekly Monday 03:00 UTC database backup to admin
        now_dt = datetime.utcnow()
        backup_key = now_dt.strftime("%Y-%W")
        if now_dt.weekday() == 0 and now_dt.hour == 3 and last_backup_key != backup_key:
            last_backup_key = backup_key
            if os.path.exists(DB_PATH) and ADMIN_ID:
                try:
                    with open(DB_PATH, "rb") as db_file:
                        await main_app.bot.send_document(
                            chat_id=int(ADMIN_ID),
                            document=db_file,
                            caption=f"📦 <b>AUTOMATED WEEKLY DATABASE BACKUP</b>\n📅 {now_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC",
                            parse_mode="HTML"
                        )
                except Exception:
                    pass


# --- UNIFIED ASYNC MAIN RUNNER ---
async def main():
    init_db()

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    main_app = ApplicationBuilder().token(MAIN_BOT_TOKEN).build()
    admin_app = ApplicationBuilder().token(ADMIN_BOT_TOKEN).build()

    # Main Bot Handlers
    main_app.add_handler(CommandHandler("start", start))
    main_app.add_handler(CommandHandler("country", cmd_country))
    main_app.add_handler(CommandHandler("language", cmd_language))
    main_app.add_handler(CallbackQueryHandler(age_callback, pattern="^age_"))
    main_app.add_handler(CallbackQueryHandler(handle_callback))
    main_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    # Admin Bot Handlers
    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(CallbackQueryHandler(lambda u, c: admin_callback(u, c, main_app)))
    admin_app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, admin_message_router))

    await main_app.initialize()
    await admin_app.initialize()
    await main_app.start()
    await admin_app.start()

    await main_app.updater.start_polling()
    await admin_app.updater.start_polling()

    asyncio.create_task(background_automation_loop(main_app))

    logger.info("Main Bot & Master Admin Panel running successfully.")

    stop_event = asyncio.Event()
    await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
