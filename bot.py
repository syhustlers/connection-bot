import os
import random
import asyncio
import logging
import httpx
from datetime import datetime
from flask import Flask
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
    save_order, update_order_status, get_order_details, is_user_activated
)

# --- TOKENS & TEEPAY CONFIGS ---
MAIN_BOT_TOKEN = "8050903104:AAH0KH4ah-bdLkkNBoW2pMop3FO5-H2DN-4"
ADMIN_BOT_TOKEN = "8900606629:AAFrZXxBockQJSAJ8SqwUid98lNFt3XL4Co"
ADMIN_ID = "8231186202"
CPA_LINK = "https://tinyurl.com/Activebot"
TARGET_SITE = "https://www.tanzaniaraha.com/"

TEEPAY_API_KEY = "tp_live_cc0486287e4c2952fbe64879ef93e09d.IfmS7gvncqmrJeouoGokbBJdArQ_oeW9b69xddZu9yQ"
TEEPAY_BASE_URL = "https://api.teepay.me"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

WAITING_PHONE = 1
ADMIN_WAITING_ORDER = 2
ADMIN_WAITING_BROADCAST = 3

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
    "https://i.postimg.cc/tgRZB2dX/tanzanian-girls-20261013-0004.webp", "https://i.postimg.cc/HLWc6B0D/tanzanian-girls-20261013-0005.webp"
]

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

    load1 = await query.message.edit_text("<i>🔐 Inathibitisha vigezo vya usalama...</i>", parse_mode="HTML")
    await asyncio.sleep(1.2)
    load2 = await load1.edit_text("<i>⚙️ Inasanidi mfumo wa mikoa...</i>", parse_mode="HTML")
    await asyncio.sleep(1.2)
    await load2.delete()

    welcome_text = (
        f"🍑 Mambo <b>{query.from_user.first_name}</b>! Karibu kwenye <b>Tanzania Connection Bot</b> 🔞🇹🇿\n\n"
        "📍 Chagua mkoa wako hapa chini uanze kutafuta Masugar Mummy, Pisi kali, Watoto wa chuo, na Mashangazi sasa hivi! 💃🔥\n"
        "🆓 Huduma ni <b>BURE 100%</b> masaa 24/7!\n\n"
        "👇 <b>Chagua mkoa unaotaka kutoka kwenye orodha hapa chini</b> 👇"
    )
    await query.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=get_region_keyboard())

