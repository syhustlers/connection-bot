import os
import random
import asyncio
import logging
import requests
from datetime import datetime
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
    log_broadcast_click, get_click_count_for_url, save_product, get_product
)

# --- SECURE ENVIRONMENT CONFIGS ---
MAIN_BOT_TOKEN = os.environ.get("MAIN_BOT_TOKEN", "8050903104:AAH0KH4ah-bdLkkNBoW2pMop3FO5-H2DN-4")
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8900606629:AAFrZXxBockQJSAJ8SqwUid98lNFt3XL4Co")
ADMIN_ID = os.environ.get("ADMIN_ID", "8231186202")
HARAKAPAY_API_KEY = os.environ.get("HARAKAPAY_API_KEY", "hpk_29f08857e1613f2df534581540097759168284249880fa85")

CPA_LINK = "https://tinyurl.com/Activebot"
TARGET_SITE = "https://www.tanzaniaraha.com/"
REQUIRED_CHANNEL = "@connectiontzz"
HARAKAPAY_BASE_URL = "https://harakapay.net"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Conversation States
WAITING_PHONE = 1
ADMIN_WAITING_ORDER = 2
ADMIN_WAITING_BROADCAST = 3
USER_BUYING_PHONE = 4

# Admin Product Creation Steps
ADMIN_PROD_SALES_POST = 10
ADMIN_PROD_PRICE = 11
ADMIN_PROD_BTN_TEXT = 12
ADMIN_PROD_SUCCESS_POST = 13

user_cooldowns = {}

async def check_antispam(user_id):
    now = datetime.utcnow()
    last_time = user_cooldowns.get(user_id)
    if last_time and (now - last_time).total_seconds() < 0.8:
        return False
    user_cooldowns[user_id] = now
    return True

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
    "Khadija", "Mwanaidi", "Saada", "Zainab", "Mwashamba", "Mwanaisha", "Asia", "Mwamvita", "Mwamini", "Kulthum"
]

IMAGES = [
    "https://i.postimg.cc/vm1M8nbg/1791854037257.jpg",
    "https://i.postimg.cc/fynkD7PG/1791906305237.jpg",
    "https://i.postimg.cc/G2s9WgXM/1791906329014.jpg",
    "https://i.postimg.cc/50FjhKs8/1791906348662.jpg",
    "https://i.postimg.cc/LsWn0F3Z/1791906353383.jpg"
]

