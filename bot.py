import os
import random
import asyncio
import logging
from datetime import datetime
from flask import Flask
from threading import Thread

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters
)

from database import init_db, add_user, add_referral, get_referral_count, get_all_users, get_total_users_count

# --- TOKENS & CONFIGS ---
MAIN_BOT_TOKEN = "8050903104:AAH0KH4ah-bdLkkNBoW2pMop3FO5-H2DN-4"
ADMIN_BOT_TOKEN = "8900606629:AAFrZXxBockQJSAJ8SqwUid98lNFt3XL4Co"
ADMIN_ID = "8231186202"
CPA_LINK = "https://tinyurl.com/Activebot"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- REGIONS LIST ---
REGIONS = [
    "Arusha", "Dar es Salaam", "Dodoma", "Geita", "Iringa", "Kagera", "Katavi", "Kigoma", "Kilimanjaro",
    "Lindi", "Manyara", "Mara", "Mbeya", "Morogoro", "Mtwara", "Mwanza", "Njombe", "Pwani", "Rukwa",
    "Ruvuma", "Shinyanga", "Simiyu", "Singida", "Tabora", "Tanga", "Zanzibar"
]

# --- LARGE POOL OF TANZANIAN NAMES ---
NAMES = [
    "Asha", "Neema", "Amina", "Rehema", "Subira", "Zainabu", "Mariam", "Sophia", "Latifa", "Yasmin",
    "Tatu", "Zuhura", "Janet", "Vero", "Happy", "Joyce", "Stella", "Lilian", "Agnes", "Mwanahamis",
    "Fatma", "Saida", "Zakia", "Fatuma", "Jamila", "Hadija", "Mariamu", "Salma",
    "Mwanahawa", "Sharifa", "Khadija", "Mwanaidi", "Saada", "Zainab", "Mwashamba", "Mwanaisha", "Asia", "Mwamvita",
    "Mwamini", "Kulthum", "Mwatima", "Mwashiuya", "Mwaashumta", "Hafsa", "Halima", "Rukia", "Mtumwa", "Muna",
    "Mwajuma", "Mwaka", "Siti", "Zulekha", "Sakina", "Mwanne", "Mwajabu", "Batuli",
    "Vanessa", "Sarah", "Irene", "Diana", "Natasha", "Linda", "Elizabeth", "Jackline", "Grace", "Naomi",
    "Brenda", "Judith", "Carol", "Mercy", "Ruth", "Catherine", "Joan", "Gloria",
    "Lucy", "Rose", "Florence", "Winnie", "Veronica", "Angel", "Faith", "Hope", "Nancy",
    "Sylvia", "Belinda", "Miriam", "Dorcas", "Queen", "Precious", "Rebecca", "Deborah", "Tina", "Aida", "Flora",
    "Anita", "Rashida", "Zuleha", "Magreth", "Zaina", "Glory", "Paulina", "Emmy", "Shamsa",
    "Ester", "Vicky", "Frida", "Brenda", "Prisca", "Frola", "Beatrice", "Diana", "Priscila"
]

# --- IMAGE POOL (You can add or update links here anytime) ---
IMAGES = [
    "https://i.postimg.cc/0j5pWDd3/FB-IMG-17498784707977300.jpg",
    "https://i.postimg.cc/Bbh2dbmv/FB-IMG-17498785863347517.jpg",
    "https://i.postimg.cc/qMTfRRBF/FB-IMG-17498786090088579.jpg",
    "https://i.postimg.cc/s2y14yJH/FB-IMG-17530068750873814.jpg",
    "https://i.postimg.cc/xdR8s7xf/FB-IMG-17530068973508200.jpg",
    "https://i.postimg.cc/MT25DnL2/FB-IMG-17530069104410087.jpg",
    "https://i.postimg.cc/VktbFKPv/FB-IMG-17530069297805077.jpg",
    "https://i.postimg.cc/T2HLMzRh/FB-IMG-17530069427792985.jpg",
    "https://i.postimg.cc/PxVxHDn0/FB-IMG-17530069517293714.jpg",
    "https://i.postimg.cc/Px5x049m/FB-IMG-17530069634125447.jpg"
]

def get_region_keyboard():
    keyboard = []
    for i in range(0, len(REGIONS), 3):
        group = REGIONS[i:i+3]
        keyboard.append([KeyboardButton(region) for region in group])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- MAIN BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))

    # Handle referral check
    if context.args:
        ref_id = context.args[0]
        add_referral(ref_id, user_id)

    # Intro message & self-deleting loading animation
    intro_msg = await update.message.reply_text("🍑 Mambo! Karibu kwenye @connectiontzzbot 🔞🇹🇿\nTunatayarisha mfumo wa Mikoa...")
    await asyncio.sleep(2)
    load_msg = await intro_msg.edit_text("Inatayarisha...... ⏳")
    await asyncio.sleep(2)
    await load_msg.delete()

    welcome_text = (
        f"🍑 Mambo {user.first_name}! Karibu kwenye *Tanzania Connection Bot* 🔞🇹🇿\n\n"
        "📍 Chagua mkoa wako hapa chini uanze kutafuta Masugar Mummy, Pisi kali, Watoto wa chuo, na Mashangazi sasa hivi! 💃🔥\n"
        "🆓 Huduma ni *BURE 100%* masaa 24/7!\n\n"
        "👇 *Bonyeza mkoa uliopo hapa chini* 👇"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_region_keyboard())