async def region_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    region = update.message.text.strip()
    if region not in REGIONS:
        return

    user_id = str(update.effective_user.id)

    hide_kb = await update.message.reply_text("<i>🔄 Inapakia taarifa za eneo lako...</i>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    await hide_kb.delete()

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

    await update.message.reply_photo(
        photo=image_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 KUONGANISHWA NAE", callback_data="get_connection")],
            [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
        ])
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)

    if query.data == "get_connection":
        if is_user_activated(user_id):
            verified_success_text = (
                "🎉 <b>AKAUNTI YAKO IMEWEZESHWA KIKAMILIFU!</b> ✅\n\n"
                "Uthibitisho wako umekubaliwa kwenye mfumo. Sasa unaweza kufikia tovuti rasmi ya connection pamoja na channel na magroup yetu ya VIP hapa chini! 💃🔥\n\n"
                "🌐 <b>TOVUTI RASMI:</b>\n"
                f"🔗 <a href='{TARGET_SITE}'>Bofya Hapa Kufungua Tanzania Raha</a>\n\n"
                "📌 <b>VIP CHANNELS & GROUPS:</b>\n"
                "🔗 <a href='https://t.me/rawexotichub'>Raw Exotic Hub</a>\n"
                "🔗 <a href='https://t.me/hadithizamapenzi'>Hadithi za Mapenzi</a>\n"
                "🔗 <a href='https://t.me/hunterjay12345'>Hunterjay Channel</a>\n"
                "🔗 <a href='https://t.me/+4Zp-ZGleL1tlZmU0'>VIP Group 1</a>\n"
                "🔗 <a href='https://t.me/+t5wPETWeNGk1NDlk'>VIP Group 2</a>\n"
                "🔗 <a href='https://t.me/+nLWCZ_D1zN8zNzg8'>VIP Group 3</a>\n"
                "🔗 <a href='https://t.me/+Mn-pvG_YXqQzNTQ0'>VIP Group 4</a>\n"
                "🔗 <a href='https://t.me/+xzbacOOTVwkxNjZk'>VIP Group 5</a>\n"
                "🔗 <a href='https://t.me/+QeTJSEa1s2xmZTJk'>VIP Group 6</a>\n"
                "🔗 <a href='https://t.me/joinchat/AAAAAEzFd9XDWqbcyqXiOg'>Archive / Backup Group</a>"
            )
            await query.message.reply_text(
                verified_success_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🟢 FUNGUA LINK YA CONNECTION", url=TARGET_SITE)],
                    [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
                ])
            )
            return

        msg = await query.message.reply_text("<i>🔍 Kuchunguza seva za usalama...</i>", parse_mode="HTML")
        await asyncio.sleep(1)
        msg = await msg.edit_text("<i>🔄 Inatafuta data za mtumiaji...</i>", parse_mode="HTML")
        await asyncio.sleep(1)
        msg = await msg.edit_text("<i>🔐 Inapitia mfumo wa uthibitisho...</i>", parse_mode="HTML")
        await asyncio.sleep(1)
        msg = await msg.edit_text("<i>⚠️ Firewall imezuia upatikanaji wa namba...</i>", parse_mode="HTML")
        await asyncio.sleep(1)
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
            "Tafadhali fuata maelezo na maagizo yote yaliyopo kwenye mfumo wa tovuti yetu ili kukamilisha hatua hii kwa usahihi. 🎯",
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
            success_unlocked_text = (
                "🎉 <b>HONGERA! AKAUNTI YAKO IMEWEZESHWA!</b>\n\n"
                "✅ Umefikisha referral 10 zilizotakiwa. Hapa chini ni tovuti pamoja na channel na magroup yako ya VIP:\n\n"
                "🌐 <b>TOVUTI RASMI:</b>\n"
                f"🔗 <a href='{TARGET_SITE}'>Bofya Hapa Kufungua Tanzania Raha</a>\n\n"
                "📌 <b>VIP CHANNELS & GROUPS:</b>\n"
                "🔗 <a href='https://t.me/rawexotichub'>Raw Exotic Hub</a>\n"
                "🔗 <a href='https://t.me/hadithizamapenzi'>Hadithi za Mapenzi</a>\n"
                "🔗 <a href='https://t.me/hunterjay12345'>Hunterjay Channel</a>\n"
                "🔗 <a href='https://t.me/+4Zp-ZGleL1tlZmU0'>VIP Group 1</a>\n"
                "🔗 <a href='https://t.me/+t5wPETWeNGk1NDlk'>VIP Group 2</a>\n"
                "🔗 <a href='https://t.me/+nLWCZ_D1zN8zNzg8'>VIP Group 3</a>\n"
                "🔗 <a href='https://t.me/+Mn-pvG_YXqQzNTQ0'>VIP Group 4</a>\n"
                "🔗 <a href='https://t.me/+xzbacOOTVwkxNjZk'>VIP Group 5</a>\n"
                "🔗 <a href='https://t.me/+QeTJSEa1s2xmZTJk'>VIP Group 6</a>\n"
                "🔗 <a href='https://t.me/joinchat/AAAAAEzFd9XDWqbcyqXiOg'>Archive / Backup Group</a>"
            )
            await query.message.reply_text(
                success_unlocked_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 KWENDA KWENYE TOVUTI", url=TARGET_SITE)]])
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
        public_ref = query.data.split("_")[2]
        status_msg = await query.message.reply_text("<i>🔄 Inakagua hali ya malipo kupitia TeePay...</i>", parse_mode="HTML")
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(
                    f"{TEEPAY_BASE_URL}/v1/collections/{public_ref}",
                    headers={"Authorization": f"Bearer {TEEPAY_API_KEY}"},
                    timeout=15
                )
                res_data = res.json()

            if res.status_code == 200:
                status = res_data.get("status", "pending")
                if status == "succeeded":
                    update_order_status(public_ref, "completed")
                    payment_unlocked_text = (
                        "🎉 <b>MALIPO YAMEKAMILIKA KWA MAFANIKIO!</b> ✅\n\n"
                        "Akaunti yako sasa imewashwa rasmi kupitia TeePay. Hapa chini ni tovuti pamoja na channel na magroup yako ya VIP:\n\n"
                        "🌐 <b>TOVUTI RASMI:</b>\n"
                        f"🔗 <a href='{TARGET_SITE}'>Bofya Hapa Kufungua Tanzania Raha</a>\n\n"
                        "📌 <b>VIP CHANNELS & GROUPS:</b>\n"
                        "🔗 <a href='https://t.me/rawexotichub'>Raw Exotic Hub</a>\n"
                        "🔗 <a href='https://t.me/hadithizamapenzi'>Hadithi za Mapenzi</a>\n"
                        "🔗 <a href='https://t.me/hunterjay12345'>Hunterjay Channel</a>\n"
                        "🔗 <a href='https://t.me/+4Zp-ZGleL1tlZmU0'>VIP Group 1</a>\n"
                        "🔗 <a href='https://t.me/+t5wPETWeNGk1NDlk'>VIP Group 2</a>\n"
                        "🔗 <a href='https://t.me/+nLWCZ_D1zN8zNzg8'>VIP Group 3</a>\n"
                        "🔗 <a href='https://t.me/+Mn-pvG_YXqQzNTQ0'>VIP Group 4</a>\n"
                        "🔗 <a href='https://t.me/+xzbacOOTVwkxNjZk'>VIP Group 5</a>\n"
                        "🔗 <a href='https://t.me/+QeTJSEa1s2xmZTJk'>VIP Group 6</a>\n"
                        "🔗 <a href='https://t.me/joinchat/AAAAAEzFd9XDWqbcyqXiOg'>Archive / Backup Group</a>"
                    )
                    await status_msg.edit_text(
                        payment_unlocked_text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 FUNGUA LINK YA CONNECTION", url=TARGET_SITE)]])
                    )
                else:
                    await status_msg.edit_text(
                        f"⏳ <b>MALIPO YANAENDELEA (PENDING)</b>\n\n"
                        f"Hali ya sasa: <code>{status}</code>\nTafadhali thibitisha malipo kwenye simu yako kisha uguse tena kitufe cha kukagua hapa chini.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 ANGALIA TENA MALIPO", callback_data=f"check_pay_{public_ref}")],
                            [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
                        ])
                    )
            else:
                await status_msg.edit_text("❌ Imeshindikana kuangalia malipo. Jaribu tena baada ya sekunde chache.")
        except Exception:
            await status_msg.edit_text("❌ Hitilafu ya kimtandao wakati wa kuwasiliana na TeePay.")
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

    user = update.effective_user
    user_id = str(user.id)
    phone = text

    if not phone.startswith("0") or len(phone) < 10:
        await update.message.reply_text("❌ Namba si sahihi. Weka namba sahihi ya simu (mfano: 0712345678) au tuma /cancel kusitisha:")
        return WAITING_PHONE

    status_msg = await update.message.reply_text("⏳ Inatuma ombi la USSD Push kupitia TeePay kwenye simu yako...")

    formatted_phone = "+255" + phone[1:] if phone.startswith("0") else "+" + phone
    idempotency_key = f"tp-push-{user_id}-{int(datetime.utcnow().timestamp())}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{TEEPAY_BASE_URL}/v1/collections",
                json={
                    "money": {"amount_minor": "350000", "currency": "TZS"},
                    "customer": {
                        "country": "TZ",
                        "phone": formatted_phone,
                        "name": user.first_name or "Tanzania User",
                        "email": f"user{user_id}@teepay.co.tz"
                    },
                    "description": "Connection Activation Fee"
                },
                headers={
                    "Authorization": f"Bearer {TEEPAY_API_KEY}",
                    "Idempotency-Key": idempotency_key,
                    "Content-Type": "application/json"
                },
                timeout=20
            )
            res_data = response.json()

        if response.status_code in [200, 202]:
            public_ref = res_data.get("public_reference") or idempotency_key
            save_order(public_ref, user_id, phone, 3500, "pending")
            await status_msg.edit_text(
                f"📱 <b>USSD PUSH IMETUMWA NA TEEPAY!</b>\n\n"
                f"Weka PIN kwenye simu yako kulipia TZS 3,500.\n\n"
                f"Baada ya kuweka PIN, bonyeza kitufe hapa chini kukagua kama malipo yamethibitishwa:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 ANGALIA HALI YA MALIPO", callback_data=f"check_pay_{public_ref}")],
                    [InlineKeyboardButton("🔙 RUDI KWENYE MKOA", callback_data="back_to_regions")]
                ])
            )
        else:
            err_msg = res_data.get("error", {}).get("message", "Jaribu tena baadaye.")
            await status_msg.edit_text(f"❌ Imeshindikana: {err_msg}")
    except Exception:
        await status_msg.edit_text("❌ Hitilafu ya kimtandao wakati wa kuwasiliana na TeePay.")

    return ConversationHandler.END