def get_verified_success_text():
    return (
        "🎉 <b>AKAUNTI YAKO IMEWEZESHWA KIKAMILIFU!</b> ✅\n\n"
        "Hongera! Uthibitisho wako umekubaliwa kwenye mfumo na sasa una ufikiaji kamili wa huduma zote za VIP na machapisho ya kipekee. 💃🔥\n\n"
        "🔗 <b>TOVUTI KUU YA CONNECTION:</b>\n"
        "👉 <a href=\"https://www.tanzaniaraha.com/\">Fungua Tanzania Raha</a>"
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
        args_text = context.args[0]
        if args_text.startswith("buy_"):
            try:
                prod_id = int(args_text.split("_")[1])
                prod = get_product(prod_id)
                if prod:
                    pid, price = prod[0], prod[1]
                    context.user_data['buying_product_id'] = pid
                    context.user_data['buying_product_price'] = price
                    
                    await update.message.reply_text(
                        f"🛍️ <b>UNAKARIBIA KUNUNUA BIDHAA</b>\n\n"
                        f"💵 <b>BEI:</b> TZS {price:,}\n\n"
                        f"Tafadhali tuma namba yako ya simu ya mtandao (M-Pesa, TigoPesa, AirtelMoney) ili nikutumie ombi la malipo (mfano: 0712345678):",
                        parse_mode="HTML"
                    )
                    return USER_BUYING_PHONE
            except Exception:
                pass

        ref_id = args_text
        add_referral(ref_id, user_id)

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
            f"👉 <a href=\"https://t.me/connectiontzz\">Jiunge na Connection TZZ</a>\n\n"
            f"Baada ya kujiunga, bonyeza hapa chini:",
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
    if not await check_membership(context.bot, query.from_user.id):
        await query.answer("⚠️ Bado hujajiunga na channel!", show_alert=True)
        return
    await query.answer("✅ Uanachama umethibitishwa!")
    try:
        await query.message.delete()
    except Exception:
        pass
    await proceed_to_regions(query.message)

async def proceed_to_regions(message):
    welcome_text = (
        f"🍑 Karibu kwenye <b>Tanzania Connection Bot</b> 🔞🇹🇿\n\n"
        "📍 Chagua mkoa wako hapa chini uanze kutafuta Masugar Mummy na Pisi kali sasa hivi! 💃🔥\n\n"
        "👇 <b>Chagua mkoa unaotaka kutoka kwenye orodha hapa chini</b> 👇"
    )
    await message.reply_text(welcome_text, parse_mode="HTML", reply_markup=get_region_keyboard())

async def region_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_antispam(str(user_id)):
        return

    region = update.message.text.strip()
    if region not in REGIONS:
        # Fallback text handler for any random text outside flows -> returns region keyboard
        await update.message.reply_text(
            "✨ <b>Chagua mkoa wako kutoka kwenye orodha hapa chini:</b>",
            parse_mode="HTML",
            reply_markup=get_region_keyboard()
        )
        return

    hide_kb = await update.message.reply_text("<i>🔄 Inapakia taarifa za eneo lako...</i>", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(0.5)
    await hide_kb.delete()

    seen = get_seen_images(str(user_id))
    available = [img for img in IMAGES if img not in seen]
    if not available:
        reset_seen_images(str(user_id))
        available = IMAGES

    image_url = random.choice(available)
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
        f"📞 <b>NAMBA YA SIMU:</b> {number}\n\n"
        "👇 <b>Bonyeza kitufe hapa chini kuunganishwa nae</b> 👇"
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
    user_id = str(query.from_user.id)
    if not await check_antispam(user_id):
        await query.answer("⚠️ Subiri kidogo...", show_alert=True)
        return

    await query.answer()

    if query.data == "check_sub":
        if not await check_membership(context.bot, query.from_user.id):
            await query.answer("⚠️ Bado hujajiunga!", show_alert=True)
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
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🟢 FUNGUA TOVUTI", url=TARGET_SITE)],
                    [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_regions")]
                ])
            )
            return

        await query.message.reply_text(
            "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\n"
            "Chagua njia ya activation hapa chini 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
                 InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")],
                [InlineKeyboardButton("✅ ACTIVATION 3", callback_data="activation3")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "activation1":
        await query.message.edit_text(
            "🔐 <b>ACTIVATION [1]</b>\n\nFuata maelezo kwenye mfumo wetu.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 FUNGUA TOVUTI", url=CPA_LINK)],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
    elif query.data == "activation2":
        ref_count = get_referral_count(user_id)
        await query.message.edit_text(
            f"👥 <b>ACTIVATION [2]</b>\n\n"
            f"🔗 <b>Link yako:</b>\n<pre><code>https://t.me/connectiontzzbot?start={user_id}</code></pre>\n\n"
            f"⏳ <b>Waliojiunga:</b> <code>{ref_count}/10</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 CHEKI IDADI", callback_data="check_refs")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
    elif query.data == "check_refs":
        if get_referral_count(user_id) < 10:
            await query.answer("🚫 Bado hujatimiza referral 10!", show_alert=True)
        else:
            await query.message.reply_text(get_verified_success_text(), parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 FUNGUA TOVUTI", url=TARGET_SITE)]]))
    elif query.data == "activation3":
        await query.message.edit_text(
            "💳 <b>ACTIVATION YA HARAKA - TZS 3,500</b>\n\nWeka namba yako ya simu (mfano: 0712345678):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]])
        )
        return WAITING_PHONE
    elif query.data.startswith("check_pay_"):
        order_id = query.data.split("_")[2]
        status_msg = await query.message.reply_text("<i>🔄 Inakagua malipo...</i>", parse_mode="HTML")
        try:
            res = requests.get(f"{HARAKAPAY_BASE_URL}/api/v1/status/{order_id}", headers={"X-API-Key": HARAKAPAY_API_KEY}, timeout=15).json()
            if res.get("success") and res.get("payment", {}).get("status") == "completed":
                update_order_status(order_id, "completed")
                order_data = get_order_details(order_id)
                
                # If product purchase, deliver product content
                if order_data and len(order_data) >= 5 and order_data[4]:
                    prod = get_product(order_data[4])
                    if prod:
                        _, _, _, _, _, _, s_type, s_file, s_cap, s_btn_txt, s_btn_url = prod
                        markup = InlineKeyboardMarkup([[InlineKeyboardButton(s_btn_txt, url=s_btn_url)]]) if s_btn_txt and s_btn_url else None
                        if s_type == "photo" and s_file:
                            await context.bot.send_photo(chat_id=query.from_user.id, photo=s_file, caption=s_cap, parse_mode="HTML", reply_markup=markup)
                        elif s_type == "video" and s_file:
                            await context.bot.send_video(chat_id=query.from_user.id, video=s_file, caption=s_cap, parse_mode="HTML", reply_markup=markup)
                        else:
                            await context.bot.send_message(chat_id=query.from_user.id, text=s_cap, parse_mode="HTML", reply_markup=markup)

                await status_msg.edit_text(get_verified_success_text(), parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🟢 FUNGUA TOVUTI", url=TARGET_SITE)]]))
            else:
                await status_msg.edit_text("⏳ Malipo bado yanaendelea (Pending). Jaribu tena baada ya sekunde chache.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 ANGALIA TENA", callback_data=f"check_pay_{order_id}")]]))
        except Exception:
            await status_msg.edit_text("❌ Hitilafu ya mtandao.")
    elif query.data == "back_to_error":
        await query.message.edit_text("🛑 Chagua njia ya activation 👇", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"), InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")],
            [InlineKeyboardButton("✅ ACTIVATION 3", callback_data="activation3")],
            [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
        ]))
    elif query.data == "back" or query.data == "back_to_regions":
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.reply_text("✨ Chagua mkoa wako:", parse_mode="HTML", reply_markup=get_region_keyboard())

