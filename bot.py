import os
import re
import time
import random
import asyncio
import logging
import copy
from html import escape as html_escape, unescape as html_unescape
from datetime import datetime
from urllib.parse import quote
from threading import Thread
from flask import Flask, request, redirect

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton,
    InputMediaPhoto, InputMediaVideo
)
from telegram.error import Forbidden, BadRequest, RetryAfter
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
    is_user_activated,
    log_broadcast_click, create_broadcast, finish_broadcast,
    get_recent_broadcasts, get_broadcast_click_detail, get_untracked_click_total,
    set_user_requested_country, get_top_requested_countries, get_requested_countries_total,
    track_user_message, get_expired_messages, delete_tracked_messages_by_ids,
    get_broadcast_users, mark_user_blocked, get_blocked_count,
    set_profile_file_id, get_profile_file_ids, get_extra_profile_keys, profile_unique_id_exists,
    DB_PATH
)

# --- ENVIRONMENT CONFIGS ---
MAIN_BOT_TOKEN = os.environ.get("MAIN_BOT_TOKEN", "")
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "")
ADMIN_ID = os.environ.get("ADMIN_ID", "")
# Private channel where the bot keeps the profile pictures (main bot must be an admin there)
PROFILE_CHANNEL_ID = int(os.environ.get("PROFILE_CHANNEL_ID") or "-1004399690789")
DEFAULT_ACTIVATION_CODE = "vip_unlock_9842"
ACTIVATION_SECRET_CODE = (os.environ.get("ACTIVATION_SECRET_CODE") or DEFAULT_ACTIVATION_CODE).strip()
ACTIVATION_CODES = {code for code in (DEFAULT_ACTIVATION_CODE, ACTIVATION_SECRET_CODE) if code}
BOT_USERNAME = os.environ.get("BOT_USERNAME", "connectiontzzbot").lstrip("@")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://connection-bot.onrender.com").rstrip("/")

# --- LINKS & CHANNELS ---
CPA_LINK = "https://tinyurl.com/Activebot"

COUNTRY_CONFIG = {
    "Tanzania": {
        "flag": "🇹🇿",
        "price_label": "TSH 5,500",
        "pay_url": "https://host.stanymaxhub.online/pay/connection-bot-subscription-mwpyeqqj",
        "site_url": "https://www.exotictanzania.com",
        "site_name": "Exotic Tanzania",
        "intl_only": False,
    },
    "Kenya": {
        "flag": "🇰🇪",
        "price_label": "KES 270",
        "pay_url": "https://host.stanymaxhub.online/pay/connection-bot-subscription-mwrg696v",
        "site_url": "https://www.exotickenya.com",
        "site_name": "Exotic Kenya",
        "intl_only": False,
    },
    "Uganda": {
        "flag": "🇺🇬",
        "price_label": "UGX 9,000",
        "pay_url": "https://host.stanymaxhub.online/pay/connection-bot-subscription-mwrgfhtt",
        "site_url": "https://www.exoticuganda.com",
        "site_name": "Exotic Uganda",
        "intl_only": False,
    },
    "Ghana": {
        "flag": "🇬🇭",
        "price_label": "GHS 25",
        "pay_url": "https://host.stanymaxhub.online/pay/connection-bot-subscription-mwro6u2b",
        "site_url": "https://www.exoticghana.com",
        "site_name": "Exotic Ghana",
        "intl_only": False,
    },
    "Nigeria": {
        "flag": "🇳🇬",
        "price_label": "NGN 3,000",
        "pay_url": "https://host.stanymaxhub.online/pay/connection-bot-subscription-mwro3lcp",
        "site_url": "https://www.exoticnigeria.com",
        "site_name": "Exotic Nigeria",
        "intl_only": False,
    },
    "Zimbabwe": {
        "flag": "🇿🇼",
        "price_label": "$ 3",
        "pay_url": "https://host.stanymaxhub.online/pay/connection-bot-subscription-mwrgc952",
        "site_url": "https://www.exoticzimbabwe.com",
        "site_name": "Exotic Zimbabwe",
        "intl_only": True,
    },
    "Ethiopia": {
        "flag": "🇪🇹",
        "price_label": "$ 3",
        "pay_url": "https://host.stanymaxhub.online/pay/connection-bot-subscription-mwrgc952",
        "site_url": "https://www.exoticethiopia.com",
        "site_name": "Exotic Ethiopia",
        "intl_only": True,
    },
}

DEFAULT_COUNTRY = "Tanzania"
TARGET_SITE = COUNTRY_CONFIG[DEFAULT_COUNTRY]["site_url"]
REQUIRED_CHANNEL = "@connectiontzz"

TWO_DAYS_SECONDS = 48 * 3600

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Runtime state stores
user_cooldowns = {}
active_step_prompts = {}  # {user_id: {"chat_id": int, "message_id": int}}

# Admin pending input modes
ADMIN_MODE_BROADCAST = "broadcast"
ADMIN_MODE_BTN_LABEL = "btn_label"
ADMIN_MODE_BTN_URL = "btn_url"
ADMIN_MODE_BTN_EDIT_LABEL = "btn_edit_label"
ADMIN_MODE_BTN_EDIT_URL = "btn_edit_url"

# Pending multi-media broadcast drafts per admin user: {admin_id: {"items": [...], "text": ""}}
admin_broadcast_drafts = {}

# Live state of the broadcast that is currently being sent (only one at a time)
broadcast_state = {"running": False, "stop": False, "id": None, "sent": 0, "failed": 0, "blocked": 0, "total": 0, "task": None, "panel": None}


def get_country_info(country):
    return COUNTRY_CONFIG.get(country, COUNTRY_CONFIG[DEFAULT_COUNTRY])


async def check_antispam(user_id):
    now = time.time()
    last_time = user_cooldowns.get(str(user_id))
    if last_time and (now - last_time) < 0.7:
        return False
    user_cooldowns[str(user_id)] = now
    return True


async def safe_delete_message(bot, chat_id, message_id):
    if not chat_id or not message_id:
        return
    try:
        await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
    except Exception:
        pass


async def safe_edit_text(message, text, reply_markup=None, disable_web_page_preview=False):
    if not message:
        return None
    try:
        return await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview
        )
    except Exception:
        try:
            await safe_delete_message(message.get_bot(), message.chat_id, message.message_id)
            return await message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        except Exception:
            return None


async def register_step_prompt(bot, user_id, chat_id, message_id):
    uid = str(user_id)
    prev = active_step_prompts.get(uid)
    if prev:
        if int(prev["chat_id"]) != int(chat_id) or int(prev["message_id"]) != int(message_id):
            await safe_delete_message(bot, prev["chat_id"], prev["message_id"])
    active_step_prompts[uid] = {"chat_id": int(chat_id), "message_id": int(message_id)}


async def clear_step_prompt(bot, user_id, current_message=None):
    uid = str(user_id)
    prev = active_step_prompts.pop(uid, None)
    if current_message:
        await safe_delete_message(current_message.get_bot(), current_message.chat_id, current_message.message_id)
    if prev:
        if not current_message or int(prev["message_id"]) != int(current_message.message_id):
            await safe_delete_message(bot, prev["chat_id"], prev["message_id"])


async def send_and_track(bot, user_id, chat_id, send_coro):
    try:
        sent = await send_coro
    except Exception as exc:
        logger.warning(f"Failed sending message to {user_id}: {exc}")
        return None
    if sent and getattr(sent, "message_id", None):
        try:
            track_user_message(user_id, chat_id, sent.message_id, time.time())
        except Exception:
            pass
    return sent


async def run_paced_loader(target_message, steps, delay=0.9, delete_after=True):
    """Displays realistic staged system progress before moving to the next screen."""
    if not target_message or not steps:
        return None
    status_msg = None
    try:
        status_msg = await target_message.reply_text(steps[0], parse_mode="HTML")
    except Exception:
        return None

    for idx, step_text in enumerate(steps[1:], start=1):
        await asyncio.sleep(delay + (0.15 if idx == len(steps) - 1 else 0.0))
        try:
            edited = await status_msg.edit_text(step_text, parse_mode="HTML")
            if edited:
                status_msg = edited
        except Exception:
            pass

    await asyncio.sleep(delay * 0.75)
    if delete_after and status_msg:
        await safe_delete_message(status_msg.get_bot(), status_msg.chat_id, status_msg.message_id)
        return None
    return status_msg


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
    ],
    "Ghana": [
        "Greater Accra", "Ashanti", "Western", "Eastern", "Central", "Volta", "Northern",
        "Upper East", "Upper West", "Bono", "Bono East", "Ahafo", "Savannah", "North East",
        "Oti", "Western North"
    ],
    "Nigeria": [
        "Lagos", "Abuja (FCT)", "Rivers", "Kano", "Oyo", "Edo", "Delta", "Anambra", "Enugu",
        "Kaduna", "Ogun", "Imo", "Akwa Ibom", "Cross River", "Kwara", "Borno", "Plateau",
        "Abia", "Adamawa", "Bauchi", "Bayelsa", "Benue", "Ebonyi", "Ekiti", "Gombe",
        "Jigawa", "Katsina", "Kebbi", "Kogi", "Nasarawa", "Niger", "Osun", "Sokoto",
        "Taraba", "Yobe", "Zamfara"
    ],
    "Zimbabwe": [
        "Harare", "Bulawayo", "Manicaland", "Mashonaland Central", "Mashonaland East",
        "Mashonaland West", "Masvingo", "Matabeleland North", "Matabeleland South", "Midlands"
    ],
    "Ethiopia": [
        "Addis Ababa", "Dire Dawa", "Oromia", "Amhara", "Tigray", "Somali", "Sidama",
        "Central Ethiopia", "South Ethiopia", "South West Ethiopia Peoples", "Afar",
        "Benishangul-Gumuz", "Gambela", "Harari"
    ]
}

ALL_REGIONS = {
    reg for region_list in REGIONS_BY_COUNTRY.values() for reg in region_list
}

SWITCH_KB_LABELS = {"🌍 Nchi / Lugha", "🌍 Country / Lang"}