async def cancel_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Imesitishwa.", reply_markup=get_region_keyboard())
    return ConversationHandler.END


# --- SUPERCHARGED INTERACTIVE ADMIN BOT WITH PREVIEW & BUTTON SUPPORT ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    await update.message.reply_text(
        "👑 <b>Tanzania Connection - Master Admin Panel</b>\n\n"
        "Chagua huduma au kipengele unachotaka kusimamia hapa chini:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Takwimu za Jumla", callback_data="admin_stats"),
             InlineKeyboardButton("💰 Salio la TeePay", callback_data="admin_wallet")],
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
        await query.message.edit_text(
            f"💰 <b>TEEPAY WALLET STATUS</b>\n\n"
            f"💵 Gateway: <b>TeePay USSD Push Active</b>\n"
            f"🚀 Status: <b>Online & Ready</b>\n\n"
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
            "🔍 <b>ANGALIA PUBLIC REFERENCE YA MALIPO</b>\n\n"
            "Tafadhali tuma Public Reference (mfano: TP8K2M4QZ1) kwenye chat hii kukagua hali yake:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]])
        )
        return ADMIN_WAITING_ORDER
    elif query.data == "admin_broadcast_prompt":
        await query.message.edit_text(
            "📢 <b>MFUMO WA KUTUMA MATANGAZO (BROADCAST HUB)</b>\n\n"
            "Tuma hapa <b>Ujumbe, Picha, au Video</b> unayotaka kuwatumia watumiaji wote.\n\n"
            "💡 <i>Kama unahitaji kitufe (button) kwenye tangazo lako, andika ujumbe wako kisha weka mstari wa mwisho kwa mfumo huu:</i>\n"
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
        await query.message.edit_text(
            "👑 <b>Tanzania Connection - Master Admin Panel</b>\n\n"
            "Chagua huduma au kipengele unachotaka kusimamia hapa chini:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Takwimu za Jumla", callback_data="admin_stats"),
                 InlineKeyboardButton("💰 Salio la TeePay", callback_data="admin_wallet")],
                [InlineKeyboardButton("👥 Orodha ya Watumiaji", callback_data="admin_users"),
                 InlineKeyboardButton("🔍 Angalia Order", callback_data="admin_check_order")],
                [InlineKeyboardButton("📢 Tuma Tangazo", callback_data="admin_broadcast_prompt"),
                 InlineKeyboardButton("🔄 Safisha Mfumo", callback_data="admin_clean")]
            ])
        )

