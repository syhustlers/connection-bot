import os
import re
import time
import random
import asyncio
import logging
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
    get_order_details, is_user_activated,
    log_broadcast_click,
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
ADMIN_MODE_ORDER = "order"
ADMIN_MODE_BROADCAST = "broadcast"

# Pending multi-media broadcast drafts per admin user: {admin_id: {"items": [...], "text": ""}}
admin_broadcast_drafts = {}


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
        ]
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
def parse_broadcast_text_and_buttons(raw_text):
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
            f"🌐 Unset: <code>{c_counts['Unset']}</code>\n"
            "🚀 Status: <b>Online & Stable 24/7</b>",
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

    if data == "admin_check_order":
        context.user_data["admin_mode"] = ADMIN_MODE_ORDER
        await safe_edit_text(
            query.message,
            "🔍 <b>ANGALIA ORDER YA MALIPO</b>\n\n"
            "Tuma Order ID / Ref kwenye chat hii kuangalia rekodi yake kwenye database:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return

    if data == "admin_broadcast_menu":
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        admin_broadcast_drafts.setdefault(admin_uid, {"items": [], "text": ""})
        msg, kb = get_broadcast_composer_text_and_kb(admin_uid)
        await safe_edit_text(query.message, msg, reply_markup=kb)
        return

    if data == "bcast_clear":
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        admin_broadcast_drafts[admin_uid] = {"items": [], "text": ""}
        msg, kb = get_broadcast_composer_text_and_kb(admin_uid)
        await safe_edit_text(query.message, msg, reply_markup=kb)
        return

    if data == "bcast_preview":
        context.user_data["admin_mode"] = ADMIN_MODE_BROADCAST
        draft = admin_broadcast_drafts.get(admin_uid, {"items": [], "text": ""})
        items = draft.get("items", [])
        clean_text, markup = parse_broadcast_text_and_buttons(draft.get("text", ""))

        try:
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
        except Exception as exc:
            await query.message.reply_text(f"⚠️ Preview issue: <code>{exc}</code>", parse_mode="HTML")

        msg, kb = get_broadcast_composer_text_and_kb(admin_uid)
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
        return

    if data == "bcast_send":
        context.user_data.pop("admin_mode", None)
        draft = admin_broadcast_drafts.get(admin_uid, {"items": [], "text": ""})
        items = draft.get("items", [])
        clean_text, markup = parse_broadcast_text_and_buttons(draft.get("text", ""))

        if not items and not clean_text:
            await safe_edit_text(
                query.message,
                "❌ Hakuna media wala ujumbe uliowekwa. Rudi kwenye Broadcast Studio.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_broadcast_menu")]])
            )
            return

        users = get_broadcast_users()
        success = 0
        failed = 0
        newly_blocked = 0
        status_msg = await safe_edit_text(query.message, f"🚀 Inatuma broadcast kwa watumiaji {len(users)}...")

        async def deliver(uid):
            # First send uploads the file; every later send reuses Telegram's file_id (no upload).
            if len(items) > 1:
                media_group = []
                for idx, item in enumerate(items):
                    cap = clean_text if idx == 0 and clean_text else None
                    ref = item.get("file_id") or item["bytes"]
                    if item["type"] == "photo":
                        media_group.append(InputMediaPhoto(media=ref, caption=cap, parse_mode="HTML" if cap else None))
                    else:
                        media_group.append(InputMediaVideo(media=ref, caption=cap, parse_mode="HTML" if cap else None))
                sent = await main_app.bot.send_media_group(chat_id=uid, media=media_group)
                for item, sent_msg in zip(items, sent):
                    _cache_media_file_id(item, sent_msg)
                if markup:
                    await main_app.bot.send_message(
                        chat_id=uid,
                        text="👇" if not clean_text else "🔗",
                        reply_markup=markup
                    )
            elif len(items) == 1:
                item = items[0]
                ref = item.get("file_id") or item["bytes"]
                if item["type"] == "photo":
                    sent_msg = await main_app.bot.send_photo(
                        chat_id=uid,
                        photo=ref,
                        caption=clean_text or None,
                        parse_mode="HTML" if clean_text else None,
                        reply_markup=markup
                    )
                else:
                    sent_msg = await main_app.bot.send_video(
                        chat_id=uid,
                        video=ref,
                        caption=clean_text or None,
                        parse_mode="HTML" if clean_text else None,
                        reply_markup=markup
                    )
                _cache_media_file_id(item, sent_msg)
            else:
                await main_app.bot.send_message(
                    chat_id=uid,
                    text=clean_text,
                    parse_mode="HTML",
                    reply_markup=markup
                )

        for uid in users:
            try:
                try:
                    await deliver(uid)
                except RetryAfter as e:
                    await asyncio.sleep(_retry_seconds(e) + 1)
                    await deliver(uid)
                success += 1
            except Forbidden:
                # bot blocked / user deactivated: stop sending to this user in future broadcasts
                failed += 1
                mark_user_blocked(uid)
                newly_blocked += 1
            except BadRequest as e:
                failed += 1
                if "chat not found" in str(e).lower():
                    mark_user_blocked(uid)
                    newly_blocked += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)

        admin_broadcast_drafts[admin_uid] = {"items": [], "text": ""}
        done_text = (
            "✅ <b>BROADCAST IMEKAMILIKA!</b>\n\n"
            f"📤 Imefanikiwa: <code>{success}</code>\n"
            f"❌ Imeshindikana: <code>{failed}</code>\n"
            f"🚫 Wamezuia bot (hawatatumiwa tena): <code>{newly_blocked}</code>"
        )
        done_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KWENYE MENYU", callback_data="admin_home")]])
        if status_msg:
            await safe_edit_text(status_msg, done_text, reply_markup=done_kb)
        else:
            await query.message.reply_text(done_text, parse_mode="HTML", reply_markup=done_kb)
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
    try:
        log_broadcast_click("user", target_url)
    except Exception:
        pass
    return redirect(target_url)


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- BACKGROUND LOOP: 2-DAY AUTO-DELETE + REGION KEYBOARD RETURN & WEEKLY BACKUP ---
CLEANUP_NOTICE_COOLDOWN = 24 * 60 * 60   # at most one "old messages cleared" notice per user per day
last_cleanup_notice = {}


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
                notified_users = set()

                for row_id, uid, chat_id, msg_id in expired_rows:
                    await safe_delete_message(main_app.bot, chat_id, msg_id)
                    processed_ids.append(row_id)

                    if uid not in notified_users and now_ts - last_cleanup_notice.get(uid, 0) >= CLEANUP_NOTICE_COOLDOWN:
                        notified_users.add(uid)
                        last_cleanup_notice[uid] = now_ts
                        lang = get_user_language(uid)
                        country = get_user_country(uid) or DEFAULT_COUNTRY
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