def get_region_keyboard(country=None, lang="sw"):
    selected_country = country if country in REGIONS_BY_COUNTRY else DEFAULT_COUNTRY
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
    return user_country or DEFAULT_COUNTRY


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


def get_verified_success_text(lang, country=None):
    info = get_country_info(country)
    site_url = info["site_url"]
    site_name = info["site_name"]
    country_name = country or DEFAULT_COUNTRY

    if lang == "en":
        return (
            "🎉 <b>YOUR ACCOUNT IS NOW ACTIVATED!</b> ✅\n\n"
            f"Your VIP access for <b>{info['flag']} {country_name}</b> is active. "
            "Continue browsing regions or open your dedicated connection site below: 💃🔥\n\n"
            f"🔗 <b>YOUR {country_name.upper()} CONNECTION SITE:</b>\n"
            f"👉 <a href=\"{site_url}\">{site_name}</a>\n"
            f"<code>{site_url}</code>\n\n"
            "👇 <i>Choose an option below or return to your regions:</i>"
        )

    return (
        "🎉 <b>AKAUNTI YAKO IMEWEZESHWA KIKAMILIFU!</b> ✅\n\n"
        f"Ufikiaji wako wa VIP kwa <b>{info['flag']} {country_name}</b> umekamilika. "
        "Endelea kuchagua mikoa au fungua tovuti yako maalum ya connection hapa chini: 💃🔥\n\n"
        f"🔗 <b>TOVUTI YAKO YA CONNECTION ({country_name.upper()}):</b>\n"
        f"👉 <a href=\"{site_url}\">{site_name}</a>\n"
        f"<code>{site_url}</code>\n\n"
        "👇 <i>Chagua huduma unayotaka hapa chini au rudi kwenye mikoa:</i>"
    )


def get_verified_success_keyboard(lang, country=None):
    info = get_country_info(country)
    site_url = info["site_url"]
    site_name = info["site_name"]

    if lang == "en":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🟢 OPEN {site_name.upper()}", url=site_url)],
            [
                InlineKeyboardButton("🌍 COUNTRY", callback_data="pick_country"),
                InlineKeyboardButton("🌐 LANGUAGE", callback_data="pick_language")
            ],
            [InlineKeyboardButton("🔙 BACK TO REGIONS", callback_data="back_to_regions")]
        ])

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🟢 FUNGUA {site_name.upper()}", url=site_url)],
        [
            InlineKeyboardButton("🌍 NCHI", callback_data="pick_country"),
            InlineKeyboardButton("🌐 LUGHA", callback_data="pick_language")
        ],
        [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
    ])


def get_error_403_text(lang, country=None):
    info = get_country_info(country)
    country_name = country or DEFAULT_COUNTRY
    if lang == "en":
        return (
            "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\n"
            f"Selected Country: <b>{info['flag']} {country_name}</b> (<b>{info['price_label']}</b>)\n"
            "Direct connection is temporarily locked. Complete one of the verification options below 👇"
        )
    return (
        "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\n"
        f"Nchi Iliyochaguliwa: <b>{info['flag']} {country_name}</b> (<b>{info['price_label']}</b>)\n"
        "Uunganishwaji umesitishwa kwa muda. Kamilisha uthibitisho kupitia mojawapo ya njia hapa chini 👇"
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


def get_country_keyboard():
    # Creative multi-column layout: 2-col pairs + full-width featured country rows
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇹🇿 Tanzania", callback_data="set_country_Tanzania"),
            InlineKeyboardButton("🇰🇪 Kenya", callback_data="set_country_Kenya")
        ],
        [InlineKeyboardButton("🇺🇬 Uganda — East Africa Hub", callback_data="set_country_Uganda")],
        [
            InlineKeyboardButton("🇬🇭 Ghana", callback_data="set_country_Ghana"),
            InlineKeyboardButton("🇳🇬 Nigeria", callback_data="set_country_Nigeria")
        ],
        [
            InlineKeyboardButton("🇿🇼 Zimbabwe", callback_data="set_country_Zimbabwe"),
            InlineKeyboardButton("🇪🇹 Ethiopia", callback_data="set_country_Ethiopia")
        ],
        [InlineKeyboardButton("🌍 Other country / Nchi nyingine", callback_data="other_country")]
    ])


def get_language_keyboard():
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
def normalize_country_input(text):
    """Clean a typed country name. Returns None if it does not look like a country name."""
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not (2 <= len(value) <= 40):
        return None
    if not re.fullmatch(r"[^\W\d_]+(?:[ '\-.][^\W\d_]+)*\.?", value, re.UNICODE):
        return None
    return value.title()


async def handle_other_country_text(update, context, user_id, lang, text):
    """User chose 'Other country' and typed a name. Returns True if the message was consumed."""
    if text in SWITCH_KB_LABELS or text in ALL_REGIONS or text.startswith("/"):
        context.user_data.pop("awaiting_other_country", None)
        return False

    name = normalize_country_input(text)
    if not name:
        await update.message.reply_text(
            "⚠️ Please type just your country name (letters only), e.g. <i>Rwanda</i>." if lang == "en"
            else "⚠️ Tafadhali andika jina la nchi yako tu (herufi tu), mfano <i>Rwanda</i>.",
            parse_mode="HTML"
        )
        return True

    context.user_data.pop("awaiting_other_country", None)
    supported = next((c for c in REGIONS_BY_COUNTRY if c.lower() == name.lower()), None)
    if supported:
        # they typed a country we already support -> treat it like a normal pick
        set_user_country(user_id, supported)
        await clear_step_prompt(context.bot, user_id)
        await send_language_prompt(update.message, user_id, lang, replace_current=False)
        return True

    set_user_requested_country(user_id, name)
    await clear_step_prompt(context.bot, user_id)
    await update.message.reply_text(
        f"✅ Thanks! We noted <b>{html_escape(name)}</b> and we are working on adding more countries.\n\n"
        "You can keep using the bot as normal 👇" if lang == "en"
        else f"✅ Asante! Tumeandika <b>{html_escape(name)}</b> na tunafanya kazi kuongeza nchi zaidi.\n\n"
        "Unaweza kuendelea kutumia bot kama kawaida 👇",
        parse_mode="HTML"
    )
    await send_language_prompt(update.message, user_id, lang, replace_current=False)
    return True


async def send_country_prompt(target_message, user_id, lang, replace_current=False):
    if lang == "en":
        text = (
            "🌍 <b>SELECT YOUR COUNTRY</b>\n\n"
            "Choose your country below so we load your regions, pricing, and connection site:"
        )
    else:
        text = (
            "🌍 <b>CHAGUA NCHI YAKO</b>\n\n"
            "Chagua nchi yako hapa chini ili tukuletee mikoa, bei ya malipo, na tovuti yako:"
        )

    await clear_step_prompt(target_message.get_bot(), user_id, current_message=target_message if replace_current else None)
    sent = await target_message.reply_text(text, parse_mode="HTML", reply_markup=get_country_keyboard())
    if sent:
        await register_step_prompt(target_message.get_bot(), user_id, sent.chat_id, sent.message_id)
    return sent


async def send_language_prompt(target_message, user_id, lang, replace_current=False):
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

    await clear_step_prompt(target_message.get_bot(), user_id, current_message=target_message if replace_current else None)
    sent = await target_message.reply_text(text, parse_mode="HTML", reply_markup=get_language_keyboard())
    if sent:
        await register_step_prompt(target_message.get_bot(), user_id, sent.chat_id, sent.message_id)
    return sent