async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.startswith("0") or len(phone) < 10:
        await update.message.reply_text("❌ Namba si sahihi. Weka tena (mfano: 0712345678):")
        return WAITING_PHONE

    status_msg = await update.message.reply_text("⏳ Inatuma ombi la USSD Push...")
    try:
        response = requests.post(f"{HARAKAPAY_BASE_URL}/api/v1/collect", json={"phone": phone, "amount": 3500, "description": "Activation"}, headers={"Content-Type": "application/json", "X-API-Key": HARAKAPAY_API_KEY}, timeout=15).json()
        if response.get("success"):
            order_id = response.get("order_id")
            save_order(order_id, str(update.effective_user.id), phone, 3500, "pending")
            await status_msg.edit_text(f"📱 Weka PIN kwenye simu yako kulipia TZS 3,500.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 ANGALIA HALI", callback_data=f"check_pay_{order_id}")]]))
        else:
            await status_msg.edit_text(f"❌ Imeshindikana: {response.get('error')}")
    except Exception:
        await status_msg.edit_text("❌ Hitilafu ya mtandao.")
    return ConversationHandler.END

async def receive_buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if not phone.startswith("0") or len(phone) < 10:
        await update.message.reply_text("❌ Namba si sahihi. Weka tena:")
        return USER_BUYING_PHONE

    prod_id = context.user_data.get('buying_product_id')
    price = context.user_data.get('buying_product_price', 0)
    status_msg = await update.message.reply_text(f"⏳ Inatuma ombi la TZS {price:,}...")
    try:
        response = requests.post(f"{HARAKAPAY_BASE_URL}/api/v1/collect", json={"phone": phone, "amount": price, "description": "Product Buy"}, headers={"Content-Type": "application/json", "X-API-Key": HARAKAPAY_API_KEY}, timeout=15).json()
        if response.get("success"):
            order_id = response.get("order_id")
            save_order(order_id, str(update.effective_user.id), phone, price, "pending", prod_id)
            await status_msg.edit_text(f"📱 Weka PIN kulipia TZS {price:,}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 ANGALIA HALI", callback_data=f"check_pay_{order_id}")]]))
        else:
            await status_msg.edit_text(f"❌ Imeshindikana: {response.get('error')}")
    except Exception:
        await status_msg.edit_text("❌ Hitilafu ya mtandao.")
    return ConversationHandler.END