async def admin_receive_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return ConversationHandler.END
    public_ref = update.message.text.strip()
    order_data = get_order_details(public_ref)
    
    api_status = "Unknown"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{TEEPAY_BASE_URL}/v1/collections/{public_ref}",
                headers={"Authorization": f"Bearer {TEEPAY_API_KEY}"},
                timeout=10
            )
            if res.status_code == 200:
                api_status = res.json().get("status", "Unknown")
    except Exception:
        pass

    if order_data:
        uid, phone, amount, db_status = order_data
        await update.message.reply_text(
            f"📦 <b>MAELEZO YA COLLECTION: {public_ref}</b>\n\n"
            f"👤 User ID: <code>{uid}</code>\n"
            f"📱 Namba ya Simu: <code>{phone}</code>\n"
            f"💵 Kiasi: <code>TZS {amount}</code>\n"
            f"💾 Hali (DB): <code>{db_status}</code>\n"
            f"🌐 Hali (TeePay API): <code>{api_status}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KUBWA", callback_data="admin_home")]])
        )
    else:
        await update.message.reply_text(
            f"❌ Reference <code>{public_ref}</code> haipatikani kwenye database.\n(Hali ya API: {api_status})",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI KUBWA", callback_data="admin_home")]])
        )
    return ConversationHandler.END