async def proceed_to_regions(message, user_id, with_loader=False):
    lang = get_user_language(user_id)
    country = get_user_country(user_id) or DEFAULT_COUNTRY
    info = get_country_info(country)

    if with_loader:
        loader_steps = (
            [
                "<i>🔄 Applying your preferences...</i>",
                f"<i>{info['flag']} Loading {country} regions...</i>",
                "<i>⚡ Preparing region menu...</i>"
            ]
            if lang == "en"
            else [
                "<i>🔄 Inahifadhi chaguo lako...</i>",
                f"<i>{info['flag']} Inapakia mikoa ya {country}...</i>",
                "<i>⚡ Inaandaa orodha ya mikoa...</i>"
            ]
        )
        await run_paced_loader(message, loader_steps, delay=0.8, delete_after=True)

    if lang == "en":
        welcome_text = (
            f"🍑 Welcome to <b>Tanzania Connection Bot</b> 🔞\n\n"
            f"🌍 Country: <b>{info['flag']} {country}</b>\n"
            "📍 Pick your region/area below to browse active connections right now! 💃🔥\n"
            "🆓 Free 24/7 browsing!\n\n"
            "👇 <b>Choose a region from the menu below</b> 👇"
        )
    else:
        welcome_text = (
            f"🍑 Karibu kwenye <b>Tanzania Connection Bot</b> 🔞\n\n"
            f"🌍 Nchi: <b>{info['flag']} {country}</b>\n"
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


def extract_start_payload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        return context.args[0].strip()
    raw_text = (update.message.text or "").strip() if update.message else ""
    if raw_text.startswith("/start"):
        parts = raw_text.split(maxsplit=1)
        if len(parts) > 1:
            return parts[1].strip()
    return ""


# --- MAIN BOT COMMANDS & HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    existed_before = user_exists(user_id)

    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))

    payload_arg = extract_start_payload(update, context)
    logger.info(f"/start user={user_id} payload={payload_arg!r}")

    if payload_arg and payload_arg.strip() in ACTIVATION_CODES:
        set_user_activated(user_id, True)
        lang = get_user_language(user_id)
        country = get_user_country(user_id) or DEFAULT_COUNTRY
        success_msg = (
            "✅ <b>ACTIVATION LINK VERIFIED!</b>\n\nYour VIP access is now active. You can keep using the bot normally."
            if lang == "en"
            else "✅ <b>LINK YA ACTIVATION IMETHIBITISHWA!</b>\n\nAkaunti yako ya VIP sasa imewezeshwa kikamilifu. Unaweza kuendelea kutumia bot kawaida."
        )
        await send_and_track(
            context.bot,
            user_id,
            update.effective_chat.id,
            update.message.reply_text(
                success_msg,
                parse_mode="HTML",
                reply_markup=get_region_keyboard(country, lang)
            )
        )
        await send_and_track(
            context.bot,
            user_id,
            update.effective_chat.id,
            update.message.reply_text(
                get_verified_success_text(lang, country),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=get_verified_success_keyboard(lang, country)
            )
        )
        return

    # Referral check: strictly counts ONLY if user did not exist prior to this /start
    if payload_arg:
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

    await clear_step_prompt(context.bot, user_id)
    sent = await send_and_track(
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
    if sent:
        await register_step_prompt(context.bot, user_id, sent.chat_id, sent.message_id)


async def cmd_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lang = get_user_language(user_id)
    await send_country_prompt(update.message, user_id, lang, replace_current=False)


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    lang = get_user_language(user_id)
    await send_language_prompt(update.message, user_id, lang, replace_current=False)


async def age_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    lang = get_user_language(user_id)
    await query.answer()

    if query.data == "age_no":
        active_step_prompts.pop(user_id, None)
        deny_text = (
            "❌ Sorry, you cannot use this bot if you are under 18."
            if lang == "en"
            else "❌ Samahani, huwezi kutumia bot hii ikiwa una chini ya miaka 18."
        )
        await safe_edit_text(query.message, deny_text)
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

        await safe_edit_text(
            query.message,
            join_text,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(btn_join, url="https://t.me/connectiontzz")],
                [InlineKeyboardButton(btn_check, callback_data="check_sub")]
            ])
        )
        return

    await clear_step_prompt(context.bot, user_id, current_message=query.message)
    await run_paced_loader(
        query.message,
        [
            "<i>🔐 Verifying age & session...</i>" if lang == "en" else "<i>🔐 Inathibitisha umri na mfumo...</i>",
            "<i>🌍 Loading available countries...</i>" if lang == "en" else "<i>🌍 Inapakia nchi zinazopatikana...</i>"
        ],
        delay=0.75,
        delete_after=True
    )
    await send_country_prompt(query.message, user_id, lang, replace_current=False)


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    if not await check_antispam(user_id):
        return

    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))
    lang = get_user_language(user_id)
    saved_country = get_user_country(user_id)
    text = (update.message.text or "").strip()

    if context.user_data.get("awaiting_other_country"):
        if await handle_other_country_text(update, context, user_id, lang, text):
            return

    if text in SWITCH_KB_LABELS:
        await run_paced_loader(
            update.message,
            [
                "<i>🔄 Opening country & language settings...</i>" if lang == "en" else "<i>🔄 Inafungua mipangilio ya nchi na lugha...</i>",
                "<i>🌍 Loading country options...</i>" if lang == "en" else "<i>🌍 Inapakia chaguo la nchi...</i>"
            ],
            delay=0.7,
            delete_after=True
        )
        await send_country_prompt(update.message, user_id, lang, replace_current=False)
        return

    if text in ALL_REGIONS:
        effective_country = detect_country_for_region(text, saved_country)
        if not saved_country:
            set_user_country(user_id, effective_country)
        info = get_country_info(effective_country)

        hide_kb = None
        try:
            hide_kb = await update.message.reply_text(
                "<i>🔄 Loading area details...</i>" if lang == "en" else "<i>🔄 Inapakia taarifa za eneo lako...</i>",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception:
            pass

        await asyncio.sleep(0.75)
        try:
            if hide_kb:
                await hide_kb.edit_text(
                    f"<i>📍 Searching active connections in {text}...</i>"
                    if lang == "en"
                    else f"<i>📍 Inatafuta waliopo active {text}...</i>",
                    parse_mode="HTML"
                )
        except Exception:
            pass

        await asyncio.sleep(0.75)
        if hide_kb:
            await safe_delete_message(context.bot, hide_kb.chat_id, hide_kb.message_id)

        profile_ids = get_profile_file_ids()
        all_keys = list(dict.fromkeys(list(IMAGES) + get_extra_profile_keys()))
        seen = get_seen_images(user_id)
        available_images = [img for img in all_keys if img not in seen]
        if not available_images:
            reset_seen_images(user_id)
            available_images = all_keys

        image_key = random.choice(available_images)
        add_seen_image(user_id, image_key)

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
                f"🌍 <b>COUNTRY:</b> {info['flag']} {effective_country}\n"
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
                f"🌍 <b>NCHI:</b> {info['flag']} {effective_country}\n"
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
            reply_profile_photo(
                update.message,
                image_key,
                profile_ids.get(image_key),
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
            reply_markup=get_region_keyboard(saved_country or DEFAULT_COUNTRY, lang)
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
    country = get_user_country(user_id) or DEFAULT_COUNTRY
    data = query.data

    if data == "check_sub":
        is_joined = await check_membership(context.bot, query.from_user.id)
        if not is_joined:
            await query.answer(
                "⚠️ You haven't joined the channel yet!" if lang == "en" else "⚠️ Bado hujajiunga na channel! Tafadhali jiunge kwanza.",
                show_alert=True
            )
            return
        await clear_step_prompt(context.bot, user_id, current_message=query.message)
        await run_paced_loader(
            query.message,
            [
                "<i>✅ Channel membership confirmed...</i>" if lang == "en" else "<i>✅ Uanachama wa channel umethibitishwa...</i>",
                "<i>🌍 Loading country selection...</i>" if lang == "en" else "<i>🌍 Inapakia chaguo la nchi...</i>"
            ],
            delay=0.75,
            delete_after=True
        )
        await send_country_prompt(query.message, user_id, lang, replace_current=False)
        return

    if data != "other_country":
        context.user_data.pop("awaiting_other_country", None)

    if data == "other_country":
        context.user_data["awaiting_other_country"] = True
        await clear_step_prompt(context.bot, user_id, current_message=query.message)
        sent = await query.message.reply_text(
            "🌍 <b>OTHER COUNTRY</b>\n\nType the name of your country (for example: <i>Rwanda</i>) 👇" if lang == "en"
            else "🌍 <b>NCHI NYINGINE</b>\n\nAndika jina la nchi yako (mfano: <i>Rwanda</i>) 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                "🔙 Back" if lang == "en" else "🔙 Rudi", callback_data="pick_country")]])
        )
        if sent:
            await register_step_prompt(context.bot, user_id, sent.chat_id, sent.message_id)
        return

    if data == "pick_country":
        await run_paced_loader(
            query.message,
            [
                "<i>🌍 Loading countries...</i>" if lang == "en" else "<i>🌍 Inapakia nchi...</i>"
            ],
            delay=0.65,
            delete_after=True
        )
        await send_country_prompt(query.message, user_id, lang, replace_current=False)
        return

    if data.startswith("set_country_"):
        chosen_country = data.replace("set_country_", "", 1)
        if chosen_country not in REGIONS_BY_COUNTRY:
            chosen_country = DEFAULT_COUNTRY
        set_user_country(user_id, chosen_country)
        await clear_step_prompt(context.bot, user_id, current_message=query.message)
        await run_paced_loader(
            query.message,
            [
                f"<i>🌍 Selected {chosen_country}...</i>" if lang == "en" else f"<i>🌍 Umechagua {chosen_country}...</i>",
                "<i>🌐 Loading language options...</i>" if lang == "en" else "<i>🌐 Inapakia chaguo la lugha...</i>"
            ],
            delay=0.75,
            delete_after=True
        )
        await send_language_prompt(query.message, user_id, lang, replace_current=False)
        return

    if data == "pick_language":
        await run_paced_loader(
            query.message,
            [
                "<i>🌐 Loading language options...</i>" if lang == "en" else "<i>🌐 Inapakia chaguo la lugha...</i>"
            ],
            delay=0.65,
            delete_after=True
        )
        await send_language_prompt(query.message, user_id, lang, replace_current=False)
        return

    if data.startswith("set_lang_"):
        chosen_lang = "en" if data.endswith("_en") else "sw"
        set_user_language(user_id, chosen_lang)
        await clear_step_prompt(context.bot, user_id, current_message=query.message)
        await proceed_to_regions(query.message, user_id, with_loader=True)
        return

    if data == "get_connection":
        if is_user_activated(user_id):
            await run_paced_loader(
                query.message,
                [
                    "<i>🔐 Checking VIP account status...</i>" if lang == "en" else "<i>🔐 Inakagua hali ya akaunti ya VIP...</i>",
                    "<i>✅ VIP status verified! Unlocking access...</i>" if lang == "en" else "<i>✅ Akaunti ya VIP imethibitishwa! Inafungua...</i>"
                ],
                delay=0.8,
                delete_after=True
            )
            await send_and_track(
                context.bot,
                user_id,
                query.message.chat_id,
                query.message.reply_text(
                    get_verified_success_text(lang, country),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=get_verified_success_keyboard(lang, country)
                )
            )
            return

        steps = (
            [
                "<i>🔍 Scanning security servers...</i>",
                "<i>🔄 Looking up profile & connection records...</i>",
                "<i>🔐 Running verification gate check...</i>",
                "<i>⚠️ Security firewall restricted direct number access...</i>"
            ]
            if lang == "en"
            else [
                "<i>🔍 Kuchunguza seva za usalama...</i>",
                "<i>🔄 Inatafuta data za mtumiaji na connection...</i>",
                "<i>🔐 Inapitia mfumo wa uthibitisho...</i>",
                "<i>⚠️ Firewall imezuia upatikanaji wa namba...</i>"
            ]
        )
        await run_paced_loader(query.message, steps, delay=0.95, delete_after=True)

        await send_and_track(
            context.bot,
            user_id,
            query.message.chat_id,
            query.message.reply_text(
                get_error_403_text(lang, country),
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

        await safe_edit_text(
            query.message,
            text,
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

        await safe_edit_text(
            query.message,
            text,
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
            set_user_activated(user_id, True)
            await send_and_track(
                context.bot,
                user_id,
                query.message.chat_id,
                query.message.reply_text(
                    get_verified_success_text(lang, country),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=get_verified_success_keyboard(lang, country)
                )
            )
        return

    if data == "activation3":
        info = get_country_info(country)
        intl_note_en = "\n⚠️ <i>International cards only for this country.</i>" if info["intl_only"] else ""
        intl_note_sw = "\n⚠️ <i>Kadi za kimataifa pekee (International cards only) kwa nchi hii.</i>" if info["intl_only"] else ""

        if lang == "en":
            text = (
                "💳 <b>ACTIVATION [3] — FAST DIRECT PAYMENT</b>\n\n"
                f"Selected Country: <b>{info['flag']} {country}</b>\n"
                f"Required Payment: <b>{info['price_label']}</b>{intl_note_en}\n\n"
                "All country payment options:\n"
                "• 🇹🇿 <b>Tanzania:</b> TSH 5,500\n"
                "• 🇰🇪 <b>Kenya:</b> KES 270\n"
                "• 🇺🇬 <b>Uganda:</b> UGX 9,000\n"
                "• 🇬🇭 <b>Ghana:</b> GHS 25\n"
                "• 🇳🇬 <b>Nigeria:</b> NGN 3,000\n"
                "• 🇿🇼 <b>Zimbabwe:</b> $ 3 (International cards only)\n"
                "• 🇪🇹 <b>Ethiopia:</b> $ 3 (International cards only)\n\n"
                "After completing payment on the checkout page, open the bot activation link provided to activate your account."
            )
            btn_back = "🔙 BACK"
        else:
            text = (
                "💳 <b>ACTIVATION [3] — MALIPO YA HARAKA YA MOJA KWA MOJA</b>\n\n"
                f"Nchi Iliyochaguliwa: <b>{info['flag']} {country}</b>\n"
                f"Malipo Yanayohitajika: <b>{info['price_label']}</b>{intl_note_sw}\n\n"
                "Chaguo zote za malipo kwa nchi:\n"
                "• 🇹🇿 <b>Tanzania:</b> TSH 5,500\n"
                "• 🇰🇪 <b>Kenya:</b> KES 270\n"
                "• 🇺🇬 <b>Uganda:</b> UGX 9,000\n"
                "• 🇬🇭 <b>Ghana:</b> GHS 25\n"
                "• 🇳🇬 <b>Nigeria:</b> NGN 3,000\n"
                "• 🇿🇼 <b>Zimbabwe:</b> $ 3 (International cards only)\n"
                "• 🇪🇹 <b>Ethiopia:</b> $ 3 (International cards only)\n\n"
                "Ukishamaliza kulipa kwenye ukurasa wa malipo, fungua link ya activation ya bot utayopewa ili kuwezesha akaunti yako."
            )
            btn_back = "🔙 RUDI"

        pay_rows = [
            [
                InlineKeyboardButton(
                    f"{info['flag']} Pay {country} ({info['price_label']})",
                    url=info["pay_url"]
                )
            ],
            [
                InlineKeyboardButton("🇹🇿 TSH 5,500", url=COUNTRY_CONFIG["Tanzania"]["pay_url"]),
                InlineKeyboardButton("🇰🇪 KES 270", url=COUNTRY_CONFIG["Kenya"]["pay_url"])
            ],
            [
                InlineKeyboardButton("🇺🇬 UGX 9,000", url=COUNTRY_CONFIG["Uganda"]["pay_url"]),
                InlineKeyboardButton("🇬🇭 GHS 25", url=COUNTRY_CONFIG["Ghana"]["pay_url"])
            ],
            [
                InlineKeyboardButton("🇳🇬 NGN 3,000", url=COUNTRY_CONFIG["Nigeria"]["pay_url"]),
                InlineKeyboardButton("🇿🇼 $ 3 (Intl)", url=COUNTRY_CONFIG["Zimbabwe"]["pay_url"])
            ],
            [InlineKeyboardButton("🇪🇹 Ethiopia — $ 3 (International Cards Only)", url=COUNTRY_CONFIG["Ethiopia"]["pay_url"])],
            [InlineKeyboardButton(btn_back, callback_data="back_to_error")]
        ]

        await safe_edit_text(
            query.message,
            text,
            reply_markup=InlineKeyboardMarkup(pay_rows)
        )
        return

    if data == "back_to_error":
        await safe_edit_text(
            query.message,
            get_error_403_text(lang, country),
            reply_markup=get_error_403_keyboard(lang)
        )
        return

    if data in ("back", "back_to_regions"):
        await clear_step_prompt(context.bot, user_id, current_message=query.message)
        await proceed_to_regions(query.message, user_id, with_loader=False)


# --- BROADCAST FORMATTING & MULTI-BUTTON PARSER ---
# =====================================================================
#  BROADCAST STUDIO - text, buttons and live preview helpers
# =====================================================================
MAX_BUTTONS_TOTAL = 50
MAX_BUTTONS_PER_ROW = 8
MAX_MEDIA_ITEMS = 10
_PLAIN_ENTITY_TYPES = {"url", "mention", "hashtag", "cashtag", "bot_command", "email", "phone_number"}
_HTML_TAG_RE = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|a|blockquote|tg-spoiler|tg-emoji|span)(?:\s[^>]*)?>",
    re.IGNORECASE
)


def strip_tags(value):
    return html_unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def message_to_html(msg):
    """Turn what the admin typed in Telegram (bold, italic, `monospace`, links...) into HTML.
    Plain text is escaped; text that already contains hand-typed HTML tags keeps working as before."""
    if msg.text is not None:
        raw, ents, formatted = msg.text, (msg.entities or []), msg.text_html
    else:
        raw, ents, formatted = (msg.caption or ""), (msg.caption_entities or []), msg.caption_html
    if not raw:
        return ""
    if any(getattr(e, "type", None) not in _PLAIN_ENTITY_TYPES for e in ents):
        return formatted
    if _HTML_TAG_RE.search(raw):
        return raw
    return html_escape(raw, quote=False)


def extract_button_rows(text):
    """Quick syntax (still supported): trailing lines `Label | https://link`, use `||` for 2+ buttons in a row."""
    if not text:
        return "", []
    lines = text.split("\n")
    body, rows_rev = [], []
    url_pattern = re.compile(r"^https?://\S+$", re.IGNORECASE)
    trailing = True
    for line in reversed(lines):
        stripped = line.strip()
        if trailing and stripped and "|" in stripped:
            row, valid = [], True
            for seg in stripped.split("||"):
                if "|" not in seg:
                    valid = False
                    break
                label, target = seg.split("|", 1)
                label, target = strip_tags(label), strip_tags(target)
                if not label or not url_pattern.match(target):
                    valid = False
                    break
                row.append({"text": label[:64], "url": target})
            if valid and row:
                rows_rev.append(row)
                continue
        trailing = False
        body.append(line)
    body.reverse()
    rows_rev.reverse()
    return "\n".join(body).strip(), rows_rev


def normalize_button_url(raw):
    value = (raw or "").strip()
    if value and not re.match(r"^https?://", value, re.IGNORECASE) and re.match(r"^[\w.-]+\.[a-zA-Z]{2,}(/\S*)?$", value):
        value = "https://" + value
    if re.match(r"^https?://\S+$", value, re.IGNORECASE) and "." in value:
        return value
    return None


def flat_buttons(rows):
    return [btn for row in rows for btn in row]


def locate_button(rows, flat_index):
    n = 0
    for r, row in enumerate(rows):
        for c, _btn in enumerate(row):
            if n == flat_index:
                return r, c
            n += 1
    return None


def rows_from_flat(flat, per_row):
    return [flat[i:i + per_row] for i in range(0, len(flat), per_row)]


def add_button_to_draft(draft, label, url, same_row):
    btn = {"text": label, "url": url}
    rows = draft["buttons"]
    if same_row and rows and len(rows[-1]) < MAX_BUTTONS_PER_ROW:
        rows[-1].append(btn)
    else:
        rows.append([btn])


def build_markup(rows, track=None):
    """Inline keyboard. track=(broadcast_id, user_id) wraps links so clicks are counted per broadcast."""
    out = []
    for row in rows or []:
        line = []
        for btn in row:
            url = btn["url"]
            if track:
                url = f"{RENDER_EXTERNAL_URL}/click?url={quote(url, safe='')}&b={track[0]}&u={track[1]}"
            line.append(InlineKeyboardButton(btn["text"], url=url))
        if line:
            out.append(line)
    return InlineKeyboardMarkup(out) if out else None


def get_draft(admin_uid):
    draft = admin_broadcast_drafts.setdefault(str(admin_uid), {})
    draft.setdefault("items", [])
    draft.setdefault("text", "")
    draft.setdefault("buttons", [])
    draft.setdefault("ui", [])
    draft.setdefault("panel", None)
    draft.setdefault("pending", {})
    draft.setdefault("error", None)
    if "lock" not in draft:
        draft["lock"] = asyncio.Lock()
    return draft


def reset_draft(draft):
    draft["items"].clear()
    draft["text"] = ""
    draft["buttons"].clear()
    draft["pending"].clear()
    draft["error"] = None


def set_draft_text(draft, html_text):
    clean, rows = extract_button_rows(html_text)
    draft["text"] = clean
    if rows:
        draft["buttons"] = rows


def get_admin_home_text_and_kb():
    total_users = get_total_users_count()
    c_counts = get_users_by_country_counts()
    text = (
        "👑 <b>Tanzania Connection - Master Admin Panel</b>\n\n"
        f"👥 Total Users: <code>{total_users}</code>\n"
        f"🇹🇿 TZ: <code>{c_counts['Tanzania']}</code> | "
        f"🇰🇪 KE: <code>{c_counts['Kenya']}</code> | "
        f"🇺🇬 UG: <code>{c_counts['Uganda']}</code>\n"
        f"🇬🇭 GH: <code>{c_counts['Ghana']}</code> | "
        f"🇳🇬 NG: <code>{c_counts['Nigeria']}</code>\n"
        f"🇿🇼 ZW: <code>{c_counts['Zimbabwe']}</code> | "
        f"🇪🇹 ET: <code>{c_counts['Ethiopia']}</code>\n"
        f"🌐 Unset: <code>{c_counts['Unset']}</code>\n\n"
        "Chagua huduma unayotaka kusimamia hapa chini:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Takwimu & Nchi", callback_data="admin_stats"),
         InlineKeyboardButton("👥 Watumiaji", callback_data="admin_users")],
        [InlineKeyboardButton("📢 Rich Broadcast", callback_data="admin_broadcast_menu"),
         InlineKeyboardButton("📈 Link Clicks", callback_data="admin_clicks")],
        [InlineKeyboardButton("🔄 Safisha Mfumo", callback_data="admin_clean")]
    ])
    return text, kb


def requested_countries_block(limit=10):
    top = get_top_requested_countries(limit)
    total = get_requested_countries_total()
    if not top:
        return "🌍 <b>NCHI ZINAZOOMBWA (Other)</b>\nHakuna bado.\n"
    lines = [f"🌍 <b>NCHI ZINAZOOMBWA (Other)</b>  ·  jumla <code>{total}</code>"]
    for i, (name, cnt) in enumerate(top, start=1):
        lines.append(f"{i}. {html_escape(name)} — <code>{cnt}</code>")
    return "\n".join(lines) + "\n"


def studio_panel_text(admin_uid, notice=None):
    draft = get_draft(admin_uid)
    items = draft["items"]
    photos = sum(1 for it in items if it["type"] == "photo")
    videos = len(items) - photos
    nbtn = sum(len(r) for r in draft["buttons"])
    blocked = get_blocked_count()
    recipients = max(get_total_users_count() - blocked, 0)
    lines = [
        "📢 <b>BROADCAST STUDIO</b>",
        f"👥 Wapokeaji: <b>{recipients}</b>" + (f"  ·  🚫 {blocked} wamezuia bot" if blocked else ""),
        f"🖼 {photos}  ·  🎬 {videos}  ·  🔘 {nbtn}  ·  📝 {'✅' if draft['text'] else '—'}",
    ]
    if notice:
        lines += ["", notice]
    if not items and not draft["text"]:
        lines += [
            "",
            "✏️ <b>Anza hapa:</b> tuma ujumbe wako (text, picha au video). Tumia format ya Telegram kama kawaida: "
            "bold, italic, <code>monospace</code> (inakopiwa kwa kugusa), link n.k.",
            "Utaona muonekano halisi juu ya paneli hii."
        ]
    else:
        lines += ["", "👆 Juu ni muonekano halisi wa ujumbe watakaoupata.", "✏️ Tuma text / picha / video mpya kubadilisha au kuongeza."]
    return "\n".join(lines)


def studio_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔘 Ongeza Button", callback_data="bcast_add_btn"),
         InlineKeyboardButton("🧩 Dhibiti Buttons", callback_data="bcast_buttons")],
        [InlineKeyboardButton("🗑 Media", callback_data="bcast_clear_media"),
         InlineKeyboardButton("🗑 Text", callback_data="bcast_clear_text"),
         InlineKeyboardButton("🗑 Zote", callback_data="bcast_clear")],
        [InlineKeyboardButton("ℹ️ Msaada", callback_data="bcast_help")],
        [InlineKeyboardButton("🚀 Tuma Sasa", callback_data="bcast_send")],
        [InlineKeyboardButton("🔙 Rudi Menyu", callback_data="admin_home")],
    ])


