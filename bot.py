import os
import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Dict, List, Optional, Union
import re

from telethon import TelegramClient, errors
from telethon.tl.types import (
    User, Chat, Channel, 
    Dialog, PeerUser, PeerChat, PeerChannel
)
from telethon.errors import SessionRevokedError, AuthKeyUnregisteredError, PasswordHashInvalidError
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler, CallbackQueryHandler
from telegram.error import Conflict

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
# All private/changeable settings are read from environment variables
# (or from a local .env file). See .env.example and README.md.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"❌ Missing required setting: {name}. Copy .env.example to .env and fill it in.")
    return value


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int = 0) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


# Bot settings (required)
BOT_TOKEN = _require("BOT_TOKEN")
API_ID = int(_require("API_ID"))
API_HASH = _require("API_HASH")
ADMIN_ID = int(_require("ADMIN_ID"))

# Bot identity (used in links and message footers)
BOT_USERNAME = _str("BOT_USERNAME", "your_bot").lstrip("@")        # without @
ADMIN_USERNAME = _str("ADMIN_USERNAME", "").lstrip("@")            # shown to banned users
ADMIN_CONTACT = f"@{ADMIN_USERNAME}" if ADMIN_USERNAME else "admin"
SHARE_TEXT = _str("SHARE_TEXT", "Telegramdagi avto xabar bot")
FOOTER = f"\n<b>──────────────────</b>\n<b>📨 Xabar @{BOT_USERNAME} orqali yuborildi</b>"

# Channel / group settings
REQUIRED_BOTS = [b.strip() for b in _str("REQUIRED_BOTS").split(",") if b.strip()]
REQUIRED_CHANNEL = _str("REQUIRED_CHANNEL")             # e.g. @my_channel (empty = no check)
PAYMENTS_GROUP_ID = _int("PAYMENTS_GROUP_ID")           # receives payment screenshots
NEW_MEMBERS_GROUP_ID = _int("NEW_MEMBERS_GROUP_ID")     # new-user notifications (0 = off)
STATS_CHANNEL_ID = _int("STATS_CHANNEL_ID")             # live stats message (0 = off)

# Premium settings
PREMIUM_PRICE_STARS = _int("PREMIUM_PRICE_STARS", 40)
PREMIUM_PRICE_MONEY = _int("PREMIUM_PRICE_MONEY", 5000)
PREMIUM_DAYS = _int("PREMIUM_DAYS", 30)

# Interval settings (minutes)
PREMIUM_MIN_INTERVAL = _int("PREMIUM_MIN_INTERVAL", 2)
NON_PREMIUM_MIN_INTERVAL = _int("NON_PREMIUM_MIN_INTERVAL", 5)
MAX_INTERVAL = _int("MAX_INTERVAL", 15)

# Group limits
PREMIUM_GROUP_LIMIT = _int("PREMIUM_GROUP_LIMIT", 30)
NON_PREMIUM_GROUP_LIMIT = _int("NON_PREMIUM_GROUP_LIMIT", 5)

# Message session limits
PREMIUM_MESSAGE_LIMIT = _int("PREMIUM_MESSAGE_LIMIT", 1000)
NON_PREMIUM_MESSAGE_LIMIT = _int("NON_PREMIUM_MESSAGE_LIMIT", 100)

# Referral settings
REFERRAL_DISCOUNT_PER_USER = _int("REFERRAL_DISCOUNT_PER_USER", 250)
REFERRAL_FREE_PREMIUM_THRESHOLD = (
    PREMIUM_PRICE_MONEY / REFERRAL_DISCOUNT_PER_USER if REFERRAL_DISCOUNT_PER_USER else float("inf")
)

# Stats update settings
STATS_UPDATE_INTERVAL = 60
STATS_SAME_TEXT_SKIP_TIME = 120

# File settings
IMAGE_SIZE_LIMIT = 5 * 1024 * 1024

# Card numbers shown to users for manual payments
CARD_NUMBER = _str("CARD_NUMBER")
VISA_CARD_NUMBER = _str("VISA_CARD_NUMBER")

# --- Database Configuration ---
DATABASE_FILE = "bot_data.db"
SESSIONS_DIR = "sessions"
USER_IMAGES_DIR = "user_images"
ADMIN_IMAGE_DIR = "admin_images"

Path(SESSIONS_DIR).mkdir(exist_ok=True)
Path(USER_IMAGES_DIR).mkdir(exist_ok=True)
Path(ADMIN_IMAGE_DIR).mkdir(exist_ok=True)

# Statistics message tracking
stats_message_id = None
stats_update_task = None
last_stats_update = 0
last_stats_text = ""
last_stats_edit_time = 0