# --- ADMIN PANEL & PRODUCT CREATION WIZARD ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    await update.message.reply_text(
        f"👑 <b>Admin Panel</b>\n👥 Users: <code>{get_total_users_count()}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Takwimu", callback_data="admin_stats"), InlineKeyboardButton("💰 Wallet", callback_data="admin_wallet")],
            [InlineKeyboardButton("📢 Tuma Tangazo", callback_data="admin_broadcast_prompt"), InlineKeyboardButton("🛍️ Unda Bidhaa", callback_data="admin_create_product")],
            [InlineKeyboardButton("🔄 Safisha", callback_data="admin_clean")]
        ])
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.from_user.id) != ADMIN_ID:
        return
    await query.answer()

    if query.data == "admin_stats":
        await query.message.edit_text(f"📊 Total Users: <code>{get_total_users_count()}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]]))
    elif query.data == "admin_wallet":
        await query.message.edit_text("💰 HarakaPay Wallet Connected.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]]))
    elif query.data == "admin_broadcast_prompt":
        await query.message.edit_text("📢 Tuma ujumbe, picha, au video ya tangazo pamoja na link ya button (Mwishoni: `Kitufe | https://...`):", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]]))
        return ADMIN_WAITING_BROADCAST
    elif query.data == "admin_create_product":
        await query.message.edit_text(
            "🛍️ <b>HATUA YA 1/4: UJUMBE WA MAUZO (SALES POST)</b>\n\n"
            "Tuma picha, video, au maandishi ambayo wateja watayaona kabla ya kununua.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ GHAIRI", callback_data="admin_home")]])
        )
        return ADMIN_PROD_SALES_POST
    elif query.data == "admin_clean":
        await query.message.edit_text("🔄 Imesafishwa.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]]))
    elif query.data == "admin_home":
        await query.message.edit_text(
            "👑 <b>Admin Panel</b>", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Takwimu", callback_data="admin_stats"), InlineKeyboardButton("💰 Wallet", callback_data="admin_wallet")],
                [InlineKeyboardButton("📢 Tuma Tangazo", callback_data="admin_broadcast_prompt"), InlineKeyboardButton("🛍️ Unda Bidhaa", callback_data="admin_create_product")],
                [InlineKeyboardButton("🔄 Safisha", callback_data="admin_clean")]
            ])
        )

# Product Wizard Steps
async def admin_prod_sales_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    context.user_data['sales_media_type'] = "photo" if msg.photo else ("video" if msg.video else "text")
    context.user_data['sales_media_file_id'] = msg.photo[-1].file_id if msg.photo else (msg.video.file_id if msg.video else None)
    context.user_data['sales_caption'] = msg.text or msg.caption or ""

    await msg.reply_text("💵 <b>HATUA YA 2/4: BEI YA BIDHAA</b>\n\nAndika bei kwa TZS (mfano: 5000):", parse_mode="HTML")
    return ADMIN_PROD_PRICE

async def admin_prod_price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        context.user_data['prod_price'] = price
    except ValueError:
        await update.message.reply_text("❌ Weka namba sahihi ya bei:")
        return ADMIN_PROD_PRICE

    await update.message.reply_text("🔘 <b>HATUA YA 3/4: JINA LA KITUFE CHA KUNUNUA</b>\n\nAndika maandishi ya kitufe (mfano: <i>Nunua Sasa Hapa</i>):", parse_mode="HTML")
    return ADMIN_PROD_BTN_TEXT

async def admin_prod_btn_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['prod_btn_text'] = update.message.text.strip()
    await update.message.reply_text(
        "🎁 <b>HATUA YA 4/4: UJUMBE WA BAADA YA MALIPO (SUCCESS DELIVERY)</b>\n\n"
        "Tuma ujumbe, picha, au video pamoja na viungo/button vitakavyotumwa kwa mteja mara baada ya kulipia.\n\n"
        "💡 <i>Kama unahitaji kitufe kwenye ujumbe wa mafanikio, weka mstari wa mwisho kwa mtindo huu:</i>\n"
        "<code>Jina la Kitufe | https://linkyako.com</code>",
        parse_mode="HTML"
    )
    return ADMIN_PROD_SUCCESS_POST