def _cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Ghairi", callback_data="bcast_back")]])


def track_panel(draft, message):
    key = (message.chat_id, message.message_id)
    draft["panel"] = key
    if key not in draft["ui"]:
        draft["ui"].append(key)


async def clear_studio_ui(bot, draft, keep=None):
    remaining = []
    for cid, mid in draft["ui"]:
        if keep and (cid, mid) == tuple(keep):
            remaining.append((cid, mid))
            continue
        await safe_delete_message(bot, cid, mid)
    draft["ui"] = remaining
    if draft.get("panel") and not (keep and tuple(draft["panel"]) == tuple(keep)):
        draft["panel"] = None


async def edit_panel(bot, admin_uid, text, kb=None):
    """Edit the studio control panel in place (falls back to a new message)."""
    draft = get_draft(admin_uid)
    panel = draft.get("panel")
    if panel:
        try:
            await bot.edit_message_text(
                chat_id=panel[0], message_id=panel[1], text=text, parse_mode="HTML",
                reply_markup=kb, disable_web_page_preview=True
            )
            return
        except Exception as exc:
            if "not modified" in str(exc).lower():
                return
    sent = await bot.send_message(
        chat_id=int(ADMIN_ID), text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True
    )
    if sent:
        track_panel(draft, sent)


async def render_studio(bot, chat_id, admin_uid, notice=None):
    """Show the message EXACTLY as users will get it (media + text + buttons) followed by the control panel."""
    draft = get_draft(admin_uid)
    async with draft["lock"]:
        await clear_studio_ui(bot, draft)
        draft["panel"] = None
        draft["error"] = None
        items, text = draft["items"], draft["text"]
        markup = build_markup(draft["buttons"])
        warn = None
        try:
            if len(items) > 1:
                group = []
                for idx, item in enumerate(items):
                    cap = text if idx == 0 and text else None
                    ref = item.get("admin_file_id") or item["bytes"]
                    cls = InputMediaPhoto if item["type"] == "photo" else InputMediaVideo
                    group.append(cls(media=ref, caption=cap, parse_mode="HTML" if cap else None))
                for m in await bot.send_media_group(chat_id=chat_id, media=group):
                    draft["ui"].append((chat_id, m.message_id))
                if markup:
                    m = await bot.send_message(chat_id=chat_id, text="👇" if not text else "🔗", reply_markup=markup)
                    draft["ui"].append((chat_id, m.message_id))
            elif len(items) == 1:
                item = items[0]
                ref = item.get("admin_file_id") or item["bytes"]
                send = bot.send_photo if item["type"] == "photo" else bot.send_video
                m = await send(
                    chat_id=chat_id,
                    **{("photo" if item["type"] == "photo" else "video"): ref},
                    caption=text or None,
                    parse_mode="HTML" if text else None,
                    reply_markup=markup
                )
                draft["ui"].append((chat_id, m.message_id))
            elif text:
                m = await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup)
                draft["ui"].append((chat_id, m.message_id))
        except Exception as exc:
            warn = f"⚠️ <b>Muonekano una tatizo:</b> <code>{html_escape(str(exc))[:300]}</code>\nRekebisha ujumbe kabla ya kutuma."
            draft["error"] = str(exc)
        if not items and not text and draft["buttons"]:
            warn = (warn or "") + "\n⚠️ Ongeza text au media — button peke yake haitumwi."
        note = "\n".join(x for x in (notice, warn) if x) or None
        panel = await bot.send_message(
            chat_id=chat_id, text=studio_panel_text(admin_uid, note), parse_mode="HTML",
            reply_markup=studio_keyboard(), disable_web_page_preview=True
        )
        track_panel(draft, panel)