async def region_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    region = update.message.text.strip()
    if region not in REGIONS:
        return

    searching = await update.message.reply_text("🔍 Tunatafuta warembo eneo lako.....")
    await asyncio.sleep(3)
    await searching.delete()

    name = random.choice(NAMES)
    age = random.randint(18, 25)
    prefix = random.choice(["07", "06"])
    number = f"{prefix}•••••{random.randint(10,99)}"
    image_url = random.choice(IMAGES)

    caption = (
        f"💋 *JINA:* {name}\n"
        f"🎂 *UMRI:* {age}\n"
        f"📍 *ENEO:* {region}\n"
        f"📞 *NAMBA:* `{number}`\n"
        f"💰 *GHARAMA:* *BURE!*\n\n"
        "👇 *Bonyeza hapa chini kupata namba na connection* 👇"
    )

    await update.message.reply_photo(
        photo=image_url,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 PATA CONNECTION", callback_data="get_connection")]
        ])
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)

    if query.data == "get_connection":
        await query.message.reply_text(
            "⚠️ *ERROR MESSAGE* ⚠️\n\n"
            "ILI UPATE CONNECTION YAKE KWANZA UNATAKIWA KUACTIVATE 🔐 BOT KUPITIA MFUMO WETU ⚙️. "
            "CHAGUA NJIA MOJA HAPA CHINI 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
                    InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")
                ],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "activation1":
        await query.message.reply_text(
            "🔐 *JINSI YA KUACTIVATE [1]*\n\n"
            "1️⃣ Bonyeza button iliyo hapa chini 👇\n"
            "2️⃣ Download App & jibu maswali kwenye mfumo\n"
            "3️⃣ UkIMALIZA, utapokea ujumbe wa uthibitisho kupata connection! 🎯",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 ENDELEA", url=CPA_LINK)],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
    elif query.data == "activation2":
        ref_count = get_referral_count(user_id)
        await query.message.reply_text(
            f"👥 *JINSI YA KUFANYA VERIFICATION [2]*\n\n"
            f"🔗 *Link yako ya Mwaliko:*\n`https://t.me/connectiontzzbot?start={user_id}`\n\n"
            f"⏳ *Waliojiunga kupitia wewe:* `{ref_count}/10`\n\n"
            "📢 Sambaza link hii kwenye magroup 5 au kwa watu 10 ili mfumo ujifungue bure!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 CHEKI IDADI", callback_data="check_refs"),
                 InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
    elif query.data == "check_refs":
        ref_count = get_referral_count(user_id)
        if ref_count < 10:
            await query.message.reply_text(
                f"🚫 *BADO HUJATIMIZA REFERRAL 10.*\n👥 Waliojiunga: `{ref_count}/10`",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text(
                "🎉 *HONGERA!*\n\n✅ UMEKAMILISHA VERIFICATION KUPITIA NJIA YA PILI\n👇 Bonyeza hapa kuendelea:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 ENDELEA KUPATA CONNECTION", url=CPA_LINK)]
                ])
            )
    elif query.data == "back_to_error":
        await query.message.edit_text(
            "⚠️ *ERROR MESSAGE* ⚠️\n\nCHAGUA NJIA MOJA YA ACTIVATION HAPA CHINI 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
                    InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")
                ],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "back":
        await query.message.reply_text("⬅️ Chagua mkoa mwingine hapa chini:", reply_markup=get_region_keyboard())

# --- ADMIN BOT HANDLERS (@connectiontzzadminbot) ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    await update.message.reply_text(
        "👑 *Admin Control Panel*\n\n"
        "Commands:\n"
        "/stats - View total users\n"
        "/broadcast [message] - Send message to all users",
        parse_mode="Markdown"
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    total = get_total_users_count()
    await update.message.reply_text(f"📊 *Total Registered Users:* `{total}`", parse_mode="Markdown")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    
    text = " ".join(context.args)
    if not text and not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Andika ujumbe wa kutoa broadcast au reply kwenye picha/ujumbe!")
        return

    users = get_all_users()
    success = 0
    failed = 0

    status_msg = await update.message.reply_text(f"🚀 Inaanza kutuma kwa watumiaji {len(users)}...")

    # We will use the main bot token application to broadcast to users
    main_app = ApplicationBuilder().token(MAIN_BOT_TOKEN).build()
    async with main_app.bot:
        for uid in users:
            try:
                if update.message.reply_to_message:
                    await main_app.bot.copy_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.reply_to_message.message_id)
                else:
                    await main_app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
                success += 1
                await asyncio.sleep(0.05) # Prevent flood limits
            except Exception:
                failed += 1

    await status_msg.edit_text(f"✅ Broadcast Imekamilika!\n\nImetumika: {success}\nImeshindikana: {failed}")


# --- FLASK WEB SERVER FOR RENDER 24/7 ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Connection Bot is running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def start_web():
    t = Thread(target=run_flask)
    t.start()


# --- BOT RUNNERS ---
def run_admin_bot():
    admin_app = ApplicationBuilder().token(ADMIN_BOT_TOKEN).build()
    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(CommandHandler("stats", admin_stats))
    admin_app.add_handler(CommandHandler("broadcast", admin_broadcast))
    admin_app.run_polling()

if __name__ == "__main__":
    init_db()
    start_web()

    # Run Admin bot in background thread, Main bot on main thread
    from threading import Thread
    admin_thread = Thread(target=run_admin_bot)
    admin_thread.start()

    print("🤖 Main Bot & Admin Bot are starting...")
    main_app = ApplicationBuilder().token(MAIN_BOT_TOKEN).build()
    main_app.add_handler(CommandHandler("start", start))
    main_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, region_click))
    main_app.add_handler(CallbackQueryHandler(handle_callback))
    main_app.run_polling()