# --- TRUE PREVIEW BROADCAST WORKFLOW ---
async def admin_receive_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return ConversationHandler.END
    
    context.user_data['broadcast_msg'] = update.message

    await update.message.reply_text(
        "👁️ <b>HAKIKI YA TANGAZO (PREVIEW)</b>\n\n"
        "Hivi ndivyo ujumbe wako utakavyowafikia wanachama wote hapa chini:",
        parse_mode="HTML"
    )

    text_content = update.message.text or update.message.caption or ""
    preview_markup = None
    if "|" in text_content:
        parts = text_content.split("\n")
        last_line = parts[-1]
        if "|" in last_line:
            btn_text, btn_url = last_line.split("|", 1)
            preview_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text.strip(), url=btn_url.strip())]])

    if update.message.photo:
        await update.message.reply_photo(photo=update.message.photo[-1].file_id, caption=text_content, parse_mode="HTML", reply_markup=preview_markup)
    elif update.message.video:
        await update.message.reply_video(video=update.message.video.file_id, caption=text_content, parse_mode="HTML", reply_markup=preview_markup)
    else:
        await update.message.reply_text(text_content, parse_mode="HTML", reply_markup=preview_markup)

    await update.message.reply_text(
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

    msg_obj = context.user_data.get('broadcast_msg')
    if not msg_obj:
        await query.message.edit_text("❌ Hakuna ujumbe uliopatikana wa kutuma. Tafadhali jaribu tena.")
        return

    users = get_all_users()
    success = 0
    failed = 0

    status_msg = await query.message.edit_text(f"🚀 Inaanza kutuma tangazo kwa watumiaji {len(users)}...")

    text_content = msg_obj.text or msg_obj.caption or ""
    final_markup = None
    if "|" in text_content:
        parts = text_content.split("\n")
        last_line = parts[-1]
        if "|" in last_line:
            btn_text, btn_url = last_line.split("|", 1)
            final_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text.strip(), url=btn_url.strip())]])

    for uid in users:
        try:
            if msg_obj.photo:
                await main_app.bot.send_photo(chat_id=uid, photo=msg_obj.photo[-1].file_id, caption=text_content, parse_mode="HTML", reply_markup=final_markup)
            elif msg_obj.video:
                await main_app.bot.send_video(chat_id=uid, video=msg_obj.video.file_id, caption=text_content, parse_mode="HTML", reply_markup=final_markup)
            else:
                await main_app.bot.send_message(chat_id=uid, text=text_content, parse_mode="HTML", reply_markup=final_markup)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ <b>TANGAZO LIMETUMWA KIKAMILIFU!</b>\n\n"
        f"📤 Imefanikiwa Kutumika: <code>{success}</code>\n"
        f"❌ Imeshindikana: <code>{failed}</code>",
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


# --- FLASK WEB SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Connection Bot with TeePay USSD Push Fully Upgraded & Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

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

    print("🤖 Upgraded Main Bot & Master Admin Panel running successfully with TeePay USSD Push!")

    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