def schedule_render(bot, chat_id, admin_uid, notice=None, delay=1.0):
    """Wait briefly (so albums / quick edits arrive together) then refresh the preview once."""
    draft = get_draft(admin_uid)
    old = draft.get("render_task")
    if old:
        old.cancel()

    async def _job():
        try:
            await asyncio.sleep(delay)
            draft.pop("render_task", None)
            await render_studio(bot, chat_id, admin_uid, notice)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(f"Studio render failed: {exc}")

    draft["render_task"] = asyncio.create_task(_job())


def buttons_manager_view(draft):
    flat = flat_buttons(draft["buttons"])
    if not flat:
        return (
            "🧩 <b>BUTTONS</b>\n\nHakuna button bado.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Ongeza Button", callback_data="bcast_add_btn")],
                [InlineKeyboardButton("🔙 Rudi Studio", callback_data="bcast_back")],
            ])
        )
    lines = ["🧩 <b>BUTTONS</b>  (gusa button kuhariri)\n"]
    kb = []
    n = 0
    for r, row in enumerate(draft["buttons"], start=1):
        for btn in row:
            lines.append(f"{n + 1}. <b>{html_escape(btn['text'])}</b>  ·  row {r}")
            kb.append([InlineKeyboardButton(f"{n + 1}. {btn['text'][:28]}", callback_data=f"bcast_be_{n}")])
            n += 1
    kb.append([InlineKeyboardButton("➕ Ongeza", callback_data="bcast_add_btn"),
               InlineKeyboardButton("📐 Mpangilio", callback_data="bcast_layout")])
    kb.append([InlineKeyboardButton("🧹 Futa Zote", callback_data="bcast_btn_clear"),
               InlineKeyboardButton("✅ Maliza", callback_data="bcast_back")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def deliver_broadcast(bot, uid, items, text, markup):
    """Send one broadcast message. Media is uploaded once; after that Telegram's file_id is reused."""
    if len(items) > 1:
        group = []
        for idx, item in enumerate(items):
            cap = text if idx == 0 and text else None
            ref = item.get("file_id") or item["bytes"]
            cls = InputMediaPhoto if item["type"] == "photo" else InputMediaVideo
            group.append(cls(media=ref, caption=cap, parse_mode="HTML" if cap else None))
        sent = await bot.send_media_group(chat_id=uid, media=group)
        for item, sent_msg in zip(items, sent):
            _cache_media_file_id(item, sent_msg)
        if markup:
            await bot.send_message(chat_id=uid, text="👇" if not text else "🔗", reply_markup=markup)
    elif len(items) == 1:
        item = items[0]
        ref = item.get("file_id") or item["bytes"]
        if item["type"] == "photo":
            sent_msg = await bot.send_photo(
                chat_id=uid, photo=ref, caption=text or None,
                parse_mode="HTML" if text else None, reply_markup=markup
            )
        else:
            sent_msg = await bot.send_video(
                chat_id=uid, video=ref, caption=text or None,
                parse_mode="HTML" if text else None, reply_markup=markup
            )
        _cache_media_file_id(item, sent_msg)
    else:
        await bot.send_message(chat_id=uid, text=text, parse_mode="HTML", reply_markup=markup)


def _progress_text(title, bid):
    st = broadcast_state
    done = st["sent"] + st["failed"]
    pct = int(done * 100 / st["total"]) if st["total"] else 100
    filled = pct // 10
    bar = "█" * filled + "░" * (10 - filled)
    return (
        f"{title}  <code>#{bid}</code>\n\n"
        f"{bar}  <b>{pct}%</b>\n"
        f"👥 Jumla: <code>{st['total']}</code>\n"
        f"✅ Imetumwa: <code>{st['sent']}</code>\n"
        f"❌ Imeshindikana: <code>{st['failed']}</code>\n"
        f"🚫 Wamezuia bot: <code>{st['blocked']}</code>"
    )


async def run_broadcast(main_app, admin_bot, chat_id, panel_id, admin_uid, snap, users, bid):
    st = broadcast_state
    items, text, rows = snap["items"], snap["text"], snap["buttons"]
    stop_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⛔ Simamisha", callback_data="bcast_stop")]])
    last_edit = time.time()
    status = "done"
    try:
        for uid in users:
            if st["stop"]:
                status = "stopped"
                break
            markup = build_markup(rows, track=(bid, uid))
            try:
                try:
                    await deliver_broadcast(main_app.bot, uid, items, text, markup)
                except RetryAfter as e:
                    await asyncio.sleep(_retry_seconds(e) + 1)
                    await deliver_broadcast(main_app.bot, uid, items, text, markup)
                st["sent"] += 1
            except Forbidden:
                st["failed"] += 1
                mark_user_blocked(uid)
                st["blocked"] += 1
            except BadRequest as e:
                st["failed"] += 1
                if "chat not found" in str(e).lower():
                    mark_user_blocked(uid)
                    st["blocked"] += 1
            except Exception:
                st["failed"] += 1
            await asyncio.sleep(0.05)

            if time.time() - last_edit > 6:
                last_edit = time.time()
                try:
                    await admin_bot.edit_message_text(
                        chat_id=chat_id, message_id=panel_id, text=_progress_text("🚀 <b>BROADCAST INATUMWA...</b>", bid),
                        parse_mode="HTML", reply_markup=stop_kb
                    )
                except Exception:
                    pass
    except Exception as exc:
        status = "error"
        logger.warning(f"Broadcast crashed: {exc}")
    finally:
        try:
            finish_broadcast(bid, st["sent"], st["failed"], status)
        except Exception:
            pass
        title = {"done": "✅ <b>BROADCAST IMEKAMILIKA!</b>", "stopped": "⛔ <b>BROADCAST IMESIMAMISHWA</b>"}.get(
            status, "⚠️ <b>BROADCAST IMEKOSA (angalia logs)</b>")
        done_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Matokeo ya Clicks", callback_data=f"admin_click_{bid}")],
            [InlineKeyboardButton("🔙 RUDI KWENYE MENYU", callback_data="admin_home")]
        ])
        try:
            await admin_bot.edit_message_text(
                chat_id=chat_id, message_id=panel_id, text=_progress_text(title, bid),
                parse_mode="HTML", reply_markup=done_kb
            )
        except Exception:
            pass
        draft = get_draft(admin_uid)
        reset_draft(draft)
        st["running"] = False
        st["stop"] = False


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
        await clear_studio_ui(context.bot, get_draft(admin_uid), keep=(query.message.chat_id, query.message.message_id))
        text, kb = get_admin_home_text_and_kb()
        await safe_edit_text(query.message, text, reply_markup=kb)
        return

    if data == "admin_stats":
        total_users = get_total_users_count()
        c_counts = get_users_by_country_counts()
        await safe_edit_text(
            query.message,
            "📊 <b>SYSTEM & COUNTRY STATISTICS</b>\n\n"
            f"👥 Total Users: <code>{total_users}</code>\n"
            f"🇹🇿 Tanzania: <code>{c_counts['Tanzania']}</code>\n"
            f"🇰🇪 Kenya: <code>{c_counts['Kenya']}</code>\n"
            f"🇺🇬 Uganda: <code>{c_counts['Uganda']}</code>\n"
            f"🇬🇭 Ghana: <code>{c_counts['Ghana']}</code>\n"
            f"🇳🇬 Nigeria: <code>{c_counts['Nigeria']}</code>\n"
            f"🇿🇼 Zimbabwe: <code>{c_counts['Zimbabwe']}</code>\n"
            f"🇪🇹 Ethiopia: <code>{c_counts['Ethiopia']}</code>\n"
            f"🌐 Unset: <code>{c_counts['Unset']}</code>\n\n"
            + requested_countries_block() +
            "\n🚀 Status: <b>Online & Stable 24/7</b>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return

    if data == "admin_users":
        total_users = get_total_users_count()
        c_counts = get_users_by_country_counts()
        users = get_all_users()
        recent = ", ".join(users[-5:]) if users else "Hakuna"
        await safe_edit_text(
            query.message,
            "👥 <b>WATUMIAJI KWA NCHI</b>\n\n"
            f"📈 Jumla Kuu: <code>{total_users}</code>\n"
            f"🇹🇿 TZ: <code>{c_counts['Tanzania']}</code> | "
            f"🇰🇪 KE: <code>{c_counts['Kenya']}</code> | "
            f"🇺🇬 UG: <code>{c_counts['Uganda']}</code>\n"
            f"🇬🇭 GH: <code>{c_counts['Ghana']}</code> | "
            f"🇳🇬 NG: <code>{c_counts['Nigeria']}</code>\n"
            f"🇿🇼 ZW: <code>{c_counts['Zimbabwe']}</code> | "
            f"🇪🇹 ET: <code>{c_counts['Ethiopia']}</code>\n"
            f"🌐 Unset: <code>{c_counts['Unset']}</code>\n"
            f"🚫 Wamezuia bot: <code>{get_blocked_count()}</code>\n"
            f"🆔 ID za mwisho 5: <code>{recent}</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return

    # ---------- Broadcast Studio ----------
    if data == "admin_broadcast_menu":
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        await safe_delete_message(context.bot, query.message.chat_id, query.message.message_id)
        await render_studio(context.bot, query.message.chat_id, admin_uid)
        return

    if data in ("bcast_back", "bcast_clear", "bcast_clear_media", "bcast_clear_text"):
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        draft = get_draft(admin_uid)
        draft["pending"].clear()
        if data == "bcast_clear":
            reset_draft(draft)
        elif data == "bcast_clear_media":
            draft["items"].clear()
        elif data == "bcast_clear_text":
            draft["text"] = ""
        track_panel(draft, query.message)
        await render_studio(context.bot, query.message.chat_id, admin_uid)
        return

    if data == "bcast_help":
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        await edit_panel(
            context.bot, admin_uid,
            "ℹ️ <b>MSAADA - BROADCAST STUDIO</b>\n\n"
            "✍️ <b>Text:</b> andika kama kawaida kwenye Telegram. Chagua maneno kisha tumia menu ya Telegram: "
            "<b>bold</b>, <i>italic</i>, <u>underline</u>, <s>strike</s>, spoiler, quote, "
            "<code>monospace</code> (mtumiaji akigusa inakopiwa), na link.\n\n"
            "🖼 <b>Media:</b> tuma picha/video moja au nyingi (hadi 10). Caption yako inakuwa text ya ujumbe.\n\n"
            "🔘 <b>Buttons:</b> bonyeza <b>Ongeza Button</b> (jina → link → mpangilio). "
            "Unaweza pia kuandika mwishoni mwa text:\n"
            "<code>Jina | https://link.com</code>\n"
            "<code>A | https://a.com || B | https://b.com</code> (2 kwa row moja)\n\n"
            "📈 Kila click kwenye button inahesabiwa kwenye <b>Link Clicks</b>.\n"
            "👆 Kila mabadiliko yanaonekana juu kama watumiaji watakavyoona.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Rudi Studio", callback_data="bcast_back")]])
        )
        return

    if data == "bcast_add_btn":
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        if sum(len(r) for r in draft["buttons"]) >= MAX_BUTTONS_TOTAL:
            await render_studio(context.bot, query.message.chat_id, admin_uid, notice=f"⚠️ Kikomo cha buttons {MAX_BUTTONS_TOTAL} kimefika.")
            return
        draft["pending"] = {}
        context.user_data["admin_mode"] = ADMIN_MODE_BTN_LABEL
        await edit_panel(
            context.bot, admin_uid,
            "🔘 <b>ONGEZA BUTTON</b>  (1/2)\n\nTuma <b>jina la button</b>.\nMfano: <code>🔥 Jiunge Sasa</code>",
            _cancel_kb()
        )
        return

    if data in ("bcast_btn_same", "bcast_btn_new"):
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        pend = draft["pending"]
        if pend.get("label") and pend.get("url"):
            add_button_to_draft(draft, pend["label"], pend["url"], same_row=(data == "bcast_btn_same"))
        draft["pending"].clear()
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        await render_studio(context.bot, query.message.chat_id, admin_uid)
        return

    if data == "bcast_buttons":
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        text_, kb_ = buttons_manager_view(draft)
        await edit_panel(context.bot, admin_uid, text_, kb_)
        return

    if data == "bcast_btn_clear":
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        draft["buttons"].clear()
        text_, kb_ = buttons_manager_view(draft)
        await edit_panel(context.bot, admin_uid, text_, kb_)
        return

    if data == "bcast_layout":
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        await edit_panel(
            context.bot, admin_uid,
            "📐 <b>MPANGILIO WA BUTTONS</b>\n\nChagua buttons ngapi kwa kila row:",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("1 kwa row", callback_data="bcast_lay_1"),
                 InlineKeyboardButton("2 kwa row", callback_data="bcast_lay_2"),
                 InlineKeyboardButton("3 kwa row", callback_data="bcast_lay_3")],
                [InlineKeyboardButton("Zote row moja", callback_data="bcast_lay_all")],
                [InlineKeyboardButton("🔙 Rudi", callback_data="bcast_buttons")],
            ])
        )
        return

    if data.startswith("bcast_lay_"):
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        per = {"1": 1, "2": 2, "3": 3, "all": MAX_BUTTONS_PER_ROW}.get(data.rsplit("_", 1)[1], 2)
        draft["buttons"] = rows_from_flat(flat_buttons(draft["buttons"]), per)
        text_, kb_ = buttons_manager_view(draft)
        await edit_panel(context.bot, admin_uid, text_, kb_)
        return

    if data.startswith(("bcast_be_", "bcast_bel_", "bcast_beu_", "bcast_bed_")):
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        action, _, idx_s = data.rpartition("_")
        idx = int(idx_s) if idx_s.isdigit() else -1
        pos = locate_button(draft["buttons"], idx)
        if pos is None:
            text_, kb_ = buttons_manager_view(draft)
            await edit_panel(context.bot, admin_uid, text_, kb_)
            return
        r, c = pos
        btn = draft["buttons"][r][c]
        if action == "bcast_bed":
            draft["buttons"][r].pop(c)
            draft["buttons"] = [row for row in draft["buttons"] if row]
            text_, kb_ = buttons_manager_view(draft)
            await edit_panel(context.bot, admin_uid, text_, kb_)
            return
        if action in ("bcast_bel", "bcast_beu"):
            draft["pending"] = {"idx": idx}
            context.user_data["admin_mode"] = ADMIN_MODE_BTN_EDIT_LABEL if action == "bcast_bel" else ADMIN_MODE_BTN_EDIT_URL
            ask = "<b>jina jipya</b> la button" if action == "bcast_bel" else "<b>link mpya</b> (https://...)"
            await edit_panel(
                context.bot, admin_uid,
                f"✏️ <b>HARIRI BUTTON {idx + 1}</b>\n\nSasa: <b>{html_escape(btn['text'])}</b>\n{html_escape(btn['url'])}\n\nTuma {ask}.",
                _cancel_kb()
            )
            return
        await edit_panel(
            context.bot, admin_uid,
            f"🔘 <b>BUTTON {idx + 1}</b>\n\n📝 Jina: <b>{html_escape(btn['text'])}</b>\n🔗 Link: {html_escape(btn['url'])}\n↔️ Row: {r + 1}",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Jina", callback_data=f"bcast_bel_{idx}"),
                 InlineKeyboardButton("🔗 Link", callback_data=f"bcast_beu_{idx}")],
                [InlineKeyboardButton("🗑 Futa", callback_data=f"bcast_bed_{idx}")],
                [InlineKeyboardButton("🔙 Rudi", callback_data="bcast_buttons")],
            ])
        )
        return

    if data == "bcast_send":
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        if broadcast_state["running"]:
            if (query.message.chat_id, query.message.message_id) != broadcast_state.get("panel"):
                await safe_edit_text(
                    query.message,
                    f"⚠️ Kuna broadcast <code>#{broadcast_state['id']}</code> inayoendelea sasa. Subiri imalize au ibonyeze Simamisha kwenye paneli yake.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
                )
            return
        if not draft["items"] and not draft["text"]:
            await render_studio(context.bot, query.message.chat_id, admin_uid, notice="❌ Hakuna kitu cha kutuma. Ongeza text au media.")
            return
        if draft.get("error"):
            await render_studio(context.bot, query.message.chat_id, admin_uid, notice="❌ Rekebisha tatizo la muonekano kwanza.")
            return
        recipients = max(get_total_users_count() - get_blocked_count(), 0)
        photos = sum(1 for it in draft["items"] if it["type"] == "photo")
        await edit_panel(
            context.bot, admin_uid,
            "⚠️ <b>THIBITISHA KUTUMA</b>\n\n"
            f"Ujumbe utatumwa kwa watumiaji <b>{recipients}</b> wote.\n"
            f"🖼 {photos}  ·  🎬 {len(draft['items']) - photos}  ·  🔘 {sum(len(r) for r in draft['buttons'])}\n\n"
            "Hakikisha muonekano wa juu uko sawa. Ukishaanza unaweza kusimamisha, "
            "lakini ujumbe uliokwisha tumwa hauwezi kurudishwa.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Ndio, Tuma Sasa", callback_data="bcast_confirm")],
                [InlineKeyboardButton("❌ Ghairi", callback_data="bcast_back")],
            ])
        )
        return

    if data == "bcast_confirm":
        draft = get_draft(admin_uid)
        track_panel(draft, query.message)
        if broadcast_state["running"]:
            if (query.message.chat_id, query.message.message_id) != broadcast_state.get("panel"):
                await safe_edit_text(
                    query.message,
                    f"⚠️ Kuna broadcast <code>#{broadcast_state['id']}</code> inayoendelea sasa. Subiri imalize au ibonyeze Simamisha kwenye paneli yake.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
                )
            return
        if (not draft["items"] and not draft["text"]) or draft.get("error"):
            await render_studio(context.bot, query.message.chat_id, admin_uid, notice="❌ Hakuna kitu sahihi cha kutuma.")
            return
        users = get_broadcast_users()
        snap = {
            "items": [dict(it) for it in draft["items"]],
            "text": draft["text"],
            "buttons": copy.deepcopy(draft["buttons"]),
        }
        bid = create_broadcast(strip_tags(draft["text"])[:80] or "(media)", len(users))
        broadcast_state.update(running=True, stop=False, id=bid, sent=0, failed=0, blocked=0, total=len(users))
        panel_key = (query.message.chat_id, query.message.message_id)
        await clear_studio_ui(context.bot, draft, keep=panel_key)
        await edit_panel(
            context.bot, admin_uid, _progress_text("🚀 <b>BROADCAST INATUMWA...</b>", bid),
            InlineKeyboardMarkup([[InlineKeyboardButton("⛔ Simamisha", callback_data="bcast_stop")]])
        )
        draft["ui"] = []
        draft["panel"] = None
        broadcast_state["panel"] = panel_key
        broadcast_state["task"] = asyncio.create_task(
            run_broadcast(main_app, context.bot, panel_key[0], panel_key[1], admin_uid, snap, users, bid)
        )
        return

    if data == "bcast_stop":
        if broadcast_state["running"]:
            broadcast_state["stop"] = True
            await safe_edit_text(
                query.message,
                _progress_text("⏳ <b>INASIMAMISHA...</b>", broadcast_state["id"])
            )
        else:
            await safe_edit_text(
                query.message, "ℹ️ Hakuna broadcast inayoendelea sasa.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
            )
        return

    # ---------- Link click tracking ----------
    if data == "admin_clicks":
        rows = get_recent_broadcasts(8)
        lines = ["📈 <b>LINK CLICKS</b>\n"]
        kb = []
        if not rows:
            lines.append("Hakuna broadcast iliyotumwa bado. Clicks zitaanza kuhesabiwa baada ya broadcast yako ya kwanza yenye button.")
        for (bid, created, preview, recipients, sent, failed, status, clicks, unique) in rows:
            lines.append(f"<b>#{bid}</b> · {html_escape(str(created)[:16])} UTC · 👆 <code>{clicks}</code> · 🧑 <code>{unique}</code>")
            kb.append([InlineKeyboardButton(f"#{bid} · {str(created)[5:16]} · 👆{clicks}", callback_data=f"admin_click_{bid}")])
        old = get_untracked_click_total()
        if old:
            lines.append(f"\nℹ️ Clicks za links za zamani (bila broadcast): <code>{old}</code>")
        kb.append([InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")])
        await safe_edit_text(query.message, "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("admin_click_"):
        bid_s = data.rsplit("_", 1)[1]
        head, links = get_broadcast_click_detail(int(bid_s)) if bid_s.isdigit() else (None, [])
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Broadcasts zote", callback_data="admin_clicks")],
            [InlineKeyboardButton("🔙 RUDI KWENYE MENYU", callback_data="admin_home")]
        ])
        if not head:
            await safe_edit_text(query.message, "❌ Broadcast haipatikani.", reply_markup=back_kb)
            return
        (bid, created, preview, recipients, sent, failed, status, clicks, unique) = head
        pct = lambda n: f"{(n * 100.0 / sent):.1f}%" if sent else "0%"
        lines = [
            f"📈 <b>MATOKEO YA BROADCAST #{bid}</b>",
            f"🗓 {html_escape(str(created)[:16])} UTC  ·  {html_escape(str(status))}",
            f"📝 {html_escape(preview or '')}",
            "",
            f"👥 Wapokeaji: <code>{recipients}</code>  ·  ✅ <code>{sent}</code>  ·  ❌ <code>{failed}</code>",
            f"👆 Clicks: <code>{clicks}</code> ({pct(clicks)})",
            f"🧑 Watu tofauti: <code>{unique}</code> ({pct(unique)})",
        ]
        if links:
            lines.append("\n🔗 <b>Kwa kila link:</b>")
            for i, (url, total, uniq) in enumerate(links, start=1):
                short = url if len(url) <= 48 else url[:45] + "..."
                lines.append(f"{i}. {html_escape(short)}\n    👆 <code>{total}</code> · 🧑 <code>{uniq}</code>")
        else:
            lines.append("\nBado hakuna aliyebonyeza link.")
        await safe_edit_text(query.message, "\n".join(lines), reply_markup=back_kb, disable_web_page_preview=True)
        return

    if data == "admin_clean":
        user_cooldowns.clear()
        await safe_edit_text(
            query.message,
            "🔄 <b>USAFISHAJI WA MFUMO</b>\n\n"
            "Kache za muda mfupi zimesafishwa. Mfumo upo safi na unafanya kazi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )


async def admin_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_uid = str(update.effective_user.id)
    if admin_uid != str(ADMIN_ID):
        return
    msg = update.message
    if not msg:
        return

    mode = context.user_data.get("admin_mode")
    chat_id = msg.chat_id
    draft = get_draft(admin_uid)

    # ----- button builder steps -----
    if mode in (ADMIN_MODE_BTN_LABEL, ADMIN_MODE_BTN_EDIT_LABEL):
        label = (msg.text or "").strip()[:64]
        if not label:
            await edit_panel(context.bot, admin_uid, "⚠️ Tuma jina la button kama text.", _cancel_kb())
            return
        if mode == ADMIN_MODE_BTN_LABEL:
            draft["pending"]["label"] = label
            context.user_data["admin_mode"] = ADMIN_MODE_BTN_URL
            await edit_panel(
                context.bot, admin_uid,
                f"🔘 <b>ONGEZA BUTTON</b>  (2/2)\n\nJina: <b>{html_escape(label)}</b>\n\nSasa tuma <b>link</b> (mfano <code>https://t.me/jina</code>).",
                _cancel_kb()
            )
        else:
            pos = locate_button(draft["buttons"], draft["pending"].get("idx", -1))
            if pos:
                draft["buttons"][pos[0]][pos[1]]["text"] = label
            draft["pending"].clear()
            context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
            await render_studio(context.bot, chat_id, admin_uid)
        return

    if mode in (ADMIN_MODE_BTN_URL, ADMIN_MODE_BTN_EDIT_URL):
        url = normalize_button_url(msg.text)
        if not url:
            await edit_panel(
                context.bot, admin_uid,
                "⚠️ Link si sahihi. Tuma link kamili, mfano <code>https://example.com</code>.",
                _cancel_kb()
            )
            return
        if mode == ADMIN_MODE_BTN_EDIT_URL:
            pos = locate_button(draft["buttons"], draft["pending"].get("idx", -1))
            if pos:
                draft["buttons"][pos[0]][pos[1]]["url"] = url
            draft["pending"].clear()
            context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
            await render_studio(context.bot, chat_id, admin_uid)
            return
        draft["pending"]["url"] = url
        if not draft["buttons"]:
            add_button_to_draft(draft, draft["pending"]["label"], url, same_row=False)
            draft["pending"].clear()
            context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
            await render_studio(context.bot, chat_id, admin_uid)
            return
        await edit_panel(
            context.bot, admin_uid,
            f"🔘 <b>{html_escape(draft['pending']['label'])}</b>\n\nIweke wapi?",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("↔️ Row ya mwisho (pembeni)", callback_data="bcast_btn_same")],
                [InlineKeyboardButton("⬇️ Row mpya (chini)", callback_data="bcast_btn_new")],
                [InlineKeyboardButton("❌ Ghairi", callback_data="bcast_back")],
            ])
        )
        return

    # ----- compose the broadcast -----
    if mode == ADMIN_MODE_BROADCAST:
        notice = None
        if msg.photo or msg.video:
            if len(draft["items"]) >= MAX_MEDIA_ITEMS:
                notice = f"⚠️ Kikomo ni media {MAX_MEDIA_ITEMS} kwa broadcast moja."
            else:
                kind = "photo" if msg.photo else "video"
                file_id = msg.photo[-1].file_id if msg.photo else msg.video.file_id
                try:
                    tg_file = await context.bot.get_file(file_id)
                    raw_bytes = bytes(await tg_file.download_as_bytearray())
                    draft["items"].append({"type": kind, "bytes": raw_bytes, "admin_file_id": file_id})
                except Exception as exc:
                    notice = f"⚠️ Siwezi kupakua {('picha' if kind == 'photo' else 'video')} hii (labda ni kubwa kuliko 20MB): {html_escape(str(exc))[:120]}"
            if msg.caption:
                set_draft_text(draft, message_to_html(msg))
        elif msg.text:
            set_draft_text(draft, message_to_html(msg))
        else:
            notice = "⚠️ Aina hiyo ya ujumbe haitumiki. Tuma text, picha au video."
        schedule_render(context.bot, chat_id, admin_uid, notice)
        return

    text, kb = get_admin_home_text_and_kb()
    await msg.reply_text(text, parse_mode="HTML", reply_markup=kb)


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
    if request.method != "HEAD":
        bid_raw = request.args.get("b", "")
        uid_raw = request.args.get("u", "")
        try:
            log_broadcast_click(
                uid_raw if uid_raw.isdigit() else "unknown",
                target_url,
                int(bid_raw) if bid_raw.isdigit() else None
            )
        except Exception:
            pass
    return redirect(target_url)


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- BACKGROUND LOOP: 2-DAY AUTO-DELETE + REGION KEYBOARD RETURN & WEEKLY BACKUP ---
async def background_automation_loop(main_app):
    last_backup_key = None
    while True:
        await asyncio.sleep(60)
        try:
            now_ts = time.time()
            cutoff_ts = now_ts - TWO_DAYS_SECONDS

            expired_rows = get_expired_messages(cutoff_ts)
            if expired_rows:
                processed_ids = []

                for row_id, uid, chat_id, msg_id in expired_rows:
                    await safe_delete_message(main_app.bot, chat_id, msg_id)
                    processed_ids.append(row_id)

                delete_tracked_messages_by_ids(processed_ids)
        except Exception as exc:
            logger.warning(f"Auto-delete loop error: {exc}")

        # Weekly Monday 03:00 UTC database backup to admin
        try:
            now_dt = datetime.utcnow()
            backup_key = now_dt.strftime("%Y-%W")
            if now_dt.weekday() == 0 and now_dt.hour == 3 and last_backup_key != backup_key:
                last_backup_key = backup_key
                if os.path.exists(DB_PATH) and ADMIN_ID:
                    with open(DB_PATH, "rb") as db_file:
                        await main_app.bot.send_document(
                            chat_id=int(ADMIN_ID),
                            document=db_file,
                            caption=f"📦 <b>AUTOMATED WEEKLY DATABASE BACKUP</b>\n📅 {now_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC",
                            parse_mode="HTML"
                        )
        except Exception:
            pass