class Database:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.lock = asyncio.Lock()
        self.init_database()
    
    def init_database(self):
        self.conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                phone TEXT DEFAULT '',
                session_name TEXT DEFAULT '',
                message TEXT DEFAULT 'Salom!',
                message_type TEXT DEFAULT 'text',
                image_file_id TEXT DEFAULT NULL,
                image_path TEXT DEFAULT NULL,
                interval_minutes INTEGER DEFAULT 60,
                target_groups TEXT DEFAULT '[]',
                is_logged_in INTEGER DEFAULT 0,
                next_send_time REAL DEFAULT 0,
                is_active INTEGER DEFAULT 0,
                state TEXT DEFAULT 'menu',
                phone_code_hash TEXT DEFAULT '',
                is_premium INTEGER DEFAULT 0,
                premium_until REAL DEFAULT 0,
                messages_sent INTEGER DEFAULT 0,
                last_active REAL DEFAULT 0,
                user_started_required_bots INTEGER DEFAULT 0,
                current_payment_id TEXT DEFAULT NULL,
                session_messages_sent INTEGER DEFAULT 0,
                username TEXT DEFAULT '',
                has_joined_channel INTEGER DEFAULT 0,
                invited_by TEXT DEFAULT '',
                invite_count INTEGER DEFAULT 0,
                referral_discount_used INTEGER DEFAULT 0,
                next_message_is_admin INTEGER DEFAULT 0,
                premium_expired_notified INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                total_invites INTEGER DEFAULT 0
            )
        ''')

        self.cursor.execute("PRAGMA table_info(users)")
        existing_columns = [row[1] for row in self.cursor.fetchall()]
        expected_columns = {
            "user_id": "TEXT",
            "phone": "TEXT DEFAULT ''",
            "session_name": "TEXT DEFAULT ''",
            "message": "TEXT DEFAULT 'Salom!'",
            "message_type": "TEXT DEFAULT 'text'",
            "image_file_id": "TEXT DEFAULT NULL",
            "image_path": "TEXT DEFAULT NULL",
            "interval_minutes": "INTEGER DEFAULT 60",
            "target_groups": "TEXT DEFAULT '[]'",
            "is_logged_in": "INTEGER DEFAULT 0",
            "next_send_time": "REAL DEFAULT 0",
            "is_active": "INTEGER DEFAULT 0",
            "state": "TEXT DEFAULT 'menu'",
            "phone_code_hash": "TEXT DEFAULT ''",
            "is_premium": "INTEGER DEFAULT 0",
            "premium_until": "REAL DEFAULT 0",
            "messages_sent": "INTEGER DEFAULT 0",
            "last_active": "REAL DEFAULT 0",
            "user_started_required_bots": "INTEGER DEFAULT 0",
            "current_payment_id": "TEXT DEFAULT NULL",
            "session_messages_sent": "INTEGER DEFAULT 0",
            "username": "TEXT DEFAULT ''",
            "has_joined_channel": "INTEGER DEFAULT 0",
            "invited_by": "TEXT DEFAULT ''",
            "invite_count": "INTEGER DEFAULT 0",
            "referral_discount_used": "INTEGER DEFAULT 0",
            "next_message_is_admin": "INTEGER DEFAULT 0",
            "premium_expired_notified": "INTEGER DEFAULT 0",
            "is_banned": "INTEGER DEFAULT 0",
            "total_invites": "INTEGER DEFAULT 0"
        }
        for col_name, col_type in expected_columns.items():
            if col_name not in existing_columns:
                try:
                    self.cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}')
                    self.conn.commit()
                    print(f"Added missing column: {col_name}")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" not in str(e):
                        print(f"Error adding column {col_name}: {e}")
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount INTEGER,
                payment_type TEXT,
                status TEXT,
                created_at REAL,
                admin_notes TEXT DEFAULT '',
                additional_amount_needed INTEGER DEFAULT 0,
                user_sent_amount INTEGER DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS profit (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                money INTEGER DEFAULT 0,
                stars INTEGER DEFAULT 0
            )
        ''')
        self.cursor.execute('INSERT OR IGNORE INTO profit (id, money, stars) VALUES (1, 0, 0)')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_message (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                message TEXT DEFAULT '',
                message_type TEXT DEFAULT 'text',
                image_file_id TEXT DEFAULT NULL,
                image_path TEXT DEFAULT NULL
            )
        ''')
        self.cursor.execute('INSERT OR IGNORE INTO admin_message (id) VALUES (1)')
        
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_premium ON users(premium_until)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)')
        self.conn.commit()
    
    async def get_user(self, user_str: str) -> Optional[Dict]:
        async with self.lock:
            self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_str,))
            row = self.cursor.fetchone()
            if row:
                columns = [description[0] for description in self.cursor.description]
                user_dict = dict(zip(columns, row))
                user_dict['target_groups'] = eval(user_dict['target_groups']) if user_dict['target_groups'] else []
                return user_dict
            return None
    
    async def create_user(self, user_str: str, user_data: Dict):
        async with self.lock:
            user_data['target_groups'] = str(user_data.get('target_groups', []))
            placeholders = ', '.join(['?' for _ in user_data])
            columns = ', '.join(user_data.keys())
            values = list(user_data.values())
            self.cursor.execute(f'INSERT OR REPLACE INTO users ({columns}) VALUES ({placeholders})', values)
            self.conn.commit()
    
    async def update_user(self, user_str: str, updates: Dict):
        async with self.lock:
            if 'target_groups' in updates:
                updates['target_groups'] = str(updates['target_groups'])
            set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values())
            values.append(user_str)
            self.cursor.execute(f'UPDATE users SET {set_clause} WHERE user_id = ?', values)
            self.conn.commit()
    
    async def get_all_users(self) -> List[Dict]:
        async with self.lock:
            self.cursor.execute('SELECT * FROM users')
            rows = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]
            users = []
            for row in rows:
                user_dict = dict(zip(columns, row))
                user_dict['target_groups'] = eval(user_dict['target_groups']) if user_dict['target_groups'] else []
                users.append(user_dict)
            return users
    
    async def count_users(self) -> int:
        async with self.lock:
            self.cursor.execute('SELECT COUNT(*) FROM users')
            return self.cursor.fetchone()[0]
    
    async def get_active_users(self) -> List[Dict]:
        async with self.lock:
            self.cursor.execute('SELECT * FROM users WHERE is_active = 1')
            rows = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]
            users = []
            for row in rows:
                user_dict = dict(zip(columns, row))
                user_dict['target_groups'] = eval(user_dict['target_groups']) if user_dict['target_groups'] else []
                users.append(user_dict)
            return users
    
    async def get_logged_in_users(self) -> List[Dict]:
        async with self.lock:
            self.cursor.execute('SELECT * FROM users WHERE is_logged_in = 1')
            rows = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]
            users = []
            for row in rows:
                user_dict = dict(zip(columns, row))
                user_dict['target_groups'] = eval(user_dict['target_groups']) if user_dict['target_groups'] else []
                users.append(user_dict)
            return users
    
    async def get_premium_users(self) -> List[Dict]:
        current_time = time.time()
        async with self.lock:
            self.cursor.execute('SELECT * FROM users WHERE is_premium = 1 AND premium_until > ?', (current_time,))
            rows = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]
            users = []
            for row in rows:
                user_dict = dict(zip(columns, row))
                user_dict['target_groups'] = eval(user_dict['target_groups']) if user_dict['target_groups'] else []
                users.append(user_dict)
            return users
    
    async def count_messages_sent(self) -> int:
        async with self.lock:
            self.cursor.execute('SELECT SUM(messages_sent) FROM users')
            result = self.cursor.fetchone()[0]
            return result if result else 0
    
    async def create_payment(self, payment_data: Dict):
        async with self.lock:
            placeholders = ', '.join(['?' for _ in payment_data])
            columns = ', '.join(payment_data.keys())
            values = list(payment_data.values())
            self.cursor.execute(f'INSERT INTO payments ({columns}) VALUES ({placeholders})', values)
            self.conn.commit()
    
    async def update_payment(self, payment_id: str, updates: Dict):
        async with self.lock:
            set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
            values = list(updates.values())
            values.append(payment_id)
            self.cursor.execute(f'UPDATE payments SET {set_clause} WHERE payment_id = ?', values)
            self.conn.commit()
    
    async def get_payment(self, payment_id: str) -> Optional[Dict]:
        async with self.lock:
            self.cursor.execute('SELECT * FROM payments WHERE payment_id = ?', (payment_id,))
            row = self.cursor.fetchone()
            if row:
                columns = [description[0] for description in self.cursor.description]
                return dict(zip(columns, row))
            return None
    
    async def get_pending_payments(self) -> List[Dict]:
        async with self.lock:
            self.cursor.execute('SELECT * FROM payments WHERE status = "pending"')
            rows = self.cursor.fetchall()
            columns = [description[0] for description in self.cursor.description]
            payments = []
            for row in rows:
                payments.append(dict(zip(columns, row)))
            return payments
    
    async def count_pending_payments(self) -> int:
        async with self.lock:
            self.cursor.execute('SELECT COUNT(*) FROM payments WHERE status = "pending"')
            return self.cursor.fetchone()[0]
    
    async def delete_payment(self, payment_id: str):
        async with self.lock:
            self.cursor.execute('DELETE FROM payments WHERE payment_id = ?', (payment_id,))
            self.conn.commit()
    
    async def get_profit(self) -> Dict:
        async with self.lock:
            self.cursor.execute('SELECT money, stars FROM profit WHERE id = 1')
            row = self.cursor.fetchone()
            if row:
                return {"money": row[0], "stars": row[1]}
            return {"money": 0, "stars": 0}
    
    async def set_profit(self, money: int = None, stars: int = None):
        async with self.lock:
            if money is not None:
                self.cursor.execute('UPDATE profit SET money = ? WHERE id = 1', (money,))
            if stars is not None:
                self.cursor.execute('UPDATE profit SET stars = ? WHERE id = 1', (stars,))
            self.conn.commit()
    
    async def update_profit(self, money_delta: int = 0, stars_delta: int = 0):
        async with self.lock:
            self.cursor.execute('UPDATE profit SET money = money + ?, stars = stars + ? WHERE id = 1', 
                               (money_delta, stars_delta))
            self.conn.commit()
    
    async def increment_invite_count(self, user_str: str):
        async with self.lock:
            self.cursor.execute('UPDATE users SET invite_count = invite_count + 1, total_invites = total_invites + 1 WHERE user_id = ?', (user_str,))
            self.conn.commit()
    
    async def get_admin_message(self) -> Optional[Dict]:
        async with self.lock:
            self.cursor.execute('SELECT message, message_type, image_file_id, image_path FROM admin_message WHERE id = 1')
            row = self.cursor.fetchone()
            if row:
                return {
                    "message": row[0],
                    "message_type": row[1],
                    "image_file_id": row[2],
                    "image_path": row[3]
                }
            return None
    
    async def set_admin_message(self, message: str = "", message_type: str = "text", 
                         image_file_id: str = None, image_path: str = None):
        async with self.lock:
            self.cursor.execute('''
                UPDATE admin_message 
                SET message = ?, message_type = ?, image_file_id = ?, image_path = ?
                WHERE id = 1
            ''', (message, message_type, image_file_id, image_path))
            self.conn.commit()
    
    async def delete_admin_message(self):
        async with self.lock:
            self.cursor.execute('''
                UPDATE admin_message 
                SET message = '', message_type = 'text', image_file_id = NULL, image_path = NULL
                WHERE id = 1
            ''')
            self.conn.commit()
    
    def close(self):
        if self.conn:
            self.conn.close()

db = Database()
bot_instance = None

# --- Data Structures ---
clients: Dict[int, TelegramClient] = {}
sending_tasks: Dict[int, asyncio.Task] = {}

# --- Ban Check ---
async def check_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if user and user.get('is_banned', 0):
        await update.message.reply_text(f"⛔ Siz bloklangansiz! Admin bilan bog'lanishingiz mumkin: {ADMIN_CONTACT}")
        return True
    return False

# --- Premium Functions ---
async def get_group_limit(user_str: str) -> int:
    if await check_premium_status(user_str):
        return PREMIUM_GROUP_LIMIT
    return NON_PREMIUM_GROUP_LIMIT

async def get_message_limit(user_str: str) -> int:
    if await check_premium_status(user_str):
        return PREMIUM_MESSAGE_LIMIT
    return NON_PREMIUM_MESSAGE_LIMIT

async def check_premium_status(user_str: str) -> bool:
    user = await db.get_user(user_str)
    if not user:
        return False
    is_premium = user.get("is_premium", 0)
    premium_until = user.get("premium_until", 0)
    if is_premium and premium_until > time.time():
        return True
    elif is_premium and premium_until <= time.time():
        await downgrade_user_from_premium(user_str)
        await db.update_user(user_str, {"is_premium": 0, "premium_expired_notified": 0})
        return False
    return False

async def downgrade_user_from_premium(user_str: str):
    user = await db.get_user(user_str)
    if not user:
        return
    message_type = user.get("message_type", "text")
    if message_type in ["image", "image_text"]:
        image_path = user.get("image_path")
        if image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception as e:
                logger.error(f"Error removing image for user {user_str}: {e}")
        current_message = user.get("message", "Salom!")
        new_message = f"{current_message}{FOOTER}"
        await db.update_user(user_str, {
            "message_type": "text",
            "message": new_message,
            "image_file_id": None,
            "image_path": None,
            "premium_expired_notified": 0
        })
        if user.get("is_active", 0):
            await db.update_user(user_str, {"is_active": 0})
        return True
    return False

async def add_premium(user_str: str, days: int = 30):
    user = await db.get_user(user_str)
    if not user:
        return False
    current_time = time.time()
    premium_until = user.get("premium_until", 0)
    if premium_until > current_time:
        new_premium_until = premium_until + (days * 24 * 60 * 60)
    else:
        new_premium_until = current_time + (days * 24 * 60 * 60)
    await db.update_user(user_str, {
        "is_premium": 1,
        "premium_until": new_premium_until,
        "referral_discount_used": 1,
        "premium_expired_notified": 0,
        "invite_count": 0
    })
    return True

async def get_referral_discount(user_str: str) -> int:
    user = await db.get_user(user_str)
    if not user:
        return 0
    if user.get("referral_discount_used", 0):
        return 0
    invite_count = user.get("invite_count", 0)
    discount = invite_count * REFERRAL_DISCOUNT_PER_USER
    return min(discount, PREMIUM_PRICE_MONEY)

async def get_discounted_price(user_str: str) -> int:
    discount = await get_referral_discount(user_str)
    return max(0, PREMIUM_PRICE_MONEY - discount)

# --- Channel Join Check and Referral Award ---
async def check_channel_membership(user_id: int, bot) -> bool:
    if not REQUIRED_CHANNEL:
        return True
    try:
        member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking channel membership: {e}")
        return False

async def award_referral_if_needed(user_id: int, inviter_id: int, bot):
    inviter_str = str(inviter_id)
    inviter = await db.get_user(inviter_str)
    if not inviter:
        return
    await db.increment_invite_count(inviter_str)
    try:
        await bot.send_message(
            chat_id=inviter_id,
            text=f"🎉 Tabriklaymiz! Siz taklif qilgan odam kanalga qo'shildi!\n💰 Sizga {REFERRAL_DISCOUNT_PER_USER} so'm chegirma berildi!"
        )
    except:
        pass

async def require_channel_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not user:
        return True
    has_joined = await check_channel_membership(user_id, context.bot)
    previous_joined = user.get("has_joined_channel", 0)
    if not has_joined:
        await db.update_user(user_str, {"has_joined_channel": 0})
        keyboard = [[InlineKeyboardButton("📢 Kanal", url=f"https://t.me/{REQUIRED_CHANNEL[1:]}")],
                   [InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_channel_join")]]
        if update.callback_query:
            await update.callback_query.message.reply_text(
                "📢 Kanalga obuna bo'ling:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                "📢 Kanalga obuna bo'ling:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return False
    await db.update_user(user_str, {"has_joined_channel": 1})
    if previous_joined == 0 and user.get("invited_by"):
        inviter_id = int(user["invited_by"])
        if inviter_id != user_id:
            await award_referral_if_needed(user_id, inviter_id, context.bot)
    return True

async def check_channel_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    previous_joined = user.get("has_joined_channel", 0) if user else 0
    has_joined = await check_channel_membership(user_id, context.bot)
    if has_joined:
        await db.update_user(user_str, {"has_joined_channel": 1})
        await query.edit_message_text("✅ Obuna bo'ldingiz")
        if previous_joined == 0 and user and user.get("invited_by"):
            inviter_id = int(user["invited_by"])
            if inviter_id != user_id:
                await award_referral_if_needed(user_id, inviter_id, context.bot)
    else:
        await query.answer("❌ Obuna bo'lmagansiz!", show_alert=True)

# --- Statistics Channel Functions ---
async def update_stats_channel(bot):
    global stats_message_id, last_stats_update, last_stats_text, last_stats_edit_time
    current_time = time.time()
    if current_time - last_stats_update < STATS_UPDATE_INTERVAL and stats_message_id:
        return
    try:
        total_users = await db.count_users()
        premium_users = len(await db.get_premium_users())
        logged_in_users = len(await db.get_logged_in_users())
        active_users = len(await db.get_active_users())
        total_messages = await db.count_messages_sent()
        all_users = await db.get_all_users()
        top_inviters = sorted([(int(u['user_id']), u.get('total_invites', 0)) for u in all_users], 
                             key=lambda x: x[1], reverse=True)[:5]
        stats_text = (
            f"🤖 <b>Statistika</b>\n\n"
            f"👥 Foydalanuvchilar: {total_users}\n"
            f"👑 Premium: {premium_users}\n"
            f"──────────────────\n"
            f"🔗 Akkauntlar: {logged_in_users}\n"
            f"🚀 Faol: {active_users}\n"
            f"📨 Xabarlar: {total_messages}\n"
            f"──────────────────\n"
            f"🏆 Top Referral (umumiy):\n"
        )
        for idx, (user_id, count) in enumerate(top_inviters, 1):
            if count > 0:
                user = await db.get_user(str(user_id))
                username = user.get('username', '') if user else ''
                username_display = f"@{username}" if username else f"ID: {user_id}"
                stats_text += f"{idx}. {username_display}: {count}\n"
        stats_text += "──────────────────\n"
        stats_text += f"🕒 Yangilanish: {datetime.now().strftime('%H:%M:%S')}"
        if stats_text == last_stats_text and stats_message_id:
            if current_time - last_stats_edit_time < STATS_SAME_TEXT_SKIP_TIME:
                last_stats_update = current_time
                return
        last_stats_text = stats_text
        if stats_message_id:
            try:
                await bot.edit_message_text(
                    chat_id=STATS_CHANNEL_ID,
                    message_id=stats_message_id,
                    text=stats_text,
                    parse_mode='HTML'
                )
                last_stats_update = current_time
                last_stats_edit_time = current_time
                return
            except Exception as e:
                error_str = str(e)
                if "Message to edit not found" in error_str or "message is not modified" in error_str:
                    stats_message_id = None
                elif "Timed out" in error_str:
                    logger.warning(f"Timeout editing stats message, will retry next cycle")
                    return
                else:
                    logger.error(f"Error editing stats message: {e}")
                    stats_message_id = None
        message = await bot.send_message(
            chat_id=STATS_CHANNEL_ID,
            text=stats_text,
            parse_mode='HTML'
        )
        stats_message_id = message.message_id
        last_stats_update = current_time
        last_stats_edit_time = current_time
    except Exception as e:
        logger.error(f"Error updating stats: {e}")

async def stats_channel_updater(application: Application):
    if not STATS_CHANNEL_ID:
        logger.info("STATS_CHANNEL_ID not set - stats channel updates disabled")
        return
    while True:
        try:
            await update_stats_channel(application.bot)
        except Exception as e:
            logger.error(f"Stats updater error: {e}")
        await asyncio.sleep(STATS_UPDATE_INTERVAL)

# --- Pending Payment Functions ---
async def create_pending_payment(user_id: int, amount: int, payment_type: str = "money") -> str:
    payment_id = f"payment_{user_id}_{int(time.time())}"
    payment_data = {
        "payment_id": payment_id,
        "user_id": user_id,
        "amount": amount,
        "payment_type": payment_type,
        "status": "pending",
        "created_at": time.time()
    }
    await db.create_payment(payment_data)
    return payment_id

# --- Profit Functions ---
async def update_money_profit(amount: int):
    await db.update_profit(money_delta=amount)

async def update_stars_profit(amount: int):
    await db.update_profit(stars_delta=amount)

# --- Admin Functions ---
async def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def adminhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    help_text = (
        "👑 <b>Admin Komandalari:</b>\n\n"
        "/stats - Bot statistikasi\n"
        "/profit - Bot foydasi\n"
        "/setprofit - Foydani o'zgartirish (so'm yoki stars)\n"
        "/broadcast - Xabar yuborish\n"
        "/cancel_broadcast - Broadcastni bekor qilish\n"
        "/see &lt;user_id&gt; - Foydalanuvchi ma'lumotlari\n"
        "/entered - Ulangan akkauntlar\n"
        "/active - Faol yuboruvchilar\n"
        "/pending - Kutilayotgan to'lovlar\n"
        "/premusers - Premium foydalanuvchilar\n"
        "/addprem &lt;user_id&gt; [kunlar] - Premium qo'shish\n"
        "/removeprem &lt;user_id&gt; - Premium olib tashlash\n"
        "/setadmsg - Admin xabarini o'rnatish\n"
        "/ban &lt;user_id&gt; - Foydalanuvchini bloklash\n"
        "/unban &lt;user_id&gt; - Blokni olib tashlash\n"
        "/baned - Bloklanganlar ro'yxati\n"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')

async def entered_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    logged_in_users = await db.get_logged_in_users()
    if not logged_in_users:
        await update.message.reply_text("❌ Ulangan akkaunt yo'q")
        return
    chunk_size = 10
    user_chunks = [logged_in_users[i:i + chunk_size] for i in range(0, len(logged_in_users), chunk_size)]
    for chunk_num, user_chunk in enumerate(user_chunks, 1):
        response = f"🔗 <b>Ulangan Akkauntlar (Qism {chunk_num}/{len(user_chunks)}):</b>\n\n"
        for idx, user in enumerate(user_chunk, 1):
            user_id_int = int(user['user_id'])
            username = user.get('username', '')
            phone = user.get('phone', 'Noma\'lum')
            username_display = f"@{username}" if username else f"ID: {user_id_int}"
            response += f"{idx}. {username_display}\n"
            response += f"   📞 {phone}\n"
            response += f"   🆔 {user_id_int}\n"
            if user.get('is_active', 0):
                response += "   🟢 Faol\n"
            else:
                response += "   🔴 Faol emas\n"
            if await check_premium_status(str(user_id_int)):
                premium_until = user.get('premium_until', 0)
                until_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d") if premium_until > 0 else "Yo'q"
                response += f"   👑 Premium: {until_date}\n"
            else:
                response += f"   👑 Premium: Yo'q\n"
            response += "\n"
        await update.message.reply_text(response, parse_mode='HTML')

async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    active_users = await db.get_active_users()
    if not active_users:
        await update.message.reply_text("❌ Faol yuboruvchilar yo'q")
        return
    chunk_size = 5
    user_chunks = [active_users[i:i + chunk_size] for i in range(0, len(active_users), chunk_size)]
    for chunk_num, user_chunk in enumerate(user_chunks, 1):
        response = f"🚀 <b>Faol Yuboruvchilar (Qism {chunk_num}/{len(user_chunks)}):</b>\n\n"
        for idx, user in enumerate(user_chunk, 1):
            user_id_int = int(user['user_id'])
            username = user.get('username', '')
            phone = user.get('phone', 'Noma\'lum')
            interval = user.get('interval_minutes', 60)
            groups = user.get('target_groups', [])
            messages_sent = user.get('messages_sent', 0)
            session_sent = user.get('session_messages_sent', 0)
            username_display = f"@{username}" if username else f"ID: {user_id_int}"
            response += f"{idx}. {username_display}\n"
            response += f"   📞 {phone}\n"
            response += f"   🆔 {user_id_int}\n"
            response += f"   ⏰ {interval} daq\n"
            response += f"   👥 {len(groups)} guruh\n"
            response += f"   📨 {session_sent} xabar (sessiya)\n"
            response += f"   📊 {messages_sent} jami\n"
            if await check_premium_status(str(user_id_int)):
                response += f"   👑 Premium: Ha\n"
            else:
                response += f"   👑 Premium: Yo'q\n"
            response += "\n"
        await update.message.reply_text(response, parse_mode='HTML')

async def profit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    profit = await db.get_profit()
    money_profit = profit.get("money", 0)
    stars_profit = profit.get("stars", 0)
    profit_text = (
        "💰 <b>Bot Foydasi</b>\n\n"
        f"💵 Naqd: {money_profit:,} so'm\n"
        f"⭐ Stars: {stars_profit}\n\n"
        f"/setprofit - O'zgartirish"
    )
    await update.message.reply_text(profit_text, parse_mode='HTML')

async def set_profit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        keyboard = [
            [InlineKeyboardButton("💵 Naqd", callback_data="setprofit_cash")],
            [InlineKeyboardButton("⭐ Stars", callback_data="setprofit_stars")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Qaysi foydani o'zgartirmoqchisiz?", reply_markup=reply_markup)
        return
    try:
        amount = int(context.args[0])
        if amount < 0:
            await update.message.reply_text("❌ Miqdor manfiy bo'lishi mumkin emas")
            return
        await db.set_profit(money=amount)
        profit = await db.get_profit()
        await update.message.reply_text(
            f"✅ <b>Foyda yangilandi!</b>\n\n"
            f"💰 Yangi naqd: {profit['money']:,} so'm\n"
            f"⭐ Stars: {profit['stars']}",
            parse_mode='HTML'
        )
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format. Faqat raqam kiriting")

async def set_profit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    data = query.data
    if data == "setprofit_cash":
        context.user_data['setprofit_type'] = 'money'
        await query.edit_message_text("💵 Yangi naqd foydani kiriting (so'm):")
    elif data == "setprofit_stars":
        context.user_data['setprofit_type'] = 'stars'
        await query.edit_message_text("⭐ Yangi stars foydani kiriting:")

async def handle_setprofit_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        return
    if 'setprofit_type' not in context.user_data:
        return
    text = update.message.text.strip()
    try:
        amount = int(text)
        if amount < 0:
            await update.message.reply_text("❌ Miqdor manfiy bo'lishi mumkin emas")
            return
        profit_type = context.user_data['setprofit_type']
        if profit_type == 'money':
            await db.set_profit(money=amount)
            await update.message.reply_text(
                f"✅ Naqd foyda {amount:,} so'm qilib o'rnatildi!",
                parse_mode='HTML'
            )
        else:
            await db.set_profit(stars=amount)
            await update.message.reply_text(
                f"✅ Stars foyda {amount} qilib o'rnatildi!",
                parse_mode='HTML'
            )
        context.user_data.pop('setprofit_type', None)
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format. Faqat raqam kiriting")

async def see_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        await update.message.reply_text("❌ ID kiriting: /see <user_id>")
        return
    try:
        target_user_id = int(context.args[0])
        target_user_str = str(target_user_id)
        user = await db.get_user(target_user_str)
        if not user:
            await update.message.reply_text(f"❌ {target_user_id} topilmadi")
            return
        username = user.get('username', '')
        phone = user.get('phone', 'Yo\'q')
        is_logged_in = user.get('is_logged_in', 0)
        is_active = user.get('is_active', 0)
        is_premium = user.get('is_premium', 0)
        premium_until = user.get('premium_until', 0)
        interval = user.get('interval_minutes', 60)
        messages_sent = user.get('messages_sent', 0)
        target_groups = user.get('target_groups', [])
        has_joined_channel = user.get('has_joined_channel', 0)
        invited_by = user.get('invited_by', '')
        invite_count = user.get('invite_count', 0)
        total_invites = user.get('total_invites', 0)
        is_banned = user.get('is_banned', 0)
        premium_status = "✅ Faol" if is_premium and premium_until > time.time() else "❌ Yo'q"
        premium_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d %H:%M") if premium_until > 0 else "Yo'q"
        user_info = (
            f"👤 <b>Foydalanuvchi Ma'lumotlari</b>\n\n"
            f"🆔 ID: {target_user_id}\n"
            f"👤 Username: @{username if username else 'yoq'}\n"
            f"📞 Telefon: {phone}\n"
            f"🔐 Kirgan: {'✅ Ha' if is_logged_in else '❌ Yoq'}\n"
            f"🚀 Faol: {'✅ Ha' if is_active else '❌ Yoq'}\n"
            f"📢 Kanal: {'✅ Ha' if has_joined_channel else '❌ Yoq'}\n"
            f"👑 Premium: {premium_status}\n"
            f"📅 Premium tugashi: {premium_date}\n"
            f"⏰ Oraliq: {interval} daq\n"
            f"📨 Xabarlar: {messages_sent}\n"
            f"👥 Taklif qilgan: {invited_by if invited_by else 'Yoq'}\n"
            f"📊 Takliflar (joriy): {invite_count} ta\n"
            f"📈 Takliflar (umumiy): {total_invites} ta\n"
            f"⛔ Bloklangan: {'✅ Ha' if is_banned else '❌ Yoq'}\n\n"
        )
        groups_text = ""
        if target_groups:
            for i, group in enumerate(target_groups, 1):
                groups_text += f"{i}. {group}\n"
        else:
            groups_text = "Guruh yo'q"
        user_info += f"👥 Guruhlar ({len(target_groups)} ta):\n{groups_text}"
        await update.message.reply_text(user_info, parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    total_users = await db.count_users()
    logged_in_users = len(await db.get_logged_in_users())
    active_users = len(await db.get_active_users())
    premium_users_count = len(await db.get_premium_users())
    total_messages_sent = await db.count_messages_sent()
    pending_count = await db.count_pending_payments()
    profit = await db.get_profit()
    money_profit = profit.get("money", 0)
    stars_profit = profit.get("stars", 0)
    stats_text = (
        "📊 <b>Bot Statistikalari</b>\n\n"
        f"👥 Umumiy: {total_users}\n"
        f"✅ Kirgan: {logged_in_users}\n"
        f"🚀 Faol: {active_users}\n"
        f"👑 Premium: {premium_users_count}\n"
        f"📨 Xabarlar: {total_messages_sent}\n"
        f"💰 To'lovlar: {pending_count}\n"
        f"💵 Foyda: {money_profit:,} so'm\n"
        f"⭐ Stars: {stars_profit}"
    )
    await update.message.reply_text(stats_text, parse_mode='HTML')

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    context.user_data["broadcast_mode"] = True
    await update.message.reply_text(
        "📢 <b>Broadcast Rejimi</b>\n\n"
        "Xabar yuboring:\n"
        "• Matn\n"
        "• Rasm\n"
        "• Video\n"
        "• Fayl\n\n"
        "/cancel_broadcast - Bekor qilish"
    )

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        return
    if not context.user_data.get("broadcast_mode"):
        return
    total_users = await db.count_users()
    if total_users == 0:
        await update.message.reply_text("❌ Foydalanuvchilar yo'q")
        context.user_data["broadcast_mode"] = False
        return
    await update.message.reply_text(f"📤 {total_users} ta foydalanuvchiga yuborilmoqda...")
    sent_count = 0
    failed_count = 0
    message_type = "text"
    content = None
    if update.message.text:
        message_type = "text"
        content = update.message.text
    elif update.message.photo:
        message_type = "photo"
        photo = update.message.photo[-1]
        content = {
            "file_id": photo.file_id,
            "caption": update.message.caption or ""
        }
    elif update.message.video:
        message_type = "video"
        video = update.message.video
        content = {
            "file_id": video.file_id,
            "caption": update.message.caption or ""
        }
    elif update.message.document:
        message_type = "document"
        document = update.message.document
        content = {
            "file_id": document.file_id,
            "caption": update.message.caption or "",
            "file_name": document.file_name
        }
    users = await db.get_all_users()
    tasks = []
    for user in users:
        if user.get('is_banned', 0):
            continue
        try:
            user_id_int = int(user['user_id'])
            if message_type == "text":
                tasks.append(context.bot.send_message(chat_id=user_id_int, text=content))
            elif message_type == "photo":
                tasks.append(context.bot.send_photo(chat_id=user_id_int, photo=content["file_id"], caption=content['caption'] if content.get("caption") else None))
            elif message_type == "video":
                tasks.append(context.bot.send_video(chat_id=user_id_int, video=content["file_id"], caption=content['caption'] if content.get("caption") else None))
            elif message_type == "document":
                tasks.append(context.bot.send_document(chat_id=user_id_int, document=content["file_id"], caption=content['caption'] if content.get("caption") else None))
        except Exception as e:
            logger.error(f"Failed to queue broadcast to {user['user_id']}: {e}")
            failed_count += 1
    batch_size = 30
    for i in range(0, len(tasks), batch_size):
        batch = tasks[i:i + batch_size]
        try:
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if not isinstance(result, Exception):
                    sent_count += 1
                else:
                    failed_count += 1
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Batch error: {e}")
            failed_count += len(batch)
    context.user_data["broadcast_mode"] = False
    await update.message.reply_text(
        f"✅ Broadcast tugatildi!\n\n"
        f"📊 Natijalar:\n"
        f"• Yuborildi: {sent_count}\n"
        f"• Xatolik: {failed_count}\n"
        f"• Jami: {total_users}"
    )

async def cancel_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if context.user_data.get("broadcast_mode"):
        context.user_data["broadcast_mode"] = False
        await update.message.reply_text("❌ Broadcast bekor qilindi")
    else:
        await update.message.reply_text("❌ Broadcast rejimida emassiz")

async def add_premium_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        await update.message.reply_text("❌ ID kiriting: /addprem <user_id> <days>")
        return
    try:
        target_user_id = int(context.args[0])
        target_user_str = str(target_user_id)
        days = PREMIUM_DAYS
        if len(context.args) > 1:
            days = int(context.args[1])
        if await add_premium(target_user_str, days):
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 <b>Tabriklaymiz! Admin sizga Premium berdi</b>\n\n"
                         f"📅 Muddati: {days} kun\n"
                         f"⏰ {PREMIUM_MIN_INTERVAL} daqiqa oralik\n"
                         f"👥 {PREMIUM_GROUP_LIMIT} ta guruh\n"
                         f"✅ Rasm yuborish imkoniyati",
                    parse_mode='HTML',
                    reply_markup=await main_menu_keyboard(target_user_id)
                )
            except:
                pass
            await update.message.reply_text(f"✅ Premium {target_user_id} ga {days} kun qo'shildi (invite_count reset)")
        else:
            await update.message.reply_text(f"❌ {target_user_id} topilmadi")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format")

async def remove_premium_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        await update.message.reply_text("❌ ID kiriting: /removeprem <user_id>")
        return
    try:
        target_user_id = int(context.args[0])
        target_user_str = str(target_user_id)
        await downgrade_user_from_premium(target_user_str)
        await db.update_user(target_user_str, {
            "is_premium": 0,
            "premium_until": 0,
            "referral_discount_used": 0
        })
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="⚠️ <b>Admin sizning Premium obunangizni olib tashladi</b>\n\n"
                     "Endi faqat matn xabarlar yuborishingiz mumkin.",
                parse_mode='HTML',
                reply_markup=await main_menu_keyboard(target_user_id)
            )
        except:
            pass
        await update.message.reply_text(f"✅ Premium {target_user_id} dan olib tashlandi")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID")

async def list_premium_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    premium_users = await db.get_premium_users()
    if not premium_users:
        await update.message.reply_text("❌ Premium foydalanuvchilar yo'q")
        return
    chunk_size = 15
    user_chunks = [premium_users[i:i + chunk_size] for i in range(0, len(premium_users), chunk_size)]
    for chunk_num, user_chunk in enumerate(user_chunks, 1):
        response = f"👑 Premium Foydalanuvchilar (Qism {chunk_num}/{len(user_chunks)}):\n\n"
        for idx, user in enumerate(user_chunk, 1):
            user_id_int = int(user['user_id'])
            premium_until = user.get("premium_until", 0)
            until_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d") if premium_until > 0 else "Yo'q"
            username = user.get('username', '')
            username_display = f"@{username}" if username else ""
            response += f"{idx}. ID: {user_id_int} {username_display} - Tugash: {until_date}\n"
        await update.message.reply_text(response)

async def pending_payments_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    pending = await db.get_pending_payments()
    if not pending:
        await update.message.reply_text("✅ Kutilayotgan to'lovlar yo'q")
        return
    chunk_size = 5
    payment_chunks = [pending[i:i + chunk_size] for i in range(0, len(pending), chunk_size)]
    for chunk_num, payment_chunk in enumerate(payment_chunks, 1):
        response = f"💰 <b>Kutilayotgan To'lovlar (Qism {chunk_num}/{len(payment_chunks)}):</b>\n\n"
        for idx, payment in enumerate(payment_chunk, 1):
            user_id_int = payment["user_id"]
            amount = payment["amount"]
            payment_type = payment["payment_type"]
            created_time = datetime.fromtimestamp(payment["created_at"]).strftime("%H:%M")
            user = await db.get_user(str(user_id_int))
            username = user.get('username', '') if user else ''
            username_display = f"@{username}" if username else "Username yo'q"
            response += f"{idx}. ID: {user_id_int} ({username_display})\n"
            response += f"   Turi: {'💰 Pul' if payment_type == 'money' else '⭐ Stars'}\n"
            response += f"   Miqdor: {amount} {'so\'m' if payment_type == 'money' else 'stars'}\n"
            response += f"   Vaqt: {created_time}\n\n"
        await update.message.reply_text(response, parse_mode='HTML')

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        await update.message.reply_text("❌ ID kiriting: /ban <user_id>")
        return
    try:
        target_user_id = int(context.args[0])
        target_user_str = str(target_user_id)
        user = await db.get_user(target_user_str)
        if not user:
            await update.message.reply_text(f"❌ {target_user_id} topilmadi")
            return
        if target_user_id in sending_tasks:
            sending_tasks[target_user_id].cancel()
            sending_tasks.pop(target_user_id, None)
        await db.update_user(target_user_str, {"is_active": 0, "is_banned": 1})
        await disconnect_client(target_user_id)
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"⛔ <b>Siz bloklandingiz!</b>\n\nAdmin bilan bog'lanishingiz mumkin: {ADMIN_CONTACT}",
                parse_mode='HTML'
            )
        except:
            pass
        await update.message.reply_text(f"✅ Foydalanuvchi {target_user_id} bloklandi")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID")

async def banned_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    all_users = await db.get_all_users()
    banned_users = [u for u in all_users if u.get('is_banned', 0)]
    if not banned_users:
        await update.message.reply_text("✅ Bloklangan foydalanuvchilar yo'q")
        return
    chunk_size = 15
    chunks = [banned_users[i:i + chunk_size] for i in range(0, len(banned_users), chunk_size)]
    for i, chunk in enumerate(chunks, 1):
        response = f"⛔ <b>Bloklangan foydalanuvchilar (qism {i}/{len(chunks)}):</b>\n\n"
        for idx, user in enumerate(chunk, 1):
            uid = user['user_id']
            username = user.get('username', '')
            username_display = f"@{username}" if username else "username yo'q"
            response += f"{idx}. ID: <code>{uid}</code> – {username_display}\n"
        await update.message.reply_text(response, parse_mode='HTML')

# --- New Admin Commands: /reset and /delete ---
async def reset_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: fully reset a user's data to defaults."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        await update.message.reply_text("❌ ID kiriting: /reset <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID")
        return

    target_str = str(target_id)
    user = await db.get_user(target_str)
    if not user:
        await update.message.reply_text(f"❌ {target_id} topilmadi")
        return

    # Stop any active sending
    if target_id in sending_tasks:
        sending_tasks[target_id].cancel()
        sending_tasks.pop(target_id, None)

    # Disconnect Telethon client
    await disconnect_client(target_id)

    # Delete session file
    session_name = user.get("session_name", f"session_{target_id}")
    session_path = os.path.join(SESSIONS_DIR, session_name)
    if os.path.exists(session_path):
        try:
            os.remove(session_path)
        except Exception as e:
            logger.error(f"Error deleting session for {target_id}: {e}")

    # Delete user image folder if exists
    user_image_dir = os.path.join(USER_IMAGES_DIR, target_str)
    if os.path.exists(user_image_dir):
        import shutil
        shutil.rmtree(user_image_dir, ignore_errors=True)

    # Adjust inviter's referral counts (decrement)
    inviter_str = user.get("invited_by", "")
    if inviter_str:
        inviter = await db.get_user(inviter_str)
        if inviter:
            new_invite = max(0, inviter.get("invite_count", 0) - 1)
            new_total = max(0, inviter.get("total_invites", 0) - 1)
            await db.update_user(inviter_str, {
                "invite_count": new_invite,
                "total_invites": new_total
            })
            try:
                await context.bot.send_message(
                    chat_id=int(inviter_str),
                    text=f"⚠️ Siz taklif qilgan foydalanuvchi ({target_id}) admin tomonidan qayta tiklandi."
                )
            except Exception:
                pass

    # Full reset to default values (same as on first start)
    default_user_data = {
        "phone": "",
        "session_name": f"session_{target_id}",
        "message": "Salom!",
        "message_type": "text",
        "image_file_id": None,
        "image_path": None,
        "interval_minutes": 60,
        "target_groups": "[]",
        "is_logged_in": 0,
        "next_send_time": 0,
        "is_active": 0,
        "state": "menu",
        "phone_code_hash": "",
        "is_premium": 0,
        "premium_until": 0,
        "messages_sent": 0,
        "last_active": 0,
        "user_started_required_bots": 0,
        "current_payment_id": None,
        "session_messages_sent": 0,
        "has_joined_channel": 0,
        "invited_by": "",
        "invite_count": 0,
        "referral_discount_used": 0,
        "next_message_is_admin": 0,
        "premium_expired_notified": 0,
        "is_banned": 0,
        "total_invites": 0
    }
    await db.update_user(target_str, default_user_data)

    # Notify the user if possible
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="🔄 Sizning barcha ma'lumotlaringiz admin tomonidan qayta tiklandi."
        )
    except Exception:
        pass

    await update.message.reply_text(f"✅ Foydalanuvchi {target_id} ma'lumotlari qayta tiklandi.")


async def delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: delete a user completely from the database."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        await update.message.reply_text("❌ ID kiriting: /delete <user_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID")
        return

    target_str = str(target_id)
    user = await db.get_user(target_str)
    if not user:
        await update.message.reply_text(f"❌ {target_id} topilmadi")
        return

    # Stop active sending
    if target_id in sending_tasks:
        sending_tasks[target_id].cancel()
        sending_tasks.pop(target_id, None)

    # Disconnect client
    await disconnect_client(target_id)

    # Delete session file
    session_name = user.get("session_name", f"session_{target_id}")
    session_path = os.path.join(SESSIONS_DIR, session_name)
    if os.path.exists(session_path):
        try:
            os.remove(session_path)
        except Exception as e:
            logger.error(f"Error deleting session for {target_id}: {e}")

    # Delete user images
    user_image_dir = os.path.join(USER_IMAGES_DIR, target_str)
    if os.path.exists(user_image_dir):
        import shutil
        shutil.rmtree(user_image_dir, ignore_errors=True)

    # Adjust inviter's counts
    inviter_str = user.get("invited_by", "")
    if inviter_str:
        inviter = await db.get_user(inviter_str)
        if inviter:
            new_invite = max(0, inviter.get("invite_count", 0) - 1)
            new_total = max(0, inviter.get("total_invites", 0) - 1)
            await db.update_user(inviter_str, {
                "invite_count": new_invite,
                "total_invites": new_total
            })
            try:
                await context.bot.send_message(
                    chat_id=int(inviter_str),
                    text=f"⚠️ Siz taklif qilgan foydalanuvchi ({target_id}) admin tomonidan o'chirildi."
                )
            except Exception:
                pass

    # Delete user row from database
    async with db.lock:
        db.cursor.execute('DELETE FROM users WHERE user_id = ?', (target_str,))
        db.conn.commit()

    # Notify the deleted user
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text="⛔ Sizning hisobingiz admin tomonidan o'chirildi."
        )
    except Exception:
        pass

    await update.message.reply_text(f"✅ Foydalanuvchi {target_id} o'chirildi.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    if not context.args:
        await update.message.reply_text("❌ ID kiriting: /unban <user_id>")
        return
    try:
        target_user_id = int(context.args[0])
        target_user_str = str(target_user_id)
        user = await db.get_user(target_user_str)
        if not user:
            await update.message.reply_text(f"❌ {target_user_id} topilmadi")
            return
        await db.update_user(target_user_str, {"is_banned": 0})
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="✅ <b>Blokdan chiqarildingiz!</b>\n\nEndi botdan foydalanishingiz mumkin.",
                parse_mode='HTML',
                reply_markup=await main_menu_keyboard(target_user_id)
            )
        except:
            pass
        await update.message.reply_text(f"✅ Foydalanuvchi {target_user_id} blokdan chiqarildi")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID")

async def set_admin_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ Admin emassiz")
        return
    admin_message = await db.get_admin_message()
    if admin_message and admin_message.get('message'):
        keyboard = [
            [KeyboardButton("🗑️ Admin xabarni o'chirish")],
            [KeyboardButton("✏️ Admin xabarni almashtirish")],
            [KeyboardButton("❌ Bekor")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Admin xabari mavjud. O'chirish yoki almashtirishni tanlang:",
            reply_markup=reply_markup
        )
        context.user_data['admin_state'] = 'admin_message_options'
    else:
        await update.message.reply_text(
            "Admin xabar turini tanlang:",
            reply_markup=message_type_keyboard()
        )
        context.user_data['admin_state'] = 'admin_awaiting_message_type'

async def handle_admin_message_options(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    if text == "🗑️ Admin xabarni o'chirish":
        await db.delete_admin_message()
        await update.message.reply_text(
            "✅ Admin xabari o'chirildi.",
            reply_markup=await main_menu_keyboard(user_id)
        )
        context.user_data.pop('admin_state', None)
    elif text == "✏️ Admin xabarni almashtirish":
        await update.message.reply_text(
            "Yangi admin xabar turini tanlang:",
            reply_markup=message_type_keyboard()
        )
        context.user_data['admin_state'] = 'admin_awaiting_message_type'
    elif text == "❌ Bekor":
        await update.message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=await main_menu_keyboard(user_id)
        )
        context.user_data.pop('admin_state', None)

# --- Telethon Client Management ---
async def get_client(user_id: int) -> TelegramClient:
    if user_id in clients:
        return clients[user_id]
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not user:
        return None
    session_name = user.get("session_name", f"session_{user_id}")
    session_path = os.path.join(SESSIONS_DIR, session_name)
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()
    if await client.is_user_authorized():
        clients[user_id] = client
        return client
    return client

async def disconnect_client(user_id: int):
    if user_id in clients:
        try:
            await clients[user_id].disconnect()
        except:
            pass
        finally:
            clients.pop(user_id, None)

# --- Check Required Bots ---
async def check_and_start_required_bots(user_id: int, client: TelegramClient):
    for bot_username in REQUIRED_BOTS:
        try:
            await client.send_message(bot_username, "/start")
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Cannot connect to {bot_username}: {e}")
    return True

# --- Dynamic Main Menu Keyboard (NEW) ---
async def main_menu_keyboard(user_id: int):
    user_str = str(user_id)
    data = await db.get_user(user_str)
    if not data:
        data = {}
    is_active = data.get("is_active", 0)
    keyboard = [
        [KeyboardButton("👤 Profil")],
        [KeyboardButton("⚙️ Sozlamalar"), KeyboardButton("📊 Statistika")],
        [KeyboardButton("▶️ Yuborishni boshlash")]
    ]
    if is_active:
        keyboard[2] = [KeyboardButton("⏹️ To'xtatish")]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def settings_keyboard():
    keyboard = [
        [KeyboardButton("✏️ Xabar"), KeyboardButton("⏰ Interval")],
        [KeyboardButton("👥 Guruhlar"), KeyboardButton("🔙 Ortga")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def message_type_keyboard():
    keyboard = [
        [KeyboardButton("📝 Matn")],
        [KeyboardButton("🖼️ Rasm")],
        [KeyboardButton("📝+🖼️")],
        [KeyboardButton("❌ Bekor")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Bekor")]], resize_keyboard=True)

async def premium_inline_keyboard(discounted_price: int = None):
    if discounted_price is None:
        discounted_price = PREMIUM_PRICE_MONEY
    keyboard = [
        [InlineKeyboardButton(f"⭐ {PREMIUM_PRICE_STARS} Stars", callback_data="buy_premium_stars")],
        [InlineKeyboardButton(f"💰 {discounted_price:,} so'm", callback_data=f"buy_premium_money_{discounted_price}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_payment_actions_keyboard(payment_id: str):
    keyboard = [
        [
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{payment_id}"),
            InlineKeyboardButton("❌ Bekor", callback_data=f"cancel_{payment_id}")
        ],
        [
            InlineKeyboardButton("⚠️ Yetarli emas", callback_data=f"insufficient_{payment_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def payment_button_keyboard(payment_id: str):
    keyboard = [
        [InlineKeyboardButton("📸 Skrinshot", callback_data=f"send_screenshot_{payment_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- New Profile Section ---
async def profil_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if not await require_channel_join(update, context):
        return
    user = await db.get_user(user_str)
    if not user:
        await start(update, context)
        return
    phone = user.get('phone', 'Ulanmagan')
    phone_display = phone if phone else 'Ulanmagan'
    login_status = "Ulangan" if user.get('is_logged_in', 0) else "Ulanmagan"
    is_premium = await check_premium_status(user_str)
    if is_premium:
        premium_until = user.get('premium_until', 0)
        until_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d %H:%M")
        tariff_text = f"👑 Premium (Tugash: {until_date})"
    else:
        tariff_text = "📦 Free ❌ (Premium yo'q)"
    profile_text = (
        f"👤 <b>Profilingiz</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"📱 Ulangan raqam: {phone_display}\n"
        f"Holat: {login_status}\n"
        f"{tariff_text}"
    )
    
    # Dynamic button: if logged in -> disconnect, else -> connect
    if user.get('is_logged_in', 0):
        connect_button = InlineKeyboardButton("🔌 Profilni uzish", callback_data="profile_disconnect")
    else:
        connect_button = InlineKeyboardButton("🔗 Profil Ulash", callback_data="profile_connect")
    
    keyboard = [
        [connect_button],
        [InlineKeyboardButton("👥 Referral", callback_data="profile_referral")],
        [InlineKeyboardButton("👑 Premium", callback_data="profile_premium")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(profile_text, parse_mode='HTML', reply_markup=reply_markup)
    
async def profile_connect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await add_account_from_callback(update, context)

async def profile_disconnect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_str = str(user_id)

    # Stop any active sending
    if user_id in sending_tasks:
        sending_tasks[user_id].cancel()
        sending_tasks.pop(user_id, None)

    # Disconnect Telethon client
    await disconnect_client(user_id)

    # Delete the session file
    user = await db.get_user(user_str)
    if user:
        session_name = user.get("session_name", f"session_{user_id}")
        session_path = os.path.join(SESSIONS_DIR, session_name)
        try:
            if os.path.exists(session_path):
                os.remove(session_path)
                logger.info(f"Deleted session file for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting session file for {user_id}: {e}")

    # Update database: mark as logged out, clear related fields
    await db.update_user(user_str, {
        "is_logged_in": 0,
        "phone": "",
        "user_started_required_bots": 0,
        "phone_code_hash": "",
        "session_name": f"session_{user_id}"  # keep same name, but will be recreated on next connect
    })

    await query.edit_message_text(
        "✅ Hisobingiz botdan uzildi. Agar qayta ulanish kerak bo'lsa, Profil bo'limidan foydalaning.",
        reply_markup=None
    )
    
async def profile_referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await referral_command_from_callback(update, context)

async def profile_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_premium_info_from_callback(update, context)

async def add_account_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    user_str = str(user_id)
    await disconnect_client(user_id)
    await db.update_user(user_str, {
        "state": "awaiting_phone",
        "is_logged_in": 0,
        "user_started_required_bots": 0,
        "current_payment_id": None
    })
    await update.callback_query.message.reply_text(
        "📲 Telegram akkauntingizni ulash uchun telefon raqamingiz kerak.\n\n"
        "👉 «📱 Raqamni yuborish» ni bosing yoki to'g'ri davlat formatida yozing.",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📱 Raqamni yuborish", request_contact=True)], [KeyboardButton("❌ Bekor")]], resize_keyboard=True)
    )

async def referral_command_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not user:
        await update.callback_query.message.reply_text("❌ Xatolik")
        return
    invite_count = user.get("invite_count", 0)
    total_invites = user.get("total_invites", 0)
    discount = await get_referral_discount(user_str)
    discounted_price = await get_discounted_price(user_str)
    referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    referral_text = (
        f"👥 <b>Referral Havolasi:</b>\n\n"
        f"🔗 <code>{referral_link}</code>\n\n"
        f"💸 Linkingizdan kirgan har bir user (kanalga obuna bo'lgandan keyin) uchun {REFERRAL_DISCOUNT_PER_USER} so'm chegirma\n\n"
        f"✅ Joriy takliflar: {invite_count} ta\n"
        f"📈 Umumiy takliflar: {total_invites} ta\n"
        f"💰 Chegirma: {discount:,} so'm\n"
        f"💵 Yangi narx: {discounted_price:,} so'm"
    )
    share_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Do'stlarga yuborish", switch_inline_query=f"{SHARE_TEXT} {referral_link}")]])
    await update.callback_query.message.reply_text(
        referral_text,
        parse_mode='HTML',
        reply_markup=share_keyboard
    )

async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /referral command - show referral info (backward compatibility)"""
    user_id = update.effective_user.id
    user_str = str(user_id)
    if not await require_channel_join(update, context):
        return
    user = await db.get_user(user_str)
    if not user:
        await start(update, context)
        return
    invite_count = user.get("invite_count", 0)
    total_invites = user.get("total_invites", 0)
    discount = await get_referral_discount(user_str)
    discounted_price = await get_discounted_price(user_str)
    referral_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    referral_text = (
        f"👥 <b>Referral Havolasi:</b>\n\n"
        f"🔗 <code>{referral_link}</code>\n\n"
        f"💸 Linkingizdan kirgan har bir user (kanalga obuna bo'lgandan keyin) uchun {REFERRAL_DISCOUNT_PER_USER} so'm chegirma\n\n"
        f"✅ Joriy takliflar: {invite_count} ta\n"
        f"📈 Umumiy takliflar: {total_invites} ta\n"
        f"💰 Chegirma: {discount:,} so'm\n"
        f"💵 Yangi narx: {discounted_price:,} so'm"
    )
    share_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Do'stlarga yuborish", switch_inline_query=f"{SHARE_TEXT} {referral_link}")]])
    await update.message.reply_text(referral_text, parse_mode='HTML', reply_markup=share_keyboard)

async def show_premium_info_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.callback_query.from_user.id
    user_str = str(user_id)
    if await check_premium_status(user_str):
        user = await db.get_user(user_str)
        premium_until = user.get("premium_until", 0)
        until_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d %H:%M")
        await update.callback_query.message.reply_text(
            f"✅ <b>Sizda Premium bor!</b>\n\n"
            f"📅 Tugash: {until_date}\n"
            f"⚡ Imkoniyatlar:\n"
            f"✅ {PREMIUM_MIN_INTERVAL} daqiqa\n"
            f"✅ {PREMIUM_GROUP_LIMIT} guruh\n"
            f"✅ Rasm\n"
            f"✅ {PREMIUM_MESSAGE_LIMIT} xabar\n"
            f"✅ Admin xabari yo'q",
            parse_mode='HTML',
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    user = await db.get_user(user_str)
    invite_count = user.get("invite_count", 0)
    if invite_count >= REFERRAL_FREE_PREMIUM_THRESHOLD and not user.get("referral_discount_used", 0):
        if await add_premium(user_str, PREMIUM_DAYS):
            await update.callback_query.message.reply_text(
                f"🎉 <b>Tabriklaymiz! {invite_count} ta taklif</b>\n\n"
                f"✅ BEPUL Premium faollashtirildi!",
                parse_mode='HTML',
                reply_markup=await main_menu_keyboard(user_id)
            )
            return
    discount = await get_referral_discount(user_str)
    discounted_price = await get_discounted_price(user_str)
    premium_info_text = (
        "👑 <b>Premium Obuna</b>\n\n"
        "⚡ <b>Imkoniyatlar:</b>\n"
        f"✅ {PREMIUM_MIN_INTERVAL} daqiqa (Oddiy: {NON_PREMIUM_MIN_INTERVAL})\n"
        f"✅ {PREMIUM_GROUP_LIMIT} guruh (Oddiy: {NON_PREMIUM_GROUP_LIMIT})\n"
        f"✅ Rasm yuborish\n"
        f"✅ {PREMIUM_MESSAGE_LIMIT} xabar (Oddiy: {NON_PREMIUM_MESSAGE_LIMIT})\n"
        f"✅ Admin xabari yo'q\n\n"
        f"🎁 <b>Taklif chegirmasi:</b>\n"
        f"• Takliflar: {invite_count} ta\n"
        f"• Chegirma: {discount:,} so'm\n"
        f"• Yangi narx: {discounted_price:,} so'm\n\n"
        f"💳 <b>Narx (30 kun):</b>\n"
        f"1. ⭐ {PREMIUM_PRICE_STARS} Stars\n"
        f"2. 💰 {discounted_price:,} so'm"
    )
    await update.callback_query.message.reply_text(
        premium_info_text,
        parse_mode='HTML',
        reply_markup=await premium_inline_keyboard(discounted_price)
    )

async def statistika_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if not await require_channel_join(update, context):
        return
    user = await db.get_user(user_str)
    if not user:
        await start(update, context)
        return
    is_active = user.get("is_active", 0)
    session_sent = user.get("session_messages_sent", 0)
    message_limit = await get_message_limit(user_str)
    total_messages = user.get("messages_sent", 0)
    if is_active:
        next_time = user.get("next_send_time", 0)
        if next_time > time.time():
            next_str = datetime.fromtimestamp(next_time).strftime("%H:%M:%S")
            status = f"🟢 Faol (Keyingi: {next_str})"
        else:
            status = "🟢 Faol (Hozir yuboriladi)"
        remaining = message_limit - session_sent
        if remaining > 0:
            interval = user.get("interval_minutes", 60)
            hours = (remaining * interval) / 60
            session_info = f"{session_sent}/{message_limit} (~{hours:.1f} soat)"
        else:
            session_info = f"{session_sent}/{message_limit} (Tugagan)"
    else:
        status = "🔴 Holat: Faol emas"
        session_info = "Faol emas"
    stats_text = (
        f"{status}\n"
        f"📊 Sessiya: {session_info}\n"
        f"📨 Umumiy xabarlar: {total_messages}"
    )
    await update.message.reply_text(stats_text, parse_mode='HTML', reply_markup=await main_menu_keyboard(user_id))

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "⚙️ Sozlamalar",
        reply_markup=settings_keyboard()
    )

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "Asosiy menu",
        reply_markup=await main_menu_keyboard(user_id)
    )

async def change_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not await require_channel_join(update, context):
        return
    if not user or not user.get("is_logged_in", 0):
        await update.message.reply_text(
            "❌ Hisob ulanmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    is_premium = await check_premium_status(user_str)
    if is_premium:
        await db.update_user(user_str, {"state": "awaiting_message_type"})
        current_msg = user.get("message", "O'rnatilmagan")
        current_type = user.get("message_type", "text")
        type_text = {
            "text": "Matn",
            "image": "Rasm",
            "image_text": "Matn+Rasm"
        }.get(current_type, "Matn")
        await update.message.reply_text(
            f"📝 <b>Joriy Xabar Turi:</b> {type_text}\n"
            f"📝 <b>Joriy Xabar:</b>\n{current_msg[:100]}{'...' if len(current_msg) > 100 else ''}\n\n"
            f"O'zgartirish uchun yangi xabar yuboring yoki tur tanlang:",
            parse_mode='HTML',
            reply_markup=message_type_keyboard()
        )
    else:
        await db.update_user(user_str, {"state": "awaiting_message"})
        current_msg = user.get("message", "O'rnatilmagan")
        await update.message.reply_text(
            f"📝 Joriy Xabar:\n{current_msg}\n\n"
            "O'zgartirish uchun yangi xabar yuboring:",
            reply_markup=cancel_keyboard()
        )

# --- Updated Interval Handler with Inline Buttons and Manual Input ---
async def change_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not await require_channel_join(update, context):
        return
    if not user or not user.get("is_logged_in", 0):
        await update.message.reply_text(
            "❌ Hisob ulanmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    current_interval = user.get("interval_minutes", 60)
    is_premium = await check_premium_status(user_str)
    admin_msg = await db.get_admin_message()
    if is_premium:
        admin_status = "Yo'q (Premium)"
        admin_note = ""
    elif admin_msg and admin_msg.get('message_type'):
        admin_status = "Mavjud"
        admin_note = "\n⚠️ Har intervalda sizning xabaringiz keyingisida admin xabari yuboriladi! Premium obunasi buni olib tashlaydi!"
    else:
        admin_status = "Mavjud emas"
        admin_note = ""
    text = (
        f"⏰ <b>Joriy interval:</b> {current_interval} daqiqa\n"
        f"📢 <b>Admin Xabari:</b> {admin_status}"
    )
    if not is_premium and admin_msg and admin_msg.get('message_type'):
        text += admin_note
    intervals = [3, 5, 7, 10, 15]
    buttons = []
    row = []
    for i, val in enumerate(intervals):
        row.append(InlineKeyboardButton(f"{val} daqiqa", callback_data=f"set_interval_{val}"))
        if (i+1) % 2 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # Manual input button
    buttons.append([InlineKeyboardButton("✏️ Boshqa", callback_data="set_interval_manual")])
    buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="interval_cancel")])
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def interval_manual_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_str = str(user_id)

    # Set user state to wait for manual interval
    await db.update_user(user_str, {"state": "awaiting_manual_interval"})

    # Update the inline message to indicate manual input is expected
    await query.edit_message_text("✏️ Iltimos, yangi intervalni daqiqada kiriting.")

    # Send a new message with the cancel button (ReplyKeyboard)
    await context.bot.send_message(
        chat_id=user_id,
        text="Quyidagi tugma orqali bekor qilishingiz mumkin:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Bekor")]], resize_keyboard=True)
    )

async def interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_str = str(user_id)
    data = query.data
    if data == "interval_cancel":
        await query.edit_message_text("❌ Bekor qilindi")
        return
    if data.startswith("set_interval_"):
        try:
            interval = int(data.split("_")[2])
        except:
            return
        user = await db.get_user(user_str)
        if not user:
            return
        is_premium = await check_premium_status(user_str)
        min_interval = PREMIUM_MIN_INTERVAL if is_premium else NON_PREMIUM_MIN_INTERVAL
        if interval < min_interval:
            await query.edit_message_text(
                f"❌ Minimal interval {min_interval} daqiqa. Premium obuna orqali {PREMIUM_MIN_INTERVAL} daqiqagacha tushirishingiz mumkin.",
                reply_markup=None
            )
            return
        if interval > MAX_INTERVAL:
            await query.edit_message_text(
                f"❌ Maksimal interval {MAX_INTERVAL} daqiqa.",
                reply_markup=None
            )
            return
        await db.update_user(user_str, {"interval_minutes": interval})
        await query.edit_message_text(f"✅ Interval {interval} daqiqa qilib o'rnatildi!")

async def handle_manual_interval(update: Update, context: ContextTypes.DEFAULT_TYPE, interval_str: str):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if interval_str.lower() in ["/cancel", "❌ bekor", "cancel", "bekor"]:
        await db.update_user(user_str, {"state": "menu"})
        await update.message.reply_text(
            "❌ Bekor qilindi",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    try:
        interval = int(interval_str)
    except ValueError:
        await update.message.reply_text(
            "❌ Iltimos, faqat son kiriting!",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Bekor")]], resize_keyboard=True)
        )
        return
    is_premium = await check_premium_status(user_str)
    min_interval = PREMIUM_MIN_INTERVAL if is_premium else NON_PREMIUM_MIN_INTERVAL
    if interval < min_interval:
        await update.message.reply_text(
            f"❌ Minimal interval {min_interval} daqiqa. Premium obuna orqali {PREMIUM_MIN_INTERVAL} daqiqagacha tushirishingiz mumkin.",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Bekor")]], resize_keyboard=True)
        )
        return
    if interval > MAX_INTERVAL:
        await update.message.reply_text(
            f"❌ Maksimal interval {MAX_INTERVAL} daqiqa.",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Bekor")]], resize_keyboard=True)
        )
        return
    await db.update_user(user_str, {"interval_minutes": interval, "state": "menu"})
    await update.message.reply_text(
        f"✅ Interval {interval} daqiqa qilib o'rnatildi!",
        reply_markup=await main_menu_keyboard(user_id)
    )

# --- Group Selection with Channels excluded and Clear button ---
async def change_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if not await require_channel_join(update, context):
        return
    user = await db.get_user(user_str)
    if not user or not user.get("is_logged_in", 0):
        await update.message.reply_text(
            "❌ Hisob ulanmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    client = await get_client(user_id)
    if not client or not await client.is_user_authorized():
        await update.message.reply_text(
            "❌ Hisob ulanmagan yoki sessiya tugagan. Iltimos, qayta ulang.",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    try:
        dialogs = await client.get_dialogs()
        groups = []
        for dialog in dialogs:
            # Only include groups, not channels
            if dialog.is_group:
                entity = dialog.entity
                if hasattr(entity, 'username') and entity.username:
                    identifier = f"@{entity.username}"
                else:
                    identifier = str(entity.id)
                groups.append({
                    'id': identifier,
                    'name': dialog.name,
                    'entity': entity
                })
    except Exception as e:
        logger.error(f"Error fetching dialogs: {e}")
        await update.message.reply_text("❌ Guruhlarni olishda xatolik yuz berdi.")
        return
    if not groups:
        await update.message.reply_text("❌ Siz hech qanday guruhda emassiz.")
        return
    context.user_data['group_selection'] = {
        'groups': groups,
        'selected': user.get('target_groups', []),
        'page': 0
    }
    await send_group_page(update, context, query=None)

async def send_group_page(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    user_str = str(user_id)
    sel = context.user_data.get('group_selection')
    if not sel:
        return
    groups = sel['groups']
    selected = sel['selected']
    page = sel['page']
    page_size = 5
    total_pages = (len(groups) + page_size - 1) // page_size
    start = page * page_size
    end = min(start + page_size, len(groups))
    page_groups = groups[start:end]
    keyboard = []
    for idx, grp in enumerate(page_groups, start=start):
        is_selected = grp['id'] in selected
        emoji = "✅ " if is_selected else "➕ "
        callback_data = f"group_select_{idx}"
        keyboard.append([InlineKeyboardButton(f"{emoji}{grp['name'][:30]}", callback_data=callback_data)])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Oldingi", callback_data="group_page_prev"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Keyingi ▶️", callback_data="group_page_next"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    # Clear all button
    keyboard.append([InlineKeyboardButton("🧹 Tozalash", callback_data="group_clear_all")])
    keyboard.append([
        InlineKeyboardButton("✅ Tasdiqlash", callback_data="group_confirm"),
        InlineKeyboardButton("❌ Yopish", callback_data="group_close")
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    limit = await get_group_limit(user_str)
    text = f"Guruhlarni Tanlang (Tanlangan: {len(selected)}/{limit})"
    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def group_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_str = str(user_id)
    data = query.data
    sel = context.user_data.get('group_selection')
    if not sel:
        await query.edit_message_text("❌ Sessiya tugagan")
        return
    if data == "group_page_prev":
        sel['page'] -= 1
        await send_group_page(update, context, query)
    elif data == "group_page_next":
        sel['page'] += 1
        await send_group_page(update, context, query)
    elif data == "group_clear_all":
        sel['selected'] = []
        await send_group_page(update, context, query)
    elif data == "group_confirm":
        selected = sel['selected']
        limit = await get_group_limit(user_str)
        if len(selected) > limit:
            await query.edit_message_text(f"❌ Siz {limit} tadan ko'p guruh tanladingiz! Iltimos, qaytadan tanlang.")
            return
        await db.update_user(user_str, {"target_groups": selected})
        await query.edit_message_text("✅ Guruhlar yangilandi!")
        context.user_data.pop('group_selection', None)
    elif data == "group_close":
        await query.edit_message_text("❌ Yopildi")
        context.user_data.pop('group_selection', None)
    elif data.startswith("group_select_"):
        idx = int(data.split("_")[2])
        groups = sel['groups']
        if 0 <= idx < len(groups):
            grp_id = groups[idx]['id']
            if grp_id in sel['selected']:
                sel['selected'].remove(grp_id)
            else:
                sel['selected'].append(grp_id)
            await send_group_page(update, context, query)

# --- Original sending functions (modified for anti-spam) ---

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if phone.lower() in ["/cancel", "❌ bekor", "cancel", "bekor"]:
        await db.update_user(user_str, {"state": "menu"})
        await update.message.reply_text(
            "❌ Bekor qilindi",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')
    if not cleaned:
        await update.message.reply_text("❌ Noto'g'ri raqam")
        return
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    phone_digits = cleaned[1:]
    if not phone_digits.isdigit() or len(phone_digits) < 7:
        await update.message.reply_text("❌ Noto'g'ri format")
        return
    phone = cleaned
    await db.update_user(user_str, {"phone": phone, "state": "awaiting_code"})
    try:
        user = await db.get_user(user_str)
        session_name = user.get("session_name", f"session_{user_id}")
        session_path = os.path.join(SESSIONS_DIR, session_name)
        client = TelegramClient(session_path, API_ID, API_HASH)
        await client.connect()
        sent_code = await client.send_code_request(phone)
        phone_code_hash = sent_code.phone_code_hash
        await db.update_user(user_str, {"phone_code_hash": phone_code_hash})
        clients[user_id] = client
        await update.message.reply_text(
            "✅ Kod yuborildi!\n\n"
            "📨 5-xonali kodni 11.111 formatda kiriting:",
            reply_markup=cancel_keyboard()
        )
    except errors.FloodWaitError as e:
        await update.message.reply_text(
            f"⏳ {e.seconds} soniya kuting",
            reply_markup=await main_menu_keyboard(user_id)
        )
        await db.update_user(user_str, {"state": "menu"})
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            f"❌ Xato\n{type(e).__name__}",
            reply_markup=await main_menu_keyboard(user_id)
        )
        await db.update_user(user_str, {"state": "menu"})

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if code.lower() in ["/cancel", "❌ bekor", "cancel", "bekor"]:
        await db.update_user(user_str, {"state": "menu"})
        await update.message.reply_text(
            "❌ Bekor qilindi",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    code = ''.join(filter(str.isdigit, code))
    if len(code) != 5:
        await update.message.reply_text(
            "❌ 5 ta raqamni 11.111 formatda kiriting",
            reply_markup=cancel_keyboard()
        )
        return
    try:
        client = clients.get(user_id)
        if not client:
            await update.message.reply_text(
                "❌ Sessiya tugadi",
                reply_markup=await main_menu_keyboard(user_id)
            )
            await db.update_user(user_str, {"state": "menu"})
            return
        user = await db.get_user(user_str)
        phone = user["phone"]
        phone_code_hash = user.get("phone_code_hash", "")
        if not phone_code_hash:
            await update.message.reply_text(
                "❌ Sessiya tugadi",
                reply_markup=await main_menu_keyboard(user_id)
            )
            await db.update_user(user_str, {"state": "menu"})
            return
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        await db.update_user(user_str, {
            "is_logged_in": 1,
            "state": "menu",
            "phone_code_hash": "",
            "last_active": time.time()
        })
        logger.info("Starting required bots...")
        user = await db.get_user(user_str)
        if not user.get("user_started_required_bots"):
            await check_and_start_required_bots(user_id, client)
            await db.update_user(user_str, {"user_started_required_bots": 1})
        me = await client.get_me()
        username = me.username or me.first_name or f"user_{me.id}"
        await update.message.reply_text(
            f"✅ <b>Kirildi!</b> @{username}\n\n"
            "✅ Botlar ishga tushirildi",
            parse_mode='HTML',
            reply_markup=await main_menu_keyboard(user_id)
        )
    except errors.SessionPasswordNeededError:
        await db.update_user(user_str, {"state": "awaiting_password"})
        await update.message.reply_text(
            "🔐 2 bosqichli parolni kiriting:",
            reply_markup=cancel_keyboard()
        )
    except errors.PhoneCodeInvalidError:
        await update.message.reply_text(
            "❌ Kod xato qaytadan urinib ko'ring.",
            reply_markup=cancel_keyboard()
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            f"❌ Xato\n{type(e).__name__}",
            reply_markup=await main_menu_keyboard(user_id)
        )
        await db.update_user(user_str, {"state": "menu"})

async def handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE, password: str):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if password.lower() in ["/cancel", "❌ bekor", "cancel", "bekor"]:
        await db.update_user(user_str, {"state": "menu"})
        await update.message.reply_text(
            "❌ Bekor qilindi",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    try:
        client = clients.get(user_id)
        if not client:
            await update.message.reply_text(
                "❌ Sessiya tugadi",
                reply_markup=await main_menu_keyboard(user_id)
            )
            await db.update_user(user_str, {"state": "menu"})
            return
        await client.sign_in(password=password)
        await db.update_user(user_str, {
            "is_logged_in": 1,
            "state": "menu",
            "last_active": time.time()
        })
        logger.info("Starting required bots...")
        user = await db.get_user(user_str)
        if not user.get("user_started_required_bots"):
            await check_and_start_required_bots(user_id, client)
            await db.update_user(user_str, {"user_started_required_bots": 1})
        me = await client.get_me()
        username = me.username or me.first_name or f"user_{me.id}"
        await update.message.reply_text(
            f"✅ <b>Kirildi!</b> @{username}",
            parse_mode='HTML',
            reply_markup=await main_menu_keyboard(user_id)
        )
    except errors.PasswordHashInvalidError:
        await update.message.reply_text(
            "❌ 2 bosqichli parol xato, qaytadan urinib ko'ring.",
            reply_markup=cancel_keyboard()
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            f"❌ Xato\n{type(e).__name__}",
            reply_markup=await main_menu_keyboard(user_id)
        )
        await db.update_user(user_str, {"state": "menu"})

async def handle_new_message(update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if message.lower() in ["/cancel", "❌ bekor", "cancel", "bekor"]:
        await db.update_user(user_str, {"state": "menu"})
        await update.message.reply_text(
            "❌ Bekor qilindi",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    if not await check_premium_status(user_str):
        user = await db.get_user(user_str)
        message_type = user.get("message_type", "text")
        if message_type in ["image", "image_text"]:
            new_message = f"{message}{FOOTER}"
            await db.update_user(user_str, {
                "message": new_message,
                "message_type": "text",
                "image_file_id": None,
                "image_path": None,
                "state": "menu"
            })
            await update.message.reply_text(
                f"⚠️ <b>Premium obunangiz tugadi!</b>\n\n"
                f"📝 Endi faqat matn xabarlar yuborishingiz mumkin.\n"
                f"💬 Xabar: {message[:100]}{'...' if len(message) > 100 else ''}",
                parse_mode='HTML',
                reply_markup=await main_menu_keyboard(user_id)
            )
            return
    await db.update_user(user_str, {"message": message, "state": "menu"})
    user = await db.get_user(user_str)
    message_type = user.get("message_type", "text")
    type_text = {
        "text": "Matn",
        "image": "Rasm",
        "image_text": "Matn+Rasm"
    }.get(message_type, "Matn")
    await update.message.reply_text(
        f"✅ <b>Xabar yangilandi!</b>\n\n"
        f"📝 Turi: {type_text}\n"
        f"💬 Xabar: {message}",
        parse_mode='HTML',
        reply_markup=await main_menu_keyboard(user_id)
    )

async def handle_new_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not user or user.get("state") != "awaiting_image":
        return
    if not await check_premium_status(user_str):
        await update.message.reply_text(
            "❌ Premium obunangiz tugadi! Rasm yuborish imkoniyati yo'q.\n"
            "Iltimos, faqat matn xabar yuboring.",
            reply_markup=await main_menu_keyboard(user_id)
        )
        await db.update_user(user_str, {"state": "menu"})
        return
    if not (update.message.photo or (update.message.document and update.message.document.mime_type and 'image' in update.message.document.mime_type)):
        await update.message.reply_text(
            "❌ Rasm yuboring!",
            reply_markup=cancel_keyboard()
        )
        return
    if update.message.photo:
        photo = update.message.photo[-1]
        file_id = photo.file_id
        file_size = photo.file_size or 0
    else:
        document = update.message.document
        file_id = document.file_id
        file_size = document.file_size or 0
    if file_size > IMAGE_SIZE_LIMIT:
        size_mb = file_size / (1024 * 1024)
        await update.message.reply_text(
            f"❌ Rasm hajmi 5 MB dan katta! ({size_mb:.2f} MB)",
            reply_markup=cancel_keyboard()
        )
        return
    file = await context.bot.get_file(file_id)
    if file.file_size and file.file_size > IMAGE_SIZE_LIMIT:
        size_mb = file.file_size / (1024 * 1024)
        await update.message.reply_text(
            f"❌ Rasm hajmi 5 MB dan katta! ({size_mb:.2f} MB)",
            reply_markup=cancel_keyboard()
        )
        return
    user_image_dir = os.path.join(USER_IMAGES_DIR, user_str)
    Path(user_image_dir).mkdir(exist_ok=True, parents=True)
    old_image_path = user.get("image_path")
    if old_image_path and os.path.exists(old_image_path):
        try:
            os.remove(old_image_path)
            logger.info(f"Removed old image for user {user_id}: {old_image_path}")
        except Exception as e:
            logger.error(f"Error removing old image: {e}")
    timestamp = int(time.time())
    image_path = os.path.join(user_image_dir, f"image_{timestamp}.jpg")
    try:
        await file.download_to_drive(image_path)
        await db.update_user(user_str, {
            "image_file_id": file_id,
            "image_path": image_path
        })
        user = await db.get_user(user_str)
        message_type = user.get("message_type", "text")
        if message_type == "image":
            await db.update_user(user_str, {"state": "menu"})
            file_size_mb = (file.file_size or 0) / (1024 * 1024)
            await update.message.reply_text(
                f"✅ <b>Rasm yangilandi!</b>\n\n"
                f"📝 Turi: Rasm\n"
                f"💾 {file_size_mb:.2f} MB",
                parse_mode='HTML',
                reply_markup=await main_menu_keyboard(user_id)
            )
        elif message_type == "image_text":
            await db.update_user(user_str, {"state": "awaiting_message"})
            user = await db.get_user(user_str)
            current_msg = user.get("message", "O'rnatilmagan")
            file_size_mb = (file.file_size or 0) / (1024 * 1024)
            await update.message.reply_text(
                f"✅ <b>Rasm saqlandi!</b> ({file_size_mb:.2f} MB)\n\n"
                "📝 Endi matn yuboring:",
                parse_mode='HTML',
                reply_markup=cancel_keyboard()
            )
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            f"❌ Xato\n{type(e).__name__}",
            reply_markup=cancel_keyboard()
        )

# (handle_new_interval, handle_new_groups, handle_account_change_confirmation remain as placeholders, but not used)
async def handle_new_interval(update: Update, context: ContextTypes.DEFAULT_TYPE, interval_str: str):
    pass
async def handle_new_groups(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    pass
async def handle_account_change_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, confirmation: str):
    pass

async def add_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if not await require_channel_join(update, context):
        return
    await disconnect_client(user_id)
    await db.update_user(user_str, {
        "state": "awaiting_phone",
        "is_logged_in": 0,
        "user_started_required_bots": 0,
        "current_payment_id": None
    })
    await update.message.reply_text(
        "📱 Telefon raqamingizni yuboring (+998901234567):",
        reply_markup=cancel_keyboard()
    )

async def handle_message_type(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if text == "📝 Matn":
        await db.update_user(user_str, {
            "message_type": "text",
            "state": "awaiting_message"
        })
        await update.message.reply_text(
            "📝 Xabar yuboring:",
            reply_markup=cancel_keyboard()
        )
    elif text == "🖼️ Rasm":
        if not await check_premium_status(user_str):
            await update.message.reply_text(
                "❌ Rasm yuborish faqat Premium foydalanuvchilar uchun!",
                reply_markup=await main_menu_keyboard(user_id)
            )
            return
        await db.update_user(user_str, {
            "message_type": "image",
            "state": "awaiting_image"
        })
        await update.message.reply_text(
            "🖼️ Rasm yuboring:",
            reply_markup=cancel_keyboard()
        )
    elif text == "📝+🖼️":
        if not await check_premium_status(user_str):
            await update.message.reply_text(
                "❌ Rasm+Matn yuborish faqat Premium foydalanuvchilar uchun!",
                reply_markup=await main_menu_keyboard(user_id)
            )
            return
        await db.update_user(user_str, {
            "message_type": "image_text",
            "state": "awaiting_image"
        })
        await update.message.reply_text(
            "🖼️ Rasm yuboring:",
            reply_markup=cancel_keyboard()
        )
    elif text == "❌ Bekor":
        await db.update_user(user_str, {"state": "menu"})
        await update.message.reply_text(
            "❌ Bekor qilindi",
            reply_markup=await main_menu_keyboard(user_id)
        )

# --- Payment handlers (unchanged) ---
async def buy_premium_stars_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await require_channel_join(update, context):
        return
    user_id = query.from_user.id
    user_str = str(user_id)
    if await check_premium_status(user_str):
        user = await db.get_user(user_str)
        premium_until = user.get("premium_until", 0)
        until_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d %H:%M")
        await query.edit_message_text(f"✅ Sizda Premium bor! Tugash: {until_date}")
        return
    title = "Premium (30 kun)"
    description = f"Premium obuna 30 kun"
    payload = f"premium_stars_{user_id}_{int(time.time())}"
    currency = "XTR"
    prices = [LabeledPrice(label="Premium (30 kun)", amount=PREMIUM_PRICE_STARS)]
    try:
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency=currency,
            prices=prices,
            start_parameter="premium_stars"
        )
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await query.edit_message_text(f"❌ Xato\n{type(e).__name__}")

async def buy_premium_money_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await require_channel_join(update, context):
        return
    user_id = query.from_user.id
    user_str = str(user_id)
    if await check_premium_status(user_str):
        await query.edit_message_text("✅ Sizda Premium bor")
        return
    try:
        discounted_price = int(query.data.split("_")[-1])
    except:
        discounted_price = PREMIUM_PRICE_MONEY
    pending_payments = await db.get_pending_payments()
    for payment in pending_payments:
        if payment["user_id"] == user_id and payment["status"] == "pending" and payment["user_sent_amount"] == 0:
            await db.delete_payment(payment["payment_id"])
    await db.update_user(user_str, {"state": "awaiting_payment_screenshot"})
    payment_id = await create_pending_payment(user_id, discounted_price, "money")
    await db.update_user(user_str, {"current_payment_id": payment_id})
    payment_instructions = (
        f"💳 <b>To'lov ma'lumotlari:</b>\n\n"
        f"<b>Karta:</b> <code>{CARD_NUMBER}</code>\n"
        f"<b>Visa:</b> <code>{VISA_CARD_NUMBER}</code>\n"
        f"<b>Miqdor:</b> {discounted_price:,} so'm\n"
        f"<b>ID:</b> {payment_id}\n\n"
        "To'lov qilib, skrinshot yuboring"
    )
    await query.edit_message_text(
        payment_instructions,
        parse_mode='HTML'
    )
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Bekor qilish:",
        reply_markup=cancel_keyboard()
    )

async def handle_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not user or user.get("state") != "awaiting_payment_screenshot":
        return
    if not (update.message.photo or (update.message.document and update.message.document.mime_type and 'image' in update.message.document.mime_type)):
        await update.message.reply_text(
            "❌ Skrinshot yuboring!",
            reply_markup=cancel_keyboard()
        )
        return
    payment_id = user.get("current_payment_id")
    if not payment_id:
        pending_payments = await db.get_pending_payments()
        for payment in pending_payments:
            if payment["user_id"] == user_id and payment["status"] == "pending" and payment["payment_type"] in ["money", "money_additional"]:
                payment_id = payment["payment_id"]
                break
    if not payment_id:
        await update.message.reply_text(
            "❌ To'lov topilmadi",
            reply_markup=await main_menu_keyboard(user_id)
        )
        await db.update_user(user_str, {"state": "menu", "current_payment_id": None})
        return
    if update.message.photo:
        photo = update.message.photo[-1]
        file_id = photo.file_id
    else:
        document = update.message.document
        file_id = document.file_id
    payment = await db.get_payment(payment_id)
    if not payment:
        await update.message.reply_text(
            "❌ To'lov topilmadi",
            reply_markup=await main_menu_keyboard(user_id)
        )
        await db.update_user(user_str, {"state": "menu", "current_payment_id": None})
        return
    username = user.get('username', '')
    username_display = f"@{username}" if username else "Username yo'q"
    admin_message = (
        f"💰 <b>Yangi To'lov</b>\n\n"
        f"👤 {username_display}\n"
        f"🆔 ID: {user_id}\n"
        f"💳 ID: {payment_id}\n"
        f"💰 {payment['amount']:,} so'm\n"
        f"🕒 {datetime.now().strftime('%H:%M')}"
    )
    try:
        if update.message.photo:
            message = await context.bot.send_photo(
                chat_id=PAYMENTS_GROUP_ID,
                photo=file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=admin_payment_actions_keyboard(payment_id)
            )
        else:
            message = await context.bot.send_document(
                chat_id=PAYMENTS_GROUP_ID,
                document=file_id,
                caption=admin_message,
                parse_mode='HTML',
                reply_markup=admin_payment_actions_keyboard(payment_id)
            )
        context.user_data[f'payment_message_{payment_id}'] = message.message_id
        await db.update_user(user_str, {"state": "menu", "current_payment_id": None})
        await update.message.reply_text(
            "✅ Skrinshot yuborildi!\n\n"
            "Admin tasdiqlagach Premium beriladi",
            reply_markup=await main_menu_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            f"❌ Xato\n{type(e).__name__}",
            reply_markup=await main_menu_keyboard(user_id)
        )

async def handle_admin_payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        return
    callback_data = query.data
    try:
        if callback_data.startswith("confirm_"):
            payment_id = callback_data[8:]
            payment = await db.get_payment(payment_id)
            if not payment:
                return
            await db.update_payment(payment_id, {"status": "confirmed"})
            if payment["payment_type"] in ["money", "money_additional"]:
                await update_money_profit(payment["amount"])
            user_str = str(payment["user_id"])
            days = PREMIUM_DAYS
            if await add_premium(user_str, days):
                user = await db.get_user(user_str)
                premium_until = user.get("premium_until", 0)
                until_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d %H:%M")
                try:
                    await context.bot.send_message(
                        chat_id=payment["user_id"],
                        text=f"✅ <b>To'lov tasdiqlandi!</b>\n\n"
                             f"🎉 Premium faollashtirildi\n"
                             f"📅 Tugash: {until_date}",
                        parse_mode='HTML',
                        reply_markup=await main_menu_keyboard(payment["user_id"])
                    )
                except:
                    pass
                user_data = await db.get_user(user_str)
                username = user_data.get('username', '') if user_data else ''
                username_display = f"@{username}" if username else "Username yo'q"
                final_message = (
                    f"👤 {username_display}\n"
                    f"🆔 {payment['user_id']}\n"
                    f"💰 {payment['amount']:,} so'm\n"
                    f"────────────\n"
                    f"✅ Tasdiqlandi"
                )
                try:
                    if query.message.photo:
                        await query.edit_message_caption(
                            caption=final_message,
                            parse_mode='HTML',
                            reply_markup=None
                        )
                    else:
                        await query.edit_message_text(
                            final_message,
                            parse_mode='HTML',
                            reply_markup=None
                        )
                except:
                    pass
        elif callback_data.startswith("cancel_"):
            payment_id = callback_data[7:]
            payment = await db.get_payment(payment_id)
            if not payment:
                return
            context.user_data["admin_action"] = "cancel_payment"
            context.user_data["payment_id"] = payment_id
            context.user_data["user_id"] = payment["user_id"]
            context.user_data["original_message_id"] = query.message.message_id
            context.user_data["original_chat_id"] = query.message.chat_id
            ask_message = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Bekor qilish sababini yuboring:"
            )
            context.user_data["ask_message_id"] = ask_message.message_id
        elif callback_data.startswith("insufficient_"):
            payment_id = callback_data[13:]
            payment = await db.get_payment(payment_id)
            if not payment:
                return
            context.user_data["admin_action"] = "insufficient_payment"
            context.user_data["payment_id"] = payment_id
            context.user_data["user_id"] = payment["user_id"]
            context.user_data["required_amount"] = payment["amount"]
            context.user_data["original_message_id"] = query.message.message_id
            context.user_data["original_chat_id"] = query.message.chat_id
            context.user_data["step"] = "awaiting_sent_amount"
            user_data = await db.get_user(str(payment["user_id"]))
            username = user_data.get('username', '') if user_data else ''
            username_display = f"@{username}" if username else "Username yo'q"
            ask_message = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"⚠️ Yetarli emas\n\n"
                     f"👤 {username_display}\n"
                     f"🆔 {payment['user_id']}\n"
                     f"💰 Kerak: {payment['amount']:,} so'm\n\n"
                     "Foydalanuvchi qancha yuborgan?"
            )
            context.user_data["ask_message_id"] = ask_message.message_id
    except Exception as e:
        logger.error(f"Error: {e}")

async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        return
    text = update.message.text.strip()
    if context.user_data.get("admin_action") == "cancel_payment":
        payment_id = context.user_data.get("payment_id")
        target_user_id = context.user_data.get("user_id")
        original_message_id = context.user_data.get("original_message_id")
        original_chat_id = context.user_data.get("original_chat_id")
        ask_message_id = context.user_data.get("ask_message_id")
        if not payment_id or not target_user_id:
            await update.message.reply_text("❌ Sessiya tugadi")
            context.user_data.clear()
            return
        payment = await db.get_payment(payment_id)
        if not payment:
            return
        await db.update_payment(payment_id, {"status": "cancelled", "admin_notes": text})
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"❌ <b>To'lov bekor qilindi</b>\n\n"
                     f"📝 Sabab: {text}",
                parse_mode='HTML',
                reply_markup=await main_menu_keyboard(target_user_id)
            )
        except:
            pass
        try:
            await context.bot.delete_message(
                chat_id=original_chat_id,
                message_id=update.message.message_id
            )
            if ask_message_id:
                await context.bot.delete_message(
                    chat_id=original_chat_id,
                    message_id=ask_message_id
                )
        except:
            pass
        user_data = await db.get_user(str(target_user_id))
        username = user_data.get('username', '') if user_data else ''
        username_display = f"@{username}" if username else "Username yo'q"
        final_message = (
            f"👤 {username_display}\n"
            f"🆔 {target_user_id}\n"
            f"💰 {payment['amount']:,} so'm\n"
            f"────────────\n"
            f"❌ Bekor qilindi\n"
            f"📝 {text}"
        )
        try:
            message_id = context.user_data.get(f'payment_message_{payment_id}', original_message_id)
            await context.bot.edit_message_caption(
                chat_id=original_chat_id,
                message_id=message_id,
                caption=final_message,
                parse_mode='HTML',
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            try:
                await context.bot.edit_message_text(
                    chat_id=original_chat_id,
                    message_id=message_id,
                    text=final_message,
                    parse_mode='HTML',
                    reply_markup=None
                )
            except:
                pass
        context.user_data.clear()
        return
    elif context.user_data.get("admin_action") == "insufficient_payment":
        payment_id = context.user_data.get("payment_id")
        target_user_id = context.user_data.get("user_id")
        required_amount = context.user_data.get("required_amount")
        original_message_id = context.user_data.get("original_message_id")
        original_chat_id = context.user_data.get("original_chat_id")
        ask_message_id = context.user_data.get("ask_message_id")
        if not payment_id or not target_user_id:
            await update.message.reply_text("❌ Sessiya tugadi")
            context.user_data.clear()
            return
        if context.user_data.get("step") == "awaiting_sent_amount":
            try:
                user_sent_amount = int(text)
                if user_sent_amount <= 0:
                    await update.message.reply_text("❌ Musbat raqam kiriting")
                    return
                if user_sent_amount >= required_amount:
                    await update.message.reply_text("❌ To'liq to'lov")
                    return
                try:
                    await context.bot.delete_message(
                        chat_id=original_chat_id,
                        message_id=update.message.message_id
                    )
                    if ask_message_id:
                        await context.bot.delete_message(
                            chat_id=original_chat_id,
                            message_id=ask_message_id
                        )
                except:
                    pass
                context.user_data["user_sent_amount"] = user_sent_amount
                context.user_data["step"] = "awaiting_reason"
                ask_message = await context.bot.send_message(
                    chat_id=original_chat_id,
                    text=f"✅ Yuborgan: {user_sent_amount:,} so'm\n\n"
                         "Izohni kiriting:"
                )
                context.user_data["ask_message_id"] = ask_message.message_id
                return
            except ValueError:
                await update.message.reply_text("❌ Raqam kiriting")
                return
        elif context.user_data.get("step") == "awaiting_reason":
            user_sent_amount = context.user_data.get("user_sent_amount", 0)
            reason = text
            try:
                await context.bot.delete_message(
                    chat_id=original_chat_id,
                    message_id=update.message.message_id
                )
                if ask_message_id:
                    await context.bot.delete_message(
                        chat_id=original_chat_id,
                        message_id=ask_message_id
                    )
            except:
                pass
            additional_amount = required_amount - user_sent_amount
            await update_money_profit(user_sent_amount)
            await db.update_payment(payment_id, {
                "status": "insufficient", 
                "admin_notes": reason, 
                "additional_amount_needed": additional_amount, 
                "user_sent_amount": user_sent_amount
            })
            new_payment_id = await create_pending_payment(target_user_id, additional_amount, "money_additional")
            user_data = await db.get_user(str(target_user_id))
            username = user_data.get('username', '') if user_data else ''
            username_display = f"@{username}" if username else "Username yo'q"
            final_message = (
                f"👤 {username_display}\n"
                f"🆔 {target_user_id}\n"
                f"💰 {required_amount:,} so'm\n"
                f"────────────\n"
                f"✅ {user_sent_amount:,} so'm\n"
                f"⚠️ {additional_amount:,} so'm\n"
                f"📝 {reason}"
            )
            try:
                message_id = context.user_data.get(f'payment_message_{payment_id}', original_message_id)
                await context.bot.edit_message_caption(
                    chat_id=original_chat_id,
                    message_id=message_id,
                    caption=final_message,
                    parse_mode='HTML',
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Error editing message: {e}")
                try:
                    await context.bot.edit_message_text(
                        chat_id=original_chat_id,
                        message_id=message_id,
                        text=final_message,
                        parse_mode='HTML',
                        reply_markup=None
                    )
                except:
                    pass
            try:
                user_notification = (
                    f"⚠️ <b>To'lov yetarli emas</b>\n\n"
                    f"📝 {reason}\n"
                    f"💰 To'langan: {user_sent_amount:,} so'm\n"
                    f"⚠️ Yetishmayotgan: {additional_amount:,} so'm\n\n"
                    f"Qolgan {additional_amount:,} so'm uchun skrinshot yuboring:"
                )
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=user_notification,
                    parse_mode='HTML',
                    reply_markup=payment_button_keyboard(new_payment_id)
                )
            except:
                pass
            context.user_data.clear()
            return

async def handle_send_screenshot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await require_channel_join(update, context):
        return
    user_id = query.from_user.id
    user_str = str(user_id)
    if not query.data.startswith("send_screenshot_"):
        return
    payment_id = query.data[16:]
    payment = await db.get_payment(payment_id)
    if not payment or payment["user_id"] != user_id:
        await query.edit_message_text("❌ To'lov topilmadi")
        return
    await db.update_user(user_str, {"state": "awaiting_payment_screenshot", "current_payment_id": payment_id})
    payment_instructions = (
        f"💳 <b>To'lov ma'lumotlari:</b>\n\n"
        f"<b>Karta:</b> <code>{CARD_NUMBER}</code>\n"
        f"<b>Miqdor:</b> {payment['amount']:,} so'm\n"
        f"<b>ID:</b> {payment_id}\n\n"
        "Skrinshot yuboring"
    )
    await query.edit_message_text(
        payment_instructions,
        parse_mode='HTML'
    )
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Bekor qilish:",
        reply_markup=cancel_keyboard()
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    payment = update.message.successful_payment
    total_amount = payment.total_amount
    await update_stars_profit(int(total_amount))
    if await add_premium(user_str, PREMIUM_DAYS):
        user = await db.get_user(user_str)
        premium_until = user.get("premium_until", 0)
        until_date = datetime.fromtimestamp(premium_until).strftime("%Y-%m-%d %H:%M")
        username = user.get('username', '')
        username_display = f"@{username}" if username else f"ID: {user_id}"
        try:
            stars_notification = (
                f"⭐ <b>Stars To'lovi</b>\n\n"
                f"👤 {username_display}\n"
                f"🆔 {user_id}\n"
                f"💰 {total_amount} stars\n"
                f"📅 {PREMIUM_DAYS} kun"
            )
            await context.bot.send_message(
                chat_id=PAYMENTS_GROUP_ID,
                text=stars_notification,
                parse_mode='HTML'
            )
        except:
            pass
        await update.message.reply_text(
            f"✅ <b>Premium sotib olindi!</b>\n\n"
            f"📅 Tugash: {until_date}",
            parse_mode='HTML',
            reply_markup=await main_menu_keyboard(user_id)
        )
    else:
        await update.message.reply_text(
            "❌ Xatolik",
            reply_markup=await main_menu_keyboard(user_id)
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    payment_id = user.get("current_payment_id") if user else None
    if payment_id:
        payment = await db.get_payment(payment_id)
        if payment and payment["status"] == "pending" and payment["user_sent_amount"] == 0:
            await db.delete_payment(payment["payment_id"])
    await db.update_user(user_str, {"current_payment_id": None, "state": "menu"})
    await update.message.reply_text(
        "✅ Bekor qilindi",
        reply_markup=await main_menu_keyboard(user_id)
    )

# --- Sending functions with 5‑second anti‑spam delay ---
async def start_sending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not await require_channel_join(update, context):
        return
    if not user:
        await update.message.reply_text(
            "❌ Ro'yxatdan o'tmagansiz",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    if user.get("is_active", 0):
        await update.message.reply_text(
            "⚠️ Allaqachon yoqilgan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    if not user.get("is_logged_in", 0):
        await update.message.reply_text(
            "❌ Hisob ulanmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    is_premium = await check_premium_status(user_str)
    interval = user.get("interval_minutes", 60)
    min_interval = PREMIUM_MIN_INTERVAL if is_premium else NON_PREMIUM_MIN_INTERVAL
    new_interval = interval
    if interval < min_interval:
        new_interval = min_interval
    if interval > MAX_INTERVAL:
        new_interval = MAX_INTERVAL
    if new_interval != interval:
        await db.update_user(user_str, {"interval_minutes": new_interval})
        interval = new_interval
    if not is_premium:
        if user.get("message_type") in ["image", "image_text"]:
            await downgrade_user_from_premium(user_str)
            user = await db.get_user(user_str)
            message = user.get("message", "Salom!")
        else:
            current_message = user.get("message", "Salom!")
            footer = FOOTER
            if not current_message.endswith(footer):
                new_message = current_message + footer
                await db.update_user(user_str, {"message": new_message})
                user = await db.get_user(user_str)
    else:
        current_message = user.get("message", "Salom!")
        footer = FOOTER
        if current_message.endswith(footer):
            new_message = current_message[:-len(footer)]
            await db.update_user(user_str, {"message": new_message})
            user = await db.get_user(user_str)
    groups = user.get("target_groups", [])
    group_limit = await get_group_limit(user_str)
    if len(groups) > group_limit:
        await update.message.reply_text(
            f"❌ <b>Chegaradan oshib ketgan!</b>\n\n"
            f"📊 {len(groups)}/{group_limit}\n"
            f"👑 Premium: {'✅' if is_premium else '❌'}\n\n"
            f"Guruhlarni kamaytiring yoki Premium sotib oling",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("👑 Premium"), KeyboardButton("❌ Bekor")]], resize_keyboard=True)
        )
        return
    message_type = user.get("message_type", "text")
    if message_type == "text" and not user.get("message"):
        await update.message.reply_text(
            "❌ Xabar o'rnatilmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    if message_type in ["image", "image_text"] and not user.get("image_path"):
        await update.message.reply_text(
            "❌ Rasm o'rnatilmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    if message_type == "image_text" and not user.get("message"):
        await update.message.reply_text(
            "❌ Xabar o'rnatilmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    if not user.get("target_groups"):
        await update.message.reply_text(
            "❌ Guruhlar o'rnatilmagan",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    try:
        client = clients.get(user_id)
        if not client:
            client = await get_client(user_id)
            if not client or not await client.is_user_authorized():
                await update.message.reply_text(
                    "❌ Hisob ulanmagan yoki sessiya muddati tugagan. Iltimos, hisobni qayta ulang.",
                    reply_markup=await main_menu_keyboard(user_id)
                )
                await db.update_user(user_str, {"is_logged_in": 0})
                return
        logger.info("Checking bots...")
        if not user.get("user_started_required_bots"):
            bots_started = await check_and_start_required_bots(user_id, client)
            await db.update_user(user_str, {"user_started_required_bots": 1})
            if not bots_started:
                await update.message.reply_text(
                    "⚠️ Botlar ishlamayapti\n"
                    "Botlarni ishga tushiring va qayta urinib ko'ring",
                    reply_markup=await main_menu_keyboard(user_id)
                )
                return
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            f"❌ Xatolik\n{type(e).__name__}",
            reply_markup=await main_menu_keyboard(user_id)
        )
        return
    if user_id in sending_tasks:
        sending_tasks[user_id].cancel()
        sending_tasks.pop(user_id, None)
    await db.update_user(user_str, {
        "is_active": 1,
        "session_messages_sent": 0,
        "next_message_is_admin": 0
    })
    safe_interval = interval
    next_send_time = time.time() + (safe_interval * 60)
    await db.update_user(user_str, {"next_send_time": next_send_time})
    sending_tasks[user_id] = asyncio.create_task(send_scheduled_messages(user_id))
    message_type_text = {
        "text": "Matn",
        "image": "Rasm",
        "image_text": "Matn+Rasm"
    }.get(message_type, "Matn")
    message_limit = await get_message_limit(user_str)
    await update.message.reply_text(
        f"✅ <b>Yuborish boshlandi!</b>\n\n"
        f"📊 <b>Sozlamalar:</b>\n"
        f"⏰ {safe_interval} daq\n"
        f"📝 {message_type_text}\n"
        f"👥 {len(groups)}/{group_limit}\n"
        f"👑 {'✅' if is_premium else '❌'}\n"
        f"📨 {message_limit} xabar",
        parse_mode='HTML',
        reply_markup=await main_menu_keyboard(user_id)
    )

async def stop_sending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    if user_id in sending_tasks:
        sending_tasks[user_id].cancel()
        sending_tasks.pop(user_id, None)
    user = await db.get_user(user_str)
    if user:
        session_sent = user.get("session_messages_sent", 0)
        await db.update_user(user_str, {"is_active": 0})
        await update.message.reply_text(
            f"⏹️ <b>Yuborish to'xtatildi!</b>\n\n"
            f"📊 {session_sent} xabar yuborildi",
            parse_mode='HTML',
            reply_markup=await main_menu_keyboard(user_id)
        )
    else:
        await update.message.reply_text(
            "⏹️ To'xtatildi",
            reply_markup=await main_menu_keyboard(user_id)
        )

async def send_scheduled_messages(user_id: int):
    user_str = str(user_id)
    while True:
        user = await db.get_user(user_str)
        if not user or not user.get("is_active", 0):
            break
        is_premium = await check_premium_status(user_str)
        if not is_premium and user.get("message_type") in ["image", "image_text"]:
            await downgrade_user_from_premium(user_str)
            await db.update_user(user_str, {"is_active": 0})
            try:
                from telegram import Bot
                bot = Bot(token=BOT_TOKEN)
                await bot.send_message(
                    chat_id=user_id,
                    text="⚠️ <b>Premium obunangiz tugadi!</b>\n\n"
                         "Rasm yuborish imkoniyati olib tashlandi.\n"
                         "Endi faqat matn xabarlar yuborishingiz mumkin.\n"
                         "Iltimos, yangi xabar o'rnating.",
                    parse_mode='HTML',
                    reply_markup=await main_menu_keyboard(user_id)
                )
            except:
                pass
            break
        next_time = user.get("next_send_time", 0)
        current_time = time.time()
        if current_time >= next_time:
            try:
                session_sent = user.get("session_messages_sent", 0)
                message_limit = await get_message_limit(user_str)
                is_premium = await check_premium_status(user_str)
                next_message_is_admin = user.get("next_message_is_admin", 0)
                admin_message = await db.get_admin_message()
                admin_message_exists = admin_message and admin_message.get('message_type')
                send_admin_message = False
                if not is_premium and next_message_is_admin and admin_message_exists:
                    send_admin_message = True
                if not send_admin_message:
                    if session_sent >= message_limit:
                        await db.update_user(user_str, {"is_active": 0})
                        try:
                            from telegram import Bot
                            bot = Bot(token=BOT_TOKEN)
                            await bot.send_message(
                                chat_id=user_id,
                                text=f"✅ <b>Sessiya tugadi!</b>\n\n"
                                     f"📊 {session_sent} xabar yuborildi",
                                parse_mode='HTML',
                                reply_markup=await main_menu_keyboard(user_id)
                            )
                        except:
                            pass
                        break
                await send_to_groups(user_id, send_admin_message)
                interval = user.get("interval_minutes", 60)
                min_interval = PREMIUM_MIN_INTERVAL if is_premium else NON_PREMIUM_MIN_INTERVAL
                safe_interval = max(min_interval, interval)
                if safe_interval > MAX_INTERVAL:
                    safe_interval = MAX_INTERVAL
                next_send_time = current_time + (safe_interval * 60)
                current_total = user.get("messages_sent", 0)
                current_session = user.get("session_messages_sent", 0)
                groups = user.get("target_groups", [])
                groups_count = len(groups) if groups else 0
                if not send_admin_message:
                    await db.update_user(user_str, {
                        "next_send_time": next_send_time,
                        "messages_sent": current_total + groups_count,
                        "session_messages_sent": current_session + 1,
                        "next_message_is_admin": 1 if admin_message_exists else 0
                    })
                    logger.info(f"Sent user message for {user_id}, session: {current_session + 1}/{message_limit}")
                    if current_session + 1 == message_limit - 3:
                        try:
                            from telegram import Bot
                            bot = Bot(token=BOT_TOKEN)
                            await bot.send_message(
                                chat_id=user_id,
                                text=f"⚠️ <b>Diqqat!</b> 3 interval qoldi!\n\n"
                                     f"📊 {current_session + 1}/{message_limit}",
                                parse_mode='HTML',
                                reply_markup=await main_menu_keyboard(user_id)
                            )
                        except:
                            pass
                else:
                    await db.update_user(user_str, {
                        "next_send_time": next_send_time,
                        "messages_sent": current_total + groups_count,
                        "next_message_is_admin": 0
                    })
                    logger.info(f"Sent admin message for {user_id}")
                user = await db.get_user(user_str)
                session_sent = user.get("session_messages_sent", 0)
                if session_sent >= message_limit and not send_admin_message:
                    await db.update_user(user_str, {"is_active": 0})
                    try:
                        from telegram import Bot
                        bot = Bot(token=BOT_TOKEN)
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"✅ <b>Sessiya tugadi!</b>\n\n"
                                 f"📊 {session_sent} interval",
                            parse_mode='HTML',
                            reply_markup=await main_menu_keyboard(user_id)
                        )
                    except:
                        pass
                    break
            except Exception as e:
                logger.error(f"Error: {e}")
        await asyncio.sleep(10)

async def send_to_groups(user_id: int, send_admin_message: bool = False):
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if not user:
        return
    is_premium = await check_premium_status(user_str)
    client = clients.get(user_id)
    if not client:
        client = await get_client(user_id)
    if not client or not await client.is_user_authorized():
        logger.error(f"Client not authorized for {user_id}")
        await db.update_user(user_str, {"is_logged_in": 0, "is_active": 0, "user_started_required_bots": 0})
        if user_id in sending_tasks:
            sending_tasks[user_id].cancel()
            sending_tasks.pop(user_id, None)
        try:
            if bot_instance:
                await bot_instance.send_message(
                    chat_id=user_id,
                    text="❌ <b>Hisob ulanmagan yoki sessiya tugagan!</b>\n\n"
                         "Iltimos, yangi hisob qo'shing.",
                    parse_mode='HTML',
                    reply_markup=await main_menu_keyboard(user_id)
                )
        except Exception as e:
            logger.error(f"Failed to send auth warning to {user_id}: {e}")
        return
    if send_admin_message:
        admin_message = await db.get_admin_message()
        if not admin_message:
            return
        message_type = admin_message.get("message_type", "text")
        message = admin_message.get("message", "")
        image_path = admin_message.get("image_path")
    else:
        message_type = user.get("message_type", "text")
        message = user.get("message", "")
        image_path = user.get("image_path")
    groups = user.get("target_groups", [])
    if not groups:
        return
    groups_to_remove = []
    remove_reasons = []
    account_error_occurred = False
    account_error_reason = ""
    for group in groups:
        try:
            if group.lstrip('-').isdigit():
                entity = int(group)
            elif group.startswith('@'):
                entity = group
            elif group.startswith('https://t.me/'):
                entity = '@' + group.split('/')[-1]
            else:
                entity = '@' + group
            if message_type == "text":
                # 🔁 FIX: use stored message as‑is – no extra footer added here
                full_message = message
                await client.send_message(entity, full_message, parse_mode="html")
            elif message_type == "image" and image_path and os.path.exists(image_path):
                await client.send_file(entity, image_path)
            elif message_type == "image_text" and image_path and os.path.exists(image_path):
                await client.send_file(entity, image_path, caption=message)
            # 5‑second delay after each successfully sent message
            await asyncio.sleep(3)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send to {group}: {error_msg}")

            # Account‑level fatal errors (stop everything)
            if (isinstance(e, (errors.SessionRevokedError, errors.AuthKeyUnregisteredError,
                                errors.InputUserDeactivatedError, errors.UnauthorizedError)) or
                "SESSION_REVOKED" in error_msg or "AUTH_KEY_UNREGISTERED" in error_msg):
                account_error_occurred = True
                account_error_reason = "Sessiya tugagan"
                break

            # Permanent group‑level errors – remove the group and warn user
            elif isinstance(e, (errors.ChannelPrivateError, errors.ChatWriteForbiddenError,
                                errors.UserBannedInChannelError, errors.ChatAdminRequiredError,
                                errors.MessageTooLongError, errors.FloodWaitError,
                                errors.RPCError)):  # broad Telethon base class
                # Determine a friendly reason
                if isinstance(e, errors.ChannelPrivateError):
                    reason = f"{group} – Maxfiy guruh"
                elif isinstance(e, errors.ChatWriteForbiddenError):
                    reason = f"{group} – Yozish taqiqlangan"
                elif isinstance(e, errors.UserBannedInChannelError):
                    reason = f"{group} – Bloklangan"
                elif isinstance(e, errors.ChatAdminRequiredError):
                    reason = f"{group} – Adminlik kerak"
                elif isinstance(e, errors.MessageTooLongError):
                    reason = f"{group} – Xabar juda uzun"
                elif isinstance(e, errors.FloodWaitError):
                    reason = f"{group} – Juda koʻp urinish (kutish kerak)"
                else:
                    reason = f"{group} – {error_msg[:50]}"
                groups_to_remove.append(group)
                remove_reasons.append(reason)

            # Any other exception (network, etc.) – also remove to be safe
            else:
                reason = f"{group} – {error_msg[:50]}"
                groups_to_remove.append(group)
                remove_reasons.append(reason)

            # Still wait before next attempt
            await asyncio.sleep(2)

    if account_error_occurred:
        await db.update_user(user_str, {
            "is_logged_in": 0,
            "is_active": 0,
            "user_started_required_bots": 0
        })
        if user_id in clients:
            try:
                await clients[user_id].disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting client {user_id}: {e}")
            clients.pop(user_id, None)
        if user_id in sending_tasks:
            sending_tasks[user_id].cancel()
            sending_tasks.pop(user_id, None)
        try:
            if bot_instance:
                await bot_instance.send_message(
                    chat_id=user_id,
                    text=f"❌ <b>Akkauntdan chiqarib yuborildi!</b>\n\n"
                         f"{account_error_reason}\n"
                         f"Iltimos, yangi hisob qo'shing.",
                    parse_mode='HTML',
                    reply_markup=await main_menu_keyboard(user_id)
                )
        except Exception as e:
            logger.error(f"Failed to send account error warning to {user_id}: {e}")
        return

    if groups_to_remove:
        current_groups = user.get("target_groups", [])
        updated_groups = [g for g in current_groups if g not in groups_to_remove]
        await db.update_user(user_str, {"target_groups": updated_groups})
        try:
            if bot_instance:
                if updated_groups:
                    groups_text = "\n".join([f"{i+1}. {g}" for i, g in enumerate(updated_groups)])
                    warning_msg = "⚠️ <b>Xatolik!</b>\n\n"
                    for reason in remove_reasons:
                        warning_msg += f"• {reason}\n"
                    warning_msg += f"\n📋 <b>Qolgan ({len(updated_groups)}):</b>\n{groups_text}"
                else:
                    warning_msg = "⚠️ <b>Barcha guruhlar olib tashlandi!</b>\n\n"
                    for reason in remove_reasons:
                        warning_msg += f"• {reason}\n"
                    warning_msg += f"\nYangi guruhlar qo'shing"
                    await db.update_user(user_str, {"is_active": 0})
                    if user_id in sending_tasks:
                        sending_tasks[user_id].cancel()
                        sending_tasks.pop(user_id, None)
                await bot_instance.send_message(
                    chat_id=user_id,
                    text=warning_msg,
                    parse_mode='HTML',
                    reply_markup=await main_menu_keyboard(user_id)
                )
        except Exception as e:
            logger.error(f"Error notifying group removal: {e}")

            
# --- Start command ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message with new menu"""
    user_id = update.effective_user.id
    user_str = str(user_id)
    
    # Check for referral parameter
    referral_id = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referral_id = int(arg[4:])
                if referral_id == user_id:
                    referral_id = None
            except ValueError:
                referral_id = None
    
    if not await require_channel_join(update, context):
        return
    
    username = update.effective_user.username or ''
    first_name = update.effective_user.first_name or ''
    last_name = update.effective_user.last_name or ''
    full_name = f"{first_name} {last_name}".strip()
    
    user = await db.get_user(user_str)
    is_new_user = False
    is_existing_user = user is not None
    
    if not user:
        user_data = {
            "user_id": user_str,
            "phone": "",
            "session_name": f"session_{user_id}",
            "message": "Salom!",
            "message_type": "text",
            "image_file_id": None,
            "image_path": None,
            "interval_minutes": 60,
            "target_groups": [],
            "is_logged_in": 0,
            "next_send_time": 0,
            "is_active": 0,
            "state": "menu",
            "phone_code_hash": "",
            "is_premium": 0,
            "premium_until": 0,
            "messages_sent": 0,
            "last_active": time.time(),
            "user_started_required_bots": 0,
            "current_payment_id": None,
            "session_messages_sent": 0,
            "username": username,
            "has_joined_channel": 0,
            "invited_by": str(referral_id) if referral_id else "",
            "invite_count": 0,
            "referral_discount_used": 0,
            "next_message_is_admin": 0,
            "premium_expired_notified": 0,
            "is_banned": 0,
            "total_invites": 0
        }
        await db.create_user(user_str, user_data)
        is_new_user = True
        
        if referral_id and is_existing_user:
            inviter_str = str(referral_id)
            inviter = await db.get_user(inviter_str)
            if inviter:
                try:
                    await context.bot.send_message(
                        chat_id=referral_id,
                        text=f"⚠️ Siz taklif qilgan odam ({full_name}) allaqachon botning foydalanuvchisi!"
                    )
                except:
                    pass
    else:
        if username != user.get('username', ''):
            await db.update_user(user_str, {"username": username})
    
    if is_new_user and NEW_MEMBERS_GROUP_ID:
        try:
            total_users = await db.count_users()
            username_display = f"@{username}" if username else 'yoq'
            group_message = (
                f"👤 <b>Yangi foydalanuvchi:</b>\n\n"
                f"🆔 ID: {user_id}\n"
                f"👤 Username: {username_display}\n"
                f"📛 Ism: {full_name}\n"
                f"👥 Jami: {total_users}"
            )
            if referral_id:
                inviter = await db.get_user(str(referral_id))
                inviter_username = inviter.get('username', '') if inviter else ''
                inviter_display = f"@{inviter_username}" if inviter_username else f"ID: {referral_id}"
                group_message += f"\n📢 Taklif: {inviter_display}"
            await context.bot.send_message(
                chat_id=NEW_MEMBERS_GROUP_ID,
                text=group_message,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    welcome_message = (
        "🤖 <b>Xush Kelibsiz!</b>\n\n"
        "⚡ <b>Premium:</b>\n"
        f"✅ {PREMIUM_MIN_INTERVAL} daqiqa oralik\n"
        f"✅ {PREMIUM_GROUP_LIMIT} ta guruh\n"
        f"✅ Rasm yuborish\n"
        f"✅ {PREMIUM_MESSAGE_LIMIT} xabar\n"
        f"✅ Admin xabari yo'q"
    )
    if REQUIRED_BOTS:
        welcome_message += "\n\n⚠️ <b>Majburiy botlar:</b>\n" + "\n".join(REQUIRED_BOTS)
    
    await update.message.reply_text(
        welcome_message,
        parse_mode='HTML',
        reply_markup=await main_menu_keyboard(user_id)
    )

# --- Handle contact ---
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_str = str(user_id)
    user = await db.get_user(user_str)
    if user and user.get("state") == "awaiting_phone":
        contact = update.message.contact
        if contact.user_id == user_id:
            phone = contact.phone_number
            await handle_phone(update, context, phone)
        else:
            await update.message.reply_text("❌ Iltimos, o'z raqamingizni yuboring.")

# --- Remove group command (old) ---
async def remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

# --- Handle message (main dispatcher) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages with new menu"""
    user_id = update.effective_user.id
    user_str = str(user_id)

    # Check if user is banned
    if await check_ban(update, context):
        return

    if user_id == ADMIN_ID and context.user_data.get("admin_action"):
        return
    
    if user_id == ADMIN_ID and context.user_data.get("broadcast_mode"):
        return
    
    if not update.message:
        return
    
    if update.message.text:
        text = update.message.text.strip()
        
        user = await db.get_user(user_str)
        if not user:
            await start(update, context)
            return
        
        # Check setprofit input
        if 'setprofit_type' in context.user_data:
            await handle_setprofit_input(update, context)
            return
        
        user_state = user.get("state", "menu")
        
        # Handle admin message options first
        if user_id == ADMIN_ID and context.user_data.get('admin_state'):
            admin_state = context.user_data['admin_state']
            
            if admin_state == 'admin_message_options':
                await handle_admin_message_options(update, context, text)
                return
            
            elif admin_state == 'admin_awaiting_message_type':
                if text == "📝 Matn":
                    context.user_data['admin_message_type'] = 'text'
                    context.user_data['admin_state'] = 'admin_awaiting_message'
                    await update.message.reply_text(
                        "📝 Admin xabar matnini yuboring:",
                        reply_markup=cancel_keyboard()
                    )
                elif text == "🖼️ Rasm":
                    context.user_data['admin_message_type'] = 'image'
                    context.user_data['admin_state'] = 'admin_awaiting_image'
                    await update.message.reply_text(
                        "🖼️ Admin xabar uchun rasm yuboring:",
                        reply_markup=cancel_keyboard()
                    )
                elif text == "📝+🖼️":
                    context.user_data['admin_message_type'] = 'image_text'
                    context.user_data['admin_state'] = 'admin_awaiting_image'
                    await update.message.reply_text(
                        "🖼️ Admin xabar uchun rasm yuboring:",
                        reply_markup=cancel_keyboard()
                    )
                elif text == "❌ Bekor":
                    await update.message.reply_text(
                        "❌ Bekor qilindi.",
                        reply_markup=await main_menu_keyboard(user_id)
                    )
                    context.user_data.pop('admin_state', None)
                    context.user_data.pop('admin_message_type', None)
                else:
                    await update.message.reply_text("Iltimos, tugmalardan foydalaning.")
                return
            
            elif admin_state == 'admin_awaiting_message':
                if text.lower() in ["/cancel", "❌ bekor", "cancel", "bekor"]:
                    await update.message.reply_text(
                        "❌ Bekor qilindi.",
                        reply_markup=await main_menu_keyboard(user_id)
                    )
                    context.user_data.pop('admin_state', None)
                    context.user_data.pop('admin_message_type', None)
                    return
                
                context.user_data['admin_message'] = text
                message_type = context.user_data.get('admin_message_type', 'text')
                
                if message_type == 'text':
                    await db.set_admin_message(text, message_type)
                    await update.message.reply_text(
                        f"✅ Admin xabari yangilandi!\n\n📝 {text}",
                        reply_markup=await main_menu_keyboard(user_id)
                    )
                    context.user_data.pop('admin_state', None)
                    context.user_data.pop('admin_message_type', None)
                    context.user_data.pop('admin_message', None)
                else:
                    if 'admin_image_path' in context.user_data:
                        image_path = context.user_data['admin_image_path']
                        image_file_id = context.user_data.get('admin_image_file_id')
                        await db.set_admin_message(text, message_type, image_file_id, image_path)
                        await update.message.reply_text(
                            f"✅ Admin xabari yangilandi!\n\n📝 {text}",
                            reply_markup=await main_menu_keyboard(user_id)
                        )
                        for key in ['admin_state', 'admin_message_type', 'admin_message', 'admin_image_path', 'admin_image_file_id']:
                            context.user_data.pop(key, None)
                    else:
                        await update.message.reply_text("❌ Rasm topilmadi. Qaytadan boshlang.")
                        context.user_data.clear()
                return
        
        # Handle user states
        if user_state == "awaiting_phone":
            await handle_phone(update, context, text)
        elif user_state == "awaiting_code":
            await handle_code(update, context, text)
        elif user_state == "awaiting_password":
            await handle_password(update, context, text)
        elif user_state == "awaiting_message_type":
            await handle_message_type(update, context, text)
        elif user_state == "awaiting_message":
            await handle_new_message(update, context, text)
        elif user_state == "awaiting_interval":
            await handle_new_interval(update, context, text)
        elif user_state == "awaiting_groups":
            await handle_new_groups(update, context, text)
        elif user_state == "awaiting_account_change_confirmation":
            await handle_account_change_confirmation(update, context, text)
        elif user_state == "awaiting_payment_screenshot":
            if text == "❌ Bekor":
                await cancel(update, context)
                return
            else:
                await update.message.reply_text(
                    "❌ Skrinshot yuboring yoki '❌ Bekor' tugmasini bosing!",
                    reply_markup=cancel_keyboard()
                )
                return
        elif user_state == "awaiting_manual_interval":
            await handle_manual_interval(update, context, text)
        # New menu buttons
        elif text == "👤 Profil":
            await profil_command(update, context)
        elif text == "⚙️ Sozlamalar":
            await settings_command(update, context)
        elif text == "📊 Statistika":
            await statistika_command(update, context)
        elif text == "▶️ Yuborishni boshlash":
            await start_sending(update, context)
        elif text == "⏹️ To'xtatish":
            await stop_sending(update, context)
        # Settings submenu buttons
        elif text == "✏️ Xabar":
            await change_message(update, context)
        elif text == "⏰ Interval":
            await change_interval(update, context)
        elif text == "👥 Guruhlar":
            await change_groups(update, context)
        elif text == "🔙 Ortga":
            await back_to_main(update, context)
        # Message type buttons (handled in state)
        elif text in ["📝 Matn", "🖼️ Rasm", "📝+🖼️", "❌ Bekor"]:
            await handle_message_type(update, context, text)
        # If user in menu and text not recognized
        elif user_state == "menu":
            await update.message.reply_text(
                "Menyu tugmalaridan foydalaning:",
                reply_markup=await main_menu_keyboard(user_id)
            )
    
    # Handle photo
    elif update.message.photo:
        user = await db.get_user(user_str)
        user_state = user.get("state", "menu") if user else "menu"
        if user_id == ADMIN_ID and context.user_data.get('admin_state') == 'admin_awaiting_image':
            # Handle admin image upload (same as before)
            photo = update.message.photo[-1]
            file_id = photo.file_id
            file_size = photo.file_size or 0
            if file_size > IMAGE_SIZE_LIMIT:
                size_mb = file_size / (1024 * 1024)
                await update.message.reply_text(
                    f"❌ Rasm hajmi 5 MB dan katta! ({size_mb:.2f} MB)",
                    reply_markup=cancel_keyboard()
                )
                return
            file = await context.bot.get_file(file_id)
            if file.file_size and file.file_size > IMAGE_SIZE_LIMIT:
                size_mb = file.file_size / (1024 * 1024)
                await update.message.reply_text(
                    f"❌ Rasm hajmi 5 MB dan katta! ({size_mb:.2f} MB)",
                    reply_markup=cancel_keyboard()
                )
                return
            Path(ADMIN_IMAGE_DIR).mkdir(exist_ok=True, parents=True)
            old_admin_message = await db.get_admin_message()
            if old_admin_message and old_admin_message.get('image_path'):
                old_image_path = old_admin_message['image_path']
                if os.path.exists(old_image_path):
                    try:
                        os.remove(old_image_path)
                    except:
                        pass
            timestamp = int(time.time())
            image_path = os.path.join(ADMIN_IMAGE_DIR, f"admin_image_{timestamp}.jpg")
            try:
                await file.download_to_drive(image_path)
                context.user_data['admin_image_file_id'] = file_id
                context.user_data['admin_image_path'] = image_path
                message_type = context.user_data.get('admin_message_type', 'image')
                if message_type == 'image':
                    await db.set_admin_message('', message_type, file_id, image_path)
                    await update.message.reply_text(
                        "✅ Admin xabari yangilandi! (Rasm)",
                        reply_markup=await main_menu_keyboard(user_id)
                    )
                    context.user_data.clear()
                elif message_type == 'image_text':
                    context.user_data['admin_state'] = 'admin_awaiting_message'
                    await update.message.reply_text(
                        "✅ Rasm saqlandi! Endi matn yuboring:",
                        reply_markup=cancel_keyboard()
                    )
            except Exception as e:
                logger.error(f"Error: {e}")
                await update.message.reply_text(
                    f"❌ Xato\n{type(e).__name__}",
                    reply_markup=cancel_keyboard()
                )
            return
        elif user_state == "awaiting_image":
            await handle_new_image(update, context)
        elif user_state == "awaiting_payment_screenshot":
            await handle_payment_screenshot(update, context)
    
    # Handle document
    elif update.message.document:
        user = await db.get_user(user_str)
        user_state = user.get("state", "menu") if user else "menu"
        mime_type = update.message.document.mime_type
        if mime_type and 'image' in mime_type:
            if user_state == "awaiting_image":
                await handle_new_image(update, context)
            elif user_state == "awaiting_payment_screenshot":
                await handle_payment_screenshot(update, context)
        elif user_id == ADMIN_ID and context.user_data.get('admin_state') == 'admin_awaiting_image':
            # Admin document image (same as before)
            document = update.message.document
            file_id = document.file_id
            file_size = document.file_size or 0
            if file_size > IMAGE_SIZE_LIMIT:
                size_mb = file_size / (1024 * 1024)
                await update.message.reply_text(
                    f"❌ Rasm hajmi 5 MB dan katta! ({size_mb:.2f} MB)",
                    reply_markup=cancel_keyboard()
                )
                return
            file = await context.bot.get_file(file_id)
            if file.file_size and file.file_size > IMAGE_SIZE_LIMIT:
                size_mb = file.file_size / (1024 * 1024)
                await update.message.reply_text(
                    f"❌ Rasm hajmi 5 MB dan katta! ({size_mb:.2f} MB)",
                    reply_markup=cancel_keyboard()
                )
                return
            Path(ADMIN_IMAGE_DIR).mkdir(exist_ok=True, parents=True)
            old_admin_message = await db.get_admin_message()
            if old_admin_message and old_admin_message.get('image_path'):
                old_image_path = old_admin_message['image_path']
                if os.path.exists(old_image_path):
                    try:
                        os.remove(old_image_path)
                    except:
                        pass
            timestamp = int(time.time())
            image_path = os.path.join(ADMIN_IMAGE_DIR, f"admin_image_{timestamp}.jpg")
            try:
                await file.download_to_drive(image_path)
                context.user_data['admin_image_file_id'] = file_id
                context.user_data['admin_image_path'] = image_path
                message_type = context.user_data.get('admin_message_type', 'image')
                if message_type == 'image':
                    await db.set_admin_message('', message_type, file_id, image_path)
                    await update.message.reply_text(
                        "✅ Admin xabari yangilandi! (Rasm)",
                        reply_markup=await main_menu_keyboard(user_id)
                    )
                    context.user_data.clear()
                elif message_type == 'image_text':
                    context.user_data['admin_state'] = 'admin_awaiting_message'
                    await update.message.reply_text(
                        "✅ Rasm saqlandi! Endi matn yuboring:",
                        reply_markup=cancel_keyboard()
                    )
            except Exception as e:
                logger.error(f"Error: {e}")
                await update.message.reply_text(
                    f"❌ Xato\n{type(e).__name__}",
                    reply_markup=cancel_keyboard()
                )
            return

# --- Post init and stop ---
async def post_init(application: Application):
    global stats_update_task
    await notify_active_users_on_restart(application)
    stats_update_task = asyncio.create_task(stats_channel_updater(application))
    logger.info("Bot started and active users restarted")

async def notify_active_users_on_restart(application: Application):
    active_users = await db.get_active_users()
    for user in active_users:
        user_id = int(user['user_id'])
        user_str = str(user_id)
        if user_id in sending_tasks:
            sending_tasks[user_id].cancel()
            sending_tasks.pop(user_id, None)
        is_premium = await check_premium_status(user_str)
        interval = user.get("interval_minutes", 60)
        min_interval = PREMIUM_MIN_INTERVAL if is_premium else NON_PREMIUM_MIN_INTERVAL
        new_interval = max(min_interval, min(interval, MAX_INTERVAL))
        if new_interval != interval:
            await db.update_user(user_str, {"interval_minutes": new_interval})
            interval = new_interval
        if not is_premium and user.get("message_type") in ["image", "image_text"]:
            await downgrade_user_from_premium(user_str)
        await db.update_user(user_str, {
            "is_active": 1,
            "session_messages_sent": 0,
            "next_message_is_admin": 0
        })
        next_send_time = time.time() + (interval * 60)
        await db.update_user(user_str, {"next_send_time": next_send_time})
        sending_tasks[user_id] = asyncio.create_task(send_scheduled_messages(user_id))
        try:
            await application.bot.send_message(
                chat_id=user_id,
                text="🔄 <b>Bot yangilandi!</b>\n\n"
                     "Yuborish qayta boshlanadi.",
                parse_mode='HTML',
                reply_markup=await main_menu_keyboard(user_id)
            )
            logger.info(f"Restarted sending for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")

async def post_stop(application: Application):
    global stats_update_task
    if stats_update_task:
        stats_update_task.cancel()
        try:
            await stats_update_task
        except:
            pass

def main():
    print("Starting bot...")
    application = Application.builder() \
        .token(BOT_TOKEN) \
        .post_init(post_init) \
        .post_stop(post_stop) \
        .build()
    global bot_instance
    bot_instance = application.bot

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("referral", referral_command))  # Backward compatibility
    application.add_handler(CommandHandler("adminhelp", adminhelp_command))
    application.add_handler(CommandHandler("profit", profit_command))
    application.add_handler(CommandHandler("setprofit", set_profit_command))
    application.add_handler(CommandHandler("see", see_user_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("cancel_broadcast", cancel_broadcast_command))
    application.add_handler(CommandHandler("addprem", add_premium_admin))
    application.add_handler(CommandHandler("removeprem", remove_premium_admin))
    application.add_handler(CommandHandler("premusers", list_premium_users))
    application.add_handler(CommandHandler("pending", pending_payments_command))
    application.add_handler(CommandHandler("remove", remove_group))  # Kept for compatibility
    application.add_handler(CommandHandler("entered", entered_command))
    application.add_handler(CommandHandler("active", active_command))
    application.add_handler(CommandHandler("setadmsg", set_admin_message_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("banned", banned_command))
    application.add_handler(CommandHandler("reset", reset_user_command))
    application.add_handler(CommandHandler("delete", delete_user_command))

    # Payment handlers
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # Callback query handlers
    application.add_handler(CallbackQueryHandler(buy_premium_stars_callback, pattern="^buy_premium_stars$"))
    application.add_handler(CallbackQueryHandler(buy_premium_money_callback, pattern="^buy_premium_money_"))
    application.add_handler(CallbackQueryHandler(handle_admin_payment_action, pattern="^(confirm_|cancel_|insufficient_)"))
    application.add_handler(CallbackQueryHandler(handle_send_screenshot_callback, pattern="^send_screenshot_"))
    application.add_handler(CallbackQueryHandler(check_channel_join_callback, pattern="^check_channel_join$"))
    application.add_handler(CallbackQueryHandler(set_profit_callback, pattern="^setprofit_"))
    # New profile callbacks
    application.add_handler(CallbackQueryHandler(profile_connect_callback, pattern="^profile_connect$"))
    application.add_handler(CallbackQueryHandler(profile_referral_callback, pattern="^profile_referral$"))
    application.add_handler(CallbackQueryHandler(profile_premium_callback, pattern="^profile_premium$"))
    application.add_handler(CallbackQueryHandler(profile_disconnect_callback, pattern="^profile_disconnect$"))

    # Interval callbacks
    application.add_handler(
        CallbackQueryHandler(
            interval_callback,
            pattern=r"^(set_interval_\d+|interval_cancel)$"
        )
    )
    application.add_handler(CallbackQueryHandler(interval_manual_callback, pattern="^set_interval_manual$"))

    # Group selection callbacks (including clear)
    application.add_handler(
        CallbackQueryHandler(
            group_selection_callback,
            pattern=r"^(group_select_.*|group_page_.*|group_confirm|group_close|group_clear_all)$"
        )
    )

    # Admin handlers
    admin_filter = filters.User(ADMIN_ID)
    application.add_handler(MessageHandler(
        admin_filter & filters.TEXT & ~filters.COMMAND,
        handle_admin_text_input
    ), group=1)
    application.add_handler(MessageHandler(
        admin_filter & (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
        handle_broadcast_message
    ), group=1)

    # User handlers
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_message), group=2)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_message), group=2)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL, handle_message), group=2)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.CONTACT, handle_contact), group=2)

    logger.info("Bot starting...")
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except Conflict:
        logger.error("Another bot is running!")
        print("\n❌ ERROR: Another bot is running!")
    except Exception as e:
        logger.error(f"Error: {e}")
        print(f"\n❌ Error: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    main()