async def admin_prod_success_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    raw_text = msg.text or msg.caption or ""
    s_caption = raw_text
    s_btn_txt, s_btn_url = None, None

    if "|" in raw_text:
        parts = raw_text.split("\n")
        last = parts[-1]
        if "|" in last:
            s_btn_txt, s_btn_url = [x.strip() for x in last.split("|", 1)]
            s_caption = "\n".join(parts[:-1]).strip()

    s_type = "photo" if msg.photo else ("video" if msg.video else "text")
    s_file = msg.photo[-1].file_id if msg.photo else (msg.video.file_id if msg.video else None)

    # Save to Database
    prod_id = save_product(
        price=context.user_data['prod_price'],
        sales_media_type=context.user_data['sales_media_type'],
        sales_media_file_id=context.user_data['sales_media_file_id'],
        sales_caption=context.user_data['sales_caption'],
        button_text=context.user_data['prod_btn_text'],
        success_media_type=s_type,
        success_media_file_id=s_file,
        success_caption=s_caption,
        success_btn_text=s_btn_txt,
        success_btn_url=s_btn_url
    )

    bot_username = (await context.bot.get_me()).username
    buy_link = f"https://t.me/{bot_username}?start=buy_{prod_id}"

    await update.message.reply_text(
        f"✅ <b>BIDHAA IMEWEKWA KIKAMILIFU!</b> 🎉\n\n"
        f"🔗 <b>Link ya Kutangaza Bidhaa:</b>\n<pre><code>{buy_link}</code></pre>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI MENYU", callback_data="admin_home")]])
    )
    return ConversationHandler.END


# --- BROADCAST HANDLER ---
async def admin_receive_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    users = get_all_users()
    success, failed = 0, 0

    status_msg = await msg.reply_text(f"🚀 Inatuma kwa watumiaji {len(users)}...")
    for uid in users:
        try:
            if msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption=msg.caption or "", parse_mode="HTML")
            elif msg.video:
                await context.bot.send_video(chat_id=uid, video=msg.video.file_id, caption=msg.caption or "", parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=uid, text=msg.text or "", parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.03)
        except Exception:
            failed += 1

    await status_msg.edit_text(f"✅ Imetumika: {success} | Imeshindikana: {failed}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 RUDI", callback_data="admin_home")]]))
    return ConversationHandler.END


# --- FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Running 24/7 with Persistent Disk!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))


# --- MAIN RUNNER ---
async def main():
    init_db()
    Thread(target=run_flask, daemon=True).start()

    main_app = ApplicationBuilder().token(MAIN_BOT_TOKEN).build()
    admin_app = ApplicationBuilder().token(ADMIN_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^activation3$")],
        states={WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)]},
        fallbacks=[]
    )

    buyer_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={USER_BUYING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_buyer_phone)]},
        fallbacks=[]
    )

    admin_prod_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^admin_create_product$")],
        states={
            ADMIN_PROD_SALES_POST: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_prod_sales_content)],
            ADMIN_PROD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_prod_price_handler)],
            ADMIN_PROD_BTN_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_prod_btn_handler)],
            ADMIN_PROD_SUCCESS_POST: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_prod_success_handler)]
        },
        fallbacks=[]
    )

    admin_broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^admin_broadcast_prompt$")],
        states={ADMIN_WAITING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_receive_broadcast)]},
        fallbacks=[]
    )

    # Main Bot Handlers
    main_app.add_handler(buyer_conv)
    main_app.add_handler(CallbackQueryHandler(age_callback, pattern="^age_"))
    main_app.add_handler(conv_handler)
    main_app.add_handler(CallbackQueryHandler(handle_callback))
    main_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, region_click))

    # Admin Bot Handlers
    admin_app.add_handler(CommandHandler("start", admin_start))
    admin_app.add_handler(admin_prod_conv)
    admin_app.add_handler(admin_broadcast_conv)
    admin_app.add_handler(CallbackQueryHandler(admin_callback))

    await main_app.initialize()
    await admin_app.initialize()
    await main_app.start()
    await admin_app.start()

    await main_app.updater.start_polling()
    await admin_app.updater.start_polling()

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