async def reply_profile_photo(message, image_key, file_id, **kwargs):
    """Send the picture from Telegram's own storage (file_id); fall back to the old link."""
    try:
        return await message.reply_photo(photo=file_id or image_key, **kwargs)
    except Exception:
        if file_id and str(image_key).startswith("http"):
            return await message.reply_photo(photo=image_key, **kwargs)
        raise


def _retry_seconds(err):
    value = getattr(err, "retry_after", 5)
    try:
        return float(value.total_seconds())
    except AttributeError:
        return float(value)


async def sync_profile_media(main_app, admin_app=None):
    """One-time (resumable): post each IMAGES link into the private channel and remember its file_id."""
    if not PROFILE_CHANNEL_ID:
        return
    stored = get_profile_file_ids()
    todo = [u for u in dict.fromkeys(IMAGES) if u not in stored]
    if not todo:
        logger.info("Profile channel sync: all %d pictures already stored.", len(stored))
        return

    logger.info("Profile channel sync: posting %d pictures to the channel...", len(todo))
    done, failed, consecutive_fail, aborted = 0, [], 0, False
    for url in todo:
        ok = False
        for _attempt in range(2):
            try:
                msg = await main_app.bot.send_photo(chat_id=PROFILE_CHANNEL_ID, photo=url)
                photo = msg.photo[-1]
                set_profile_file_id(url, photo.file_id, photo.file_unique_id)
                ok = True
                break
            except RetryAfter as e:
                await asyncio.sleep(_retry_seconds(e) + 1)
            except Exception as e:
                logger.warning("Profile sync failed for %s: %s", url, e)
                break
        if ok:
            done += 1
            consecutive_fail = 0
        else:
            failed.append(url)
            consecutive_fail += 1
            if consecutive_fail >= 3:
                aborted = True
                break
        await asyncio.sleep(3.5)

    if aborted:
        text = (
            "❌ <b>Imeshindikana kuweka picha kwenye channel.</b>\n"
            f"Hakikisha main bot ni admin kwenye channel (<code>{PROFILE_CHANNEL_ID}</code>) na ana ruhusa ya kutuma ujumbe."
        )
    else:
        text = (
            "✅ <b>Picha za profile zimewekwa kwenye channel.</b>\n"
            f"📤 Zimefanikiwa: <code>{done}</code>\n"
            f"❌ Zimeshindikana: <code>{len(failed)}</code>"
        )
    logger.info("Profile channel sync finished: done=%d failed=%d aborted=%s", done, len(failed), aborted)
    if ADMIN_ID:
        for app_ in (admin_app, main_app):
            if app_ is None:
                continue
            try:
                await app_.bot.send_message(chat_id=int(ADMIN_ID), text=text, parse_mode="HTML")
                break
            except Exception:
                continue


async def profile_channel_post(update, context):
    """A photo posted in the private channel becomes a new profile picture automatically."""
    post = update.channel_post
    if not post or not post.photo:
        return
    photo = post.photo[-1]
    if profile_unique_id_exists(photo.file_unique_id):
        return
    set_profile_file_id(f"tg:{photo.file_unique_id}", photo.file_id, photo.file_unique_id, extra=True)
    logger.info("New profile picture added from channel: tg:%s", photo.file_unique_id)


def _cache_media_file_id(item, message):
    """After the first successful send, remember Telegram's file_id so we never upload again."""
    try:
        if item["type"] == "photo" and message.photo:
            item["file_id"] = message.photo[-1].file_id
        elif item["type"] == "video" and message.video:
            item["file_id"] = message.video.file_id
    except Exception:
        pass


async def on_error(update, context):
    # Without this, handler crashes are silent. Now they show up in the Render logs.
    logger.error("Unhandled exception while handling an update", exc_info=context.error)


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
    main_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE, text_message_handler))
    if PROFILE_CHANNEL_ID:
        main_app.add_handler(MessageHandler(
            filters.UpdateType.CHANNEL_POST & filters.Chat(chat_id=PROFILE_CHANNEL_ID) & filters.PHOTO,
            profile_channel_post
        ))

    main_app.add_error_handler(on_error)
    admin_app.add_error_handler(on_error)

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
    asyncio.create_task(sync_profile_media(main_app, admin_app))

    logger.info("Main Bot & Master Admin Panel running successfully.")

    stop_event = asyncio.Event()
    await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
    
