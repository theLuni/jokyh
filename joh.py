#!/usr/bin/env python3
# -<b>- coding: utf-8 -</b>-
"""
╔══════════════════════════════════════════════════════════════════╗
║                    JokyHost — Telegram Bot                       ║
║              Хостинг Heroku Userbot (coddrago)                   ║
║                      v4.0 — Premium Style                        ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import sqlite3
import subprocess
import json
import random
import shutil
import os
import html
import re
import time
import threading
import ssl
import math
import uuid
import aiohttp

from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta
from pytz import timezone

from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.types import TelegramObject
from collections import defaultdict
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
    ChosenInlineResult
)
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from flask import Flask, request, jsonify, render_template_string
from functools import wraps

# ═══════════════════════════════════════════════════════════════════
#                           КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════════
BOT_TOKEN        = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN.")
ADMIN_ID         = int(os.getenv("ADMIN_ID", "5929120983"))
ADMIN_CONTACT    = os.getenv("ADMIN_CONTACT", "@theLunatik")
CHANNEL_REQUIRED = os.getenv("CHANNEL_REQUIRED", "@JokyHub")
TERMS_LINK       = os.getenv("TERMS_LINK", "https://github.com/theLuni/JokyHost/blob/main/README.md")
SERVER_IP        = os.getenv("SERVER_IP", "202.181.188.91")
PRICE_PER_MONTH  = int(os.getenv("PRICE_PER_MONTH", "50"))

def ym_total(amount: int) -> int:
    """Сумма к оплате с учётом комиссии ЮMани 3% (мин. 1 ₽ для целых чисел)."""
    commission = max(1, round(amount * 0.03))
    return amount + commission

def make_payment_link(user_id: int, amount: int) -> tuple[str, str]:
    """Генерирует уникальную ЮMани-ссылку. Возвращает (proxy_url, label)."""
    from yoomoney import Quickpay
    label = str(uuid.uuid4())
    total = ym_total(amount)
    qp = Quickpay(
        receiver=YOOMONEY_WALLET,
        quickpay_form="button",
        targets=f"JokyHost | tg:{user_id}",
        paymentType="AC",
        sum=total,
        label=label,
    )
    # Сохраняем реальную ссылку, отдаём прокси-URL без параметров
    _pay_links[label] = qp.base_url
    proxy_url = f"https://{AUTH_DOMAIN}:{AUTH_PORT}/pay/{label}"
    return proxy_url, label

def check_payment_yoomoney(label: str, amount: int) -> bool:
    """Синхронная проверка оплаты через YooMoney API по уникальному label."""
    from yoomoney import Client
    if not YOOMONEY_TOKEN:
        log.error("[YM] YOOMONEY_TOKEN не задан! Установите переменную окружения.")
        return False
    log.info(f"[YM] Проверка | label={label!r} | amount={amount}")
    try:
        client = Client(token=YOOMONEY_TOKEN)
        history = client.operation_history(label=label, records=10)
        ops = history.operations
        if not ops:
            log.warning(f"[YM] Операций не найдено | label={label!r}")
            return False
        for op in ops:
            op_label  = getattr(op, "label",  None)
            op_status = getattr(op, "status", None)
            op_amount = float(getattr(op, "amount", 0))
            op_id     = getattr(op, "operation_id", "N/A")
            log.info(f"[YM] op={op_id} label={op_label!r} status={op_status} amount={op_amount}")
            if op_label != label:
                continue
            if op_status != "success":
                log.warning(f"[YM] Статус не success: {op_status!r}")
                continue
            log.info(f"[YM] ✅ Оплата подтверждена | op_id={op_id} | amount={op_amount}")
            return True
        log.warning(f"[YM] ❌ Не прошла проверку | label={label!r}")
    except Exception as e:
        log.exception(f"[YM] Ошибка: {e}")
    return False

REVIEWS_CHANNEL  = int(os.getenv("REVIEWS_CHANNEL", "-1003836802028"))

# Канал статуса сервера (сообщение обновляется каждые 5 минут)
STATUS_CHANNEL_ID  = int(os.getenv("STATUS_CHANNEL_ID",  "-1003836802028"))
STATUS_MESSAGE_ID  = int(os.getenv("STATUS_MESSAGE_ID",  "250"))
STATUS_THREAD_ID   = int(os.getenv("STATUS_THREAD_ID",   "204"))
REVIEWS_THREAD_ID  = int(os.getenv("REVIEWS_THREAD_ID",  "205"))

CPU_LIMIT        = "1"
MEMORY_LIMIT     = "650m"

# ЮMани
YOOMONEY_TOKEN  = os.getenv("YOOMONEY_TOKEN", "")
YOOMONEY_SECRET = os.getenv("YOOMONEY_SECRET", "")  # notification_secret из настроек приложения
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "4100119099824546")

# Локальный API-сервер для AI-диагностики логов (как в akari.py)
LOCAL_API_URL   = os.getenv("LOCAL_API_URL",   "http://localhost:9998")
LOCAL_API_TOKEN = os.getenv("LOCAL_API_TOKEN", "pomogator_groq_proxy_secret_token_2024")
LOCAL_API_MODEL = os.getenv("LOCAL_API_MODEL", "gpt-4o")

AUTH_DOMAIN      = os.getenv("AUTH_DOMAIN", "ub.theluni.ru")
AUTH_PORT        = int(os.getenv("AUTH_PORT", "3443"))

FLASK_SECRET     = os.getenv("FLASK_SECRET", "")
if not FLASK_SECRET:
    import secrets as _secrets
    FLASK_SECRET = _secrets.token_hex(32)
    log_placeholder = logging.getLogger("jokyhost_init")
    log_placeholder.warning("FLASK_SECRET не задан — сгенерирован случайный. Установите переменную окружения FLASK_SECRET для стабильной работы.")

BASE_USERS_DIR   = Path(os.getenv("BASE_USERS_DIR", "/home/users"))
GIT_REPO_URL     = "https://github.com/coddrago/Heroku"
TEMP_REPO_DIR    = "/tmp/heroku_repo_cache"
DB_PATH          = "jokyhost.db"
SCREENSHOTS_DIR  = Path("screenshots")

MSK = timezone("Europe/Moscow")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
log = logging.getLogger("jokyhost")

# ═══════════════════════════════════════════════════════════════════
#                         ИНИЦИАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════════════
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = Flask(__name__)

pending_creation: Dict[int, dict] = {}
pending_telethon: Dict[int, dict] = {}
pending_relogin: Dict[int, dict] = {}
relogin_in_progress: set = set()  # uid пользователей, проходящих релогин

# Кэш проверки подписки: uid -> (is_member: bool, expires: float)
_subscribe_cache: dict[int, tuple[bool, float]] = {}
_SUBSCRIBE_CACHE_TTL = 60.0  # секунд

# ═══════════════════════════════════════════════════════════════════
#                   MIDDLEWARE: ПРОВЕРКА ПОДПИСКИ НА КАНАЛ
# ═══════════════════════════════════════════════════════════════════
# Пропускаем только /start и проверку подписки — всё остальное блокируем
_CHANNEL_WHITELIST_COMMANDS = {"/start"}
_CHANNEL_WHITELIST_CALLBACKS = {"check_subscribe"}

class ChannelSubscriptionMiddleware(BaseMiddleware):
    """
    Блокирует весь функционал бота для пользователей,
    не подписанных на обязательный канал.
    Проверка идёт через Telegram API (не только БД) —
    то есть даже если пользователь отписался после регистрации.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        msg  = getattr(event, "message",       None)
        cq   = getattr(event, "callback_query", None)
        iq   = getattr(event, "inline_query",   None)

        user = None
        if msg:  user = msg.from_user
        elif cq: user = cq.from_user
        elif iq: user = iq.from_user

        if not user:
            return await handler(event, data)

        uid = user.id
        if uid == ADMIN_ID:
            return await handler(event, data)

        # Пропускаем /start (с любым аргументом) и кнопку "Я подписался"
        if msg and msg.text:
            cmd = msg.text.split()[0].split("@")[0].lower()
            if cmd in _CHANNEL_WHITELIST_COMMANDS:
                return await handler(event, data)

        if cq and cq.data in _CHANNEL_WHITELIST_CALLBACKS:
            # Принудительно сбрасываем кэш при нажатии "Я подписался"
            _subscribe_cache.pop(uid, None)
            return await handler(event, data)

        # Проверяем подписку через кэш (TTL 60 сек), потом Telegram API
        now_t = time.monotonic()
        cached = _subscribe_cache.get(uid)
        if cached and now_t < cached[1]:
            is_member = cached[0]
        else:
            try:
                member = await bot.get_chat_member(CHANNEL_REQUIRED, uid)
                is_member = member.status not in ("left", "kicked", "banned")
            except Exception:
                is_member = False
            _subscribe_cache[uid] = (is_member, now_t + _SUBSCRIBE_CACHE_TTL)
            # Периодически чистим устаревшие записи кэша
            if len(_subscribe_cache) > 10000:
                expired = [k for k, v in _subscribe_cache.items() if now_t > v[1]]
                for k in expired:
                    _subscribe_cache.pop(k, None)

        if is_member:
            # Обновляем статус в БД если нужно
            ensure_user(user)
            u = get_user(uid)
            if u and not u["subscribed"]:
                set_subscribed(uid)
            return await handler(event, data)

        # Пользователь НЕ подписан — показываем заглушку
        channel_name = CHANNEL_REQUIRED.lstrip("@")
        block_text = (
            f"🔒 <b>Доступ ограничен</b>\n\n"
            f"<blockquote>Для использования бота необходимо быть подписчиком канала <b>{CHANNEL_REQUIRED}</b>.</blockquote>\n\n"
            "Подпишитесь на канал и нажмите «✅ Я подписался» 👇"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"📢 Подписаться на {CHANNEL_REQUIRED}",
                url=f"https://t.me/{channel_name}"
            )],
            [InlineKeyboardButton(
                text="✅ Я подписался",
                callback_data="check_subscribe"
            )],
        ])

        if cq:
            try:
                await cq.answer(
                    f"🔒 Подпишитесь на {CHANNEL_REQUIRED}, чтобы продолжить!",
                    show_alert=True
                )
            except Exception:
                pass
            try:
                await cq.message.edit_text(
                    block_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb
                )
            except Exception:
                try:
                    await bot.send_message(uid, block_text, parse_mode=ParseMode.HTML, reply_markup=kb)
                except Exception:
                    pass
        elif msg:
            try:
                await msg.answer(block_text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception:
                pass
        # Не передаём событие дальше
        return

_channel_check = ChannelSubscriptionMiddleware()

# ═══════════════════════════════════════════════════════════════════
#               MIDDLEWARE: АНТИСПАМ (КД на сообщения/кнопки)
# ═══════════════════════════════════════════════════════════════════
ANTISPAM_COOLDOWN    = 0.75  # секунд между сообщениями
ANTISPAM_CB_COOLDOWN = 0.75  # секунд между нажатиями кнопок

_antispam_last: dict[int, float] = {}    # uid -> timestamp последнего сообщения
_antispam_cb_last: dict[int, float] = {} # uid -> timestamp последнего callback


class AntiSpamMiddleware(BaseMiddleware):
    """
    Блокирует слишком частые запросы от одного пользователя.
    Сообщения и кнопки: не чаще 1 раза в 0.75 сек.
    Уведомление — только toast (show_alert=False), без сообщений в чат.
    Администратор не ограничен.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        msg = getattr(event, "message",       None)
        cq  = getattr(event, "callback_query", None)

        user = None
        if msg:  user = msg.from_user
        elif cq: user = cq.from_user

        if not user:
            return await handler(event, data)

        uid = user.id
        if uid == ADMIN_ID:
            return await handler(event, data)

        now = time.monotonic()

        if cq:
            last = _antispam_cb_last.get(uid, 0.0)
            if now - last < ANTISPAM_CB_COOLDOWN:
                try:
                    await cq.answer("⏳ Не так быстро!", show_alert=False)
                except Exception:
                    pass
                return
            _antispam_cb_last[uid] = now
            # Чистим устаревшие записи антиспама
            if len(_antispam_cb_last) > 10000:
                cutoff = now - 60.0
                stale = [k for k, v in _antispam_cb_last.items() if v < cutoff]
                for k in stale:
                    _antispam_cb_last.pop(k, None)

        elif msg:
            last = _antispam_last.get(uid, 0.0)
            if now - last < ANTISPAM_COOLDOWN:
                # Для сообщений toast недоступен — просто игнорируем молча
                return
            _antispam_last[uid] = now
            # Чистим устаревшие записи антиспама
            if len(_antispam_last) > 10000:
                cutoff = now - 60.0
                stale = [k for k, v in _antispam_last.items() if v < cutoff]
                for k in stale:
                    _antispam_last.pop(k, None)

        return await handler(event, data)


_antispam = AntiSpamMiddleware()

# ═══════════════════════════════════════════════════════════════════
_local = threading.local()

def db_connect():
    """Возвращает соединение из thread-local пула (1 соединение на поток)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")    # параллельные чтения
        conn.execute("PRAGMA synchronous=NORMAL")  # баланс скорость/надёжность
        conn.execute("PRAGMA cache_size=-8000")    # 8 MB кэш
        conn.execute("PRAGMA temp_store=MEMORY")
        _local.conn = conn
    return conn

def migrate_db():
    """Безопасная миграция: добавляем все недостающие колонки не ломая существующие данные"""
    migrations = [
        "ALTER TABLE reviews ADD COLUMN stars INTEGER DEFAULT 5",
        "ALTER TABLE reviews ADD COLUMN full_name TEXT DEFAULT ''",
        "ALTER TABLE reviews ADD COLUMN username TEXT DEFAULT ''",
        "ALTER TABLE reviews ADD COLUMN text TEXT DEFAULT ''",
        "ALTER TABLE reviews ADD COLUMN admin_msg_id INTEGER DEFAULT 0",
        "ALTER TABLE reviews ADD COLUMN msg_id INTEGER DEFAULT 0",
        "ALTER TABLE reviews ADD COLUMN status TEXT DEFAULT 'pending'",
        "ALTER TABLE reviews ADD COLUMN created_at TEXT",
        "ALTER TABLE users ADD COLUMN hosting_created INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN subscribed_at TEXT",
        "ALTER TABLE referrals ADD COLUMN bonus_granted INTEGER DEFAULT 0",
    ]
    with db_connect() as conn:
        for sql in migrations:
            try:
                conn.execute(sql)
                log.info(f"Migration OK: {sql[:70]}")
            except sqlite3.OperationalError:
                pass  # колонка уже есть — нормально

def init_db():
    with db_connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        INTEGER PRIMARY KEY,
                username       TEXT,
                full_name      TEXT,
                subscribed     INTEGER DEFAULT 0,
                terms_accepted INTEGER DEFAULT 0,
                balance        INTEGER DEFAULT 0,
                hosting_created INTEGER DEFAULT 0,
                created_at     TEXT,
                subscribed_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS hosting (
                user_id    INTEGER PRIMARY KEY,
                port       INTEGER,
                status     TEXT DEFAULT 'active',
                created_at TEXT,
                expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS payments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER,
                amount          INTEGER,
                months          INTEGER,
                screenshot_path TEXT,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS warnings_sent (
                user_id      INTEGER,
                warning_type TEXT,
                sent_at      TEXT,
                PRIMARY KEY (user_id, warning_type)
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                username    TEXT,
                full_name   TEXT,
                text        TEXT,
                stars       INTEGER DEFAULT 5,
                status      TEXT DEFAULT 'pending',
                msg_id      INTEGER,
                admin_msg_id INTEGER,
                created_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS server_sharing (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id    INTEGER NOT NULL,
                shared_uid  INTEGER NOT NULL,
                created_at  TEXT,
                UNIQUE(owner_id, shared_uid)
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id   INTEGER NOT NULL,
                referred_id   INTEGER NOT NULL UNIQUE,
                bonus_granted INTEGER DEFAULT 0,
                created_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS pending_flows (
                user_id    INTEGER PRIMARY KEY,
                flow_type  TEXT NOT NULL,
                data_json  TEXT DEFAULT '{}',
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)
    
    # Выполняем миграцию для существующей базы
    migrate_db()

def db_get_setting(key: str, default: str = None) -> Optional[str]:
    """Читает значение из таблицы bot_settings."""
    with db_connect() as conn:
        row = conn.execute("SELECT value FROM bot_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

def db_set_setting(key: str, value: str):
    """Сохраняет значение в таблице bot_settings."""
    with db_connect() as conn:
        conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?,?)", (key, value))


def db_save_flow(user_id: int, flow_type: str, data: dict):
    """Сохраняет текущий flow пользователя в БД (переживает перезапуск)."""
    with db_connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO pending_flows (user_id, flow_type, data_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, flow_type, json.dumps(data), datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")))

def db_get_flow(user_id: int) -> Optional[dict]:
    """Возвращает сохранённый flow или None."""
    with db_connect() as conn:
        row = conn.execute("SELECT flow_type, data_json FROM pending_flows WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    try:
        return {"flow_type": row["flow_type"], **json.loads(row["data_json"])}
    except Exception:
        return {"flow_type": row["flow_type"]}

def db_clear_flow(user_id: int):
    """Удаляет flow пользователя из БД."""
    with db_connect() as conn:
        conn.execute("DELETE FROM pending_flows WHERE user_id = ?", (user_id,))

init_db()

def ensure_user(user: types.User):
    with db_connect() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
        """, (user.id, user.username, user.full_name,
              datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")))

def get_user(user_id: int) -> Optional[sqlite3.Row]:
    with db_connect() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def set_subscribed(user_id: int):
    with db_connect() as conn:
        conn.execute("""
            UPDATE users SET subscribed = 1, subscribed_at = ? WHERE user_id = ?
        """, (datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"), user_id))

def set_terms_accepted(user_id: int):
    with db_connect() as conn:
        conn.execute("UPDATE users SET terms_accepted = 1 WHERE user_id = ?", (user_id,))

def get_balance(user_id: int) -> int:
    row = get_user(user_id)
    return row["balance"] if row else 0

def add_balance(user_id: int, amount: int):
    with db_connect() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))

def subtract_balance(user_id: int, amount: int) -> bool:
    with db_connect() as conn:
        row = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and row["balance"] >= amount:
            conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            return True
    return False

def user_has_hosting(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["hosting_created"])

def get_hosting(user_id: int) -> Optional[sqlite3.Row]:
    with db_connect() as conn:
        return conn.execute("SELECT * FROM hosting WHERE user_id = ?", (user_id,)).fetchone()

def save_hosting(user_id: int, port: int, months: float = 1, days: int = None):
    if days is None:
        days = round(months * 30)
    expires_at = (datetime.now(MSK) + timedelta(days=days)).strftime("%Y-%m-%d")
    now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
    with db_connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO hosting (user_id, port, status, created_at, expires_at)
            VALUES (?, ?, 'active', ?, ?)
        """, (user_id, port, now, expires_at))
        conn.execute("""
            UPDATE users SET hosting_created = 1, created_at = ? WHERE user_id = ?
        """, (now, user_id))

def delete_hosting(user_id: int):
    with db_connect() as conn:
        conn.execute("DELETE FROM hosting WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE users SET hosting_created = 0 WHERE user_id = ?", (user_id,))

def annihilate_user_data(user_id: int):
    """Полное удаление всех данных пользователя из БД (аннигиляция)."""
    with db_connect() as conn:
        conn.execute("DELETE FROM hosting         WHERE user_id = ?",        (user_id,))
        conn.execute("DELETE FROM payments        WHERE user_id = ?",        (user_id,))
        conn.execute("DELETE FROM warnings_sent   WHERE user_id = ?",        (user_id,))
        conn.execute("DELETE FROM reviews         WHERE user_id = ?",        (user_id,))
        conn.execute("DELETE FROM server_sharing  WHERE owner_id = ? OR shared_uid = ?", (user_id, user_id))
        conn.execute("DELETE FROM referrals       WHERE referrer_id = ? OR referred_id = ?", (user_id, user_id))
        conn.execute("DELETE FROM users           WHERE user_id = ?",        (user_id,))
    log.info(f"[ANNIHILATE] All DB data removed for user {user_id}")

def update_hosting_expiry(user_id: int, new_expires_at: str):
    with db_connect() as conn:
        conn.execute("""
            UPDATE hosting SET expires_at = ?, status = 'active' WHERE user_id = ?
        """, (new_expires_at, user_id))

def extend_hosting(user_id: int, months: float = None, days: int = None) -> bool:
    h = get_hosting(user_id)
    if not h:
        return False
    if days is None:
        days = round((months or 1) * 30)
    try:
        base = datetime.strptime(h["expires_at"], "%Y-%m-%d").date()
        today = datetime.now(MSK).date()
        if base < today:
            base = today
        new_exp = (datetime.combine(base, datetime.min.time()) + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        new_exp = (datetime.now(MSK) + timedelta(days=days)).strftime("%Y-%m-%d")
    update_hosting_expiry(user_id, new_exp)
    return True

def get_all_hostings():
    with db_connect() as conn:
        return conn.execute("SELECT * FROM hosting ORDER BY created_at DESC").fetchall()

def create_payment(user_id: int, amount: int, months: int, screenshot_path: str = "") -> int:
    now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
    with db_connect() as conn:
        cur = conn.execute("""
            INSERT INTO payments (user_id, amount, months, screenshot_path, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
        """, (user_id, amount, months, screenshot_path, now))
        return cur.lastrowid

def get_pending_payments():
    with db_connect() as conn:
        return conn.execute("""
            SELECT * FROM payments WHERE status = 'pending' ORDER BY created_at DESC
        """).fetchall()

def approve_payment(payment_id: int) -> Optional[sqlite3.Row]:
    with db_connect() as conn:
        pay = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if pay:
            conn.execute("UPDATE payments SET status = 'approved' WHERE id = ?", (payment_id,))
        return pay

def reject_payment(payment_id: int) -> Optional[sqlite3.Row]:
    with db_connect() as conn:
        pay = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if pay:
            conn.execute("UPDATE payments SET status = 'rejected' WHERE id = ?", (payment_id,))
        return pay

def get_payment_history(user_id: int):
    with db_connect() as conn:
        return conn.execute("""
            SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC LIMIT 10
        """, (user_id,)).fetchall()

def was_warning_sent(user_id: int, wtype: str) -> bool:
    with db_connect() as conn:
        row = conn.execute("""
            SELECT 1 FROM warnings_sent WHERE user_id = ? AND warning_type = ?
        """, (user_id, wtype)).fetchone()
        return row is not None

def save_warning_sent(user_id: int, wtype: str):
    with db_connect() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO warnings_sent (user_id, warning_type, sent_at)
            VALUES (?, ?, ?)
        """, (user_id, wtype, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")))

def clear_warnings(user_id: int):
    with db_connect() as conn:
        conn.execute("DELETE FROM warnings_sent WHERE user_id = ?", (user_id,))

def get_stats():
    with db_connect() as conn:
        total_users    = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_hostings = conn.execute("SELECT COUNT(*) FROM hosting").fetchone()[0]
        active_hostings = conn.execute("SELECT COUNT(*) FROM hosting WHERE status = 'active'").fetchone()[0]
        pending        = conn.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'").fetchone()[0]
        revenue        = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'approved'").fetchone()[0]
    return total_users, total_hostings, active_hostings, pending, revenue

# ═══════════════════════════════════════════════════════════════════
#                     ФУНКЦИИ ОТЗЫВОВ
# ═══════════════════════════════════════════════════════════════════
def create_review(user_id: int, username: str, full_name: str, text: str, stars: int, msg_id: int, admin_msg_id: int) -> int:
    now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
    with db_connect() as conn:
        cur = conn.execute("""
            INSERT INTO reviews (user_id, username, full_name, text, stars, status, msg_id, admin_msg_id, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """, (user_id, username, full_name, text, stars, msg_id, admin_msg_id, now))
        return cur.lastrowid

def get_review(review_id: int) -> Optional[sqlite3.Row]:
    with db_connect() as conn:
        return conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()

def approve_review(review_id: int):
    with db_connect() as conn:
        conn.execute("UPDATE reviews SET status = 'approved' WHERE id = ?", (review_id,))

def reject_review(review_id: int):
    with db_connect() as conn:
        conn.execute("UPDATE reviews SET status = 'rejected' WHERE id = ?", (review_id,))

# ═══════════════════════════════════════════════════════════════════
#                     ФУНКЦИИ ШАРИНГА СЕРВЕРОВ
# ═══════════════════════════════════════════════════════════════════
def add_shared_access(owner_id: int, shared_uid: int) -> bool:
    try:
        now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
        with db_connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO server_sharing (owner_id, shared_uid, created_at)
                VALUES (?, ?, ?)
            """, (owner_id, shared_uid, now))
        return True
    except Exception as e:
        log.error(f"add_shared_access error: {e}")
        return False

def remove_shared_access(owner_id: int, shared_uid: int) -> bool:
    with db_connect() as conn:
        conn.execute(
            "DELETE FROM server_sharing WHERE owner_id = ? AND shared_uid = ?",
            (owner_id, shared_uid)
        )
    return True

def get_shared_users(owner_id: int):
    """Список uid, которым owner выдал доступ"""
    with db_connect() as conn:
        return conn.execute(
            "SELECT shared_uid, created_at FROM server_sharing WHERE owner_id = ?",
            (owner_id,)
        ).fetchall()

def get_shared_servers(shared_uid: int):
    """Список owner_id, сервера которых доступны shared_uid"""
    with db_connect() as conn:
        return conn.execute(
            "SELECT owner_id FROM server_sharing WHERE shared_uid = ?",
            (shared_uid,)
        ).fetchall()

def has_shared_access(owner_id: int, shared_uid: int) -> bool:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM server_sharing WHERE owner_id = ? AND shared_uid = ?",
            (owner_id, shared_uid)
        ).fetchone()
    return row is not None

# ═══════════════════════════════════════════════════════════════════
#                     РЕФЕРАЛЬНАЯ СИСТЕМА
# ═══════════════════════════════════════════════════════════════════
REFERRAL_BONUS_DAYS = 4   # дней за каждого реферала, купившего подписку ≥30 дней

def create_referral(referrer_id: int, referred_id: int) -> bool:
    """Сохранить связь реферер→реферал (игнорируем если уже есть)."""
    try:
        now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S")
        with db_connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus_granted, created_at)
                VALUES (?, ?, 0, ?)
            """, (referrer_id, referred_id, now))
        return True
    except Exception as e:
        log.error(f"create_referral error: {e}")
        return False

def get_referral_info(referred_id: int) -> Optional[sqlite3.Row]:
    """Получить запись реферала по его user_id."""
    with db_connect() as conn:
        return conn.execute(
            "SELECT * FROM referrals WHERE referred_id = ?", (referred_id,)
        ).fetchone()

def mark_referral_bonus_granted(referred_id: int):
    with db_connect() as conn:
        conn.execute(
            "UPDATE referrals SET bonus_granted = 1 WHERE referred_id = ?", (referred_id,)
        )

def get_referral_count(referrer_id: int) -> int:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (referrer_id,)
        ).fetchone()
        return row[0] if row else 0

def get_referral_bonus_count(referrer_id: int) -> int:
    """Сколько бонусов (оплативших рефералов) уже начислено."""
    with db_connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND bonus_granted = 1", (referrer_id,)
        ).fetchone()
        return row[0] if row else 0

async def process_referral_bonus(referred_id: int, days_purchased: int):
    """
    Вызывается после того, как реферал оплатил ≥30 дней подписки.
    Начисляет REFERRAL_BONUS_DAYS дней рефереру (один раз).
    """
    if days_purchased < 30:
        return
    ref = get_referral_info(referred_id)
    if not ref or ref["bonus_granted"]:
        return
    referrer_id = ref["referrer_id"]
    mark_referral_bonus_granted(referred_id)
    # Начисляем бонус: продлеваем если есть подписка, иначе — ничего (подписки нет)
    h = get_hosting(referrer_id)
    if h:
        extend_hosting(referrer_id, days=REFERRAL_BONUS_DAYS)
        new_h = get_hosting(referrer_id)
        try:
            await bot.send_message(
                referrer_id,
                f"🎁 <b>Реферальный бонус!</b>\n\n"
                f"<blockquote>Ваш друг оплатил подписку — вам начислено <b>+{REFERRAL_BONUS_DAYS} дня</b> к подписке!</blockquote>\n\n"
                f"📅 Подписка теперь до: <code>{new_h['expires_at'] if new_h else '—'}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    log.info(f"Referral bonus: +{REFERRAL_BONUS_DAYS}d to referrer={referrer_id} for referred={referred_id}")

# ═══════════════════════════════════════════════════════════════════
#                           FSM СТЕЙТЫ
# ═══════════════════════════════════════════════════════════════════
class PaymentSS(StatesGroup):
    waiting_ym_check      = State()   # ожидание нажатия «Проверить оплату»
    waiting_custom_days   = State()   # произвольный срок для topup/create
    waiting_custom_amount = State()   # произвольная сумма пополнения
    waiting_extend_days   = State()   # произвольный срок продления

class CreateServerStates(StatesGroup):
    pass  # API данные вводятся через webapp
    waiting_auth     = State()

class ReloginStates(StatesGroup):
    waiting_api_id   = State()
    waiting_api_hash = State()
    waiting_auth     = State()

class AdminStates(StatesGroup):
    add_balance_uid    = State()
    add_balance_amount = State()
    force_sub_uid      = State()
    force_sub_expires  = State()
    change_expiry_uid  = State()
    change_expiry_date = State()
    broadcast_text     = State()
    annihilate_uid     = State()
    annihilate_confirm = State()

class HostingStates(StatesGroup):
    reinstall_confirm = State()
    delete_confirm    = State()
    relogin_confirm   = State()

class ReviewStates(StatesGroup):
    waiting_stars = State()
    waiting_text = State()

class SharingStates(StatesGroup):
    waiting_uid_to_add    = State()
    waiting_uid_to_remove = State()
    choosing_server       = State()
    choosing_action       = State()

class TerminalStates(StatesGroup):
    waiting_command = State()

# ═══════════════════════════════════════════════════════════════════
#                     УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════════
def fmt_status(status: str) -> str:
    return {
        "running": "🟢 Работает",
        "exited":  "🔴 Остановлен",
        "paused":  "⏸ Пауза",
        "active":  "✅ Активна",
        "expired": "⛔ Истекла",
        "pending": "⏳ Ожидание",
    }.get(status, f"❓ {status}")

def stars_kb() -> InlineKeyboardMarkup:
    """Клавиатура для выбора количества звёзд"""
    b = InlineKeyboardBuilder()
    star_labels = {1: "1 ⭐", 2: "2 ⭐", 3: "3 ⭐", 4: "4 ⭐", 5: "5 ⭐"}
    for stars in range(1, 6):
        b.button(text=star_labels[stars], callback_data=f"stars_{stars}")
    b.button(text="◀️ Отмена", callback_data="menu")
    b.adjust(5, 1)
    return b.as_markup()

# ═══════════════════════════════════════════════════════════════════
#                     КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════════════
def back_kb(dest: str = "menu") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад", callback_data=dest)
    return b.as_markup()

def main_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚡️ Мой сервер",      callback_data="hosting_menu")
    b.button(text="💎 Кошелёк",          callback_data="finance_menu")
    b.button(text="🛠 Управление",        callback_data="manage_menu")
    b.button(text="🆘 Поддержка",         callback_data="help")
    b.button(text="✍️ Оставить отзыв",   callback_data="leave_review")
    b.button(text="🤝 Шаринг-панель",    callback_data="sharing_menu")
    if is_admin:
        b.button(text="👑 Панель Админа", callback_data="admin_panel")
        b.adjust(2, 2, 2, 1)
    else:
        b.adjust(2, 2, 2)
    return b.as_markup()

def sharing_kb(owner_id: int) -> InlineKeyboardMarkup:
    """Главное меню шаринга — управление своим сервером"""
    b = InlineKeyboardBuilder()
    b.button(text="➕ Выдать доступ",    callback_data="sharing_add")
    b.button(text="➖ Отозвать доступ",  callback_data="sharing_remove")
    b.button(text="👥 Список доступов",  callback_data="sharing_list")
    b.button(text="🔗 Мой доступ",    callback_data="sharing_my_access")
    b.button(text="◀️ Назад",            callback_data="menu")
    b.adjust(2, 1, 1, 1)
    return b.as_markup()

def shared_servers_kb(servers: list) -> InlineKeyboardMarkup:
    """Список серверов, к которым есть доступ"""
    b = InlineKeyboardBuilder()
    for row in servers:
        owner = row["owner_id"]
        b.button(text=f"🖥 Сервер #{owner}", callback_data=f"shared_manage_{owner}")
    b.button(text="🚪 Отключиться от сервера", callback_data="sharing_leave_select")
    b.button(text="◀️ Назад", callback_data="sharing_menu")
    b.adjust(1)
    return b.as_markup()

def shared_manage_kb(owner_id: int) -> InlineKeyboardMarkup:
    """Управление чужим сервером (только разрешённые действия)"""
    b = InlineKeyboardBuilder()
    b.button(text="▶️ Запустить",     callback_data=f"shared_start_{owner_id}")
    b.button(text="⏹ Остановить",     callback_data=f"shared_stop_{owner_id}")
    b.button(text="🔁 Перезапустить", callback_data=f"shared_restart_{owner_id}")
    b.button(text="📋 Логи",          callback_data=f"shared_logs_{owner_id}")
    b.button(text="◀️ Назад",         callback_data="sharing_my_access")
    b.adjust(2, 2, 1)
    return b.as_markup()

def admin_server_manage_kb(target_uid: int) -> InlineKeyboardMarkup:
    """Клавиатура управления сервером для админа (скрытая)"""
    b = InlineKeyboardBuilder()
    b.button(text="▶️ Старт",        callback_data=f"adm_srv_start_{target_uid}")
    b.button(text="⏹ Стоп",          callback_data=f"adm_srv_stop_{target_uid}")
    b.button(text="🔁 Рестарт",      callback_data=f"adm_srv_restart_{target_uid}")
    b.button(text="📋 Логи",         callback_data=f"adm_srv_logs_{target_uid}")
    b.button(text="◀️ Все серверы",  callback_data="admin_hostings")
    b.adjust(2, 2, 1)
    return b.as_markup()

def subscribe_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📢 Подписаться на канал",
             url=f"https://t.me/{CHANNEL_REQUIRED.lstrip('@')}")
    b.button(text="✅ Я подписался", callback_data="check_subscribe")
    b.button(text="📜 Условия использования", url=TERMS_LINK)
    b.adjust(1)
    return b.as_markup()

def terms_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Принимаю условия", callback_data="accept_terms")
    b.button(text="📜 Читать условия",   url=TERMS_LINK)
    b.button(text="◀️ Назад",            callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def hosting_kb(has: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has:
        b.button(text="📊 Информация",     callback_data="my_hosting")
        b.button(text="📋 Логи",           callback_data="server_logs")
        b.button(text="🔄 Переустановить", callback_data="reinstall_hosting")
        b.button(text="🔑 Сменить аккаунт", callback_data="relogin_hosting")
        b.adjust(2, 2)
    else:
        b.button(text="🚀 Создать сервер", callback_data="create_hosting")
        b.adjust(1)
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu"))
    return b.as_markup()

def finance_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💰 Мой баланс",       callback_data="my_balance")
    b.button(text="💳 Пополнить",         callback_data="topup_menu")
    b.button(text="📜 История платежей",  callback_data="payment_history")
    b.button(text="🔄 Продлить подписку", callback_data="extend_sub")
    b.button(text="🔗 Реферальная ссылка", callback_data="referral_menu")
    b.button(text="◀️ Назад",             callback_data="menu")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()

def manage_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="▶️ Запустить",    callback_data="container_start")
    b.button(text="⏹ Остановить",    callback_data="container_stop")
    b.button(text="🔁 Перезапустить", callback_data="container_restart")
    b.button(text="🗑 Удалить",       callback_data="container_delete")
    b.button(text="📋 Логи",          callback_data="server_logs")
    b.button(text="💻 Терминал",      callback_data="container_terminal")
    b.button(text="◀️ Назад",         callback_data="menu")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()

def months_kb(prefix: str = "months") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    options = [
        (1, "1 мес"),
        (3, "3 мес"),
        (6, "6 мес"),
        (12, "12 мес"),
    ]
    for m, label in options:
        price = PRICE_PER_MONTH * m
        total = ym_total(price)
        b.button(text=f"📅 {label} — {total} ₽", callback_data=f"{prefix}_{m}")
    b.button(text="✏️ Свой срок (в днях)", callback_data=f"{prefix}_custom_days")
    if prefix == "topup":
        b.button(text="💸 Своя сумма (₽)", callback_data="topup_custom_amount")
    # Кнопка назад зависит от контекста
    back_dest = {"topup": "finance_menu", "extend": "finance_menu", "months": "create_hosting"}.get(prefix, "menu")
    b.button(text="◀️ Назад", callback_data=back_dest)
    if prefix == "topup":
        b.adjust(2, 2, 1, 1, 1)
    else:
        b.adjust(2, 2, 1, 1)
    return b.as_markup()

def admin_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика",       callback_data="admin_stats")
    b.button(text="💳 Заявки на оплату", callback_data="admin_payments")
    b.button(text="➕ Начислить баланс", callback_data="admin_add_balance")
    b.button(text="📋 Все серверы",      callback_data="admin_hostings")
    b.button(text="🔧 Выдать подписку",  callback_data="admin_force_sub")
    b.button(text="📅 Изменить дату",    callback_data="admin_change_expiry")
    b.button(text="📢 Рассылка",         callback_data="admin_broadcast")
    b.button(text="☢️ Аннигиляция",      callback_data="admin_annihilate")
    b.button(text="🛠️ Исправить контейнеры", callback_data="fix_containers")
    b.button(text="📡 Обновить статус сервера", callback_data="admin_refresh_status")
    b.button(text="◀️ Главное меню",     callback_data="menu")
    b.adjust(2, 2, 2, 2, 1, 1, 1)
    return b.as_markup()

def pay_approve_kb(payment_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить", callback_data=f"approve_{payment_id}")
    b.button(text="❌ Отклонить",   callback_data=f"reject_{payment_id}")
    b.adjust(2)
    return b.as_markup()

def webapp_auth_kb(user_id: int, action: str = "create") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    web_app = WebAppInfo(url=f"https://{AUTH_DOMAIN}:{AUTH_PORT}/?user_id={user_id}&action={action}")
    b.button(text="🔐 Авторизоваться в Telegram", web_app=web_app)
    b.button(text="✅ Я авторизовался", callback_data=f"confirm_auth_{action}_{user_id}")
    b.button(text="◀️ Назад",           callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def server_info_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏠 Главное меню", callback_data="menu")
    b.adjust(1)
    return b.as_markup()

def review_approve_kb(review_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Опубликовать", callback_data=f"review_approve_{review_id}")
    b.button(text="❌ Отклонить",    callback_data=f"review_reject_{review_id}")
    b.adjust(2)
    return b.as_markup()

# ═══════════════════════════════════════════════════════════════════
#                     ФУНКЦИИ РАБОТЫ С ФАЙЛАМИ
# ═══════════════════════════════════════════════════════════════════
def get_id_dir(user_id: int) -> Path:
    return BASE_USERS_DIR / str(user_id) / "ID"

def get_config_path(user_id: int) -> Path:
    return get_id_dir(user_id) / "config.json"

def get_session_path(user_id: int) -> Path:
    return get_id_dir(user_id) / f"heroku-{user_id}.session"

def session_exists(user_id: int) -> bool:
    id_dir = get_id_dir(user_id)
    if not id_dir.exists():
        return False
    return len(list(id_dir.glob("*.session"))) > 0

def config_exists(user_id: int) -> bool:
    return get_config_path(user_id).exists()

def auth_ready(user_id: int) -> bool:
    return session_exists(user_id) and config_exists(user_id)

def write_user_config_json(user_id: int, api_id: int, api_hash: str, port: int = None) -> Tuple[bool, str]:
    id_dir = get_id_dir(user_id)
    id_dir.mkdir(parents=True, exist_ok=True)
    config_path = get_config_path(user_id)

    if port is None:
        port = random.randint(10000, 60000)

    new_config = {
        "port": port,
        "api_id": api_id,
        "api_hash": api_hash,
        "app_name": "JokyHost"
    }

    try:
        config_path.write_text(json.dumps(new_config, indent=2))
        log.info(f"Config saved for user {user_id}: port={port}")
        return True, str(config_path)
    except Exception as e:
        log.error(f"Failed to write config for user {user_id}: {e}")
        return False, str(e)

def delete_auth_files(user_id: int) -> bool:
    id_dir = get_id_dir(user_id)
    if not id_dir.exists():
        return False
    deleted = False
    for pattern in ["*.session", "config.json"]:
        for file in id_dir.glob(pattern):
            try:
                file.unlink()
                log.info(f"Deleted {file} for user {user_id}")
                deleted = True
            except Exception as e:
                log.error(f"Failed to delete {file}: {e}")
    return deleted

def delete_heroku_config(user_id: int) -> bool:
    """Удаляет config.json и config-{uid}.json из директории Heroku/."""
    repo_dir = BASE_USERS_DIR / str(user_id) / "Heroku"
    if not repo_dir.exists():
        return False
    deleted = False
    for pattern in ["config.json", f"config-{user_id}.json"]:
        target = repo_dir / pattern
        if target.exists():
            try:
                target.unlink()
                log.info(f"Deleted Heroku/{pattern} for user {user_id}")
                deleted = True
            except Exception as e:
                log.error(f"Failed to delete Heroku/{pattern} for user {user_id}: {e}")
    return deleted

def delete_user_directory_completely(user_id: int) -> bool:
    user_dir = BASE_USERS_DIR / str(user_id)
    if not user_dir.exists():
        return False
    try:
        shutil.rmtree(user_dir)
        log.info(f"Completely removed user directory for {user_id}")
        return True
    except Exception as e:
        log.error(f"Failed to remove user directory for {user_id}: {e}")
        return False

def sync_auth_to_heroku(user_id: int) -> bool:
    id_dir = get_id_dir(user_id)
    repo_dir = BASE_USERS_DIR / str(user_id) / "Heroku"

    if not id_dir.exists():
        log.warning(f"ID/ not found for user {user_id}")
        return False

    repo_dir.mkdir(parents=True, exist_ok=True)

    for pat in ["heroku-*.session", "hikka-*.session", "*.session-journal"]:
        for old_f in repo_dir.glob(pat):
            try:
                old_f.unlink()
            except Exception as e:
                log.warning(f"sync_auth: can't remove {old_f.name}: {e}")

    copied = 0
    for item in id_dir.iterdir():
        dest = repo_dir / item.name
        try:
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
            copied += 1
        except Exception as e:
            log.error(f"sync_auth: failed to copy {item.name}: {e}")

    log.info(f"sync_auth: copied {copied} items for user {user_id}")
    return copied > 0

# ═══════════════════════════════════════════════════════════════════
#                        DOCKER / СИСТЕМА
# ═══════════════════════════════════════════════════════════════════
async def run_cmd(cmd: list, timeout: int = 60) -> Tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
    except asyncio.TimeoutError:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)

def run_cmd_sync(cmd: list, timeout: int = 60) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)

def clone_repo_sync() -> bool:
    try:
        if os.path.exists(TEMP_REPO_DIR):
            shutil.rmtree(TEMP_REPO_DIR)
        code, _, err = run_cmd_sync(["git", "clone", GIT_REPO_URL, TEMP_REPO_DIR], timeout=120)
        if code != 0:
            log.error(f"Git clone failed: {err}")
            return False
        log.info("Heroku repo cloned successfully")
        return True
    except Exception as e:
        log.error(f"Clone error: {e}")
        return False

def create_user_dockerfile(user_dir: Path, user_id: int):
    dockerfile = user_dir / "Dockerfile"
    setup_py = user_dir / "setup.py"

    dockerfile.write_text(f"""FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y software-properties-common && \\
    add-apt-repository ppa:deadsnakes/ppa -y && \\
    apt-get update && apt-get install -y \\
    python3.12 python3.12-venv python3.12-dev python3-pip \\
    git curl wget procps net-tools jq && \\
    rm -rf /var/lib/apt/lists/* && \\
    ln -sf /usr/bin/python3.12 /usr/bin/python3 && \\
    ln -sf /usr/bin/python3.12 /usr/bin/python

COPY setup.py /setup.py
RUN chmod +x /setup.py
CMD ["python3", "/setup.py"]
""")

    setup_py.write_text(f'''#!/usr/bin/env python3
import os, subprocess, sys, json, shutil, time
from pathlib import Path

USER_ID     = {user_id}
USER_DIR    = Path("/home/users/{user_id}")
REPO_DIR    = USER_DIR / "Heroku"
ID_DIR      = USER_DIR / "ID"
CONFIG_FILE = REPO_DIR / "config.json"
SETUP_FLAG  = USER_DIR / ".setup_done"
VENV_DIR    = REPO_DIR / "venv"

def log(msg): print(f"[{{time.strftime('%H:%M:%S')}}] {{msg}}", flush=True)

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        log(f"CMD ERR: {{r.stderr[:400]}}")
    return r

def venv_ok():
    return (VENV_DIR / "bin" / "python3").exists()

def sync_auth():
    if not ID_DIR.exists():
        return False
    REPO_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in ID_DIR.iterdir():
        dest = REPO_DIR / item.name
        try:
            if item.is_dir():
                if dest.exists(): shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
            copied += 1
        except Exception as e:
            log(f"WARN: can't copy {{item.name}}: {{e}}")
    log(f"Auth sync: {{copied}} file(s) copied")
    return copied > 0

def clean_stale_session():
    removed = 0
    for pat in ["heroku-*.session", "hikka-*.session", "*.session-journal"]:
        for f in REPO_DIR.glob(pat):
            try:
                f.unlink()
                removed += 1
            except Exception as e:
                log(f"WARN: can't remove stale session {{f.name}}: {{e}}")
    if removed:
        log(f"Cleaned {{removed}} stale session file(s) from REPO_DIR")

def session_auth_ready():
    sessions = list(REPO_DIR.glob("heroku-*.session")) + list(REPO_DIR.glob("hikka-*.session"))
    return len(sessions) > 0

def start_heroku():
    log("Starting Heroku userbot...")
    env = os.environ.copy()
    env.setdefault("HIKKA_SKIP_SETUP", "1")
    env.setdefault("NO_ANALYTICS", "1")
    env.setdefault("HEROKU_DISABLE_CONTENT_CHANNEL", "1")
    cmd = f". {{VENV_DIR}}/bin/activate && cd {{REPO_DIR}} && python3 -m heroku --root --no-web"
    while True:
        proc = subprocess.Popen(["bash", "-c", cmd], env=env, start_new_session=True)
        exit_code = proc.wait()
        log(f"Heroku userbot exited with code {{exit_code}}, restarting in 3s...")
        clean_stale_session()
        sync_auth()
        time.sleep(3)

if not REPO_DIR.exists():
    log("ERROR: Heroku directory not found!")
    sys.exit(1)

clean_stale_session()
log("Syncing auth files...")
sync_auth()

if not session_auth_ready():
    log("Auth files not found. Waiting for authorization...")
    for attempt in range(18):
        time.sleep(10)
        sync_auth()
        if session_auth_ready():
            log("Auth files appeared, proceeding!")
            break
        log(f"Still waiting for auth... ({{attempt+1}}/18)")
    else:
        log("FATAL: Authorization never completed.")
        sys.exit(1)

log("Auth OK")

if SETUP_FLAG.exists() and venv_ok():
    start_heroku()

if VENV_DIR.exists():
    shutil.rmtree(VENV_DIR)

log("Creating virtual environment...")
r = subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], capture_output=True, text=True)
if r.returncode != 0:
    log(f"FATAL: {{r.stderr}}")
    sys.exit(1)

pip = str(VENV_DIR / "bin" / "pip")
run([pip, "install", "--upgrade", "pip", "-q"])

if (REPO_DIR / "requirements.txt").exists():
    log("Installing requirements...")
    run([pip, "install", "-r", str(REPO_DIR / "requirements.txt"), "-q"])

SETUP_FLAG.write_text("done")
log(f"Setup complete for user {{USER_ID}}!")
start_heroku()
''')
    setup_py.chmod(0o755)

def patch_heroku_entity(repo_dir: Path):
    entity_file = repo_dir / "heroku" / "utils" / "entity.py"
    if not entity_file.exists():
        log.warning(f"patch_heroku_entity: {entity_file} not found, skipping patch")
        return
    try:
        content = entity_file.read_text(encoding="utf-8")
        old = 'log.warning("Heroku content channel not found in database. Sleeping 10 seconds...")'
        new = 'log.debug("Heroku content channel not found in database, skipping.")\n            return None'
        if old in content:
            content = content.replace(old, new)
            import re as _re
            content = _re.sub(
                r'while True:.<b>?Sleeping 10 seconds\.\.\."[^\n]</b>\n\s*await asyncio\.sleep\(10\)',
                'return None',
                content,
                flags=_re.DOTALL
            )
            entity_file.write_text(content, encoding="utf-8")
            log.info("patch_heroku_entity: patched successfully")
        else:
            log.info("patch_heroku_entity: pattern not found, already patched or different version")
    except Exception as e:
        log.error(f"patch_heroku_entity failed: {e}")

def get_port_from_config(user_id: int) -> Optional[int]:
    for config_file in [
        get_config_path(user_id),
        BASE_USERS_DIR / str(user_id) / "Heroku" / "config.json",
    ]:
        try:
            if config_file.exists():
                return json.loads(config_file.read_text()).get("port")
        except Exception:
            pass
    return None

async def setup_heroku_forums(user_id: int) -> Tuple[bool, str]:
    try:
        from herokutl import TelegramClient
        from herokutl.sessions import SQLiteSession
        from herokutl.tl.functions.channels import (
            CreateChannelRequest,
            ToggleForumRequest,
            CreateForumTopicRequest,
        )
        from herokutl.tl.types import InputChannel
    except ImportError:
        return False, "herokutl не установлен"

    id_dir = get_id_dir(user_id)
    sessions = list(id_dir.glob("*.session"))
    if not sessions:
        return False, "Сессия не найдена"
    session_path = str(sessions[0]).replace(".session", "")

    try:
        cfg = json.loads(get_config_path(user_id).read_text())
        api_id = cfg["api_id"]
        api_hash = cfg["api_hash"]
    except Exception as e:
        return False, f"Ошибка чтения конфига: {e}"

    log.info(f"setup_heroku_forums: connecting with session {session_path}")
    client = TelegramClient(SQLiteSession(session_path), api_id, api_hash)
    channel_id = None
    topics = {}
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return False, "Клиент не авторизован"

        result = await client(CreateChannelRequest(
            title="heroku-userbot",
            about="JokyHost service group",
            megagroup=True,
        ))
        channel = result.chats[0]
        channel_id = channel.id
        access_hash = channel.access_hash
        input_channel = InputChannel(channel_id, access_hash)
        log.info(f"setup_heroku_forums: channel created id={channel_id}")

        await client(ToggleForumRequest(channel=input_channel, enabled=True))

        for topic_name in ["Logs", "Assets", "Backups"]:
            res = await client(CreateForumTopicRequest(
                channel=input_channel,
                title=topic_name,
            ))
            topic_id = None
            try:
                for upd in res.updates:
                    msg = getattr(upd, "message", None)
                    if msg is not None:
                        topic_id = msg.id
                        break
            except Exception:
                pass
            if topic_id is None:
                try:
                    topic_id = res.updates[0].message.id
                except Exception:
                    topic_id = 1
            topics[topic_name] = topic_id
            log.info(f"setup_heroku_forums: created topic '{topic_name}' id={topic_id}")
            await asyncio.sleep(1)

        await client.disconnect()

    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, f"Ошибка Telegram: {e}"

    heroku_config_path = BASE_USERS_DIR / str(user_id) / "Heroku" / f"config-{user_id}.json"
    forums_cache = {
        "heroku-userbot": {
            "Backups": topics.get("Backups"),
            "Assets":  topics.get("Assets"),
            "Logs":    topics.get("Logs"),
        }
    }

    try:
        cfg_data = {}
        if heroku_config_path.exists():
            try:
                cfg_data = json.loads(heroku_config_path.read_text(encoding="utf-8"))
            except Exception:
                cfg_data = {}

        if "heroku.forums" not in cfg_data:
            cfg_data["heroku.forums"] = {}
        cfg_data["heroku.forums"]["forums_cache"] = forums_cache
        cfg_data["heroku.forums"]["channel_id"] = channel_id

        heroku_config_path.write_text(
            json.dumps(cfg_data, ensure_ascii=False, indent=4),
            encoding="utf-8"
        )
        log.info(f"setup_heroku_forums: wrote config for user {user_id}, channel_id={channel_id}")
    except Exception as e:
        return False, f"Ошибка записи в config.json: {e}"

    return True, f"Группа создана (id={channel_id}), топики: {topics}"

async def docker_create(user_id: int, status_cb=None) -> Tuple[bool, str]:
    name = f"jh_user_{user_id}"
    image = f"jh_user_{user_id}:latest"
    udir = BASE_USERS_DIR / str(user_id)

    async def status(msg_text):
        if status_cb:
            try:
                await status_cb(msg_text)
            except Exception:
                pass

    try:
        udir.mkdir(parents=True, exist_ok=True)

        await status("📦 Клонирование репозитория Heroku...")
        ok = await asyncio.get_running_loop().run_in_executor(None, clone_repo_sync)
        if not ok:
            return False, "Не удалось склонировать репозиторий"

        heroku_dest = udir / "Heroku"
        if heroku_dest.exists():
            shutil.rmtree(heroku_dest)
        shutil.copytree(TEMP_REPO_DIR, heroku_dest)

        patch_heroku_entity(heroku_dest)

        await status("📁 Перенос файлов авторизации...")
        sync_auth_to_heroku(user_id)

        await status("🐳 Генерация Dockerfile...")
        create_user_dockerfile(udir, user_id)

        await run_cmd(["docker", "rm", "-f", name])
        await run_cmd(["docker", "rmi", "-f", image])

        await status("🏗 Сборка образа (2–3 мин)...")
        code, _, err = await run_cmd(["docker", "build", "-t", image, str(udir)], timeout=360)
        if code != 0:
            return False, f"Ошибка сборки: {err[:400]}"

        await status("🚀 Запуск контейнера...")
        code, _, err = await run_cmd([
            "docker", "run", "-d",
            "--name", name,
            "--restart", "always",
            "--network", "host",
            "--cpus", CPU_LIMIT,
            "--memory", MEMORY_LIMIT,
            "--memory-swap", MEMORY_LIMIT,
            "--pids-limit", "128",
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--tmpfs", "/tmp",
            "--tmpfs", "/run",
            "-e", "HIKKA_SKIP_SETUP=1",
            "-e", "NO_ANALYTICS=1",
            "-e", "HEROKU_DISABLE_CONTENT_CHANNEL=1",
            "-v", f"{udir.absolute()}:/home/users/{user_id}",
            image
        ], timeout=60)
        if code != 0:
            return False, f"Ошибка запуска: {err[:400]}"

        await status("✅ Контейнер запущен!")

        await asyncio.sleep(5)
        await status("💬 Создание служебной группы и топиков...")
        forums_ok, forums_msg = await setup_heroku_forums(user_id)
        if forums_ok:
            log.info(f"setup_heroku_forums OK for {user_id}: {forums_msg}")
            await status(f"✅ Группа создана!")
        else:
            log.warning(f"setup_heroku_forums FAILED for {user_id}: {forums_msg}")
            await status(f"⚠️ Группа не создана: {forums_msg}")
        await asyncio.sleep(2)

        port = get_port_from_config(user_id) or (10000 + user_id % 55535)
        return True, str(port)

    except Exception as e:
        log.error(f"docker_create error for {user_id}: {e}")
        return False, str(e)

async def docker_delete(user_id: int, keep_files: bool = False, delete_all_files: bool = True) -> Tuple[bool, str]:
    name = f"jh_user_{user_id}"
    image = f"jh_user_{user_id}:latest"
    udir = BASE_USERS_DIR / str(user_id)

    try:
        await run_cmd(["docker", "stop", name], timeout=30)
        await run_cmd(["docker", "rm", "-f", name])
        await run_cmd(["docker", "rmi", "-f", image], timeout=30)

        if delete_all_files and udir.exists():
            delete_user_directory_completely(user_id)

        delete_hosting(user_id)
        log.info(f"Docker container and all files removed for user {user_id}")
        return True, "OK"
    except Exception as e:
        log.error(f"docker_delete error for {user_id}: {e}")
        return False, str(e)

async def docker_stop(user_id: int) -> bool:
    name = f"jh_user_{user_id}"
    # Сначала убираем auto-restart, иначе Docker поднимет контейнер сам
    await run_cmd(["docker", "update", "--restart=no", name], timeout=10)
    code, _, _ = await run_cmd(["docker", "stop", name], timeout=30)
    return code == 0


async def docker_stop_expired(user_id: int) -> bool:
    """Останавливает контейнер истёкшего пользователя без возможности автоподъёма."""
    return await docker_stop(user_id)

async def docker_start(user_id: int) -> bool:
    name = f"jh_user_{user_id}"
    # Восстанавливаем политику автоперезапуска перед стартом
    await run_cmd(["docker", "update", "--restart=always", name], timeout=10)
    code, _, _ = await run_cmd(["docker", "start", name])
    return code == 0

async def docker_restart(user_id: int) -> bool:
    name = f"jh_user_{user_id}"
    await asyncio.get_running_loop().run_in_executor(None, lambda: sync_auth_to_heroku(user_id))
    code, _, _ = await run_cmd(["docker", "stop", name], timeout=30)
    if code != 0:
        pass
    await asyncio.sleep(2)
    code, _, _ = await run_cmd(["docker", "start", name], timeout=30)
    return code == 0

async def docker_logs(user_id: int, lines: int = 40) -> str:
    _, stdout, stderr = await run_cmd(
        ["docker", "logs", "--tail", str(lines), f"jh_user_{user_id}"]
    )
    raw = (stdout + stderr).strip()
    clean = re.sub(r'\x1b\[[0-9;]*[mGKHFJA-Z]', '', raw)
    clean = re.sub(r'Is the text above colored\? \[y/N\].*', '', clean)
    return clean.strip() or "Логи пусты"


# ═══════════════════════════════════════════════════════════════════
#                    ПОЛНОЦЕННЫЙ AI-АССИСТЕНТ
# ═══════════════════════════════════════════════════════════════════
# История диалогов: uid -> list[{"role": ..., "content": ...}]
_ai_history: dict[int, list] = {}
_AI_MAX_HISTORY = 16   # сообщений в контексте
_AI_MAX_TOKENS  = 1024

_AI_SYSTEM = (
    "Ты — JokyAI, DevOps-ассистент хостинга JokyHost (Heroku Userbot, Python, Docker, Ubuntu 22.04). "
    "Ты помогаешь пользователям управлять их Docker-контейнерами, диагностировать ошибки в логах, "
    "давать советы по настройке юзерботов. Отвечай кратко, по делу, с эмодзи. "
    "Если просят диагностику логов — анализируй и предлагай команду исправления. "
    "Никогда не говори 'не могу помочь' если вопрос по теме хостинга/DevOps."
)

# Промпт специально для анализа логов (Диагностика AI)
_AI_SYSTEM_LOGS = """Ты — AI-диагност бота JokyHost. Тебе дают docker logs контейнера с Heroku Userbot пользователя.

Твоя задача:
1. Найти реальную причину проблемы в логах
2. Объяснить её коротко и понятным языком (без технического жаргона)
3. Указать точное решение ONLY через кнопки бота JokyHost или из FAQ ниже

━━━ КНОПКИ БОТА (единственный способ управления) ━━━

«⚡️ Мой сервер» → статус, порт, срок подписки
«⚡️ Мой сервер» → «📋 Логи» → просмотр последних логов
«⚡️ Мой сервер» → «🔁 Перезапустить» → перезапуск контейнера (быстро, данные сохраняются)
«⚡️ Мой сервер» → «🔄 Переустановить» → пересоздать контейнер (установит зависимости заново, сессия/конфиг сохранятся)
«⚡️ Мой сервер» → «🔑 Сменить аккаунт» → полный релогин: удаляет сессию, запрашивает новые API ID + API Hash, затем авторизацию через Web App
«🛠 Управление» → «▶️ Запустить» / «⏹ Остановить» / «🔁 Перезапустить»
«🛠 Управление» → «💻 Терминал» → выполнить команду внутри контейнера

━━━ ❤ FAQ (обновлён 25.04.2026) ━━━

[FAQ-1] ЮБ не реагирует после авторизации?
→ Просто перезапусти контейнер: «🛠 Управление» → «🔁 Перезапустить»

[FAQ-2] Авторизация не удаётся?
→ Попробуй «🔄 Переустановить». Если не помогло — обратись в поддержку @JokyHub

[FAQ-3] Ошибка: "Heroku content channel not found in database. Sleeping 10 seconds..."
→ Нужно вручную прописать форум-группу. Через «🛠 Управление» → «💻 Терминал» выполни:
  .e fix = { "heroku-userbot": { "Backups": <id топика Backups>, "Assets": <id топика Assets>, "Logs": <id топика Logs> } }
  db.set("heroku.forums", "forums_cache", fix)
  db.set("heroku.forums", "channel_id", <id группы без -100>)
  Где взять id топиков: открой форум-группу, зайди в нужный топик, id — число в ссылке после /

[FAQ-4] Создалось 16 модулей вместо 20 (не хватает 4)?
→ Причина: у бота не включён Inline Mode. Инструкция:
  1. Зайди в @BotFather, найди бота от Heroku (или создай нового)
  2. Выбери бота → Bot Settings → Inline Mode → Turn On
  3. Нажми API Token → Revoke Current Token → скопируй новый токен
  4. В любом чате напиши: .chbottoken <вставь токен>
     Пример: .chbottoken 8237986915:AAHayvsq9IBb-B4fEFRzBJIFk3q5FIeHdVk
  5. Перезапусти контейнер через JokyHost — подгрузится ещё 4 модуля

━━━ ТАБЛИЦА ОШИБОК ━━━

ОШИБКА В ЛОГАХ → critical → решение

"EOFError: EOF when reading a line" → true → Сессия повреждена. «🔑 Сменить аккаунт»
"Please enter your phone number" → true → Сессия слетела, юзербот ждёт авторизацию. «🔑 Сменить аккаунт»
"AUTH_KEY_UNREGISTERED" → true → Сессия отозвана Telegram. «🔑 Сменить аккаунт»
"SESSION_EXPIRED" → true → Сессия истекла. «🔑 Сменить аккаунт»
"SESSION_REVOKED" → true → Сессия отозвана. «🔑 Сменить аккаунт»
"Auth files not found. Waiting for authorization" → true → Пользователь никогда не авторизовывался. «🔑 Сменить аккаунт»
"Heroku directory not found" → true → Папка с кодом юзербота отсутствует. «🔄 Переустановить»
"ModuleNotFoundError" / "No module named" → true → Не хватает Python-пакета. «🔄 Переустановить»
"requirements.txt" + ошибка → true → Ошибка установки зависимостей. «🔄 Переустановить»
"struct.error: 'i' format requires" → true → Неверный API ID. «🔑 Сменить аккаунт», ввести корректный API ID
"ConnectionRefusedError" / "Network is unreachable" → false → Временная сетевая ошибка. «🔁 Перезапустить»
"FloodWaitError" / "FloodWait" → false → Telegram заблокировал запросы на время. Подождать 10-30 мин, затем «🔁 Перезапустить»
"Heroku userbot exited with code" + restart → false → Штатный перезапуск. Если часто — смотри «📋 Логи»
"Up-to-date" / "Version: 2.0.0" → false → Всё работает нормально
"HerokuBackup failed" / "send_document" NoneType → false → Модуль бэкапа не настроен, не критично
"ConnectTimeout" / "api.fixyres.com" → false → Сторонний сервис модулей недоступен, юзербот работает
"Heroku content channel not found" → false → См. FAQ-3 выше для исправления

━━━ ПРАВИЛА ОТВЕТА ━━━

- Если логи показывают нормальную работу ("Up-to-date", "Version: 2.0.0") → critical: false, solution: пусто
- Если ошибка некритичная → critical: false, объясни что это не страшно
- Если ошибка из FAQ → используй точную инструкцию из FAQ в поле solution
- Если несколько ошибок — анализируй самую важную
- НЕ придумывай решения через терминал вне FAQ
- summary: 1-2 предложения, понятным языком
- solution: конкретные шаги (максимум 5 если это FAQ-инструкция)

Отвечай ТОЛЬКО валидным JSON без markdown-обёртки:
{"critical": true/false, "summary": "...", "solution": "...", "fix_cmd": null}

fix_cmd ВСЕГДА null."""


async def _local_request(
    messages: list,
    system: str,
    max_tokens: int = _AI_MAX_TOKENS,
    timeout: int = 45,
) -> Optional[str]:
    """
    Запрос к локальному OpenAI-совместимому серверу (как в akari.py).
    Системный промпт передаётся первым сообщением с role=system.
    Возвращает текст ответа или None при ошибке.
    """
    full_messages = [{"role": "system", "content": system}] + messages
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{LOCAL_API_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {LOCAL_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LOCAL_API_MODEL,
                    "max_tokens": max_tokens,
                    "messages": full_messages,
                },
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    log.error(f"Local AI API {resp.status}: {err[:200]}")
                    return None
                data = await resp.json()
        # Поддержка стандартного OpenAI-формата
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        # Поддержка кастомного формата {"success": True, "response": "..."}
        if "response" in data:
            return data["response"].strip()
        log.error(f"_local_request unexpected format: {str(data)[:200]}")
        return None
    except Exception as e:
        log.error(f"_local_request error: {e}")
        return None


async def ai_chat(uid: int, user_text: str) -> str:
    """
    Полноценный диалог с AI с историей.
    Используется для кнопки 'Спросить AI' и inline-чата.
    """
    history = _ai_history.setdefault(uid, [])
    history.append({"role": "user", "content": user_text})

    # Ограничиваем историю
    messages = history[-_AI_MAX_HISTORY:]

    answer = await _local_request(messages, system=_AI_SYSTEM)
    if answer is None:
        history.pop()  # откатываем запрос
        return "❌ Ошибка запроса к AI. Попробуйте позже."

    history.append({"role": "assistant", "content": answer})

    # Обрезаем историю если слишком длинная
    if len(history) > _AI_MAX_HISTORY * 2:
        _ai_history[uid] = history[-_AI_MAX_HISTORY * 2:]

    return answer


def ai_clear_history(uid: int):
    """Очистить историю AI-диалога пользователя."""
    _ai_history.pop(uid, None)


async def ai_analyze_logs(logs: str) -> dict:
    """
    Отправляет логи в локальную модель и получает диагноз + инструкцию через кнопки бота.
    Возвращает dict:
      {
        "critical": bool,
        "summary": str,
        "solution": str,
        "fix_cmd": None
      }
    """
    user_msg = f"Логи контейнера (последние ~60 строк):\n\n{logs[:5000]}"
    raw_text = await _local_request(
        messages=[{"role": "user", "content": user_msg}],
        system=_AI_SYSTEM_LOGS,
        max_tokens=512,
    )

    if raw_text is None:
        return {"critical": False, "summary": "Ошибка запроса к AI.", "solution": "", "fix_cmd": None}

    try:
        clean = re.sub(r"^```json|^```|```$", "", raw_text, flags=re.MULTILINE).strip()
        result = json.loads(clean)
        for k, default in [("critical", False), ("summary", ""), ("solution", ""), ("fix_cmd", None)]:
            result.setdefault(k, default)
        result["fix_cmd"] = None  # Принудительно — никогда не выполняем команды
        return result
    except Exception as e:
        log.error(f"ai_analyze_logs parse error: {e}, raw: {raw_text[:300]}")
        return {"critical": False, "summary": f"Ошибка разбора ответа AI: {e}", "solution": "", "fix_cmd": None}


async def ai_execute_fix(user_id: int, fix_cmd: str) -> tuple:
    """
    Выполняет fix_cmd внутри docker-контейнера пользователя.
    Возвращает (ok: bool, output: str).
    """
    container = f"jh_user_{user_id}"
    code, stdout, stderr = await run_cmd(
        ["docker", "exec", container, "sh", "-c", fix_cmd],
        timeout=60,
    )
    output = (stdout + stderr).strip()[:1500] or "(нет вывода)"
    return (code == 0), output


async def docker_container_status(user_id: int) -> str:
    """Получить статус контейнера (running / exited / unknown)."""
    code, out, _ = await run_cmd(
        ["docker", "inspect", "--format", "{{.State.Status}}", f"jh_user_{user_id}"]
    )
    return out.strip() if code == 0 else "unknown"

async def docker_container_stats(user_id: int) -> dict:
    """Получить статистику контейнера: CPU, RAM, сеть"""
    name = f"jh_user_{user_id}"
    code, out, _ = await run_cmd(
        ["docker", "stats", "--no-stream", "--format",
         "{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}|{{.BlockIO}}",
         name],
        timeout=15
    )
    if code != 0 or not out.strip():
        return {}
    try:
        parts = out.strip().split("|")
        if len(parts) < 5:
            return {}
        return {
            "cpu":    parts[0].strip(),
            "mem":    parts[1].strip(),
            "mem_p":  parts[2].strip(),
            "net":    parts[3].strip(),
            "block":  parts[4].strip(),
        }
    except Exception:
        return {}

async def get_server_status_data() -> dict:
    """
    Собирает полную статистику сервера:
    всего контейнеров jh_user_*, активных, CPU хоста, RAM хоста.
    Возвращает dict с полями: total, running, cpu_pct, ram_used, ram_total, ram_pct
    """
    # Список всех контейнеров проекта
    code, out, _ = await run_cmd(
        ["docker", "ps", "-a", "--filter", "name=jh_user_",
         "--format", "{{.Status}}"],
        timeout=15
    )
    containers = [l.strip() for l in out.strip().splitlines() if l.strip()] if code == 0 else []
    total   = len(containers)
    running = sum(1 for s in containers if s.lower().startswith("up"))

    # CPU и RAM хоста через /proc
    cpu_pct  = "—"
    ram_used = "—"
    ram_total = "—"
    ram_pct  = "—"
    try:
        # CPU (1-sec sample)
        with open("/proc/stat") as f:
            line1 = f.readline()
        await asyncio.sleep(1)
        with open("/proc/stat") as f:
            line2 = f.readline()
        vals1 = list(map(int, line1.split()[1:]))
        vals2 = list(map(int, line2.split()[1:]))
        idle1, idle2 = vals1[3], vals2[3]
        total1, total2 = sum(vals1), sum(vals2)
        dtotal = total2 - total1
        didle  = idle2 - idle1
        cpu_pct = f"{round((1 - didle / dtotal) * 100, 1)}%" if dtotal else "—"
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            mem_lines = f.readlines()
        mem = {}
        for ln in mem_lines:
            k, v = ln.split(":", 1)
            mem[k.strip()] = int(v.strip().split()[0])
        total_kb    = mem.get("MemTotal", 0)
        avail_kb    = mem.get("MemAvailable", 0)
        used_kb     = total_kb - avail_kb
        ram_total   = f"{total_kb // 1024} MB"
        ram_used    = f"{used_kb // 1024} MB"
        ram_pct     = f"{round(used_kb / total_kb * 100, 1)}%" if total_kb else "—"
    except Exception:
        pass

    return {
        "total":     total,
        "running":   running,
        "cpu_pct":   cpu_pct,
        "ram_used":  ram_used,
        "ram_total": ram_total,
        "ram_pct":   ram_pct,
    }


async def build_status_message_text(data: dict) -> str:
    """Форматирует текст для сообщения статуса канала."""
    now_msk = datetime.now(MSK).strftime("%d.%m.%Y %H:%M")
    running  = data["running"]
    total    = data["total"]
    stopped  = total - running

    # Иконка общего состояния
    if total == 0:
        overall = "⚪️ Нет контейнеров"
    elif stopped == 0:
        overall = "🟢 Все контейнеры работают"
    elif running == 0:
        overall = "🔴 Все контейнеры остановлены"
    else:
        overall = f"🟡 {stopped} из {total} остановлено"

    text = (
        f"🖥 <b>JokyHost — Статус сервера</b>\n\n"
        f"┌ {overall}\n"
        f"├ 📦 Контейнеров всего: <b>{total}</b>\n"
        f"├ ▶️ Активных: <b>{running}</b>\n"
        f"├ ⏹ Остановлено: <b>{stopped}</b>\n"
        f"├ 🧠 CPU хоста: <b>{data['cpu_pct']}</b>\n"
        f"├ 💾 RAM: <b>{data['ram_used']} / {data['ram_total']}</b> ({data['ram_pct']})\n"
        f"└ 🕐 Обновлено: <b>{now_msk}</b> МСК"
    )
    return text


async def _status_get_msg_id() -> int:
    """Возвращает актуальный message_id для статус-сообщения (из БД или конфига)."""
    saved = db_get_setting("status_message_id")
    if saved:
        return int(saved)
    return STATUS_MESSAGE_ID


async def _status_send_new(text: str) -> int:
    """Отправляет новое сообщение статуса в топик и сохраняет его ID в БД."""
    msg = await bot.send_message(
        STATUS_CHANNEL_ID,
        text,
        message_thread_id=STATUS_THREAD_ID,
        parse_mode=ParseMode.HTML,
    )
    db_set_setting("status_message_id", str(msg.message_id))
    log.info(f"Status: sent new message {msg.message_id} in thread {STATUS_THREAD_ID}")
    return msg.message_id


async def update_status_channel_message():
    """Обновляет сообщение статуса в форум-топике.
    Алгоритм: edit существующего → если не вышло (нет сообщения / другая ошибка) → send_message → сохранить ID.
    """
    # Шаг 1 — собираем данные
    try:
        data = await get_server_status_data()
        text = await build_status_message_text(data)
    except Exception as e:
        log.error(f"get_server_status_data error: {e}")
        text = f"❌ <b>Ошибка получения статуса</b>\n\n<code>{e}</code>"

    # Шаг 2 — пытаемся edit, при ошибке шлём новое
    msg_id = await _status_get_msg_id()
    try:
        await bot.edit_message_text(
            text,
            chat_id=STATUS_CHANNEL_ID,
            message_id=msg_id,
            parse_mode=ParseMode.HTML,
        )
        log.info(f"Status channel message {msg_id} updated")
    except Exception as e:
        log.warning(f"status_channel edit failed (msg_id={msg_id}): {e} — sending new message")
        try:
            await _status_send_new(text)
        except Exception as e2:
            log.error(f"status_channel send_new failed: {e2}")


async def status_channel_watcher():
    """Фоновая задача: обновляет сообщение статуса в канале каждые 5 минут."""
    await asyncio.sleep(15)  # небольшой старт-задержка
    while True:
        try:
            await update_status_channel_message()
        except Exception as e:
            log.error(f"status_channel_watcher error: {e}")
        await asyncio.sleep(300)  # 5 минут


def fix_all_containers() -> int | str:
    """Пересоздаёт все контейнеры jh_user_* с флагами безопасной изоляции."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        containers = [c for c in result.stdout.strip().split("\n") if c.startswith("jh_user_")]
        fixed = 0

        for name in containers:
            try:
                tg_id = name.split("_")[2]
            except IndexError:
                continue

            image = f"jh_user_{tg_id}:latest"
            udir = BASE_USERS_DIR / tg_id

            subprocess.run(["docker", "stop", name], capture_output=True, timeout=30)
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)

            r = subprocess.run([
                "docker", "run", "-d",
                "--name", name,
                "--restart", "always",
                "--network", "host",
                "--cpus", CPU_LIMIT,
                "--memory", MEMORY_LIMIT,
                "--memory-swap", MEMORY_LIMIT,
                "--pids-limit", "128",
                "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL",
                "--tmpfs", "/tmp",
                "--tmpfs", "/run",
                "-e", "HIKKA_SKIP_SETUP=1",
                "-e", "NO_ANALYTICS=1",
                "-e", "HEROKU_DISABLE_CONTENT_CHANNEL=1",
                "-v", f"{udir.absolute()}:/home/users/{tg_id}",
                image
            ], capture_output=True, text=True, timeout=60)

            if r.returncode == 0:
                fixed += 1
                log.info(f"fix_all_containers: restarted {name}")
            else:
                log.warning(f"fix_all_containers: failed {name}: {r.stderr[:200]}")

        return fixed
    except Exception as e:
        log.error(f"fix_all_containers error: {e}")
        return str(e)


# ═══════════════════════════════════════════════════════════════════
#                     ФОНОВАЯ ПРОВЕРКА ИСТЕЧЕНИЙ
# ═══════════════════════════════════════════════════════════════════
async def expiry_watcher():
    await asyncio.sleep(60)  # небольшой старт-задержка
    while True:
        try:
            today = datetime.now(MSK).date()
            hostings = get_all_hostings()
            for h in hostings:
                uid = h["user_id"]
                expires_str = h["expires_at"]
                try:
                    exp_date = datetime.strptime(expires_str, "%Y-%m-%d").date()
                except Exception:
                    continue
                days = (exp_date - today).days

                # ── Подписка истекла — останавливаем сервер ──────────────
                if days <= 0:
                    if h["status"] != "expired":
                        log.info(f"Hosting expired for user {uid}, deleting...")
                        ok, _ = await docker_delete(uid, keep_files=False, delete_all_files=True)
                        try:
                            await bot.send_message(
                                uid,
                                "🔴 <b>Подписка истекла!</b>\n\n"
                                "<blockquote>Ваш сервер и все его файлы были удалены.</blockquote>\n\n"
                                "💎 Пополните баланс и создайте новый сервер через «🖥 Хостинг».",
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            pass
                    continue

                # ── Предупреждения за 7, 5, 3, 1 день — раз в день ──────
                # wtype включает дату чтобы одно предупреждение слалось строго раз в сутки
                today_str = today.strftime("%Y-%m-%d")
                for threshold in [7, 5, 3, 1]:
                    if days == threshold:
                        wtype = f"{threshold}d_{today_str}"
                        if not was_warning_sent(uid, wtype):
                            plural = {7: "7 дней", 5: "5 дней", 3: "3 дня", 1: "1 день"}[threshold]
                            try:
                                await bot.send_message(
                                    uid,
                                    f"⚠️ <b>Внимание!</b>\n\n"
                                    f"<blockquote>Ваш сервер истекает через <b>{plural}</b>.\n"
                                    f"📅 Дата истечения: <code>{expires_str}</code></blockquote>\n\n"
                                    "💎 Продлите в разделе «Кошелёк» → «Продлить подписку».",
                                    parse_mode=ParseMode.HTML,
                                )
                                save_warning_sent(uid, wtype)
                            except Exception:
                                pass
                        break  # только одно уведомление за итерацию

        except Exception as e:
            log.error(f"expiry_watcher error: {e}")

        await asyncio.sleep(1800)  # проверяем каждые 30 минут

# ═══════════════════════════════════════════════════════════════════
#                    TELEGRAM WEB APP (Auth)
# ═══════════════════════════════════════════════════════════════════
HTML_WEBAPP = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JokyHost Panel</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{
  --red:#e63946;--red-d:rgba(230,57,70,.12);--red-g:rgba(230,57,70,.3);
  --bg:#090807;--bg2:#101010;--bg3:#161514;--bg4:#1b1a18;
  --fg:#ede8df;--muted:#5c5855;--muted2:#807c78;
  --brd:rgba(237,232,223,.07);--brd2:rgba(237,232,223,.13);
  --green:#4ade80;--green-d:rgba(74,222,128,.1);
  --amber:#f59e0b;--amber-d:rgba(245,158,11,.1);
  --blue:#60a5fa;--blue-d:rgba(96,165,250,.1);
  --purple:#a78bfa;--purple-d:rgba(167,139,250,.1);
  --sidebar:220px;
}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{background:var(--bg);color:var(--fg);font-family:'Space Mono',monospace;min-height:100vh;overflow-x:hidden}

/* BG */
.bg{position:fixed;inset:0;z-index:0;pointer-events:none}
.bg-grid{position:absolute;inset:0;background-image:linear-gradient(rgba(237,232,223,.016) 1px,transparent 1px),linear-gradient(90deg,rgba(237,232,223,.016) 1px,transparent 1px);background-size:44px 44px}
.bg-grad{position:absolute;inset:0;background:radial-gradient(ellipse 80% 50% at 50% -10%,rgba(230,57,70,.055) 0%,transparent 60%)}
canvas#scan{position:absolute;inset:0;width:100%;height:100%}

/* ═══ LAYOUT ═══ */
.app{position:relative;z-index:1;display:flex;min-height:100vh}

/* SIDEBAR (desktop) */
.sidebar{
  width:var(--sidebar);flex-shrink:0;
  background:var(--bg2);border-right:1px solid var(--brd2);
  display:flex;flex-direction:column;
  position:fixed;top:0;left:0;bottom:0;z-index:60;
  transform:translateX(0);transition:transform .25s;
}
.sidebar-logo{padding:20px 18px 16px;border-bottom:1px solid var(--brd)}
.sidebar-logo .logo{font-family:'Bebas Neue',sans-serif;font-size:.95rem;letter-spacing:5px;color:var(--muted2)}
.sidebar-logo .logo b{color:var(--red)}
.sidebar-pill{display:flex;align-items:center;gap:5px;margin-top:6px;font-size:.52rem;letter-spacing:2px;text-transform:uppercase;color:var(--muted)}
.sidebar-nav{flex:1;padding:12px 0;overflow-y:auto}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 18px;cursor:pointer;font-size:.62rem;letter-spacing:2px;text-transform:uppercase;color:var(--muted2);transition:color .15s,background .15s;border-left:2px solid transparent;user-select:none}
.nav-item:hover{color:var(--fg);background:rgba(237,232,223,.03)}
.nav-item.active{color:var(--fg);border-left-color:var(--red);background:rgba(230,57,70,.06)}
.nav-item svg{flex-shrink:0;opacity:.7}
.nav-item.active svg{opacity:1;color:var(--red)}
.nav-sep{height:1px;background:var(--brd);margin:8px 18px}
.nav-section{font-size:.47rem;letter-spacing:3px;text-transform:uppercase;color:var(--muted);padding:8px 18px 4px}
.sidebar-footer{padding:14px 18px;border-top:1px solid var(--brd);font-size:.52rem;color:var(--muted);letter-spacing:1px}

/* MAIN CONTENT */
.main{flex:1;margin-left:var(--sidebar);display:flex;flex-direction:column;min-height:100vh}
.topbar-mobile{display:none;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--brd);background:var(--bg2);position:sticky;top:0;z-index:40}
.topbar-mobile .logo{font-family:'Bebas Neue',sans-serif;font-size:.85rem;letter-spacing:4px;color:var(--muted2)}
.topbar-mobile .logo b{color:var(--red)}
.burger{background:none;border:none;color:var(--muted2);cursor:pointer;padding:4px;display:flex}
.content{flex:1;padding:28px 32px 40px;max-width:960px}

/* SCREEN system */
.screen{display:none}.screen.active{display:block}

/* PAGE HEADER */
.page-hdr{margin-bottom:24px}
.page-hdr h1{font-family:'Bebas Neue',sans-serif;font-size:1.6rem;letter-spacing:4px;color:var(--fg)}
.page-hdr p{font-size:.62rem;color:var(--muted);letter-spacing:1.5px;margin-top:4px}
.back-btn{display:inline-flex;align-items:center;gap:7px;font-size:.58rem;letter-spacing:2px;text-transform:uppercase;color:var(--muted);cursor:pointer;margin-bottom:16px;transition:color .15s;background:none;border:none;padding:0}
.back-btn:hover{color:var(--fg)}
.back-btn svg{opacity:.6}

/* CARDS */
.card{background:var(--bg2);border:1px solid var(--brd2);padding:20px;margin-bottom:12px;position:relative;border-radius:4px}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,var(--red),transparent 55%)}
.card-lbl{font-size:.54rem;letter-spacing:3px;text-transform:uppercase;color:var(--red);margin-bottom:14px}

/* GRID COLS */
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}

/* META CELLS */
.meta-cell{background:var(--bg3);padding:10px 12px;border-radius:3px}
.meta-k{font-size:.5rem;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:3px}
.meta-v{font-size:.78rem;font-family:'Space Mono',monospace;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* STATUS BADGE */
.status-badge{display:inline-flex;align-items:center;gap:5px;font-size:.58rem;letter-spacing:1.5px;text-transform:uppercase;padding:3px 10px;border-radius:2px}
.status-badge.run{background:var(--green-d);color:var(--green)}
.status-badge.stop{background:rgba(92,88,85,.15);color:var(--muted2)}
.status-badge.unk{background:var(--amber-d);color:var(--amber)}

/* DOT */
.dot{width:5px;height:5px;border-radius:50%;background:var(--red);animation:blink 2s infinite;flex-shrink:0}
.dot.g{background:var(--green)}.dot.a{background:var(--amber)}.dot.b{background:var(--blue)}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}

/* ACTION GRID */
.act-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:4px}
.act-btn{background:var(--bg3);border:1px solid var(--brd);padding:12px 8px;display:flex;flex-direction:column;align-items:center;gap:5px;cursor:pointer;transition:border-color .15s,background .12s,transform .08s,opacity .15s;border-radius:3px;color:var(--fg)}
.act-btn:hover{border-color:var(--brd2);background:var(--bg2)}.act-btn:active{transform:scale(.95)}
.act-btn:disabled{opacity:.3;cursor:not-allowed;pointer-events:none}
.act-btn .al{font-size:.55rem;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2)}
.act-btn.grn{border-color:rgba(74,222,128,.25)}.act-btn.grn svg{color:var(--green)}.act-btn.grn .al{color:var(--green)}
.act-btn.red{border-color:rgba(230,57,70,.25)}.act-btn.red svg{color:var(--red)}.act-btn.red .al{color:var(--red)}
.act-btn.amb{border-color:rgba(245,158,11,.25)}.act-btn.amb svg{color:var(--amber)}.act-btn.amb .al{color:var(--amber)}
.act-btn.blu{border-color:rgba(96,165,250,.25)}.act-btn.blu svg{color:var(--blue)}.act-btn.blu .al{color:var(--blue)}
.act-btn.pur{border-color:rgba(167,139,250,.25)}.act-btn.pur svg{color:var(--purple)}.act-btn.pur .al{color:var(--purple)}
.act-btn.dng{border-color:rgba(230,57,70,.35)}.act-btn.dng svg{color:var(--red)}.act-btn.dng .al{color:var(--red)}

/* INPUTS */
.ig{margin-bottom:12px}.ig label{display:block;font-size:.56rem;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.ig input,.ig textarea{width:100%;padding:10px 12px;background:var(--bg3);border:1px solid var(--brd2);color:var(--fg);font-size:.8rem;font-family:'Space Mono',monospace;outline:none;transition:border-color .2s,box-shadow .2s;border-radius:2px;resize:vertical}
.ig input:focus,.ig textarea:focus{border-color:var(--red);box-shadow:0 0 0 2px var(--red-d)}
.ig input::placeholder,.ig textarea::placeholder{color:var(--muted)}

/* BUTTONS */
.btn{width:100%;padding:11px 14px;background:transparent;border:1px solid var(--red);color:var(--fg);font-size:.64rem;font-family:'Bebas Neue',sans-serif;letter-spacing:3px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;transition:background .2s,box-shadow .15s,transform .1s;position:relative;overflow:hidden;border-radius:2px}
.btn::after{content:'';position:absolute;inset:0;background:var(--red-d);opacity:0;transition:opacity .2s}
.btn:hover::after{opacity:1}.btn:hover{box-shadow:0 0 16px var(--red-d)}.btn:active{transform:scale(.985)}.btn:disabled{opacity:.3;cursor:not-allowed;pointer-events:none}
.btn.sec{border-color:var(--brd2);color:var(--muted2)}.btn.sec::after{background:rgba(237,232,223,.04)}
.btn.grn{border-color:var(--green)}.btn.grn::after{background:var(--green-d)}
.btn.dng{border-color:var(--red)}.btn.dng::after{background:var(--red-d)}
.btn-row{display:flex;gap:8px}.btn-row .btn{flex:1}

/* FLASH */
.flash{padding:8px 11px;font-size:.64rem;letter-spacing:1px;border-left:2px solid;margin-top:8px;display:none;border-radius:0 2px 2px 0;line-height:1.5}
.flash.ok{background:var(--green-d);color:var(--green);border-color:var(--green);display:block}
.flash.err{background:var(--red-d);color:var(--red);border-color:var(--red);display:block}
.flash.info{background:var(--amber-d);color:var(--amber);border-color:var(--amber);display:block}
.flash.ai{background:var(--purple-d);color:var(--purple);border-color:var(--purple);display:block}

/* SPINNER */
.sp{width:13px;height:13px;border:2px solid rgba(237,232,223,.15);border-top-color:var(--fg);border-radius:50%;animation:spin .7s linear infinite;flex-shrink:0}
.sp.big{width:22px;height:22px;border-top-color:var(--red)}
@keyframes spin{to{transform:rotate(360deg)}}

/* LOGS BOX */
.logs-box{background:var(--bg3);border:1px solid var(--brd);border-radius:2px;padding:10px 12px;font-size:.62rem;font-family:'Space Mono',monospace;line-height:1.7;color:#b0aa9e;white-space:pre-wrap;word-break:break-all;max-height:420px;overflow-y:auto;margin-top:10px}
.logs-box::-webkit-scrollbar{width:3px}.logs-box::-webkit-scrollbar-track{background:transparent}.logs-box::-webkit-scrollbar-thumb{background:var(--brd2);border-radius:2px}

/* TERMINAL */
.term-output{background:#0d0c0b;border:1px solid var(--brd);border-radius:2px;padding:12px;font-size:.65rem;font-family:'Space Mono',monospace;line-height:1.7;color:#c8c0b0;white-space:pre-wrap;word-break:break-all;max-height:380px;overflow-y:auto;min-height:80px;margin-top:10px}
.term-output .rc-ok{color:var(--green)}.term-output .rc-err{color:var(--red)}

/* AI BOX */
.ai-box{background:var(--purple-d);border:1px solid var(--purple);border-radius:3px;padding:12px 14px;margin-top:10px}
.ai-box .ai-lbl{font-size:.52rem;letter-spacing:2.5px;text-transform:uppercase;color:var(--purple);margin-bottom:8px}
.ai-sev{font-size:.58rem;letter-spacing:1px;margin-bottom:7px;padding:3px 8px;display:inline-block;border-radius:2px}
.ai-sev.crit{background:var(--red-d);color:var(--red)}.ai-sev.warn{background:var(--amber-d);color:var(--amber)}.ai-sev.ok{background:var(--green-d);color:var(--green)}

/* SHARED LIST */
.shared-item{background:var(--bg2);border:1px solid var(--brd);padding:12px 14px;margin-bottom:6px;display:flex;align-items:center;gap:12px;cursor:pointer;transition:border-color .15s,background .15s;border-radius:3px}
.shared-item:hover{border-color:var(--brd2);background:var(--bg3)}
.sh-icon{width:34px;height:34px;background:var(--bg3);border:1px solid var(--brd2);border-radius:2px;display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--muted2)}
.sh-info{flex:1}.sh-name{font-size:.72rem}.sh-sub{font-size:.58rem;color:var(--muted);margin-top:2px}

/* CONFIRM DIALOG */
.confirm-box{background:var(--red-d);border:1px solid rgba(230,57,70,.4);border-radius:3px;padding:14px 16px;margin-top:10px}
.confirm-box p{font-size:.67rem;line-height:1.7;color:var(--fg);margin-bottom:12px}

/* AUTH SCREEN */
.auth-wrap{max-width:420px;margin:0 auto;padding:40px 20px}
.auth-head{font-family:'Bebas Neue',sans-serif;font-size:clamp(3rem,14vw,4.5rem);line-height:.9;letter-spacing:-1px;margin-bottom:8px}
.auth-head .r{color:var(--red);text-shadow:0 0 30px var(--red-g)}
.auth-sub{font-size:.56rem;letter-spacing:3px;text-transform:uppercase;color:var(--muted);margin-bottom:32px}

/* LOADING */
.loading-overlay{position:fixed;inset:0;background:var(--bg);z-index:200;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.loading-overlay .sp.big{width:24px;height:24px}
.loading-txt{font-size:.6rem;letter-spacing:3px;text-transform:uppercase;color:var(--muted)}

/* TOAST */
.toast{position:fixed;bottom:24px;right:24px;background:var(--bg2);border:1px solid var(--brd2);padding:9px 16px;font-size:.63rem;letter-spacing:1.5px;border-radius:3px;transition:opacity .25s,transform .25s;z-index:300;opacity:0;transform:translateY(8px);pointer-events:none}
.toast.show{opacity:1;transform:translateY(0)}
.toast.ok{border-color:var(--green);color:var(--green)}
.toast.err{border-color:var(--red);color:var(--red)}

/* OVERLAY (mobile sidebar) */
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:55}

/* ═══ RESPONSIVE ═══ */
@media(max-width:768px){
  .sidebar{transform:translateX(-100%)}
  .sidebar.open{transform:translateX(0)}
  .overlay.open{display:block}
  .main{margin-left:0}
  .topbar-mobile{display:flex}
  .content{padding:20px 16px 32px}
  .act-grid{grid-template-columns:repeat(2,1fr)}
  .grid-2{grid-template-columns:1fr}
  .grid-3{grid-template-columns:repeat(2,1fr)}
  .grid-4{grid-template-columns:repeat(2,1fr)}
}
@media(min-width:769px) and (max-width:1100px){
  .act-grid{grid-template-columns:repeat(3,1fr)}
}
</style>
</head>
<body>

<!-- BG -->
<div class="bg">
  <canvas id="scan"></canvas>
  <div class="bg-grid"></div>
  <div class="bg-grad"></div>
</div>

<!-- LOADING -->
<div class="loading-overlay" id="lov">
  <div class="sp big"></div>
  <div class="loading-txt" id="ltxt">ИНИЦИАЛИЗАЦИЯ...</div>
</div>

<!-- TOAST -->
<div class="toast" id="toast"></div>

<!-- APP -->
<div class="app">

  <!-- SIDEBAR -->
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-logo">
      <div class="logo">JOKY<b>HOST</b></div>
      <div class="sidebar-pill">
        <div class="dot" id="sDot"></div>
        <span id="sTxt">SYNC</span>
      </div>
    </div>
    <nav class="sidebar-nav">
      <div class="nav-section">МОЙ СЕРВЕР</div>
      <div class="nav-item" id="nav-dash" onclick="navTo('dash')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
        Обзор
      </div>
      <div class="nav-item" id="nav-manage" onclick="navTo('manage')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>
        Управление
      </div>
      <div class="nav-item" id="nav-logs" onclick="navTo('logs')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        Логи
      </div>
      <div class="nav-item" id="nav-terminal" onclick="navTo('terminal')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
        Терминал
      </div>
      <div class="nav-sep"></div>
      <div class="nav-section">ШАРИНГ</div>
      <div class="nav-item" id="nav-shared" onclick="navTo('shared')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
        Чужие серверы
      </div>
      <div class="nav-sep"></div>
      <div class="nav-section">ОПАСНАЯ ЗОНА</div>
      <div class="nav-item" id="nav-danger" onclick="navTo('danger')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <span style="color:var(--red)">Удалить / Переустановить</span>
      </div>
    </nav>
    <div class="sidebar-footer">© 2026 · JOKYHOST · @theLunatik</div>
  </aside>

  <!-- MOBILE OVERLAY -->
  <div class="overlay" id="overlay" onclick="closeSidebar()"></div>

  <!-- MAIN -->
  <div class="main">
    <!-- Mobile topbar -->
    <div class="topbar-mobile">
      <div class="logo">JOKY<b style="color:var(--red)">HOST</b></div>
      <button class="burger" onclick="openSidebar()">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
    </div>

    <div class="content">

      <!-- ══ AUTH SCREEN ══ -->
      <div class="screen" id="sAuth">
        <div class="auth-wrap">
          <div class="auth-head">JOKY<span class="r">HOST</span></div>
          <div class="auth-sub">// TELEGRAM · USERBOT · HOSTING</div>

          <div class="card" id="s0" style="display:none">
            <div class="card-lbl">// ШАГ 00 — API ДАННЫЕ</div>
            <div class="ig"><label>API ID</label><input type="number" id="apiId" placeholder="12345678" autocomplete="off"></div>
            <div class="ig"><label>API HASH</label><input type="text" id="apiHash" placeholder="0123456789abcdef..." autocomplete="off"></div>
            <div style="font-size:.58rem;color:var(--muted);margin-bottom:12px;line-height:1.6">Получите на <a href="https://my.telegram.org/apps" target="_blank" style="color:var(--red);text-decoration:none">my.telegram.org</a> → API development tools</div>
            <button class="btn" id="bSaveApi" onclick="saveApi()"><div id="bSaveApiIco" style="display:flex;align-items:center;gap:8px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>СОХРАНИТЬ И ПРОДОЛЖИТЬ</div></button>
            <div id="m0" class="flash"></div>
          </div>

          <div class="card" id="s1" style="display:none">
            <div class="card-lbl">// ШАГ 01 — НОМЕР ТЕЛЕФОНА</div>
            <div class="ig"><label>Номер телефона</label><input type="tel" id="phone" placeholder="+7 900 000 00 00" autocomplete="tel"></div>
            <button class="btn" id="bSendCode" onclick="sendCode()"><div id="bSendCodeIco" style="display:flex;align-items:center;gap:8px"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>ОТПРАВИТЬ КОД</div></button>
            <div id="m1" class="flash"></div>
          </div>

          <div class="card" id="s2" style="display:none">
            <div class="card-lbl">// ШАГ 02 — КОД ИЗ TELEGRAM</div>
            <div class="ig"><label>Код подтверждения</label><input type="text" id="code" placeholder="12345" maxlength="10" autocomplete="one-time-code"></div>
            <button class="btn" onclick="verifyCode()">ПОДТВЕРДИТЬ КОД</button>
            <div id="m2" class="flash"></div>
            <button class="btn-ghost" onclick="toggleAltAuth()" id="btnNoCode" style="margin-top:8px;width:100%;background:rgba(230,57,70,.08);border:1px solid var(--red);color:var(--red);font-family:inherit;font-size:.6rem;letter-spacing:2px;padding:9px 14px;cursor:pointer;text-transform:uppercase;transition:.2s">⚠ НЕ ПРИШЁЛ КОД</button>
            <div id="altAuth" style="display:none;margin-top:12px">
              <div style="font-size:.58rem;color:var(--muted);letter-spacing:1.5px;margin-bottom:10px;text-align:center">// АЛЬТЕРНАТИВНАЯ АВТОРИЗАЦИЯ</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                <button class="btn" id="btnLinkAuth" onclick="startLinkAuth()" style="font-size:.55rem;padding:10px 6px;letter-spacing:1.5px">
                  <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                    ПО ССЫЛКЕ
                  </div>
                </button>
                <button class="btn" id="btnQrAuth" onclick="startQrAuth()" style="font-size:.55rem;padding:10px 6px;letter-spacing:1.5px;background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid var(--border)">
                  <div style="display:flex;flex-direction:column;align-items:center;gap:4px">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="4" height="4"/></svg>
                    ПО QR-КОДУ
                  </div>
                </button>
              </div>
              <div id="mAlt" class="flash" style="margin-top:8px"></div>

              <!-- Link auth block -->
              <div id="linkAuthBlock" style="display:none;margin-top:12px;background:var(--card-bg);border:1px solid var(--border);border-radius:4px;padding:14px">
                <div style="font-size:.58rem;color:var(--muted);letter-spacing:1.5px;margin-bottom:10px">// АВТОРИЗАЦИЯ ПО ССЫЛКЕ</div>
                <button id="btnOpenLink" onclick="openTgLink()" style="display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:12px;background:linear-gradient(135deg,#0088cc,#0055aa);border:none;border-radius:4px;color:#fff;font-family:inherit;font-size:.62rem;letter-spacing:2px;cursor:pointer;margin-bottom:10px;transition:.2s" disabled>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                  ⏳ ГЕНЕРАЦИЯ...
                </button>
                <div style="background:#111;border:1px solid #2a2a2a;border-radius:3px;padding:10px;margin-bottom:10px">
                  <div style="font-size:.58rem;color:var(--muted);margin-bottom:6px;letter-spacing:1px">КАК ЭТО РАБОТАЕТ:</div>
                  <div style="font-size:.6rem;color:var(--fg);line-height:1.9">
                    1. Нажмите <b style="color:#0af">ОТКРЫТЬ В TELEGRAM</b><br>
                    2. Telegram покажет диалог — нажмите <b style="color:var(--green)">OK</b><br>
                    3. Вернитесь сюда и нажмите <b style="color:var(--green)">Я АВТОРИЗОВАЛСЯ</b>
                  </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                  <button class="btn" onclick="copyLink(document.getElementById('linkAuthUrl'))" style="font-size:.52rem;padding:8px">📋 КОПИРОВАТЬ ССЫЛКУ</button>
                  <button class="btn" onclick="checkQrDone()" style="font-size:.52rem;padding:8px;background:var(--green);color:#000">✓ Я АВТОРИЗОВАЛСЯ</button>
                </div>
                <div id="linkAuthUrl" style="display:none"></div>
              </div>

              <!-- QR auth block -->
              <div id="qrAuthBlock" style="display:none;margin-top:12px;background:var(--card-bg);border:1px solid var(--border);border-radius:4px;padding:14px;text-align:center">
                <div style="font-size:.58rem;color:var(--muted);letter-spacing:1.5px;margin-bottom:10px">// СКАНИРУЙТЕ QR-КОД ЧЕРЕЗ TELEGRAM</div>
                <div id="qrContainer" style="display:inline-block;background:#fff;padding:12px;border-radius:4px;margin-bottom:10px">
                  <canvas id="qrCanvas" width="160" height="160"></canvas>
                </div>
                <div style="font-size:.58rem;color:var(--muted);line-height:1.7;margin-bottom:10px">Telegram → Настройки → Устройства → Подключить устройство</div>
                <button class="btn" onclick="checkQrDone()" style="font-size:.55rem;padding:8px;width:100%;background:var(--green);color:#000">✓ Я АВТОРИЗОВАЛСЯ</button>
              </div>
            </div>
          </div>

          <div class="card" id="s3" style="display:none">
            <div class="card-lbl">// ШАГ 03 — 2FA</div>
            <div class="ig"><label>Пароль 2FA</label><input type="password" id="passwd" placeholder="••••••••"></div>
            <button class="btn" onclick="verify2FA()">ВОЙТИ</button>
            <div id="m3" class="flash"></div>
          </div>

          <div class="card" id="s4" style="display:none">
            <div style="text-align:center;padding:20px 0">
              <div style="font-family:'Bebas Neue',sans-serif;font-size:3rem;color:var(--green);letter-spacing:4px">OK</div>
              <div style="font-size:.62rem;letter-spacing:3px;text-transform:uppercase;color:var(--fg);margin-top:6px">АВТОРИЗАЦИЯ УСПЕШНА</div>
              <div style="font-size:.64rem;color:var(--muted);margin-top:10px;line-height:1.7">Вернитесь в бот и нажмите<br>«Я авторизовался»</div>
            </div>
          </div>
        </div>
      </div>

      <!-- ══ DASH SCREEN ══ -->
      <div class="screen" id="sDash">
        <div class="page-hdr"><h1>ОБЗОР</h1><p>// СТАТУС ВАШЕГО СЕРВЕРА</p></div>
        <div id="dashContent"><div style="display:flex;align-items:center;gap:10px;color:var(--muted);font-size:.65rem"><div class="sp"></div> Загрузка...</div></div>
      </div>

      <!-- ══ MANAGE SCREEN ══ -->
      <div class="screen" id="sManage">
        <div class="page-hdr"><h1>УПРАВЛЕНИЕ</h1><p>// ДЕЙСТВИЯ С КОНТЕЙНЕРОМ</p></div>
        <div id="manageContent"></div>
      </div>

      <!-- ══ LOGS SCREEN ══ -->
      <div class="screen" id="sLogs">
        <div class="page-hdr"><h1>ЛОГИ</h1><p>// ВЫВОД DOCKER-КОНТЕЙНЕРА</p></div>
        <div id="logsContent"></div>
      </div>

      <!-- ══ TERMINAL SCREEN ══ -->
      <div class="screen" id="sTerminal">
        <div class="page-hdr"><h1>ТЕРМИНАЛ</h1><p>// ВЫПОЛНЕНИЕ КОМАНД ВНУТРИ КОНТЕЙНЕРА</p></div>
        <div id="termContent"></div>
      </div>

      <!-- ══ SHARED SCREEN ══ -->
      <div class="screen" id="sShared">
        <div class="page-hdr"><h1>ШАРИНГ</h1><p>// ДОСТУПНЫЕ ЧУЖИЕ СЕРВЕРЫ</p></div>
        <div id="sharedListContent"></div>
      </div>

      <!-- ══ SHARED MANAGE SCREEN ══ -->
      <div class="screen" id="sSharedManage">
        <button class="back-btn" onclick="navTo('shared')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
          НАЗАД К ШАРИНГУ
        </button>
        <div class="page-hdr"><h1 id="sharedManageTitle">СЕРВЕР</h1><p>// УПРАВЛЕНИЕ ЧУЖИМ СЕРВЕРОМ</p></div>
        <div id="sharedManageContent"></div>
      </div>

      <!-- ══ DANGER SCREEN ══ -->
      <div class="screen" id="sDanger">
        <div class="page-hdr"><h1>ОПАСНАЯ ЗОНА</h1><p>// НЕОБРАТИМЫЕ ДЕЙСТВИЯ</p></div>
        <div id="dangerContent"></div>
      </div>

    </div><!-- /content -->
  </div><!-- /main -->
</div><!-- /app -->

<script>
// ── BG scan ──
(function(){
  const c=document.getElementById('scan'),ctx=c.getContext('2d');
  let W,H,y=0;
  function r(){W=c.width=window.innerWidth;H=c.height=window.innerHeight}
  r();window.addEventListener('resize',r);
  (function draw(){
    ctx.clearRect(0,0,W,H);
    const g=ctx.createLinearGradient(0,y-100,0,y+100);
    g.addColorStop(0,'transparent');g.addColorStop(.5,'rgba(230,57,70,.03)');g.addColorStop(1,'transparent');
    ctx.fillStyle=g;ctx.fillRect(0,y-100,W,200);
    y+=0.4;if(y>H+100)y=-100;
    requestAnimationFrame(draw);
  })();
})();

// ── State ──
const tg=window.Telegram.WebApp;tg.ready();
let userId=0,waToken='',actionMode='create',dashData=null,currentSharedOwner=null;
function qp(n){return new URLSearchParams(location.search).get(n)}

// ── Sidebar ──
function openSidebar(){document.getElementById('sidebar').classList.add('open');document.getElementById('overlay').classList.add('open')}
function closeSidebar(){document.getElementById('sidebar').classList.remove('open');document.getElementById('overlay').classList.remove('open')}

// ── Toast ──
let _tt;
function toast(msg,type='ok'){
  const el=document.getElementById('toast');
  el.textContent=msg;el.className='toast show '+(type==='ok'?'ok':'err');
  clearTimeout(_tt);_tt=setTimeout(()=>el.classList.remove('show'),2600);
}

// ── Pill ──
function setPill(txt,color){
  document.getElementById('sTxt').textContent=txt;
  const d=document.getElementById('sDot');
  d.className='dot'+(color?' '+color:'');
}

// ── Flash ──
function flash(id,text,type){const el=document.getElementById(id);if(!el)return;el.className='flash '+type;el.innerHTML=text}

// ── Loading ──
function ltxt(t){document.getElementById('ltxt').textContent=t}
function hideLoading(){const ol=document.getElementById('lov');ol.style.transition='opacity .3s';ol.style.opacity='0';setTimeout(()=>ol.style.display='none',300)}

// ── Screen ──
const SCREENS=['sAuth','sDash','sManage','sLogs','sTerminal','sShared','sSharedManage','sDanger'];
function showScreen(id){SCREENS.forEach(s=>{const el=document.getElementById(s);if(el)el.className='screen'+(s===id?' active':'')});closeSidebar()}

// ── Nav ──
const NAV_MAP={dash:'sDash',manage:'sManage',logs:'sLogs',terminal:'sTerminal',shared:'sShared',danger:'sDanger'};
const NAV_LOADERS={dash:loadDash,manage:loadManage,logs:loadLogsScreen,terminal:loadTerminal,shared:loadShared,danger:loadDanger};
function navTo(page){
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.remove('active'));
  const ni=document.getElementById('nav-'+page);if(ni)ni.classList.add('active');
  showScreen(NAV_MAP[page]);
  if(NAV_LOADERS[page])NAV_LOADERS[page]();
  closeSidebar();
}

// ── Status helpers ──
function stCls(s){return s==='running'?'run':s==='exited'?'stop':'unk'}
function stLbl(s){return s==='running'?'РАБОТАЕТ':s==='exited'?'ОСТАНОВЛЕН':'НЕИЗВЕСТНО'}
function dotCol(s){return s==='running'?'g':s==='exited'?'':'a'}

// ── Icons ──
const IC={
  start:'<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
  stop:'<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>',
  restart:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
  logs:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
  term:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
  ai:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>',
  trash:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>',
  reload:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
  srv:'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>',
};

// ══════ API HELPERS ══════
async function api(path,body){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-WA-Token':waToken},body:JSON.stringify({user_id:userId,...body})});
  return r.json();
}

// ══════ DASHBOARD ══════
async function loadDash(){
  document.getElementById('dashContent').innerHTML='<div style="display:flex;align-items:center;gap:10px;color:var(--muted);font-size:.65rem"><div class="sp"></div> Загрузка...</div>';
  try{
    dashData=await api('/api/dashboard',{});
    renderDash();
  }catch(e){
    document.getElementById('dashContent').innerHTML='<div style="color:var(--red);font-size:.65rem">Ошибка загрузки</div>';
  }
}

function renderDash(){
  const d=dashData;
  if(!d.has_server){
    document.getElementById('dashContent').innerHTML=`
      <div class="card" style="text-align:center;padding:32px 20px">
        <div style="color:var(--muted);margin-bottom:12px">${IC.srv}</div>
        <div style="font-family:'Bebas Neue',sans-serif;font-size:1.1rem;letter-spacing:3px;color:var(--muted2)">СЕРВЕР НЕ СОЗДАН</div>
        <div style="font-size:.62rem;color:var(--muted);margin-top:8px;line-height:1.7">Создайте сервер через Telegram бота</div>
      </div>`;
    return;
  }
  const sc=stCls(d.container_status),sl=stLbl(d.container_status);
  // Дней до истечения
  let daysLeft='—',daysColor='var(--muted2)';
  if(d.expires_at){
    const diff=Math.ceil((new Date(d.expires_at)-new Date())/(1000*60*60*24));
    daysLeft=diff>0?diff+' дн.':'ИСТЁК';
    daysColor=diff<=7?'var(--red)':diff<=14?'var(--amb)':'var(--grn)';
  }
  // История платежей
  const pays=d.payments||[];
  const statusLabel={approved:'✅ Принят',pending:'⏳ Ожидает',rejected:'❌ Отклонён'};
  const paysHTML=pays.length?pays.map(p=>`
    <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--brd);font-size:.6rem">
      <div style="color:var(--muted2)">${p.created_at.slice(0,10)}</div>
      <div style="color:var(--muted2)">${p.months} мес. · ${p.amount} ₽</div>
      <div style="color:var(--muted)">${statusLabel[p.status]||p.status}</div>
    </div>`).join('')
    :'<div style="color:var(--muted);font-size:.6rem;padding:8px 0">Нет платежей</div>';
  document.getElementById('dashContent').innerHTML=`
    <div class="card">
      <div class="card-lbl">// МОЙ СЕРВЕР</div>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
        <div style="font-family:'Bebas Neue',sans-serif;font-size:1.1rem;letter-spacing:3px">USERBOT</div>
        <div class="status-badge ${sc}"><div class="dot ${dotCol(d.container_status)}"></div>${sl}</div>
      </div>
      <div class="grid-4" style="margin-bottom:4px">
        <div class="meta-cell"><div class="meta-k">ПОРТ</div><div class="meta-v">${d.port||'—'}</div></div>
        <div class="meta-cell"><div class="meta-k">ИСТЕКАЕТ</div><div class="meta-v" style="color:${daysColor}">${d.expires_at||'—'}</div></div>
        <div class="meta-cell"><div class="meta-k">ОСТАЛОСЬ</div><div class="meta-v" style="color:${daysColor}">${daysLeft}</div></div>
        <div class="meta-cell"><div class="meta-k">БАЛАНС</div><div class="meta-v" style="color:var(--grn)">${d.balance||0} ₽</div></div>
      </div>
    </div>
    <div class="card">
      <div class="card-lbl">// РЕСУРСЫ</div>
      <div class="grid-4">
        <div class="meta-cell"><div class="meta-k">CPU</div><div class="meta-v">${d.stats&&d.stats.cpu?d.stats.cpu:'—'}</div></div>
        <div class="meta-cell"><div class="meta-k">RAM</div><div class="meta-v">${d.stats&&d.stats.mem_p?d.stats.mem_p:'—'}</div></div>
        <div class="meta-cell"><div class="meta-k">RAM МБ</div><div class="meta-v">${d.stats&&d.stats.mem_mb?d.stats.mem_mb+' MB':'—'}</div></div>
        <div class="meta-cell"><div class="meta-k">ЛИМИТ</div><div class="meta-v">650 MB</div></div>
      </div>
    </div>
    <div class="card">
      <div class="card-lbl">// ИСТОРИЯ ПЛАТЕЖЕЙ</div>
      ${paysHTML}
    </div>`;
}

// ══════ MANAGE SCREEN ══════
function loadManage(){
  if(!dashData||!dashData.has_server){
    document.getElementById('manageContent').innerHTML='<div style="color:var(--muted);font-size:.65rem">Сначала загрузите данные сервера (перейдите в Обзор)</div>';
    return;
  }
  const d=dashData;
  const sc=stCls(d.container_status),sl=stLbl(d.container_status);
  document.getElementById('manageContent').innerHTML=`
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
        <div class="card-lbl" style="margin:0">// КОНТЕЙНЕР</div>
        <div class="status-badge ${sc}"><div class="dot ${dotCol(d.container_status)}"></div>${sl}</div>
      </div>
      <div class="act-grid" id="manageGrid">
        <button class="act-btn grn" onclick="serverAction('start')">
          ${IC.start}<span class="al">ЗАПУСТИТЬ</span>
        </button>
        <button class="act-btn red" onclick="serverAction('stop')">
          ${IC.stop}<span class="al">ОСТАНОВИТЬ</span>
        </button>
        <button class="act-btn amb" onclick="serverAction('restart')">
          ${IC.restart}<span class="al">ПЕРЕЗАПУСТИТЬ</span>
        </button>
        <button class="act-btn blu" onclick="navTo('logs')">
          ${IC.logs}<span class="al">ЛОГИ</span>
        </button>
        <button class="act-btn pur" onclick="navTo('terminal')">
          ${IC.term}<span class="al">ТЕРМИНАЛ</span>
        </button>
      </div>
      <div id="manageResult" style="margin-top:12px"></div>
    </div>`;
}

async function serverAction(action,targetId=null,type='own'){
  const id=targetId||userId;
  const grid=document.getElementById(type==='own'?'manageGrid':'sharedActGrid');
  if(grid)grid.querySelectorAll('button').forEach(b=>{b.disabled=true});
  const resultEl=document.getElementById(type==='own'?'manageResult':'sharedActResult');
  const _actLabels={start:'Запускаем...',stop:'Останавливаем...',restart:'Перезапускаем...'};
  if(resultEl)resultEl.innerHTML=`<div style="display:flex;align-items:center;gap:8px;font-size:.63rem;color:var(--muted)"><div class="sp"></div>${_actLabels[action]||'Выполняем...'}</div>`;
  try{
    const d=await api('/api/server_action',{target_id:id,action,type});
    if(resultEl){
      const cls=d.success?'ok':'err';
      resultEl.innerHTML=`<div class="flash ${cls}">${d.message||'OK'}</div>`;
    }
    if(d.success)toast(d.message||'OK','ok');else toast(d.message||'ОШИБКА','err');
    setTimeout(()=>{loadDash();if(type==='own')loadManage();},1200);
  }catch(e){
    if(resultEl)resultEl.innerHTML='<div class="flash err">ОШИБКА СЕТИ</div>';
    toast('ОШИБКА СЕТИ','err');
  }finally{
    setTimeout(()=>{if(grid)grid.querySelectorAll('button').forEach(b=>{b.disabled=false})},1200);
  }
}

// Quick action from dash
async function doAction(type,action,targetId){
  const grid=document.querySelector('#dashContent .act-grid');
  if(grid)grid.querySelectorAll('button').forEach(b=>b.disabled=true);
  toast({start:'ЗАПУСК...',stop:'СТОП...',restart:'РЕСТАРТ...'}[action]||'...','ok');
  try{
    const d=await api('/api/server_action',{target_id:targetId,action,type});
    if(d.success)toast(d.message||'OK','ok');else toast(d.message||'ОШИБКА','err');
    setTimeout(loadDash,1000);
  }catch(e){toast('ОШИБКА СЕТИ','err')}
  finally{setTimeout(()=>{if(grid)grid.querySelectorAll('button').forEach(b=>b.disabled=false)},1200)}
}

// ══════ LOGS SCREEN ══════
function loadLogsScreen(){
  const el=document.getElementById('logsContent');
  el.innerHTML=`
    <div class="card">
      <div class="card-lbl">// DOCKER LOGS (60 СТРОК)</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <button class="btn sec" style="width:auto;padding:7px 14px;font-size:.6rem" onclick="fetchLogs('own',${userId})">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          ОБНОВИТЬ
        </button>
        <button class="btn" style="width:auto;padding:7px 14px;font-size:.6rem;border-color:var(--purple);color:var(--purple)" onclick="fetchAiDiagnose('own',${userId})">
          ${IC.ai} ДИАГНОСТИКА AI
        </button>
      </div>
      <div id="logsBox" class="logs-box">Загрузка...</div>
      <div id="aiBox"></div>
    </div>`;
  fetchLogs('own',userId);
}

async function fetchLogs(type,targetId){
  const box=document.getElementById('logsBox');
  if(box)box.textContent='Загрузка...';
  try{
    const d=await api('/api/server_logs',{target_id:targetId,type});
    const logs=d.success?(d.logs||'(нет данных)'):('ОШИБКА: '+(d.message||''));
    if(box)box.textContent=logs;
    // auto scroll to bottom
    if(box){box.scrollTop=box.scrollHeight}
  }catch(e){if(box)box.textContent='ОШИБКА СОЕДИНЕНИЯ'}
}

async function fetchAiDiagnose(type,targetId){
  const box=document.getElementById('aiBox');
  if(!box)return;
  box.innerHTML=`<div class="flash ai" style="display:flex;align-items:center;gap:8px"><div class="sp"></div>АНАЛИЗИРУЮ ЛОГИ...</div>`;
  try{
    const d=await api('/api/ai_diagnose',{target_id:targetId,type});
    if(!d.success){box.innerHTML=`<div class="flash err">ОШИБКА: ${d.message||'неизвестно'}</div>`;return}
    const sev=d.critical?'crit':(d.solution?'warn':'ok');
    const sevLbl=d.critical?'🔴 КРИТИЧНО':(d.solution?'🟡 ПРЕДУПРЕЖДЕНИЕ':'🟢 НОРМА');
    box.innerHTML=`<div class="ai-box">
      <div class="ai-lbl">// 🤖 ДИАГНОСТИКА AI</div>
      <div class="ai-sev ${sev}">${sevLbl}</div>
      <div style="font-size:.67rem;line-height:1.7;margin-bottom:${d.solution?'10px':'0'}">${esc(d.summary||'Анализ завершён')}</div>
      ${d.solution?`<div style="font-size:.57rem;letter-spacing:1.5px;text-transform:uppercase;color:var(--amber);margin-bottom:5px">// КАК ИСПРАВИТЬ</div><div style="font-size:.65rem;line-height:1.7">${esc(d.solution)}</div>`:''}
    </div>`;
  }catch(e){box.innerHTML='<div class="flash err">ОШИБКА СОЕДИНЕНИЯ</div>'}
}

// ══════ TERMINAL SCREEN ══════
function loadTerminal(){
  document.getElementById('termContent').innerHTML=`
    <div class="card">
      <div class="card-lbl">// ВЫПОЛНЕНИЕ КОМАНД В КОНТЕЙНЕРЕ</div>
      <div style="font-size:.6rem;color:var(--muted);margin-bottom:14px;line-height:1.7">
        Команды выполняются от пользователя <code style="color:var(--amber)">nobody</code> внутри Docker-контейнера.<br>
        Опасные команды (rm -rf /, mkfs и т.д.) заблокированы.
      </div>
      <div class="ig">
        <label>КОМАНДА</label>
        <textarea id="termCmd" placeholder="ls /app&#10;cat /app/config.json&#10;ps aux" rows="3" onkeydown="termKeydown(event)"></textarea>
      </div>
      <button class="btn" id="termRunBtn" onclick="runTermCmd('own',${userId})">
        ${IC.term} ВЫПОЛНИТЬ
      </button>
      <div id="termHistory"></div>
    </div>`;
}

function termKeydown(e){
  if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();runTermCmd('own',userId)}
}

async function runTermCmd(type,targetId){
  const cmdEl=document.getElementById('termCmd');
  const btn=document.getElementById('termRunBtn');
  const history=document.getElementById('termHistory');
  if(!cmdEl||!btn||!history)return;
  const cmd=cmdEl.value.trim();
  if(!cmd)return;
  btn.disabled=true;btn.innerHTML='<div class="sp"></div> ВЫПОЛНЯЮ...';
  try{
    const d=await api('/api/terminal',{target_id:targetId,cmd,type});
    const rcCls=d.rc===0?'rc-ok':'rc-err';
    const entry=document.createElement('div');
    entry.style.marginTop='14px';
    entry.innerHTML=`
      <div style="font-size:.52rem;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-bottom:4px">// ${esc(cmd.substring(0,60))}${cmd.length>60?'...':''}</div>
      <div class="term-output"><span class="${d.success?rcCls:'rc-err'}">${esc(d.success?(d.output||'(нет вывода)'):(d.message||'ОШИБКА'))}</span></div>`;
    history.prepend(entry);
    cmdEl.value='';
  }catch(e){
    const entry=document.createElement('div');
    entry.innerHTML='<div class="flash err" style="margin-top:10px">ОШИБКА СЕТИ</div>';
    history.prepend(entry);
  }finally{
    btn.disabled=false;btn.innerHTML=IC.term+' ВЫПОЛНИТЬ';
  }
}

// ══════ SHARED SCREEN ══════
function loadShared(){
  const el=document.getElementById('sharedListContent');
  if(!dashData){el.innerHTML='<div style="color:var(--muted);font-size:.65rem">Перейдите в Обзор для загрузки данных</div>';return}
  const servers=dashData.shared_servers||[];
  if(!servers.length){
    el.innerHTML='<div class="card" style="text-align:center;padding:28px 20px"><div style="font-size:.65rem;color:var(--muted)">Вам не открыт доступ ни к одному серверу</div></div>';
    return;
  }
  el.innerHTML=servers.map(s=>`
    <div class="shared-item" onclick="openSharedManage(${s.owner_id})">
      <div class="sh-icon">${IC.srv}</div>
      <div class="sh-info">
        <div class="sh-name">СЕРВЕР #${s.owner_id}</div>
        <div class="sh-sub">ПОРТ ${s.port||'—'}</div>
      </div>
      <div class="status-badge ${stCls(s.container_status)}">${stLbl(s.container_status)}</div>
    </div>`).join('');
}

function openSharedManage(ownerId){
  currentSharedOwner=ownerId;
  const s=dashData&&dashData.shared_servers&&dashData.shared_servers.find(x=>x.owner_id===ownerId);
  document.getElementById('sharedManageTitle').textContent='СЕРВЕР #'+ownerId;
  document.getElementById('sharedManageContent').innerHTML=`
    <div class="card">
      <div class="card-lbl">// УПРАВЛЕНИЕ СЕРВЕРОМ #${ownerId}</div>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
        <div style="font-size:.7rem">ВЛАДЕЛЕЦ: <code>${ownerId}</code></div>
        ${s?`<div class="status-badge ${stCls(s.container_status)}">${stLbl(s.container_status)}</div>`:''}
      </div>
      <div class="act-grid" id="sharedActGrid">
        <button class="act-btn grn" onclick="serverAction('start',${ownerId},'shared')">
          ${IC.start}<span class="al">ЗАПУСТИТЬ</span>
        </button>
        <button class="act-btn red" onclick="serverAction('stop',${ownerId},'shared')">
          ${IC.stop}<span class="al">СТОП</span>
        </button>
        <button class="act-btn amb" onclick="serverAction('restart',${ownerId},'shared')">
          ${IC.restart}<span class="al">РЕСТАРТ</span>
        </button>
        <button class="act-btn blu" onclick="loadSharedLogs(${ownerId})">
          ${IC.logs}<span class="al">ЛОГИ</span>
        </button>
      </div>
      <div id="sharedActResult" style="margin-top:10px"></div>
    </div>
    <div class="card" id="sharedLogsCard" style="display:none">
      <div class="card-lbl">// ЛОГИ СЕРВЕРА #${ownerId}</div>
      <div style="display:flex;gap:8px;margin-bottom:4px;flex-wrap:wrap">
        <button class="btn sec" style="width:auto;padding:7px 14px;font-size:.6rem" onclick="loadSharedLogs(${ownerId})">↺ ОБНОВИТЬ</button>
        <button class="btn" style="width:auto;padding:7px 14px;font-size:.6rem;border-color:var(--purple);color:var(--purple)" onclick="fetchSharedAi(${ownerId})">🤖 AI</button>
      </div>
      <div id="sharedLogsBox" class="logs-box">Нажмите ЛОГИ выше</div>
      <div id="sharedAiBox"></div>
    </div>`;
  showScreen('sSharedManage');
}

async function loadSharedLogs(ownerId){
  const card=document.getElementById('sharedLogsCard');
  const box=document.getElementById('sharedLogsBox');
  if(card)card.style.display='';
  if(box)box.textContent='Загрузка...';
  try{
    const d=await api('/api/server_logs',{target_id:ownerId,type:'shared'});
    if(box)box.textContent=d.success?(d.logs||'(нет данных)'):('ОШИБКА: '+(d.message||''));
    if(box)box.scrollTop=box.scrollHeight;
  }catch(e){if(box)box.textContent='ОШИБКА СОЕДИНЕНИЯ'}
}

async function fetchSharedAi(ownerId){
  const box=document.getElementById('sharedAiBox');
  if(!box)return;
  box.innerHTML=`<div class="flash ai" style="display:flex;align-items:center;gap:8px"><div class="sp"></div>АНАЛИЗИРУЮ...</div>`;
  try{
    const d=await api('/api/ai_diagnose',{target_id:ownerId,type:'shared'});
    if(!d.success){box.innerHTML=`<div class="flash err">${d.message||'ОШИБКА'}</div>`;return}
    const sev=d.critical?'crit':(d.solution?'warn':'ok');
    box.innerHTML=`<div class="ai-box"><div class="ai-lbl">// 🤖 AI</div><div class="ai-sev ${sev}">${d.critical?'🔴 КРИТИЧНО':(d.solution?'🟡 ПРЕДУПРЕЖДЕНИЕ':'🟢 НОРМА')}</div><div style="font-size:.66rem;line-height:1.7">${esc(d.summary||'')}</div>${d.solution?`<div style="font-size:.64rem;line-height:1.7;margin-top:8px;color:var(--amber)">${esc(d.solution)}</div>`:''}</div>`;
  }catch(e){box.innerHTML='<div class="flash err">ОШИБКА</div>'}
}

// ══════ DANGER SCREEN ══════
function loadDanger(){
  document.getElementById('dangerContent').innerHTML=`
    <div class="card" style="border-color:rgba(230,57,70,.3)">
      <div class="card-lbl" style="color:var(--red)">// 🔄 ПЕРЕУСТАНОВКА СЕРВЕРА</div>
      <p style="font-size:.65rem;color:var(--muted2);line-height:1.7;margin-bottom:14px">
        Контейнер будет пересоздан с чистого образа.<br>
        <span style="color:var(--green)">✓ Сохраняется:</span> сессия, конфиг (папка ID/), порт, дата подписки.<br>
        <span style="color:var(--amber)">⚠ Пересоздаётся:</span> Docker-контейнер и образ.
      </p>
      <div id="reinstallConfirm" style="display:none" class="confirm-box">
        <p>⚠️ Подтвердите переустановку. Контейнер будет остановлен и пересоздан.</p>
        <div class="btn-row">
          <button class="btn grn" onclick="doReinstall()">✓ ПЕРЕУСТАНОВИТЬ</button>
          <button class="btn sec" onclick="hideConfirm('reinstall')">ОТМЕНА</button>
        </div>
      </div>
      <div id="reinstallResult"></div>
      <button class="btn amb" id="reinstallBtn" onclick="showConfirm('reinstall')">${IC.reload} ПЕРЕУСТАНОВИТЬ</button>
    </div>

    <div class="card" style="border-color:rgba(230,57,70,.5);margin-top:16px">
      <div class="card-lbl" style="color:var(--red)">// 🗑 ПОЛНОЕ УДАЛЕНИЕ СЕРВЕРА</div>
      <p style="font-size:.65rem;color:var(--muted2);line-height:1.7;margin-bottom:14px">
        Это действие <strong style="color:var(--red)">НЕОБРАТИМО</strong>.<br>
        <span style="color:var(--red)">✗ Удаляется:</span> Docker-контейнер, образ, ВСЕ файлы (включая сессию), запись в БД.
      </p>
      <div id="deleteConfirm" style="display:none" class="confirm-box">
        <p>⚠️ Вы уверены? Все данные будут удалены безвозвратно. Восстановление невозможно.</p>
        <div class="btn-row">
          <button class="btn dng" onclick="doDelete()">🗑 ДА, УДАЛИТЬ ВСЁ</button>
          <button class="btn sec" onclick="hideConfirm('delete')">ОТМЕНА</button>
        </div>
      </div>
      <div id="deleteResult"></div>
      <button class="btn dng" id="deleteBtn" onclick="showConfirm('delete')">${IC.trash} УДАЛИТЬ СЕРВЕР</button>
    </div>`;
}

function showConfirm(type){
  document.getElementById(type+'Confirm').style.display='block';
  document.getElementById(type+'Btn').style.display='none';
}
function hideConfirm(type){
  document.getElementById(type+'Confirm').style.display='none';
  document.getElementById(type+'Btn').style.display='flex';
}

async function doReinstall(){
  const res=document.getElementById('reinstallResult');
  document.getElementById('reinstallConfirm').style.display='none';
  res.innerHTML='<div style="display:flex;align-items:center;gap:8px;font-size:.63rem;color:var(--muted);margin-top:10px"><div class="sp"></div>Переустанавливаем... это может занять 1-2 минуты</div>';
  document.getElementById('reinstallBtn').style.display='none';
  try{
    const d=await api('/api/reinstall_server',{});
    if(d.success){
      res.innerHTML=`<div class="flash ok">✅ Сервер переустановлен! Порт: ${d.port||'—'}, активен до: ${d.expires_at||'—'}</div>`;
      setTimeout(loadDash,1000);
    } else {
      res.innerHTML=`<div class="flash err">ОШИБКА: ${d.message||'неизвестно'}</div>`;
      document.getElementById('reinstallBtn').style.display='flex';
    }
  }catch(e){
    res.innerHTML='<div class="flash err">ОШИБКА СЕТИ</div>';
    document.getElementById('reinstallBtn').style.display='flex';
  }
}

async function doDelete(){
  const res=document.getElementById('deleteResult');
  document.getElementById('deleteConfirm').style.display='none';
  res.innerHTML='<div style="display:flex;align-items:center;gap:8px;font-size:.63rem;color:var(--muted);margin-top:10px"><div class="sp"></div>Удаляем сервер...</div>';
  document.getElementById('deleteBtn').style.display='none';
  try{
    const d=await api('/api/delete_server',{});
    if(d.success){
      res.innerHTML='<div class="flash ok">✅ Сервер полностью удалён. Создайте новый через бота.</div>';
      dashData=null;
    } else {
      res.innerHTML=`<div class="flash err">ОШИБКА: ${d.message||'неизвестно'}</div>`;
      document.getElementById('deleteBtn').style.display='flex';
    }
  }catch(e){
    res.innerHTML='<div class="flash err">ОШИБКА СЕТИ</div>';
    document.getElementById('deleteBtn').style.display='flex';
  }
}

// ══════ AUTH ══════
async function saveApi(){
  const btn=document.getElementById('bSaveApi'),ai=document.getElementById('apiId').value.trim(),ah=document.getElementById('apiHash').value.trim();
  if(!ai||!ah){flash('m0','// ЗАПОЛНИТЕ ОБА ПОЛЯ','err');return}
  if(!/^\\d+$/.test(ai)){flash('m0','// API ID ДОЛЖЕН БЫТЬ ЧИСЛОМ','err');return}
  if(ah.length<10){flash('m0','// НЕКОРРЕКТНЫЙ API HASH','err');return}
  btn.disabled=true;document.getElementById('bSaveApiIco').innerHTML='<div class="sp"></div> СОХРАНЕНИЕ...';
  try{
    const d=await api('/api/set_api_credentials',{api_id:ai,api_hash:ah,action:actionMode});
    if(d.success){document.getElementById('s0').style.display='none';document.getElementById('s1').style.display='block';flash('m1','// API СОХРАНЕНЫ · ВВЕДИТЕ ТЕЛЕФОН','ok')}
    else{flash('m0',d.message||'// ОШИБКА','err');btn.disabled=false;document.getElementById('bSaveApiIco').innerHTML='СОХРАНИТЬ И ПРОДОЛЖИТЬ'}
  }catch(e){flash('m0','// ОШИБКА СЕТИ','err');btn.disabled=false;document.getElementById('bSaveApiIco').innerHTML='СОХРАНИТЬ И ПРОДОЛЖИТЬ'}
}

async function sendCode(){
  const btn=document.getElementById('bSendCode'),ph=document.getElementById('phone').value.trim();
  if(!ph){flash('m1','// ВВЕДИТЕ НОМЕР','err');return}
  btn.disabled=true;document.getElementById('bSendCodeIco').innerHTML='<div class="sp"></div> ОТПРАВКА...';
  try{
    const d=await api('/api/send_code',{phone:ph,action:actionMode});
    if(d.success){document.getElementById('s1').style.display='none';document.getElementById('s2').style.display='block';flash('m2','// КОД ОТПРАВЛЕН','ok')}
    else{flash('m1',d.message||'// ОШИБКА','err');btn.disabled=false;document.getElementById('bSendCodeIco').innerHTML='ОТПРАВИТЬ КОД'}
  }catch(e){flash('m1','// ОШИБКА СЕТИ','err');btn.disabled=false;document.getElementById('bSendCodeIco').innerHTML='ОТПРАВИТЬ КОД'}
}

async function verifyCode(){
  flash('m2','// ПРОВЕРЯЕМ...','info');
  try{
    const d=await api('/api/verify_code',{code:document.getElementById('code').value.trim(),action:actionMode});
    if(d.success){document.getElementById('s2').style.display='none';document.getElementById('s4').style.display='block'}
    else if(d.need_password){document.getElementById('s2').style.display='none';document.getElementById('s3').style.display='block'}
    else flash('m2',d.message||'// НЕВЕРНЫЙ КОД','err');
  }catch(e){flash('m2','// ОШИБКА','err')}
}

async function verify2FA(){
  flash('m3','// ПРОВЕРЯЕМ ПАРОЛЬ...','info');
  try{
    const d=await api('/api/verify_password',{password:document.getElementById('passwd').value,action:actionMode});
    if(d.success){document.getElementById('s3').style.display='none';document.getElementById('s4').style.display='block'}
    else flash('m3',d.message||'// НЕВЕРНЫЙ ПАРОЛЬ','err');
  }catch(e){flash('m3','// ОШИБКА','err')}
}

// ══════ ALT AUTH (no code) ══════
let _altOpen = false;
let _qrToken = null;
let _qrPollTimer = null;
let _altCdUntil = 0; // cooldown timestamp

function _altCd(btnId, sec){
  const btn = document.getElementById(btnId);
  if(!btn) return;
  _altCdUntil = Date.now() + sec*1000;
  btn.disabled = true;
  const orig = btn.innerHTML;
  let t = sec;
  btn.innerHTML = `⏳ ${t}с`;
  const iv = setInterval(()=>{
    t--;
    if(t<=0){ clearInterval(iv); btn.disabled=false; btn.innerHTML=orig; }
    else btn.innerHTML=`⏳ ${t}с`;
  },1000);
}

function toggleAltAuth(){
  _altOpen = !_altOpen;
  document.getElementById('altAuth').style.display = _altOpen ? 'block' : 'none';
}

async function startLinkAuth(){
  if(Date.now() < _altCdUntil){ flash('mAlt','// ПОДОЖДИТЕ ПЕРЕД ПОВТОРНЫМ ЗАПРОСОМ','err'); return; }
  document.getElementById('linkAuthBlock').style.display = 'block';
  document.getElementById('qrAuthBlock').style.display = 'none';
  document.getElementById('linkAuthUrl').textContent = '';
  const btn = document.getElementById('btnOpenLink');
  btn.disabled = true;
  btn.innerHTML = '<div class="sp" style="border-color:#fff3;border-top-color:#fff;width:10px;height:10px"></div> ГЕНЕРАЦИЯ...';
  flash('mAlt','// ГЕНЕРИРУЕМ ССЫЛКУ...','info');
  _altCd('btnLinkAuth', 12);
  try{
    const d = await api('/api/qr_login',{action:actionMode});
    if(d.success && d.url){
      _qrToken = d.token;
      document.getElementById('linkAuthUrl').textContent = d.url;
      btn.disabled = false;
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg> ОТКРЫТЬ В TELEGRAM';
      flash('mAlt','// ССЫЛКА ГОТОВА · НАЖМИТЕ КНОПКУ ВЫШЕ','ok');
      _startQrPoll();
    } else {
      btn.innerHTML = '❌ ОШИБКА — ПОПРОБУЙТЕ ЕЩЁ РАЗ';
      flash('mAlt', d.message||'// ОШИБКА ГЕНЕРАЦИИ','err');
    }
  }catch(e){
    btn.innerHTML = '❌ ОШИБКА СЕТИ';
    flash('mAlt','// ОШИБКА СЕТИ','err');
  }
}

function openTgLink(){
  const url = document.getElementById('linkAuthUrl').textContent;
  if(!url) return;
  // В Telegram WebView window.location не работает для tg:// — используем SDK
  try {
    if(tg && tg.openLink) { tg.openLink(url); return; }
  } catch(e){}
  // Fallback — создаём невидимую ссылку и кликаем
  const a = document.createElement('a');
  a.href = url; a.target = '_blank'; a.rel = 'noopener';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

async function startQrAuth(){
  if(Date.now() < _altCdUntil){ flash('mAlt','// ПОДОЖДИТЕ ПЕРЕД ПОВТОРНЫМ ЗАПРОСОМ','err'); return; }
  document.getElementById('qrAuthBlock').style.display = 'block';
  document.getElementById('linkAuthBlock').style.display = 'none';
  flash('mAlt','// ГЕНЕРИРУЕМ QR-КОД...','info');
  _altCd('btnQrAuth', 12);
  try{
    const d = await api('/api/qr_login',{action:actionMode});
    if(d.success && d.url){
      _qrToken = d.token;
      _renderQr(d.url);
      flash('mAlt','// СКАНИРУЙТЕ QR В TELEGRAM','ok');
      _startQrPoll();
    } else {
      flash('mAlt', d.message||'// ОШИБКА ГЕНЕРАЦИИ','err');
    }
  }catch(e){ flash('mAlt','// ОШИБКА СЕТИ','err'); }
}

// ── QR-код: полностью встроенная реализация, без внешних зависимостей ──
function _renderQr(url){
  const canvas = document.getElementById('qrCanvas');
  try { _qrDraw(canvas, url, 4); }
  catch(e){ const ctx=canvas.getContext('2d'); ctx.fillStyle='#e63946'; ctx.font='10px monospace'; ctx.fillText('QR ERROR',10,80); }
}

// Минимальный QR encoder (версия 1-10, ECC=M, byte mode)
function _qrDraw(canvas, text, scale){
  const modules = _qrMatrix(text);
  const n = modules.length;
  const sz = n * scale;
  canvas.width = sz + scale*8;
  canvas.height = sz + scale*8;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.fillStyle = '#000000';
  const off = scale*4;
  for(let r=0;r<n;r++) for(let c=0;c<n;c++)
    if(modules[r][c]) ctx.fillRect(off+c*scale, off+r*scale, scale, scale);
}

function _qrMatrix(text){
  // encode via qrcode-generator algorithm (embedded minimal version)
  const PAD0=0xEC,PAD1=0x11;
  const bytes=[...new TextEncoder().encode(text)];
  const len=bytes.length;
  // pick version: capacity table for ECC=M, byte mode
  const caps=[0,16,28,44,64,86,108,124,154,182,216,254];
  let ver=1; while(ver<11&&caps[ver]<len)ver++;
  if(ver>10) ver=10;
  const {total,ecc,blocks}=_qrParams(ver);
  // build data bits
  let bits=[];
  const push=(v,n)=>{ for(let i=n-1;i>=0;i--) bits.push((v>>i)&1); };
  push(0b0100,4); push(len,8);
  bytes.forEach(b=>push(b,8));
  push(0,4);
  while(bits.length%8) bits.push(0);
  const db=[];
  for(let i=0;i<bits.length;i+=8) db.push(bits.slice(i,i+8).reduce((a,b,j)=>a|(b<<(7-j)),0));
  while(db.length<total){ db.push(PAD0); if(db.length<total) db.push(PAD1); }
  // split into blocks and compute ECC
  const allData=[],allEcc=[];
  let pos=0;
  for(const [cnt,dcw] of blocks){
    for(let b=0;b<cnt;b++){
      const blk=db.slice(pos,pos+dcw); pos+=dcw;
      allData.push(blk);
      allEcc.push(_rsEcc(blk,ecc));
    }
  }
  // interleave
  const final=[];
  const maxD=Math.max(...allData.map(b=>b.length));
  for(let i=0;i<maxD;i++) allData.forEach(b=>{ if(i<b.length) final.push(b[i]); });
  for(let i=0;i<ecc;i++) allEcc.forEach(b=>{ if(i<b.length) final.push(b[i]); });
  // to bitstream
  const fbits=[];
  final.forEach(b=>{ for(let i=7;i>=0;i--) fbits.push((b>>i)&1); });
  // build matrix
  const sz=ver*4+17;
  const M=Array.from({length:sz},()=>new Array(sz).fill(null));
  _placeFinderAll(M,sz);
  _placeTiming(M,sz);
  _placeAlign(M,ver,sz);
  _placeDark(M,ver);
  _placeFormat(M,sz,0b101010000010010); // mask 0, ECC=M
  // place data with mask 0: (r+c)%2==0
  let bi=0; let up=true;
  for(let c=sz-1;c>=0;c-=2){
    if(c===6) c=5;
    for(let rr=0;rr<sz;rr++){
      const r=up?sz-1-rr:rr;
      for(let dc=0;dc<2;dc++){
        const cc=c-dc;
        if(M[r][cc]===null){
          let bit=bi<fbits.length?fbits[bi++]:0;
          if(((r+cc)%2)===0) bit^=1; // mask 0
          M[r][cc]=bit===1;
        }
      }
    }
    up=!up;
  }
  return M;
}

function _qrParams(v){
  // [total codewords, ecc per block, [[count,dcw],...]]
  const t={
    1:[26,10,[[1,16]]],
    2:[44,16,[[1,28]]],
    3:[70,26,[[1,44]]],
    4:[100,18,[[2,32]]],
    5:[134,24,[[2,43]]],
    6:[172,16,[[4,27]]],
    7:[196,18,[[4,31]]],
    8:[242,22,[[2,38],[2,39]]],  // simplified
    9:[292,22,[[3,36],[2,37]]],
    10:[346,26,[[4,43],[1,43]]],
  };
  const [total,ecc,blocks]=t[v];
  return {total,ecc,blocks};
}

function _rsEcc(data,n){
  const GF=new Uint8Array(256); const LOG=new Uint8Array(256);
  let x=1; for(let i=0;i<255;i++){ GF[i]=x; LOG[x]=i; x<<=1; if(x&256) x^=285; }
  const gf_mul=(a,b)=>a&&b?GF[(LOG[a]+LOG[b])%255]:0;
  // generator polynomial for n
  let g=[1];
  for(let i=0;i<n;i++){
    const p=[1,GF[i]];
    const r=new Array(g.length+1).fill(0);
    for(let j=0;j<g.length;j++) for(let k=0;k<p.length;k++) r[j+k]^=gf_mul(g[j],p[k]);
    g=r;
  }
  const msg=[...data,...new Array(n).fill(0)];
  for(let i=0;i<data.length;i++){
    const c=msg[i]; if(!c) continue;
    for(let j=0;j<g.length;j++) msg[i+j]^=gf_mul(g[j],c);
  }
  return msg.slice(data.length);
}

function _placeFinderAll(M,sz){
  [[0,0],[0,sz-7],[sz-7,0]].forEach(([r,c])=>_placeFinder(M,r,c));
  // separators
  for(let i=0;i<8;i++){
    _set(M,7,i,false);_set(M,i,7,false);
    _set(M,7,sz-8+i,false);_set(M,i,sz-8,false);
    _set(M,sz-8,i,false);_set(M,sz-8+i,7,false);
  }
}
function _placeFinder(M,r,c){
  for(let dr=0;dr<7;dr++) for(let dc=0;dc<7;dc++)
    _set(M,r+dr,c+dc,dr===0||dr===6||dc===0||dc===6||(dr>=2&&dr<=4&&dc>=2&&dc<=4));
}
function _placeTiming(M,sz){
  for(let i=8;i<sz-8;i++){ _set(M,6,i,i%2===0); _set(M,i,6,i%2===0); }
}
function _placeAlign(M,ver,sz){
  const pos={2:[6,18],3:[6,22],4:[6,26],5:[6,30],6:[6,34],7:[6,22,38],8:[6,24,42],9:[6,28,46],10:[6,28,50]};
  const pts=pos[ver]||[];
  for(const r of pts) for(const c of pts){
    if(M[r][c]!==null) continue;
    for(let dr=-2;dr<=2;dr++) for(let dc=-2;dc<=2;dc++)
      _set(M,r+dr,c+dc,Math.abs(dr)===2||Math.abs(dc)===2||(!dr&&!dc));
  }
}
function _placeDark(M,ver){ _set(M,(4*ver)+9,8,true); }
function _placeFormat(M,sz,fmt){
  const bits=[];
  for(let i=14;i>=0;i--) bits.push((fmt>>i)&1);
  const seq=[...Array(6).keys()].concat([7,8]).concat([...Array(sz-15,sz-8).keys()].map((_,i)=>sz-8+i>sz?sz-8+i:sz-8+i)).map((_,i)=>i);
  // simplified: place format around finder
  const f=[0,1,2,3,4,5,7,8];
  const g=[sz-1,sz-2,sz-3,sz-4,sz-5,sz-6,sz-7,sz-8];
  for(let i=0;i<8;i++){
    _set(M,8,f[i],!!bits[i]); _set(M,f[i],8,!!bits[14-i]);
    _set(M,8,g[i],!!bits[14-i]); _set(M,g[i],8,!!bits[i]);
  }
}
function _set(M,r,c,v){ if(r>=0&&r<M.length&&c>=0&&c<M.length) M[r][c]=v; }

function _startQrPoll(){
  _stopQrPoll();
  _qrPollTimer = setInterval(async ()=>{
    try{
      const d = await api('/api/qr_check',{token:_qrToken,action:actionMode});
      if(d.success){
        _stopQrPoll();
        document.getElementById('s2').style.display='none';
        document.getElementById('s4').style.display='block';
      }
    }catch(e){}
  }, 2500);
}

function _stopQrPoll(){
  if(_qrPollTimer){ clearInterval(_qrPollTimer); _qrPollTimer=null; }
}

async function checkQrDone(){
  if(!_qrToken){ flash('mAlt','// СНАЧАЛА СГЕНЕРИРУЙТЕ ССЫЛКУ / QR','err'); return; }
  flash('mAlt','// ПРОВЕРЯЕМ...','info');
  try{
    const d = await api('/api/qr_check',{token:_qrToken,action:actionMode});
    if(d.success){
      _stopQrPoll();
      document.getElementById('s2').style.display='none';
      document.getElementById('s4').style.display='block';
    } else {
      flash('mAlt', d.message||'// ЕЩЁ НЕ АВТОРИЗОВАНО','err');
    }
  }catch(e){ flash('mAlt','// ОШИБКА СЕТИ','err'); }
}

function copyLink(el){
  const txt = el.textContent;
  if(!txt || txt.startsWith('⏳')) return;
  navigator.clipboard.writeText(txt).then(()=>{ flash('mAlt','// ССЫЛКА СКОПИРОВАНА','ok'); }).catch(()=>{
    const ta=document.createElement('textarea'); ta.value=txt; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    flash('mAlt','// СКОПИРОВАНО','ok');
  });
}

document.addEventListener('keydown',e=>{
  if(e.key!=='Enter')return;
  const vis=id=>document.getElementById(id)&&document.getElementById(id).style.display!=='none';
  if(vis('s0'))saveApi();else if(vis('s1'))sendCode();else if(vis('s2'))verifyCode();else if(vis('s3'))verify2FA();
});

// ══════ UTIL ══════
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// ══════ INIT ══════
async function init(){
  if(tg.initDataUnsafe&&tg.initDataUnsafe.user)userId=tg.initDataUnsafe.user.id;
  else userId=parseInt(qp('user_id')||'0');
  actionMode=qp('action')||'create';

  if(!userId){
    document.getElementById('lov').innerHTML='<div style="font-size:.7rem;letter-spacing:2px;color:#e63946;padding:20px;text-align:center">// ОТКРОЙТЕ ЧЕРЕЗ TELEGRAM БОТА</div>';
    return;
  }

  // Верифицируем initData на сервере — получаем session token
  try{
    const initData=tg.initData||'';
    if(initData){
      const ar=await fetch('/api/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initData})});
      const ad=await ar.json();
      if(ad.token){waToken=ad.token;userId=ad.user_id;}
      else{
        document.getElementById('lov').innerHTML='<div style="font-size:.7rem;letter-spacing:2px;color:#e63946;padding:20px;text-align:center">// ОШИБКА АВТОРИЗАЦИИ</div>';
        return;
      }
    }
  }catch(e){console.warn('auth error',e);}

  ltxt('ПРОВЕРКА СЕССИИ...');
  let hasSession=false,hasConfig=false;
  try{
    const d=await api('/api/check_session',{});
    hasSession=d.has_session||false;
    hasConfig=d.has_config||false;
  }catch(e){}

  // Если сервер есть (есть конфиг или сессия) и не релогин — идём на дашборд
  // Авторизация через webapp нужна только при create/relogin явном запросе
  if(actionMode!=='relogin'){
    // Проверяем есть ли сервер через dashboard
    let hasDash=false;
    try{
      const dd=await api('/api/dashboard',{});
      hasDash=dd.has_server;
      if(hasDash){
        dashData=dd;
        ltxt('ЗАГРУЗКА ДАННЫХ...');
        setPill('ONLINE','g');
        renderDash();
        document.getElementById('nav-dash').classList.add('active');
        showScreen('sDash');
        hideLoading();
        return;
      }
    }catch(e){}
  }

  setPill('AUTH');

  // Определяем с какого шага начинать
  if(actionMode==='relogin'){
    // Релогин — проверяем credentials, если нет — показываем s0 (API данные)
    try{
      const d=await api('/api/check_api_credentials',{action:actionMode});
      document.getElementById(d.has_credentials?'s1':'s0').style.display='block';
    }catch(e){document.getElementById('s0').style.display='block'}
  } else if(!hasSession&&!hasConfig){
    // Нет ничего — с API данных
    try{
      const d=await api('/api/check_api_credentials',{action:actionMode});
      document.getElementById(!d.has_credentials?'s0':'s1').style.display='block';
    }catch(e){document.getElementById('s0').style.display='block'}
  } else if(hasConfig&&!hasSession){
    // Конфиг есть, сессии нет — восстанавливаем credentials и к телефону
    try{ await api('/api/check_api_credentials',{action:actionMode}); }catch(e){}
    document.getElementById('s1').style.display='block';
  } else if(hasSession&&!hasConfig){
    // Сессия есть, конфига нет — нужны API данные
    document.getElementById('s0').style.display='block';
  } else {
    document.getElementById('s0').style.display='block';
  }

  showScreen('sAuth');
  hideLoading();
}

init();
</script>
</body>
</html>"""

# ── Flask security decorator ─────────────────────
def require_secret(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if FLASK_SECRET and request.headers.get("X-Secret") != FLASK_SECRET:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

def validate_init_data(init_data: str) -> Optional[int]:
    """
    Проверяет подпись initData от Telegram WebApp.
    Возвращает user_id если подпись верна, иначе None.
    Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    import hmac as _hmac
    import hashlib as _hashlib
    from urllib.parse import parse_qsl as _parse_qsl
    try:
        params = dict(_parse_qsl(init_data, keep_blank_values=True))
        received_hash = params.pop("hash", None)
        if not received_hash:
            return None
        # Строка для проверки: отсортированные пары key=value через \n
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        # Секретный ключ: HMAC-SHA256(bot_token, "WebAppData")
        secret_key = _hmac.new(b"WebAppData", BOT_TOKEN.encode(), _hashlib.sha256).digest()
        expected = _hmac.new(secret_key, data_check.encode(), _hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, received_hash):
            return None
        # Извлекаем user_id из поля user
        user_json = params.get("user", "{}")
        user_data = json.loads(user_json)
        return int(user_data.get("id", 0)) or None
    except Exception as e:
        log.warning(f"[AUTH] initData validation error: {e}")
        return None

@app.route("/api/auth", methods=["POST"])
def flask_auth():
    """
    Принимает initData от Telegram WebApp, проверяет подпись,
    возвращает одноразовый session-токен привязанный к user_id.
    """
    import secrets as _sec
    data = request.get_json() or {}
    init_data = data.get("initData", "")
    if not init_data:
        return jsonify({"error": "no initData"}), 400
    user_id = validate_init_data(init_data)
    if not user_id:
        return jsonify({"error": "invalid initData"}), 403
    # Генерируем session-токен, храним в памяти (TTL 1 час)
    token = _sec.token_hex(32)
    _webapp_sessions[token] = {"user_id": user_id, "expires": time.time() + 3600}
    return jsonify({"token": token, "user_id": user_id})

# Хранилище сессий webapp: token -> {user_id, expires}
_webapp_sessions: Dict[str, dict] = {}

def require_webapp_auth(f):
    """
    Декоратор для защищённых API-эндпоинтов.
    Проверяет X-Secret (старый путь для совместимости) ИЛИ X-WA-Token.
    user_id берётся ТОЛЬКО из верифицированной сессии, не из тела запроса.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Старый путь: X-Secret (для обратной совместимости)
        if FLASK_SECRET and request.headers.get("X-Secret") == FLASK_SECRET:
            return f(*args, **kwargs)
        # Новый путь: X-WA-Token
        token = request.headers.get("X-WA-Token", "")
        session = _webapp_sessions.get(token)
        if not session:
            return jsonify({"error": "Unauthorized"}), 401
        if time.time() > session["expires"]:
            _webapp_sessions.pop(token, None)
            return jsonify({"error": "Session expired"}), 401
        # Кладём верифицированный user_id в контекст запроса
        request.verified_user_id = session["user_id"]
        return f(*args, **kwargs)
    return wrapper

# ── Flask routes ─────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML_WEBAPP, secret=FLASK_SECRET)

@app.route("/api/check_api_credentials", methods=["POST"])
@require_webapp_auth
def flask_check_api_credentials():
    """Проверяет, есть ли уже API ID и API Hash в pending_creation / pending_relogin или в config.json на диске."""
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    action_val = data.get("action", "create")
    if not tg_id:
        return jsonify({"has_credentials": False})
    tg_id = int(tg_id)
    # Проверяем in-memory
    if action_val == "create":
        has = tg_id in pending_creation and bool(pending_creation[tg_id].get("api_id")) and bool(pending_creation[tg_id].get("api_hash"))
    else:
        has = tg_id in pending_relogin and bool(pending_relogin[tg_id].get("api_id")) and bool(pending_relogin[tg_id].get("api_hash"))
    # Fallback: читаем config.json с диска
    if not has:
        cfg_path = get_config_path(tg_id)
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                api_id = cfg.get("api_id")
                api_hash = cfg.get("api_hash")
                if api_id and api_hash:
                    # Восстанавливаем в in-memory чтобы send_code работал
                    if action_val == "create":
                        existing = pending_creation.get(tg_id, {})
                        pending_creation[tg_id] = {**existing, "api_id": api_id, "api_hash": api_hash}
                    else:
                        existing = pending_relogin.get(tg_id, {})
                        pending_relogin[tg_id] = {**existing, "api_id": api_id, "api_hash": api_hash}
                    has = True
            except Exception:
                pass
    return jsonify({"has_credentials": has})

@app.route("/api/set_api_credentials", methods=["POST"])
@require_webapp_auth
def flask_set_api_credentials():
    """Принимает API ID и API Hash из мини-аппа и сохраняет в pending_creation / pending_relogin."""
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    api_id_raw = data.get("api_id", "").strip()
    api_hash = data.get("api_hash", "").strip()
    action_val = data.get("action", "create")

    if not tg_id or not api_id_raw or not api_hash:
        return jsonify({"success": False, "message": "Заполните API ID и API Hash"})

    try:
        api_id = int(api_id_raw)
    except ValueError:
        return jsonify({"success": False, "message": "API ID должен быть числом"})

    tg_id = int(tg_id)
    if action_val == "create":
        existing = pending_creation.get(tg_id, {})
        pending_creation[tg_id] = {**existing, "api_id": api_id, "api_hash": api_hash}
        port = existing.get("port")
        if not port:
            cfg_path = get_config_path(tg_id)
            if cfg_path.exists():
                try:
                    port = json.loads(cfg_path.read_text()).get("port")
                except Exception:
                    pass
        if not port:
            port = random.randint(10000, 60000)
        pending_creation[tg_id]["port"] = port
    else:
        existing = pending_relogin.get(tg_id, {})
        pending_relogin[tg_id] = {**existing, "api_id": api_id, "api_hash": api_hash}
        port = existing.get("port") or random.randint(10000, 60000)

    # Сразу пишем config.json на диск
    get_id_dir(tg_id).mkdir(parents=True, exist_ok=True)
    ok, _ = write_user_config_json(tg_id, api_id, api_hash, port)

    log.info(f"API credentials set via WebApp for user {tg_id} (action={action_val}), config written={ok}")
    return jsonify({"success": True})

@app.route("/api/check_session", methods=["POST"])
@require_webapp_auth
def flask_check_session():
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    if not tg_id:
        return jsonify({"exists": False, "has_session": False, "has_config": False})
    tg_id = int(tg_id)
    has_s = session_exists(tg_id)
    has_c = config_exists(tg_id)
    return jsonify({"exists": has_s and has_c, "has_session": has_s, "has_config": has_c})

@app.route("/api/send_code", methods=["POST"])
@require_webapp_auth
def flask_send_code():
    try:
        from herokutl import TelegramClient
        from herokutl.sessions import SQLiteSession
    except ImportError:
        return jsonify({"success": False, "message": "herokutl не установлен на сервере"})

    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    phone = data.get("phone")
    action_val = data.get("action", "create")

    if not tg_id or not phone:
        return jsonify({"success": False, "message": "Заполните все поля"})

    tg_id = int(tg_id)
    id_dir = get_id_dir(tg_id)
    id_dir.mkdir(parents=True, exist_ok=True)

    if action_val == "create":
        if tg_id not in pending_creation:
            return jsonify({"success": False, "message": "Сначала введите API ID и API Hash в боте!"})
        api_id = pending_creation[tg_id].get("api_id")
        api_hash = pending_creation[tg_id].get("api_hash")
    else:
        if tg_id not in pending_relogin:
            return jsonify({"success": False, "message": "Сначала введите новые API ID и API Hash в боте!"})
        api_id = pending_relogin[tg_id].get("api_id")
        api_hash = pending_relogin[tg_id].get("api_hash")

    if not api_id or not api_hash:
        return jsonify({"success": False, "message": "API данные не найдены! Начните заново."})

    session_name = str(id_dir / f"heroku-{tg_id}")

    async def _send():
        session = SQLiteSession(session_name)
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()
        try:
            if await client.is_user_authorized():
                return {"already": True}
            result = await client.send_code_request(phone)
            return {"phone_code_hash": result.phone_code_hash}
        except Exception as e:
            return {"error": str(e)}
        finally:
            await client.disconnect()

    try:
        result = asyncio.run(_send())

        if result.get("already"):
            return jsonify({"success": True, "already_authorized": True})
        if result.get("error"):
            return jsonify({"success": False, "message": result["error"]})

        pending_data = {
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "session": session_name,
            "phone_code_hash": result["phone_code_hash"]
        }
        if action_val == "create":
            pending_telethon[tg_id] = pending_data
        else:
            old = pending_relogin.get(tg_id, {})
            pending_relogin[tg_id] = {**pending_data, "port": old.get("port"), "expires_at": old.get("expires_at")}

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/api/verify_code", methods=["POST"])
@require_webapp_auth
def flask_verify_code():
    try:
        from herokutl import TelegramClient
        from herokutl.sessions import SQLiteSession
        from herokutl.errors import SessionPasswordNeededError
    except ImportError:
        return jsonify({"success": False, "message": "herokutl не установлен"})

    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    code = data.get("code")
    action_val = data.get("action", "create")

    if not tg_id:
        return jsonify({"success": False, "message": "Нет данных. Начните заново."})
    tg_id = int(tg_id)

    if action_val == "create":
        if not code or tg_id not in pending_telethon:
            return jsonify({"success": False, "message": "Нет данных для авторизации. Начните заново."})
        auth = pending_telethon[tg_id]
    else:
        if not code or tg_id not in pending_relogin:
            return jsonify({"success": False, "message": "Нет данных для авторизации. Начните заново."})
        auth = pending_relogin[tg_id]

    async def _verify():
        session = SQLiteSession(auth["session"])
        client = TelegramClient(session, auth["api_id"], auth["api_hash"])
        await client.connect()
        try:
            await client.sign_in(auth["phone"], code, phone_code_hash=auth["phone_code_hash"])
            return {"success": True}
        except SessionPasswordNeededError:
            return {"need_password": True}
        except Exception as e:
            return {"error": str(e)}
        finally:
            await client.disconnect()

    try:
        res = asyncio.run(_verify())

        if res.get("success"):
            if action_val == "create":
                pending_telethon.pop(tg_id, None)
            sync_auth_to_heroku(tg_id)
            return jsonify({"success": True})
        elif res.get("need_password"):
            return jsonify({"need_password": True})
        return jsonify({"success": False, "message": res.get("error", "Ошибка")})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/api/verify_password", methods=["POST"])
@require_webapp_auth
def flask_verify_password():
    try:
        from herokutl import TelegramClient
        from herokutl.sessions import SQLiteSession
    except ImportError:
        return jsonify({"success": False, "message": "herokutl не установлен"})

    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    password = data.get("password")
    action_val = data.get("action", "create")

    if not tg_id:
        return jsonify({"success": False, "message": "Нет данных. Начните авторизацию заново."})
    tg_id = int(tg_id)

    if action_val == "create":
        if not password or tg_id not in pending_telethon:
            return jsonify({"success": False, "message": "Нет данных. Начните авторизацию заново."})
        auth = pending_telethon[tg_id]
    else:
        if not password or tg_id not in pending_relogin:
            return jsonify({"success": False, "message": "Нет данных. Начните авторизацию заново."})
        auth = pending_relogin[tg_id]

    async def _check():
        session = SQLiteSession(auth["session"])
        client = TelegramClient(session, auth["api_id"], auth["api_hash"])
        await client.connect()
        try:
            await client.sign_in(password=password)
            return True
        except Exception:
            return False
        finally:
            await client.disconnect()

    try:
        ok = asyncio.run(_check())
        if ok:
            if action_val == "create":
                pending_telethon.pop(tg_id, None)
            sync_auth_to_heroku(tg_id)
            return jsonify({"success": True})
        return jsonify({"success": False, "message": "Неверный пароль 2FA"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


# ── Хранилище QR/link токенов: token -> {tg_id, client, expires} ──
_qr_sessions: Dict[str, dict] = {}

@app.route("/api/qr_login", methods=["POST"])
@require_webapp_auth
def flask_qr_login():
    """
    Генерирует QR/link-токен для авторизации без SMS-кода.
    Использует TelegramClient.qr_login() из herokutl.
    Возвращает: {success, url, token}
    """
    try:
        from herokutl import TelegramClient
        from herokutl.sessions import SQLiteSession
    except ImportError:
        return jsonify({"success": False, "message": "herokutl не установлен"})

    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    action_val = data.get("action", "create")

    if not tg_id:
        return jsonify({"success": False, "message": "Нет user_id"})
    tg_id = int(tg_id)

    if action_val == "create":
        auth = pending_telethon.get(tg_id) or pending_creation.get(tg_id)
    else:
        auth = pending_relogin.get(tg_id)

    if not auth or not auth.get("api_id") or not auth.get("api_hash"):
        return jsonify({"success": False, "message": "Сначала введите API ID и Hash"})

    session_name = auth.get("session") or str(get_id_dir(tg_id) / f"heroku-{tg_id}")
    token = str(uuid.uuid4())

    async def _start_qr():
        session = SQLiteSession(session_name)
        client = TelegramClient(session, auth["api_id"], auth["api_hash"])
        await client.connect()
        try:
            if await client.is_user_authorized():
                return {"already": True}
            qr = await client.qr_login()
            return {"url": qr.url, "qr_obj": qr}
        except Exception as e:
            await client.disconnect()
            return {"error": str(e)}

    try:
        res = asyncio.run(_start_qr())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

    if res.get("already"):
        return jsonify({"success": True, "url": "tg://already", "token": token, "already": True})
    if res.get("error"):
        return jsonify({"success": False, "message": res["error"]})

    # Сохраняем qr_obj и параметры сессии для проверки
    _qr_sessions[token] = {
        "tg_id": tg_id,
        "action": action_val,
        "auth": auth,
        "session_name": session_name,
        "url": res["url"],
        "expires": time.time() + 300,  # 5 минут
    }

    # Очищаем устаревшие токены
    now_t = time.time()
    stale = [k for k, v in _qr_sessions.items() if now_t > v["expires"]]
    for k in stale:
        _qr_sessions.pop(k, None)

    return jsonify({"success": True, "url": res["url"], "token": token})


@app.route("/api/qr_check", methods=["POST"])
@require_webapp_auth
def flask_qr_check():
    """
    Проверяет, авторизовался ли пользователь по QR/ссылке.
    Пытается подтвердить qr_login и проверяет is_user_authorized.
    """
    try:
        from herokutl import TelegramClient
        from herokutl.sessions import SQLiteSession
    except ImportError:
        return jsonify({"success": False, "message": "herokutl не установлен"})

    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    token = data.get("token", "")
    action_val = data.get("action", "create")

    if not tg_id or not token:
        return jsonify({"success": False, "message": "Нет данных"})
    tg_id = int(tg_id)

    sess_data = _qr_sessions.get(token)
    if not sess_data:
        return jsonify({"success": False, "message": "Токен не найден или истёк"})
    if sess_data["tg_id"] != tg_id:
        return jsonify({"success": False, "message": "Неверный токен"})
    if time.time() > sess_data["expires"]:
        _qr_sessions.pop(token, None)
        return jsonify({"success": False, "message": "Токен истёк. Начните заново."})

    auth = sess_data["auth"]
    session_name = sess_data["session_name"]

    async def _check():
        session = SQLiteSession(session_name)
        client = TelegramClient(session, auth["api_id"], auth["api_hash"])
        await client.connect()
        try:
            return await client.is_user_authorized()
        except Exception:
            return False
        finally:
            await client.disconnect()

    try:
        ok = asyncio.run(_check())
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

    if ok:
        _qr_sessions.pop(token, None)
        if action_val == "create":
            pending_telethon.pop(tg_id, None)
        else:
            pass  # pending_relogin оставляем до финального создания
        sync_auth_to_heroku(tg_id)
        return jsonify({"success": True})

    return jsonify({"success": False, "message": "Ещё не авторизовано. Попробуйте позже."})



@app.route("/api/dashboard", methods=["POST"])
@require_webapp_auth
def flask_dashboard():
    """Возвращает данные для дашборда: свой сервер + список шаринг-серверов."""
    import asyncio as _aio
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    if not tg_id:
        return jsonify({"error": "no user_id"}), 400
    tg_id = int(tg_id)

    h = get_hosting(tg_id)
    has_server = h is not None

    # Container status
    container_status = "unknown"
    stats = {}
    if has_server:
        try:
            loop = _aio.new_event_loop()
            container_status = loop.run_until_complete(docker_container_status(tg_id))
            stats = loop.run_until_complete(docker_container_stats(tg_id))
            loop.close()
        except Exception:
            pass

    # Shared servers
    shared_rows = get_shared_servers(tg_id)
    shared_list = []
    for row in shared_rows:
        owner_id = row["owner_id"]
        oh = get_hosting(owner_id)
        cs = "unknown"
        if oh:
            try:
                loop2 = _aio.new_event_loop()
                cs = loop2.run_until_complete(docker_container_status(owner_id))
                loop2.close()
            except Exception:
                pass
        shared_list.append({
            "owner_id": owner_id,
            "port": oh["port"] if oh else None,
            "container_status": cs,
        })

    balance = get_balance(tg_id)
    payments = get_payment_history(tg_id)
    payment_list = [
        {"id": p["id"], "amount": p["amount"], "months": p["months"],
         "status": p["status"], "created_at": p["created_at"]}
        for p in (payments or [])
    ]

    return jsonify({
        "has_server": has_server,
        "port": h["port"] if h else None,
        "expires_at": h["expires_at"] if h else None,
        "container_status": container_status,
        "stats": stats,
        "shared_servers": shared_list,
        "balance": balance,
        "payments": payment_list,
    })


@app.route("/api/server_action", methods=["POST"])
@require_webapp_auth
def flask_server_action():
    """Выполняет действие start/stop/restart на сервере."""
    import asyncio as _aio
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    target_id = data.get("target_id")
    action_val = data.get("action")
    access_type = data.get("type", "own")  # own / shared

    if not tg_id or not target_id or not action_val:
        return jsonify({"success": False, "message": "Неверные параметры"}), 400

    tg_id = int(tg_id)
    target_id = int(target_id)

    # Check access
    if access_type == "own":
        if tg_id != target_id and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа"})
    else:
        if not has_shared_access(target_id, tg_id) and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа к серверу"})

    try:
        loop = _aio.new_event_loop()
        if action_val == "start":
            ok = loop.run_until_complete(docker_start(target_id))
            msg = "Сервер запущен" if ok else "Ошибка запуска"
        elif action_val == "stop":
            ok = loop.run_until_complete(docker_stop(target_id))
            msg = "Сервер остановлен" if ok else "Ошибка остановки"
        elif action_val == "restart":
            ok = loop.run_until_complete(docker_restart(target_id))
            msg = "Сервер перезапущен" if ok else "Ошибка перезапуска"
        else:
            return jsonify({"success": False, "message": "Неизвестное действие"})
        loop.close()
        return jsonify({"success": ok, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/server_logs", methods=["POST"])
@require_webapp_auth
def flask_server_logs():
    """Возвращает реальные логи Docker-контейнера."""
    import asyncio as _aio
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    target_id = data.get("target_id")
    access_type = data.get("type", "own")

    if not tg_id or not target_id:
        return jsonify({"success": False, "message": "Неверные параметры"}), 400

    tg_id = int(tg_id)
    target_id = int(target_id)

    if access_type == "own":
        if tg_id != target_id and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа"})
    else:
        if not has_shared_access(target_id, tg_id) and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа к серверу"})

    try:
        loop = _aio.new_event_loop()
        logs = loop.run_until_complete(docker_logs(target_id, lines=60))
        loop.close()
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/terminal", methods=["POST"])
@require_webapp_auth
def flask_terminal():
    """Выполняет команду в docker-контейнере пользователя."""
    import asyncio as _aio
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    target_id = data.get("target_id")
    cmd = data.get("cmd", "").strip()
    access_type = data.get("type", "own")

    if not tg_id or not target_id or not cmd:
        return jsonify({"success": False, "message": "Неверные параметры"}), 400

    tg_id = int(tg_id)
    target_id = int(target_id)

    if access_type == "own":
        if tg_id != target_id and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа"})
    else:
        if not has_shared_access(target_id, tg_id) and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа к серверу"})

    _blocked = ["rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "chmod 777 /", "chown -R",
                "rm${IFS}", "r\\m ", "chmod${IFS}", "dd${IFS}", "mkfs."]
    if any(b in cmd.lower().replace("\t", " ") for b in _blocked):
        return jsonify({"success": False, "message": "Команда заблокирована из соображений безопасности"})

    container_name = f"jh_user_{target_id}"
    workdir = f"/home/users/{target_id}"

    async def _run():
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "--user", "nobody", "-w", workdir,
            container_name, "sh", "-c", cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = (stdout + stderr).decode(errors="replace").strip()
            return output, proc.returncode
        except asyncio.TimeoutError:
            try: proc.kill(); await proc.wait()
            except Exception: pass
            return "⏱ Timeout (>30 сек)", -1

    try:
        loop = _aio.new_event_loop()
        output, rc = loop.run_until_complete(_run())
        loop.close()
        return jsonify({"success": True, "output": output[:4000] or "(нет вывода)", "rc": rc})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/delete_server", methods=["POST"])
@require_webapp_auth
def flask_delete_server():
    """Полное удаление сервера пользователя."""
    import asyncio as _aio
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    if not tg_id:
        return jsonify({"success": False, "message": "Нет user_id"}), 400
    tg_id = int(tg_id)
    if not user_has_hosting(tg_id):
        return jsonify({"success": False, "message": "Сервер не найден"})
    try:
        loop = _aio.new_event_loop()
        ok, msg = loop.run_until_complete(docker_delete(tg_id, keep_files=False, delete_all_files=True))
        loop.close()
        return jsonify({"success": ok, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/reinstall_server", methods=["POST"])
@require_webapp_auth
def flask_reinstall_server():
    """Переустановка сервера (сохраняет порт, дату, файлы ID/)."""
    import asyncio as _aio
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    if not tg_id:
        return jsonify({"success": False, "message": "Нет user_id"}), 400
    tg_id = int(tg_id)
    if not user_has_hosting(tg_id):
        return jsonify({"success": False, "message": "Сервер не найден"})

    h_old = get_hosting(tg_id)
    old_port = h_old["port"] if h_old else None
    old_exp  = h_old["expires_at"] if h_old else None

    async def _reinstall():
        await docker_delete(tg_id, delete_all_files=False)
        if old_port and old_exp:
            with db_connect() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO hosting (user_id, port, status, created_at, expires_at)
                    VALUES (?, ?, 'active', ?, ?)
                """, (tg_id, old_port, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"), old_exp))
                conn.execute("UPDATE users SET hosting_created = 0 WHERE user_id = ?", (tg_id,))
        ok, result = await docker_create(tg_id, lambda t: None)
        if ok:
            port = int(result)
            with db_connect() as conn:
                conn.execute("UPDATE hosting SET port = ?, status = 'active' WHERE user_id = ?", (port, tg_id))
                conn.execute("UPDATE users SET hosting_created = 1 WHERE user_id = ?", (tg_id,))
        return ok, result

    try:
        loop = _aio.new_event_loop()
        ok, result = loop.run_until_complete(_reinstall())
        loop.close()
        if ok:
            h = get_hosting(tg_id)
            return jsonify({"success": True, "port": h["port"] if h else result, "expires_at": h["expires_at"] if h else old_exp})
        return jsonify({"success": False, "message": str(result)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


@app.route("/api/ai_diagnose", methods=["POST"])
@require_webapp_auth
def flask_ai_diagnose():
    """AI-диагностика логов через LOCAL_API."""
    import asyncio as _aio
    data = request.get_json() or {}
    tg_id = getattr(request, "verified_user_id", None) or data.get("user_id")
    target_id = data.get("target_id")
    access_type = data.get("type", "own")

    if not tg_id or not target_id:
        return jsonify({"success": False, "message": "Неверные параметры"}), 400

    tg_id = int(tg_id)
    target_id = int(target_id)

    if access_type == "own":
        if tg_id != target_id and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа"})
    else:
        if not has_shared_access(target_id, tg_id) and tg_id != ADMIN_ID:
            return jsonify({"success": False, "message": "Нет доступа к серверу"})

    try:
        loop = _aio.new_event_loop()
        logs = loop.run_until_complete(docker_logs(target_id, lines=60))
        diagnosis = loop.run_until_complete(ai_analyze_logs(logs))
        loop.close()
        return jsonify({"success": True, **diagnosis})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})



# ═══════════════════════════════════════════════════════════════════
#               ЮMАНИ — АВТОМАТИЧЕСКОЕ ЗАЧИСЛЕНИЕ
# ═══════════════════════════════════════════════════════════════════
import hashlib as _hashlib

def _verify_yoomoney_notification(params: dict, secret: str) -> bool:
    """Проверяет подпись уведомления от ЮMани."""
    keys = [
        "notification_type", "operation_id", "amount", "currency",
        "datetime", "sender", "codepro", "notification_secret", "label"
    ]
    check_str = "&".join(params.get(k, "") for k in keys)
    # Заменяем notification_secret на реальный секрет
    check_str = check_str.replace(params.get("notification_secret", ""), secret)
    sha1 = _hashlib.sha1(check_str.encode("utf-8")).hexdigest()
    return sha1 == params.get("sha1_hash", "")

# IP-адреса серверов ЮMани
_YOOMONEY_IPS = {"77.75.153.234", "77.75.156.11", "77.75.156.35", "77.75.154.128",
                 "2a02:5180:0:1509::10", "2a02:5180:0:2655::10"}

@app.route("/yoomoney/notify", methods=["POST"])
def yoomoney_notify():
    """Webhook от ЮMани — автоматическое зачисление баланса."""
    import asyncio as _aio
    params = request.form.to_dict()

    # Проверяем IP отправителя
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if client_ip not in _YOOMONEY_IPS:
        log.warning(f"YooMoney notify: rejected IP {client_ip}")
        return "forbidden", 403

    log.info(f"YooMoney notify from {client_ip}: {params}")

    # Только входящие реальные платежи (не тестовые)
    if params.get("codepro") == "true":
        log.info("YooMoney notify: codepro payment, skipping")
        return "ok", 200

    try:
        amount = int(float(params.get("amount", 0)))
    except Exception:
        return "bad amount", 400

    if amount <= 0:
        return "ok", 200

    # label = telegram user_id
    label = params.get("label", "").strip()
    if not label or not label.isdigit():
        log.info(f"YooMoney notify: no valid label (uid), amount={amount}")
        # Уведомляем админа для ручного зачисления
        try:
            loop = _aio.new_event_loop()
            loop.run_until_complete(bot.send_message(
                ADMIN_ID,
                f"💳 <b>ЮMани платёж без label</b>\n\n"
                f"Сумма: <b>{amount} ₽</b>\n"
                f"Отправитель: {params.get('sender', '—')}\n"
                f"ID операции: {params.get('operation_id', '—')}\n\n"
                f"⚠️ Зачислите вручную.",
                parse_mode="HTML"
            ))
            loop.close()
        except Exception as e:
            log.error(f"YooMoney notify: failed to notify admin: {e}")
        return "ok", 200

    user_id = int(label)

    # Проверяем что пользователь существует
    u = get_user(user_id)
    if not u:
        log.warning(f"YooMoney notify: user {user_id} not found")
        try:
            loop = _aio.new_event_loop()
            loop.run_until_complete(bot.send_message(
                ADMIN_ID,
                f"💳 <b>ЮMани платёж — неизвестный пользователь</b>\n\n"
                f"UID: <code>{user_id}</code>\n"
                f"Сумма: <b>{amount} ₽</b>\n"
                f"ID операции: {params.get('operation_id', '—')}",
                parse_mode="HTML"
            ))
            loop.close()
        except Exception:
            pass
        return "ok", 200

    # Зачисляем баланс
    operation_id = params.get("operation_id", "")
    pay_id = create_payment(user_id, amount, 0, f"yoomoney:{operation_id}")
    approve_payment(pay_id)
    add_balance(user_id, amount)

    log.info(f"YooMoney: auto-credited {amount} RUB to user {user_id}, op={operation_id}")

    # Уведомляем пользователя
    try:
        loop = _aio.new_event_loop()
        loop.run_until_complete(bot.send_message(
            user_id,
            f"✅ <b>Баланс пополнен!</b>\n\n"
            f"<blockquote>💰 Зачислено: <b>{amount} ₽</b>\n"
            f"💎 Новый баланс: <b>{get_balance(user_id)} ₽</b></blockquote>",
            parse_mode="HTML",
            reply_markup=back_kb()
        ))
        loop.close()
    except Exception as e:
        log.error(f"YooMoney notify: failed to notify user {user_id}: {e}")

    # Уведомляем админа
    try:
        loop2 = _aio.new_event_loop()
        loop2.run_until_complete(bot.send_message(
            ADMIN_ID,
            f"💳 <b>ЮMани — авто-зачисление</b>\n\n"
            f"👤 UID: <code>{user_id}</code>\n"
            f"💰 Сумма: <b>{amount} ₽</b>\n"
            f"🔑 Операция: <code>{operation_id}</code>",
            parse_mode="HTML"
        ))
        loop2.close()
    except Exception:
        pass

    return "ok", 200

# Хранилище ссылок: label -> ym_url (живут пока бот запущен)
_pay_links: Dict[str, str] = {}

@app.route("/pay/<label>")
def pay_redirect(label: str):
    """Редирект на ЮMани по label — скрывает сумму и параметры от пользователя."""
    url = _pay_links.get(label)
    if not url:
        return "Ссылка не найдена или устарела.", 404
    from flask import redirect as _redirect
    return _redirect(url)

def run_flask():
    cert = f"/etc/letsencrypt/live/{AUTH_DOMAIN}/fullchain.pem"
    key = f"/etc/letsencrypt/live/{AUTH_DOMAIN}/privkey.pem"
    ssl_ctx = None
    if os.path.exists(cert) and os.path.exists(key):
        try:
            ssl_ctx = (cert, key)
            log.info(f"Using SSL from {cert}")
        except Exception as e:
            log.warning(f"Failed to load SSL certs: {e}")
            ssl_ctx = None
    if ssl_ctx is None:
        log.warning("Running Flask without SSL (development mode)")
    try:
        app.run(host="0.0.0.0", port=AUTH_PORT, ssl_context=ssl_ctx,
                debug=False, threaded=True, use_reloader=False)
    except Exception as e:
        log.error(f"Flask error: {e}")

# ═══════════════════════════════════════════════════════════════════
#                          ХЭНДЛЕРЫ: /start
# ═══════════════════════════════════════════════════════════════════
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    ensure_user(msg.from_user)
    uid = msg.from_user.id

    # ── Обработка реферальной ссылки (/start ref_<referrer_id>) ──
    args = msg.text.split(maxsplit=1)[1] if len(msg.text.split()) > 1 else ""
    if args.startswith("ref_"):
        try:
            referrer_id = int(args[4:])
            if referrer_id != uid:  # нельзя быть своим рефералом
                create_referral(referrer_id, uid)
        except (ValueError, Exception):
            pass

    if uid == ADMIN_ID:
        safe_name = msg.from_user.first_name or "Администратор"
        h = get_hosting(uid)
        status_line = ""
        if h:
            try:
                days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
                status_line = f"\n📅 Подписка: <b>{days_left} дн.</b> до <code>{h['expires_at']}</code>"
            except Exception:
                pass
        await msg.answer(
            f"👑 С возвращением, <b>{safe_name}!</b>\n\n"
            f"<blockquote>⚡️ JokyHost — хостинг для вашего юзербота.{status_line}</blockquote>\n\n"
            "Выберите раздел 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=main_kb(is_admin=True)
        )
        return

    user = get_user(uid)
    if not user or not user["subscribed"]:
        await msg.answer(
            "⚡️ <b>Добро пожаловать в JokyHost!</b>\n\n"
            "<blockquote>Хостинг для Heroku Userbot от coddrago.</blockquote>\n\n"
            f"💰 Цена: <b>{PRICE_PER_MONTH} ₽/мес</b>\n"
            "⚙️ Ресурсы: <b>1 CPU · 650 MB RAM</b>\n\n"
            "Для начала подпишитесь на наш канал 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=subscribe_kb()
        )
    else:
        h = get_hosting(uid)
        status_line = ""
        if h:
            try:
                days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
                status_line = f"\n📅 Подписка: <b>{days_left} дн.</b> до <code>{h['expires_at']}</code>"
            except Exception:
                pass

        first_name = msg.from_user.first_name or "пользователь"
        await msg.answer(
            f"👋 С возвращением, <b>{first_name}!</b>\n\n"
            f"<blockquote>⚡️ JokyHost — хостинг для вашего юзербота.{status_line}</blockquote>\n\n"
            "Выберите раздел 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=main_kb(uid == ADMIN_ID)
        )

@dp.callback_query(F.data == "check_subscribe")
async def cb_check_subscribe(cq: CallbackQuery):
    ensure_user(cq.from_user)
    uid = cq.from_user.id
    try:
        member = await bot.get_chat_member(CHANNEL_REQUIRED, uid)
        is_member = member.status not in ("left", "kicked", "banned")
    except Exception:
        is_member = False

    if not is_member:
        await cq.answer(
            f"❌ Вы всё ещё не подписаны на {CHANNEL_REQUIRED}!",
            show_alert=True
        )
        return

    set_subscribed(uid)
    h = get_hosting(uid)
    status_line = ""
    if h:
        try:
            days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
            status_line = f"\n📅 Подписка: <b>{days_left} дн.</b> до <code>{h['expires_at']}</code>"
        except Exception:
            pass

    await cq.message.edit_text(
        f"✅ <b>Подписка на канал подтверждена!</b>\n\n"
        f"<blockquote>💰 Цена: <b>{PRICE_PER_MONTH} ₽/мес</b> · ⚙️ 1 CPU · 650 MB RAM{status_line}</blockquote>\n\n"
        "Добро пожаловать в JokyHost 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb(uid == ADMIN_ID)
    )
    await cq.answer("🎉 Добро пожаловать!")

@dp.callback_query(F.data == "menu")
async def cb_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = cq.from_user.id
    is_admin = uid == ADMIN_ID

    h = get_hosting(uid)
    status_line = ""
    if h:
        try:
            days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
            status_line = f"\n📅 Подписка: <b>{days_left} дн.</b> до <code>{h['expires_at']}</code>"
        except Exception:
            pass
    await cq.message.edit_text(
        f"⚡️ <b>JokyHost — Главное меню</b>{status_line}\n\nВыберите раздел:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb(is_admin)
    )
    await cq.answer()

# ═══════════════════════════════════════════════════════════════════
#                     ХЭНДЛЕРЫ: УПРАВЛЕНИЕ СЕРВЕРОМ
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "hosting_menu")
async def cb_hosting_menu(cq: CallbackQuery):
    uid = cq.from_user.id
    # Если пользователь нажал «Назад» во время релогина — сбрасываем состояние
    if uid in relogin_in_progress:
        relogin_in_progress.discard(uid)
        pending_relogin.pop(uid, None)
        db_clear_flow(uid)
    has = user_has_hosting(cq.from_user.id)
    h = get_hosting(cq.from_user.id)

    if has and h:
        try:
            days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
            server_block = (
                f"├ 🔌 Порт: <code>{h['port']}</code>\n"
                f"├ 📅 До: <code>{h['expires_at']}</code>\n"
                f"└ ⏳ Осталось: <b>{days_left} дн.</b>"
            )
        except Exception:
            server_block = f"└ 🔌 Порт: <code>{h['port']}</code>"
        text = f"⚡️ <b>Управление сервером</b>\n\n✅ Сервер активен\n{server_block}"
    else:
        text = "⚡️ <b>Управление сервером</b>\n\n🔧 Сервер ещё не создан."

    await cq.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=hosting_kb(has))
    await cq.answer()

@dp.callback_query(F.data == "my_hosting")
async def cb_my_hosting(cq: CallbackQuery):
    uid = cq.from_user.id
    h = get_hosting(uid)
    if not h:
        await cq.answer("❌ Сервер не найден", show_alert=True)
        return

    container_status = await docker_container_status(uid)
    status_text = fmt_status(container_status)

    exp = h["expires_at"]
    try:
        days_left = (datetime.strptime(exp, "%Y-%m-%d").date() - datetime.now(MSK).date()).days
        days_txt = f"⚠️ {days_left} дн." if days_left <= 7 else f"{days_left} дн."
    except Exception:
        days_txt = "—"

    # Получаем статистику контейнера
    stats = {}
    if container_status == "running":
        stats = await docker_container_stats(uid)

    stats_lines = ""
    if stats:
        stats_lines = (
            f"├ 🖥 CPU: <code>{stats.get('cpu', '—')}</code>\n"
            f"├ 💾 RAM: <code>{stats.get('mem', '—')}</code> ({stats.get('mem_p', '—')})\n"
        )
    else:
        stats_lines = f"├ ⚙️ Лимиты: 1 CPU · 650 MB RAM\n"

    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data="my_hosting")
    b.button(text="🏠 Главное меню", callback_data="menu")
    b.adjust(1)

    await cq.message.edit_text(
        f"📊 <b>Информация о сервере</b>\n\n"
        f"┌ 🆔 ID: <code>{uid}</code>\n"
        f"├ 🔌 Порт: <code>{h['port']}</code>\n"
        f"├ 🐳 Контейнер: {status_text}\n"
        f"{stats_lines}"
        f"└ 📅 До: <code>{exp}</code> ({days_txt})",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await cq.answer()

@dp.callback_query(F.data == "server_logs")
async def cb_server_logs(cq: CallbackQuery):
    uid = cq.from_user.id
    if not user_has_hosting(uid):
        await cq.answer("❌ Нет активного сервера", show_alert=True)
        return
    await cq.answer("Загружаем логи...")
    logs = await docker_logs(uid, lines=40)
    truncated = logs[-3500:] if len(logs) > 3500 else logs
    truncated = html.escape(truncated)
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data="server_logs")
    b.button(text="🤖 Диагностика AI", callback_data=f"fix_with_ai_{uid}_{uid}")
    b.button(text="◀️ Назад",    callback_data="hosting_menu")
    b.adjust(1)
    await cq.message.edit_text(
        f"📋 <b>Логи сервера</b> (последние 40 строк)\n\n<pre>{truncated}</pre>",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )

@dp.callback_query(F.data == "manage_menu")
async def cb_manage_menu(cq: CallbackQuery):
    if not user_has_hosting(cq.from_user.id):
        await cq.answer("❌ У вас нет активного сервера", show_alert=True)
        return
    await cq.message.edit_text(
        "🛠 <b>Управление контейнером</b>\n\nВыберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=manage_kb()
    )
    await cq.answer()

@dp.callback_query(F.data == "container_start")
async def cb_container_start(cq: CallbackQuery):
    uid = cq.from_user.id
    h = get_hosting(uid)
    if h and h["status"] == "expired":
        await cq.answer("❌ Подписка истекла!", show_alert=True)
        await cq.message.edit_text(
            "🔴 <b>Подписка истекла</b>\n\n"
            "<blockquote>Запуск сервера недоступен — ваша подписка закончилась.</blockquote>\n\n"
            "💎 Пополните баланс и продлите подписку через «💎 Кошелёк».",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("manage_menu")
        )
        return
    await cq.answer("Запускаем...")
    ok = await docker_start(uid)
    icon = "▶️" if ok else "❌"
    text = f"{icon} <b>{'Контейнер запущен!' if ok else 'Не удалось запустить контейнер.'}</b>"
    await cq.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb("manage_menu"))

@dp.callback_query(F.data == "container_stop")
async def cb_container_stop(cq: CallbackQuery):
    await cq.answer("Останавливаем...")
    ok = await docker_stop(cq.from_user.id)
    icon = "⏹" if ok else "❌"
    text = f"{icon} <b>{'Контейнер остановлен.' if ok else 'Не удалось остановить контейнер.'}</b>"
    await cq.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb("manage_menu"))

@dp.callback_query(F.data == "container_restart")
async def cb_container_restart(cq: CallbackQuery):
    await cq.answer("Перезапускаем...")
    await cq.message.edit_text(
        "🔁 <b>Перезапуск контейнера...</b>\n\nПожалуйста, подождите.",
        parse_mode=ParseMode.HTML
    )
    ok = await docker_restart(cq.from_user.id)
    if ok:
        text = "🔁 <b>Контейнер перезапущен!</b>\n\n✅ Auth-файлы синхронизированы."
    else:
        text = "❌ <b>Не удалось перезапустить контейнер.</b>\n\nПроверьте логи."
    await cq.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb("manage_menu"))

@dp.callback_query(F.data == "container_delete")
async def cb_container_delete(cq: CallbackQuery, state: FSMContext):
    b = InlineKeyboardBuilder()
    b.button(text="🗑 Да, удалить всё", callback_data="delete_confirm_yes")
    b.button(text="◀️ Отмена",           callback_data="manage_menu")
    b.adjust(1)
    await cq.message.edit_text(
        "🗑 <b>Удаление сервера</b>\n\n"
        "⚠️ Это действие ПОЛНОСТЬЮ удалит:\n"
        "• Docker-контейнер\n"
        "• Все файлы (включая ID/ с авторизацией)\n"
        "• Запись о сервере в базе данных\n\n"
        "❗ Действие <b>необратимо!</b> Вы уверены?",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await state.set_state(HostingStates.delete_confirm)
    await cq.answer()

@dp.callback_query(F.data == "delete_confirm_yes", HostingStates.delete_confirm)
async def cb_delete_confirm(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = cq.from_user.id
    await cq.message.edit_text("🗑 Полное удаление сервера...", parse_mode=ParseMode.HTML)
    ok, msg_text = await docker_delete(uid, keep_files=False, delete_all_files=True)
    if ok:
        await cq.message.edit_text(
            "✅ <b>Сервер полностью удалён!</b>\n\n"
            "Удалено: контейнер, образ, все файлы.\n\n"
            "Создайте новый сервер через главное меню.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )
    else:
        await cq.message.edit_text(
            f"❌ Ошибка удаления:\n<code>{msg_text}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )
    await cq.answer()

@dp.callback_query(F.data == "container_terminal")
async def cb_container_terminal(cq: CallbackQuery, state: FSMContext):
    """Открыть терминал для выполнения команды в docker-контейнере"""
    uid = cq.from_user.id
    if not user_has_hosting(uid):
        await cq.answer("❌ У вас нет активного сервера", show_alert=True)
        return
    step_msg = await cq.message.edit_text(
        "💻 <b>Терминал — Docker контейнер</b>\n\n"
        "Введите команду для выполнения внутри вашего контейнера:\n\n"
        "Примеры:\n"
        "• <code>ls /app</code>\n"
        "• `cat /app/config.json`\n"
        "• <code>ps aux</code>\n\n"
        "⚠️ Команда выполнится с правами контейнера.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("manage_menu")
    )
    await state.update_data(terminal_msg_id=step_msg.message_id, terminal_uid=uid)
    await state.set_state(TerminalStates.waiting_command)
    await cq.answer()


@dp.message(TerminalStates.waiting_command)
async def terminal_exec_command(msg: Message, state: FSMContext):
    """Выполнить введённую команду в docker-контейнере пользователя"""
    try:
        await msg.delete()
    except Exception:
        pass

    data = await state.get_data()
    step_msg_id = data.get("terminal_msg_id")
    uid = data.get("terminal_uid", msg.from_user.id)
    cmd_text = (msg.text or "").strip()
    chat_id = msg.chat.id

    async def edit(text: str, kb=None):
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML,
                reply_markup=kb or back_kb("manage_menu")
            )
        except Exception:
            pass

    if not cmd_text:
        await edit("💻 <b>Терминал</b>\n\n❌ Пустая команда. Введите команду:")
        return

    await edit(f"💻 <b>Терминал</b>\n\n⏳ Выполняю: <code>{cmd_text[:80]}</code>...")

    # Блокируем опасные команды (команда выполняется в --user nobody внутри Docker)
    _blocked = ["rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "chmod 777 /", "chown -R",
                "rm${IFS}", "r\\m ", "chmod${IFS}", "dd${IFS}", "mkfs."]
    _cmd_lower = cmd_text.lower().replace("\t", " ")
    if any(b in _cmd_lower for b in _blocked):
        await edit("💻 <b>Терминал</b>\n\n❌ Команда заблокирована из соображений безопасности.")
        return

    container_name = f"jh_user_{uid}"
    workdir = f"/home/users/{uid}"
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec",
            "--user", "nobody",
            "-w", workdir,
            container_name, "sh", "-c", cmd_text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = (stdout + stderr).decode(errors="replace").strip()
        rc = proc.returncode
    except asyncio.TimeoutError:
        output = "⏱ Timeout — команда выполнялась слишком долго (>30 сек)"
        rc = -1
    except Exception as e:
        output = f"❌ Ошибка запуска: {e}"
        rc = -1

    output = output[:3000] or "(нет вывода)"
    output_safe = html.escape(output)
    rc_icon = "✅" if rc == 0 else "❌"

    b = InlineKeyboardBuilder()
    b.button(text="💻 Новая команда", callback_data="container_terminal")
    b.button(text="◀️ Управление",    callback_data="manage_menu")
    b.adjust(1)

    await edit(
        f"💻 <b>Терминал</b> — <code>{container_name}</code>\n\n"
        f"<b>Команда:</b> <code>{cmd_text[:80]}</code>\n"
        f"<b>Статус:</b> {rc_icon} (код {rc})\n\n"
        f"<b>Вывод:</b>\n<pre>{output_safe}</pre>",
        kb=b.as_markup()
    )
    await state.clear()


@dp.callback_query(F.data == "reinstall_hosting")
async def cb_reinstall_start(cq: CallbackQuery, state: FSMContext):
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Да, переустановить", callback_data="reinstall_confirm_yes")
    b.button(text="◀️ Отмена",              callback_data="hosting_menu")
    b.adjust(1)
    await cq.message.edit_text(
        "🔄 <b>Переустановка сервера</b>\n\n"
        "<blockquote>⚠️ Контейнер будет пересоздан.\n"
        "Сессия и конфиг (папка ID/) сохранятся.</blockquote>\n\n"
        "Продолжить?",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await state.set_state(HostingStates.reinstall_confirm)
    await cq.answer()

@dp.callback_query(F.data == "reinstall_confirm_yes", HostingStates.reinstall_confirm)
async def cb_reinstall_confirm(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = cq.from_user.id
    msg = await cq.message.edit_text("🔄 Переустанавливаем сервер...", parse_mode=ParseMode.HTML)

    async def upd(text):
        try:
            await msg.edit_text(f"🔄 <b>Переустановка</b>\n\n{text}", parse_mode=ParseMode.HTML)
        except Exception:
            pass

    h_old = get_hosting(uid)
    old_port = h_old["port"] if h_old else None
    old_exp = h_old["expires_at"] if h_old else None

    await docker_delete(uid, delete_all_files=False)

    if old_port and old_exp:
        with db_connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hosting (user_id, port, status, created_at, expires_at)
                VALUES (?, ?, 'active', ?, ?)
            """, (uid, old_port, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"), old_exp))
            conn.execute("UPDATE users SET hosting_created = 0 WHERE user_id = ?", (uid,))

    ok, result = await docker_create(uid, upd)

    if ok:
        port = int(result)
        with db_connect() as conn:
            conn.execute("UPDATE hosting SET port = ?, status = 'active' WHERE user_id = ?", (port, uid))
            conn.execute("UPDATE users SET hosting_created = 1 WHERE user_id = ?", (uid,))
        h = get_hosting(uid)
        exp = h["expires_at"] if h else "—"
        await msg.edit_text(
            f"✅ <b>Сервер переустановлен!</b>\n\n"
            f"<blockquote>🔌 Порт: <code>{port}</code>\n"
            f"📅 Активен до: <code>{exp}</code></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=server_info_kb()
        )
    else:
        await msg.edit_text(
            f"❌ Ошибка переустановки:\n<code>{result}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )
    await cq.answer()

# ═══════════════════════════════════════════════════════════════════
#                     ХЭНДЛЕРЫ: РЕЛОГИН
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "relogin_hosting")
async def cb_relogin_start(cq: CallbackQuery, state: FSMContext):
    uid = cq.from_user.id
    if not user_has_hosting(uid):
        await cq.answer("❌ У вас нет активного сервера", show_alert=True)
        return

    if uid in relogin_in_progress:
        await cq.answer("⚠️ Релогин уже в процессе. Подождите завершения.", show_alert=True)
        return

    b = InlineKeyboardBuilder()
    b.button(text="🔑 Да, сменить аккаунт", callback_data="relogin_confirm_yes")
    b.button(text="◀️ Отмена",               callback_data="hosting_menu")
    b.adjust(1)
    await cq.message.edit_text(
        "🔑 <b>Смена аккаунта</b>\n\n"
        "<blockquote>Это действие:\n"
        "1. Остановит контейнер\n"
        "2. Удалит все данные авторизации (сессия и конфиг)\n"
        "3. Попросит авторизоваться заново через веб</blockquote>\n\n"
        "❗ Время подписки и порт сохранятся.\n\nПродолжить?",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await state.set_state(HostingStates.relogin_confirm)
    await cq.answer()

@dp.callback_query(F.data == "relogin_confirm_yes", HostingStates.relogin_confirm)
async def cb_relogin_confirm(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = cq.from_user.id

    await cq.message.edit_text("⏹ Останавливаем контейнер...", parse_mode=ParseMode.HTML)
    await docker_stop(uid)

    await cq.message.edit_text("🗑 Очищаем данные авторизации...", parse_mode=ParseMode.HTML)
    # Удаляем всё содержимое /ID/
    id_dir = get_id_dir(uid)
    if id_dir.exists():
        try:
            shutil.rmtree(id_dir)
            id_dir.mkdir(parents=True, exist_ok=True)
            log.info(f"Cleared ID/ for user {uid}")
        except Exception as e:
            log.error(f"Failed to clear ID/ for user {uid}: {e}")
    # Удаляем конфиг из /Heroku/
    delete_heroku_config(uid)

    h_old = get_hosting(uid)
    old_port = h_old["port"] if h_old else None
    old_expires = h_old["expires_at"] if h_old else None

    pending_relogin[uid] = {"port": old_port, "expires_at": old_expires}
    relogin_in_progress.add(uid)
    db_save_flow(uid, "relogin", {"port": old_port, "expires_at": old_expires})

    await cq.message.edit_text(
        "🔑 <b>Смена аккаунта</b>\n\n"
        "Данные очищены. Авторизуйтесь через веб-приложение:\n\n"
        "⚠️ После авторизации нажмите «✅ Я авторизовался».",
        parse_mode=ParseMode.HTML,
        reply_markup=webapp_auth_kb(uid, action="relogin")
    )
    await cq.answer()

@dp.message(ReloginStates.waiting_api_id)
async def relogin_get_api_id(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass

    try:
        api_id = int(msg.text.strip())
        await state.update_data(api_id=api_id)
        await state.set_state(ReloginStates.waiting_api_hash)

        text = (
            "🔧 <b>Релогин — Шаг 2/3: API Hash</b>\n\n"
            "Введите ваш <b>API Hash</b> из my.telegram.org:\n\n"
            "Пример: <code>abcdef1234567890abcdef1234567890</code>\n\n"
            "✏️ Напишите 32 символа:"
        )
        kb = back_kb("hosting_menu")
        data = await state.get_data()
        step_msg_id = data.get("step_msg_id")
        if step_msg_id:
            try:
                await bot.edit_message_text(
                    text, chat_id=msg.chat.id, message_id=step_msg_id,
                    parse_mode=ParseMode.HTML, reply_markup=kb
                )
            except Exception:
                sent = await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
                await state.update_data(step_msg_id=sent.message_id)
        else:
            sent = await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            await state.update_data(step_msg_id=sent.message_id)
    except ValueError:
        temp = await msg.answer("❌ API ID должен быть числом. Попробуйте ещё раз:")
        await asyncio.sleep(3)
        try:
            await temp.delete()
        except Exception:
            pass

@dp.message(ReloginStates.waiting_api_hash)
async def relogin_get_api_hash(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass

    api_hash = msg.text.strip()
    if len(api_hash) != 32:
        temp = await msg.answer("❌ API Hash — 32 символа. Проверьте и попробуйте снова:")
        await asyncio.sleep(3)
        try:
            await temp.delete()
        except Exception:
            pass
        return

    data = await state.get_data()
    api_id = data.get("api_id")
    uid = msg.from_user.id

    relogin_data = pending_relogin.get(uid, {})
    old_port = relogin_data.get("port")

    pending_relogin[uid] = {
        "api_id": api_id,
        "api_hash": api_hash,
        "port": old_port,
        "expires_at": relogin_data.get("expires_at")
    }

    port = old_port if old_port else random.randint(10000, 60000)
    success, config_result = write_user_config_json(uid, api_id, api_hash, port)

    if not success:
        await msg.answer(
            f"❌ Ошибка сохранения конфига:\n`{config_result}`\n\n"
            "Попробуйте позже или обратитесь к администратору.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu")
        )
        await state.clear()
        return

    await state.clear()

    auth_text = (
        "🔑 <b>Релогин — Шаг 3/3: Новая авторизация</b>\n\n"
        "Нажмите кнопку ниже для авторизации.\n\n"
        "⚠️ <b>Важно:</b> Используйте аккаунт с теми API данными, что ввели!\n\n"
        "После авторизации нажмите «✅ Я авторизовался»."
    )
    kb = webapp_auth_kb(uid, action="relogin")

    step_msg_id = data.get("step_msg_id")
    if step_msg_id:
        try:
            await bot.edit_message_text(
                auth_text, chat_id=msg.chat.id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=kb
            )
        except Exception:
            await msg.answer(auth_text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await msg.answer(auth_text, parse_mode=ParseMode.HTML, reply_markup=kb)

@dp.callback_query(F.data.startswith("confirm_auth_relogin_"))
async def cb_confirm_relogin(cq: CallbackQuery):
    uid = cq.from_user.id
    target = int(cq.data.split("_")[3])

    if uid != target:
        await cq.answer("❌ Чужая авторизация", show_alert=True)
        return

    if not session_exists(uid):
        await cq.message.edit_text(
            "❌ <b>Сессия не найдена!</b>\n\n"
            "Пройдите авторизацию в веб-приложении:\n"
            "1. Введите правильный номер телефона\n"
            "2. Введите код из Telegram\n"
            "3. Дождитесь сообщения об успехе",
            parse_mode=ParseMode.HTML,
            reply_markup=webapp_auth_kb(uid, action="relogin")
        )
        await cq.answer()
        return

    relogin_data = pending_relogin.pop(uid, {})
    relogin_in_progress.discard(uid)
    db_clear_flow(uid)

    h = get_hosting(uid)
    old_port = relogin_data.get("port") or (h["port"] if h else None)
    old_expires = relogin_data.get("expires_at") or (h["expires_at"] if h else None)

    msg_obj = await cq.message.edit_text(
        "🔄 <b>Применяю новый аккаунт...</b>\n\n"
        "⏹ Останавливаю контейнер...",
        parse_mode=ParseMode.HTML
    )

    async def upd(text: str):
        try:
            await msg_obj.edit_text(
                f"🔄 <b>Смена аккаунта</b>\n\n{text}",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    # 1. Синхронизируем новую сессию из ID/ → Heroku/ ДО остановки
    await upd("📁 Синхронизирую файлы авторизации...")
    synced = sync_auth_to_heroku(uid)
    if not synced:
        await upd(
            "❌ Файлы авторизации не найдены в ID/\n\n"
            "Пройдите авторизацию заново через «🔑 Сменить аккаунт»."
        )
        await cq.answer()
        return

    # 2. Стоп контейнера
    await upd("✅ Файлы синхронизированы\n⏹ Останавливаю контейнер...")
    await docker_stop(uid)

    # 3. Запускаем контейнер
    await upd("✅ Контейнер остановлен\n🚀 Запускаю с новым аккаунтом...")
    ok = await docker_start(uid)

    if ok:
        # Обновляем запись в БД если нужно
        if old_port and old_expires:
            with db_connect() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO hosting (user_id, port, status, created_at, expires_at)
                    VALUES (?, ?, 'active', ?, ?)
                """, (uid, old_port, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"), old_expires))
                conn.execute("UPDATE users SET hosting_created = 1 WHERE user_id = ?", (uid,))

        await msg_obj.edit_text(
            f"✅ <b>Аккаунт успешно сменён!</b>\n\n"
            f"<blockquote>🔌 Порт: <code>{old_port}</code>\n"
            f"📅 Активен до: <code>{old_expires}</code></blockquote>\n\n"
            "Контейнер запущен с новой сессией.",
            parse_mode=ParseMode.HTML,
            reply_markup=server_info_kb()
        )
    else:
        await msg_obj.edit_text(
            "❌ <b>Не удалось запустить контейнер</b>\n\n"
            "Попробуйте запустить вручную через «🛠 Управление» → «▶️ Запустить»\n\n"
            f"Если не помогает — обратитесь к {ADMIN_CONTACT}.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("manage_menu")
        )
    await cq.answer()

# ═══════════════════════════════════════════════════════════════════
#                     ХЭНДЛЕРЫ: СОЗДАНИЕ СЕРВЕРА
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "create_hosting")
async def cb_create_hosting(cq: CallbackQuery):
    uid = cq.from_user.id
    if user_has_hosting(uid):
        await cq.message.edit_text(
            "❌ <b>У вас уже есть активный сервер!</b>\n\n"
            "Используйте раздел «⚡️ Мой сервер».",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("hosting_menu")
        )
        await cq.answer()
        return

    user = get_user(uid)
    if not user or not user["terms_accepted"]:
        await cq.message.edit_text(
            "📜 <b>Условия использования</b>\n\n"
            "Перед созданием сервера ознакомьтесь с правилами:\n\n"
            "• Запрещено использование для незаконных целей\n"
            "• Запрещён спам и вредоносное ПО\n"
            "• Нарушение авторских прав недопустимо\n"
            "• Сервис предоставляется «как есть»\n\n"
            "✅ Нажимая «Принимаю», вы соглашаетесь с условиями.",
            parse_mode=ParseMode.HTML,
            reply_markup=terms_kb()
        )
    else:
        await _show_months_for_create(cq)
    await cq.answer()

@dp.callback_query(F.data == "accept_terms")
async def cb_accept_terms(cq: CallbackQuery):
    set_terms_accepted(cq.from_user.id)
    await _show_months_for_create(cq)
    await cq.answer()

async def _show_months_for_create(cq: CallbackQuery):
    bal = get_balance(cq.from_user.id)
    await cq.message.edit_text(
        "📅 <b>Выберите период подписки</b>\n\n"
        f"💎 Ваш баланс: <b>{bal} ₽</b>\n\n"
        f"• 1 мес — {PRICE_PER_MONTH} ₽\n"
        f"• 3 мес — {PRICE_PER_MONTH * 3} ₽\n"
        f"• 6 мес — {PRICE_PER_MONTH * 6} ₽\n"
        f"• 12 мес — {PRICE_PER_MONTH * 12} ₽",
        parse_mode=ParseMode.HTML,
        reply_markup=months_kb("months")
    )

@dp.callback_query(F.data.startswith("months_"))
async def cb_months_select(cq: CallbackQuery, state: FSMContext):
    suffix = cq.data[len("months_"):]

    # Произвольный срок в днях
    if suffix == "custom_days":
        await cq.message.edit_text(
            "📅 <b>Свой срок (в днях)</b>\n\n"
            "✏️ Введите количество дней (минимум <b>14 дней = 25 ₽</b>):\n\n"
            "Пример: <code>30</code> → 54 ₽  |  <code>60</code> → 107 ₽",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("create_hosting")
        )
        await state.update_data(topup_input_msg_id=cq.message.message_id, topup_prefix="months")
        await state.set_state(PaymentSS.waiting_custom_days)
        await cq.answer()
        return

    try:
        months = int(suffix)
    except ValueError:
        await cq.answer("❌ Неверный вариант", show_alert=True)
        return

    amount = months * PRICE_PER_MONTH
    uid = cq.from_user.id
    bal = get_balance(uid)

    if bal < amount:
        b = InlineKeyboardBuilder()
        b.button(text="💳 Пополнить баланс", callback_data="topup_menu")
        b.button(text="◀️ Назад",             callback_data="menu")
        b.adjust(1)
        await cq.message.edit_text(
            f"❌ <b>Недостаточно средств!</b>\n\n"
            f"💸 Стоимость: <b>{amount} ₽</b>\n"
            f"💰 Ваш баланс: <b>{bal} ₽</b>\n"
            f"📉 Не хватает: <b>{amount - bal} ₽</b>\n\n"
            "Пополните баланс в разделе «💎 Кошелёк».",
            parse_mode=ParseMode.HTML,
            reply_markup=b.as_markup()
        )
        await cq.answer()
        return

    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить", callback_data=f"pay_confirm_{months}_{amount}")
    b.button(text="◀️ Назад",       callback_data="create_hosting")
    b.adjust(1)
    await cq.message.edit_text(
        f"💰 <b>Подтверждение оплаты</b>\n\n"
        f"┌ 📅 Период: <b>{months} мес.</b>\n"
        f"├ 💸 Сумма: <b>{amount} ₽</b>\n"
        f"└ 💰 Остаток: <b>{bal - amount} ₽</b>\n\n"
        "Подтвердить списание?",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("pay_confirm_"))
async def cb_pay_confirm(cq: CallbackQuery, state: FSMContext):
    parts = cq.data.split("_")
    # months может быть float (напр. 1.5 от кастомных дней), amount — int
    try:
        months = float(parts[2])
        amount = int(parts[3])
    except (ValueError, IndexError):
        await cq.answer("❌ Ошибка данных, попробуйте снова", show_alert=True)
        return
    uid = cq.from_user.id

    if not subtract_balance(uid, amount):
        await cq.answer("❌ Недостаточно средств", show_alert=True)
        return

    pending_creation[uid] = {"months": months, "amount": amount}
    db_save_flow(uid, "create", {"months": months, "amount": amount})
    (BASE_USERS_DIR / str(uid)).mkdir(parents=True, exist_ok=True)
    get_id_dir(uid).mkdir(parents=True, exist_ok=True)

    await cq.message.edit_text(
        "🔑 <b>Авторизация Telegram</b>\n\n"
        "Нажмите кнопку ниже, введите <b>API ID</b>, <b>API Hash</b> и номер телефона.\n\n"
        "Получить API данные: <a href=\"https://my.telegram.org/apps\">my.telegram.org</a>\n\n"
        "После авторизации нажмите «✅ Я авторизовался».",
        parse_mode=ParseMode.HTML,
        reply_markup=webapp_auth_kb(uid, action="create"),
        disable_web_page_preview=True
    )
    await state.clear()
    await cq.answer()



@dp.callback_query(F.data.startswith("confirm_auth_create_"))
async def cb_confirm_auth(cq: CallbackQuery):
    uid = cq.from_user.id
    target = int(cq.data.split("_")[3])

    if uid != target:
        await cq.answer("❌ Чужая авторизация", show_alert=True)
        return

    if not session_exists(uid):
        await cq.message.edit_text(
            "❌ <b>Сессия не найдена!</b>\n\n"
            "Пройдите авторизацию в веб-приложении:\n"
            "1. Введите правильный номер телефона\n"
            "2. Введите код из Telegram\n"
            "3. Дождитесь сообщения об успехе",
            parse_mode=ParseMode.HTML,
            reply_markup=webapp_auth_kb(uid, action="create")
        )
        await cq.answer()
        return

    creation_data = pending_creation.pop(uid, {})
    db_clear_flow(uid)
    months = creation_data.get("months", 1)

    msg_obj = await cq.message.edit_text(
        "🚀 <b>Создание контейнера...</b>\n\n"
        "Подождите 2–3 минуты.\n\n"
        "📦 Клон → 📁 Авторизация → 🐳 Сборка → 🚀 Запуск",
        parse_mode=ParseMode.HTML
    )

    async def upd(text):
        try:
            await msg_obj.edit_text(f"🚀 <b>Создание сервера</b>\n\n{text}", parse_mode=ParseMode.HTML)
        except Exception:
            pass

    ok, result = await docker_create(uid, upd)

    if ok:
        port = int(result)
        save_hosting(uid, port, months)
        h = get_hosting(uid)
        exp = h["expires_at"] if h else "—"
        # Начисляем реферальный бонус если куплено ≥30 дней
        days_bought = round(months * 30)
        asyncio.create_task(process_referral_bonus(uid, days_bought))
        await msg_obj.edit_text(
            f"🎉 <b>Сервер успешно создан!</b>\n\n"
            f"<blockquote>🔌 Порт: <code>{port}</code>\n"
            f"📅 Активен до: <code>{exp}</code>\n"
            f"⚙️ 1 CPU · 650 MB RAM</blockquote>\n\n"
            "💡 Для продления: «💎 Кошелёк».",
            parse_mode=ParseMode.HTML,
            reply_markup=server_info_kb()
        )
    else:
        amount = creation_data.get("amount", months * PRICE_PER_MONTH)
        add_balance(uid, amount)
        await msg_obj.edit_text(
            f"❌ <b>Ошибка создания сервера</b>\n\n<code>{result}</code>\n\n"
            f"<blockquote>Средства <b>{amount} ₽</b> возвращены на баланс.\n"
            f"Обратитесь к {ADMIN_CONTACT}.</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )
    await cq.answer()

# ═══════════════════════════════════════════════════════════════════
#                     ХЭНДЛЕРЫ: ФИНАНСЫ
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "finance_menu")
async def cb_finance_menu(cq: CallbackQuery):
    uid = cq.from_user.id
    bal = get_balance(uid)
    h = get_hosting(uid)
    sub_line = f"\n📅 Подписка до: `{h['expires_at']}`" if h else ""
    await cq.message.edit_text(
        f"💎 <b>Кошелёк и оплата</b>\n\n"
        f"<blockquote>💰 Баланс: <b>{bal} ₽</b>{sub_line}</blockquote>\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=finance_kb()
    )
    await cq.answer()

@dp.callback_query(F.data == "my_balance")
async def cb_my_balance(cq: CallbackQuery):
    uid = cq.from_user.id
    bal = get_balance(uid)
    h = get_hosting(uid)

    text = f"💎 <b>Мой кошелёк</b>\n\n<blockquote>💰 Баланс: <b>{bal} ₽</b>\n"
    if h:
        text += f"\n📅 Подписка до: <code>{h['expires_at']}</code>"
    text += f"</blockquote>\n\n💳 Пополнить — через кнопку ниже."

    b = InlineKeyboardBuilder()
    b.button(text="💳 Пополнить", callback_data="topup_menu")
    b.button(text="◀️ Назад",     callback_data="finance_menu")
    b.adjust(1)
    await cq.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=b.as_markup())
    await cq.answer()

@dp.callback_query(F.data == "referral_menu")
async def cb_referral_menu(cq: CallbackQuery):
    import urllib.parse
    uid = cq.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
    total = get_referral_count(uid)
    bonuses = get_referral_bonus_count(uid)

    share_text = (
        f"⚡️ Попробуй JokyHost — хостинг для Heroku Userbot!\n\n"
        f"🎁 Зарегистрируйся по моей ссылке и получи стабильный хостинг "
        f"всего за {PRICE_PER_MONTH} ₽/мес · 1 CPU · 650 MB RAM\n\n"
        f"👇 Моя реферальная ссылка:"
    )
    share_url = (
        "https://t.me/share/url?"
        + urllib.parse.urlencode({"url": ref_link, "text": share_text})
    )

    text = (
        f"🔗 <b>Реферальная программа</b>\n\n"
        f"<blockquote>Как это работает:\n"
        f"1. Друг регистрируется по вашей ссылке\n"
        f"2. Он покупает подписку на <b>30 дней и более</b>\n"
        f"3. Вам автоматически начисляется <b>+{REFERRAL_BONUS_DAYS} дня</b> к подписке</blockquote>\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"<blockquote>👥 Приглашено: <b>{total}</b>\n"
        f"🎁 Бонусов получено: <b>{bonuses}</b> (+{bonuses * REFERRAL_BONUS_DAYS} дн.)</blockquote>"
    )
    b = InlineKeyboardBuilder()
    b.button(text="📤 Поделиться ссылкой", url=share_url)
    b.button(text="◀️ Назад", callback_data="finance_menu")
    b.adjust(1)
    await cq.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=b.as_markup(), disable_web_page_preview=True)
    await cq.answer()

@dp.callback_query(F.data == "topup_menu")
async def cb_topup_menu(cq: CallbackQuery, state: FSMContext):
    await cq.message.edit_text(
        "💳 <b>Пополнение баланса</b>\n\n"
        f"1 мес — <b>{ym_total(PRICE_PER_MONTH)} ₽</b>\n"
        f"3 мес — <b>{ym_total(PRICE_PER_MONTH * 3)} ₽</b>\n"
        f"6 мес — <b>{ym_total(PRICE_PER_MONTH * 6)} ₽</b>\n"
        f"12 мес — <b>{ym_total(PRICE_PER_MONTH * 12)} ₽</b>\n\n"
        f"<i>Цены указаны с учётом комиссии банка 3%</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=months_kb("topup")
    )
    await cq.answer()



# ── вспомогательная функция: показать платёжный экран ЮMани ─────────────────
async def _show_payment_screen(target_msg, state: FSMContext, amount: int, label: str):
    """Генерирует уникальную ЮMани-ссылку и показывает экран оплаты."""
    chat_id = target_msg.chat.id if hasattr(target_msg, 'chat') else 0
    total = ym_total(amount)
    commission = total - amount

    # Генерируем уникальную ссылку с uuid label для автопроверки
    try:
        ym_url, ym_label = make_payment_link(chat_id, amount)
    except Exception as e:
        log.error(f"[YM] Ошибка генерации ссылки: {e}")
        ym_url = f"https://yoomoney.ru/to/{YOOMONEY_WALLET}/{total}"
        ym_label = str(uuid.uuid4())

    await state.update_data(
        ym_label=ym_label,
        ym_url=ym_url,
        topup_amount=amount,
        topup_label=label,
    )

    b = InlineKeyboardBuilder()
    b.button(text=f"💳 Оплатить {total} ₽ → ЮMани", url=ym_url)
    b.button(text="✅ Я оплатил — проверить", callback_data=f"ym_check:{ym_label}:{amount}")
    b.button(text="◀️ Назад", callback_data="finance_menu")
    b.adjust(1)

    text = (
        f"💳 <b>Пополнение баланса</b>\n\n"
        f"Тариф: <b>{label}</b>\n"
        f"К зачислению: <b>{amount} ₽</b>\n"
        f"К оплате: <b>{total} ₽</b>\n\n"
        f"<i>Оплата проходит через ЮMани с комиссией банка 3%</i>\n\n"
        f"1. Нажмите «Оплатить» — сумма заполнена автоматически\n"
        f"2. Вернитесь и нажмите «Я оплатил»"
    )

    sent = await target_msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=b.as_markup())
    await state.update_data(topup_msg_id=sent.message_id)
    await state.set_state(PaymentSS.waiting_ym_check)


# ── проверка оплаты через ЮMани API ─────────────────────────────────────────
@dp.callback_query(F.data.startswith("ym_check:"))
async def cb_ym_check(cq: CallbackQuery, state: FSMContext):
    parts = cq.data.split(":", 2)
    if len(parts) < 3:
        await cq.answer("❌ Неверный формат", show_alert=True)
        return

    ym_label = parts[1]
    try:
        amount = int(parts[2])
    except ValueError:
        await cq.answer("❌ Неверная сумма", show_alert=True)
        return

    uid = cq.from_user.id

    # Статус: проверяем
    await cq.message.edit_text(
        f"╔══ 🔍 <b>ПРОВЕРКА ОПЛАТЫ</b> ══╗\n\n"
        f"<blockquote>"
        f"⏳ Запрашиваю данные у ЮMани...\n"
        f"💳 Сумма: <b>{amount} ₽</b>\n"
        f"🔑 ID: <code>{ym_label[:8]}…</code>"
        f"</blockquote>\n\n"
        f"<i>Обычно занимает 2–5 секунд</i>",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer("⏳ Проверяю...")

    # Запускаем синхронную проверку в executor
    paid = await asyncio.get_event_loop().run_in_executor(
        None, check_payment_yoomoney, ym_label, ym_total(amount)
    )

    if paid:
        # Создаём и авто-апрувим платёж
        pay_id = create_payment(uid, amount, 0, f"yoomoney:{ym_label}")
        approve_payment(pay_id)
        add_balance(uid, amount)
        new_balance = get_balance(uid)
        await state.clear()

        b = InlineKeyboardBuilder()
        b.button(text="💎 Мой кошелёк", callback_data="finance_menu")
        b.button(text="🏠 Главное меню", callback_data="menu")
        b.adjust(1)

        await cq.message.edit_text(
            f"╔══ ✅ <b>ОПЛАТА ПОДТВЕРЖДЕНА</b> ══╗\n\n"
            f"<blockquote>"
            f"💰 Зачислено:    <b>+{amount} ₽</b>\n"
            f"💎 Новый баланс: <b>{new_balance} ₽</b>\n"
            f"🔑 ID: <code>{ym_label[:8]}…</code>"
            f"</blockquote>\n\n"
            f"🎉 Средства успешно зачислены на ваш счёт!",
            parse_mode=ParseMode.HTML,
            reply_markup=b.as_markup(),
        )
        log.info(f"[YM] ✅ Баланс пополнен | uid={uid} | +{amount} | новый баланс={new_balance}")

        # Уведомляем администратора
        try:
            user = cq.from_user
            uname = f"@{user.username}" if user.username else "нет"
            await bot.send_message(
                ADMIN_ID,
                f"💳 <b>Автопополнение ЮMани</b>\n\n"
                f"👤 {user.full_name} ({uname})\n"
                f"🆔 <code>{uid}</code>\n"
                f"💰 Сумма: <b>{amount} ₽</b>\n"
                f"💎 Баланс: <b>{new_balance} ₽</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        total = ym_total(amount)
        # Восстанавливаем ссылку из state если есть, иначе генерируем новую
        state_data = await state.get_data()
        ym_url = state_data.get("ym_url")
        if not ym_url:
            try:
                ym_url, _ = make_payment_link(cq.from_user.id, amount)
            except Exception:
                ym_url = f"https://yoomoney.ru/to/{YOOMONEY_WALLET}/{total}"

        b = InlineKeyboardBuilder()
        b.button(text=f"💳 Оплатить {total} ₽ → ЮMани", url=ym_url)
        b.button(text="🔄 Проверить ещё раз", callback_data=f"ym_check:{ym_label}:{amount}")
        b.button(text="◀️ Отмена", callback_data="finance_menu")
        b.adjust(1)

        await cq.message.edit_text(
            f"💳 <b>Оплата не найдена</b>\n\n"
            f"Сумма к оплате: <b>{total} ₽</b>\n\n"
            f"Возможные причины:\n"
            f"• Платёж ещё обрабатывается — подождите 1–2 мин\n"
            f"• Оплата не прошла или была отменена\n\n"
            f"<i>Если проблема не решается — {ADMIN_CONTACT}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=b.as_markup(),
        )
        log.warning(f"[YM] ❌ Не найдена | uid={uid} | label={ym_label!r}")



@dp.callback_query(F.data.startswith("topup_"))
async def cb_topup_months(cq: CallbackQuery, state: FSMContext):
    suffix = cq.data[len("topup_"):]

    # ── произвольная сумма ──────────────────────────────────────────
    if suffix == "custom_amount":
        await cq.message.edit_text(
            "💸 <b>Произвольная сумма пополнения</b>\n\n"
            "Введите сумму в рублях (минимум <b>25 ₽</b>):\n\n"
            "Пример: <code>150</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("topup_menu")
        )
        await state.update_data(topup_input_msg_id=cq.message.message_id)
        await state.set_state(PaymentSS.waiting_custom_amount)
        await cq.answer()
        return

    # ── произвольный срок ───────────────────────────────────────────
    if suffix == "custom_days":
        await cq.message.edit_text(
            "📅 <b>Произвольный срок пополнения</b>\n\n"
            "Введите количество дней (минимум <b>14 дней = 25 ₽</b>):\n\n"
            "Стоимость: <b>25 ₽</b> за каждые 14 дней\n"
            "Пример: <code>30</code> → 53 ₽ · <code>60</code> → 107 ₽",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("topup_menu")
        )
        await state.update_data(topup_input_msg_id=cq.message.message_id, topup_prefix="topup")
        await state.set_state(PaymentSS.waiting_custom_days)
        await cq.answer()
        return

    # ── стандартные периоды ─────────────────────────────────────────
    try:
        months = int(suffix)
    except ValueError:
        await cq.answer("❌ Неверный вариант", show_alert=True)
        return
    amount = months * PRICE_PER_MONTH
    await state.update_data(topup_months=months, topup_amount=amount, topup_label=f"{months} мес.")
    await _show_payment_screen(cq.message, state, amount, f"{months} мес.")
    await cq.answer()


# ── произвольная сумма: ввод ────────────────────────────────────────────────
@dp.message(PaymentSS.waiting_custom_amount)
async def handler_custom_amount(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    input_msg_id = data.get("topup_input_msg_id")

    try:
        amount = int(msg.text.strip())
    except ValueError:
        if input_msg_id:
            try:
                await bot.edit_message_text(
                    "❌ Введите целое число рублей (например <code>150</code>).",
                    chat_id=msg.chat.id, message_id=input_msg_id,
                    parse_mode=ParseMode.HTML, reply_markup=back_kb("topup_menu")
                )
            except Exception:
                pass
        return

    if amount < 25:
        if input_msg_id:
            try:
                await bot.edit_message_text(
                    "❌ <b>Минимальная сумма — 25 ₽.</b>\n\nВведите сумму ещё раз:",
                    chat_id=msg.chat.id, message_id=input_msg_id,
                    parse_mode=ParseMode.HTML, reply_markup=back_kb("topup_menu")
                )
            except Exception:
                pass
        return

    # Считаем примерный срок из суммы (25 ₽ = 14 дней → 1 руб ≈ 0.56 дней)
    approx_days = round(amount / 25 * 14)
    label = f"{amount} ₽ (~{approx_days} дн.)"
    await state.update_data(topup_amount=amount, topup_months=0, topup_label=label)

    class _FakeMsg:
        """Обёртка чтобы передать message_id в _show_payment_screen."""
        def __init__(self, chat_id, message_id):
            self.chat = type("C", (), {"id": chat_id})()
            self.message_id = message_id
        async def edit_text(self, text, **kwargs):
            return await bot.edit_message_text(text, chat_id=self.chat.id, message_id=self.message_id, **kwargs)

    fake = _FakeMsg(msg.chat.id, input_msg_id)
    await _show_payment_screen(fake, state, amount, label)


# ── произвольный срок: ввод ─────────────────────────────────────────────────
@dp.message(PaymentSS.waiting_custom_days)
async def handler_custom_days(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    input_msg_id = data.get("topup_input_msg_id")
    prefix = data.get("topup_prefix", "topup")

    try:
        days = int(msg.text.strip())
    except ValueError:
        if input_msg_id:
            try:
                await bot.edit_message_text(
                    "Введите целое число дней (например 30).",
                    chat_id=msg.chat.id, message_id=input_msg_id,
                    reply_markup=back_kb("topup_menu" if prefix == "topup" else "create_hosting")
                )
            except Exception:
                pass
        return

    if days < 14:
        if input_msg_id:
            try:
                await bot.edit_message_text(
                    "Минимальный срок — 14 дней. Введите количество дней ещё раз:",
                    chat_id=msg.chat.id, message_id=input_msg_id,
                    reply_markup=back_kb("topup_menu" if prefix == "topup" else "create_hosting")
                )
            except Exception:
                pass
        return

    amount = math.ceil(days / 14 * 25)
    months_approx = round(days / 30, 1)
    label = f"{days} дн. ({amount} руб.)"

    # Для создания сервера — показываем подтверждение списания с баланса
    if prefix == "months":
        uid = msg.from_user.id
        bal = get_balance(uid)
        if bal < amount:
            try:
                await bot.edit_message_text(
                    f"Недостаточно средств!\n\nСтоимость: {amount} руб.\nВаш баланс: {bal} руб.\nНе хватает: {amount - bal} руб.\n\nПополните баланс в разделе Кошелёк.",
                    chat_id=msg.chat.id, message_id=input_msg_id,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="topup_menu")
                    ]])
                )
            except Exception:
                pass
            await state.clear()
            return

        b = InlineKeyboardBuilder()
        b.button(text="✅ Подтвердить", callback_data=f"pay_confirm_{months_approx}_{amount}")
        b.button(text="◀️ Назад", callback_data="create_hosting")
        b.adjust(1)
        try:
            await bot.edit_message_text(
                f"Подтверждение оплаты\n\nПериод: {days} дн.\nСумма: {amount} руб.\nОстаток: {bal - amount} руб.\n\nПодтвердить списание?",
                chat_id=msg.chat.id, message_id=input_msg_id,
                parse_mode=ParseMode.HTML,
                reply_markup=b.as_markup()
            )
        except Exception:
            pass
        await state.clear()
        return

    # Для пополнения баланса (topup) — показываем реквизиты
    await state.update_data(topup_amount=amount, topup_months=months_approx, topup_label=label)

    class _FakeMsg:
        def __init__(self, chat_id, message_id):
            self.chat = type("C", (), {"id": chat_id})()
            self.message_id = message_id
        async def edit_text(self, text, **kwargs):
            return await bot.edit_message_text(text, chat_id=self.chat.id, message_id=self.message_id, **kwargs)

    fake = _FakeMsg(msg.chat.id, input_msg_id)
    await _show_payment_screen(fake, state, amount, label)


@dp.callback_query(F.data.startswith("approve_"))
async def cb_approve_payment(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    pay_id = int(cq.data.split("_")[1])
    pay = approve_payment(pay_id)
    if not pay:
        await cq.answer("❌ Заявка не найдена")
        return
    add_balance(pay["user_id"], pay["amount"])
    # Удаляем скриншот после обработки
    if pay["screenshot_path"]:
        try:
            Path(pay["screenshot_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    try:
        await cq.message.delete()
    except Exception:
        pass
    try:
        await bot.send_message(
            pay["user_id"],
            f"✅ <b>Оплата подтверждена!</b>\n\n"
            f"<blockquote>💰 Зачислено: <b>{pay['amount']} ₽</b>\n"
            f"💎 Новый баланс: <b>{get_balance(pay['user_id'])} ₽</b></blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb()
        )
    except Exception:
        pass
    await cq.answer("✅ Подтверждено")

@dp.callback_query(F.data.startswith("reject_"))
async def cb_reject_payment(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    pay_id = int(cq.data.split("_")[1])
    pay = reject_payment(pay_id)
    if not pay:
        await cq.answer("❌ Заявка не найдена")
        return
    # Удаляем скриншот после обработки
    if pay["screenshot_path"]:
        try:
            Path(pay["screenshot_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    try:
        await cq.message.edit_caption(
            f"❌ Заявка #{pay_id} отклонена."
        )
    except Exception:
        pass
    try:
        await bot.send_message(
            pay["user_id"],
            f"❌ <b>Заявка на оплату отклонена.</b>\n\n"
            f"<blockquote>Обратитесь к администратору {ADMIN_CONTACT} для уточнения.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    await cq.answer("❌ Отклонено")

@dp.callback_query(F.data == "payment_history")
async def cb_payment_history(cq: CallbackQuery):
    pays = get_payment_history(cq.from_user.id)
    if not pays:
        await cq.message.edit_text(
            "╔══ 📜 <b>ИСТОРИЯ ПЛАТЕЖЕЙ</b> ══╗\n\n"
            "<blockquote>У вас пока нет платежей.\n\n"
            "Пополните баланс через раздел «Кошелёк».</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("finance_menu")
        )
        await cq.answer()
        return

    status_map = {
        "pending":  ("⏳", "ожидание"),
        "approved": ("✅", "зачислено"),
        "rejected": ("❌", "отклонено"),
    }
    lines = []
    for p in pays:
        icon, label = status_map.get(p["status"], ("❓", p["status"]))
        date = p["created_at"][:10] if p.get("created_at") else "—"
        lines.append(
            f"{icon} <code>{date}</code>  <b>{p['amount']} ₽</b>  <i>{label}</i>"
        )

    total_paid = sum(p["amount"] for p in pays if p["status"] == "approved")

    text = (
        f"╔══ 📜 <b>ИСТОРИЯ ПЛАТЕЖЕЙ</b> ══╗\n\n"
        f"<blockquote>"
        + "\n".join(lines) +
        f"\n\n━━━━━━━━━━━━━━━━━━\n"
        f"💎 Всего пополнено: <b>{total_paid} ₽</b>"
        f"</blockquote>"
    )
    await cq.message.edit_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=back_kb("finance_menu")
    )
    await cq.answer()

@dp.callback_query(F.data == "extend_sub")
async def cb_extend_sub(cq: CallbackQuery):
    if not user_has_hosting(cq.from_user.id):
        await cq.answer("Нет активного сервера", show_alert=True)
        return
    bal = get_balance(cq.from_user.id)
    h = get_hosting(cq.from_user.id)
    try:
        days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
    except Exception:
        days_left = 0
    await cq.message.edit_text(
        f"🔄 <b>Продление подписки</b>\n\n"
        f"<blockquote>📅 Текущий срок до: <code>{h['expires_at']}</code>\n"
        f"⏳ Осталось: <b>{days_left} дн.</b>\n"
        f"💰 Баланс: <b>{bal} ₽</b>\n\n"
        f"💸 Стоимость: {PRICE_PER_MONTH} ₽/мес | минимум 14 дн. = 25 ₽</blockquote>\n\n"
        "📋 Выберите период продления:",
        parse_mode=ParseMode.HTML,
        reply_markup=months_kb("extend")
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("extend_") & ~F.data.startswith("extend_confirm_"))
async def cb_extend_months(cq: CallbackQuery, state: FSMContext):
    suffix = cq.data[len("extend_"):]
    uid = cq.from_user.id

    # Произвольный срок в днях
    if suffix == "custom_days":
        h = get_hosting(uid)
        bal = get_balance(uid)
        days_left = 0
        if h:
            try:
                days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
            except Exception:
                pass
        await cq.message.edit_text(
            f"🔄 <b>Продление — свой срок</b>\n\n"
            f"📅 Текущий остаток: <b>{days_left} дн.</b> (до <code>{h['expires_at'] if h else '—'}</code>)\n"
            f"💰 Баланс: <b>{bal} ₽</b>\n\n"
            f"✏️ Введите количество дней для продления (минимум <b>14 дней = 25 ₽</b>):\n\n"
            f"Пример: <code>30</code> → 54 ₽  |  <code>60</code> → 107 ₽",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("extend_sub")
        )
        await state.update_data(extend_msg_id=cq.message.message_id)
        await state.set_state(PaymentSS.waiting_extend_days)
        await cq.answer()
        return

    try:
        months = int(suffix)
    except ValueError:
        await cq.answer("❌ Неверный вариант", show_alert=True)
        return

    amount = months * PRICE_PER_MONTH
    bal = get_balance(uid)
    h = get_hosting(uid)

    if bal < amount:
        b = InlineKeyboardBuilder()
        b.button(text="💳 Пополнить баланс", callback_data="topup_menu")
        b.button(text="◀️ Назад", callback_data="extend_sub")
        b.adjust(1)
        await cq.message.edit_text(
            f"❌ <b>Недостаточно средств!</b>\n\n"
            f"💸 Стоимость: <b>{amount} ₽</b>\n"
            f"💰 Ваш баланс: <b>{bal} ₽</b>\n"
            f"📉 Не хватает: <b>{amount - bal} ₽</b>\n\n"
            "Пополните баланс в разделе «💎 Кошелёк».",
            parse_mode=ParseMode.HTML,
            reply_markup=b.as_markup()
        )
        await cq.answer()
        return

    # Показываем экран подтверждения
    try:
        cur_exp = h["expires_at"] if h else "—"
        from datetime import datetime as _dt
        base = _dt.strptime(cur_exp, "%Y-%m-%d").date() if h else datetime.now(MSK).date()
        today = datetime.now(MSK).date()
        if base < today:
            base = today
        new_exp = (datetime.combine(base, datetime.min.time()) + timedelta(days=months * 30)).strftime("%Y-%m-%d")
    except Exception:
        new_exp = "—"

    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить списание", callback_data=f"extend_confirm_{months}_{amount}")
    b.button(text="◀️ Отмена", callback_data="extend_sub")
    b.adjust(1)
    await cq.message.edit_text(
        f"🔄 <b>Подтверждение продления</b>\n\n"
        f"┌ 📅 Период: <b>{months} мес. ({months * 30} дн.)</b>\n"
        f"├ 💸 Спишется: <b>{amount} ₽</b>\n"
        f"├ 💰 Остаток: <b>{bal - amount} ₽</b>\n"
        f"└ 📅 Новый срок до: `{new_exp}`\n\n"
        "Подтвердить?",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("extend_confirm_") & ~F.data.startswith("extend_confirm_days_"))
async def cb_extend_confirm(cq: CallbackQuery):
    parts = cq.data.split("_")
    # extend_confirm_<months>_<amount>
    try:
        months = int(parts[2])
        amount = int(parts[3])
    except (ValueError, IndexError):
        await cq.answer("❌ Ошибка данных", show_alert=True)
        return

    uid = cq.from_user.id
    bal = get_balance(uid)

    if bal < amount:
        await cq.answer(f"❌ Нужно {amount} ₽, у вас {bal} ₽", show_alert=True)
        return
    if not subtract_balance(uid, amount):
        await cq.answer("❌ Ошибка списания", show_alert=True)
        return

    extend_hosting(uid, months=months)
    clear_warnings(uid)
    asyncio.create_task(process_referral_bonus(uid, round(months * 30)))

    h = get_hosting(uid)
    if h and h["status"] == "expired":
        asyncio.create_task(docker_start(uid))
        with db_connect() as conn:
            conn.execute("UPDATE hosting SET status = 'active' WHERE user_id = ?", (uid,))

    h = get_hosting(uid)
    await cq.message.edit_text(
        f"✅ <b>Подписка продлена!</b>\n\n"
        f"<blockquote>📅 Новый срок до: <code>{h['expires_at']}</code>\n"
        f"💸 Списано: <b>{amount} ₽</b>\n"
        f"💰 Остаток: <b>{get_balance(uid)} ₽</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("finance_menu")
    )
    await cq.answer("✅ Продлено!")


@dp.message(PaymentSS.waiting_extend_days)
async def handler_extend_days(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    extend_msg_id = data.get("extend_msg_id")
    uid = msg.from_user.id

    async def edit(text):
        if extend_msg_id:
            try:
                await bot.edit_message_text(text, chat_id=msg.chat.id, message_id=extend_msg_id,
                                            parse_mode=ParseMode.HTML,
                                            reply_markup=back_kb("extend_sub"))
            except Exception:
                pass

    try:
        days = int(msg.text.strip())
    except ValueError:
        await edit("Введите целое число дней (например 30).")
        return

    if days < 14:
        await edit("Минимальный срок — 14 дней. Введите количество дней ещё раз:")
        return

    amount = math.ceil(days / 14 * 25)
    bal = get_balance(uid)

    if bal < amount:
        if extend_msg_id:
            try:
                await bot.edit_message_text(
                    f"❌ <b>Недостаточно средств!</b>\n\n"
                    f"💸 Стоимость <b>{days} дн.: {amount} ₽</b>\n"
                    f"💰 Ваш баланс: <b>{bal} ₽</b>\n"
                    f"📉 Не хватает: <b>{amount - bal} ₽</b>\n\n"
                    f"Пополните баланс в разделе «💎 Кошелёк».",
                    chat_id=msg.chat.id, message_id=extend_msg_id,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="💳 Пополнить", callback_data="topup_menu")
                    ]])
                )
            except Exception:
                pass
        await state.clear()
        return

    # Считаем новую дату для превью
    h = get_hosting(uid)
    try:
        cur_exp = h["expires_at"] if h else None
        base = datetime.strptime(cur_exp, "%Y-%m-%d").date() if cur_exp else datetime.now(MSK).date()
        today = datetime.now(MSK).date()
        if base < today:
            base = today
        new_exp = (datetime.combine(base, datetime.min.time()) + timedelta(days=days)).strftime("%Y-%m-%d")
    except Exception:
        new_exp = "—"

    # Показываем экран подтверждения
    b = InlineKeyboardBuilder()
    b.button(text="✅ Подтвердить списание", callback_data=f"extend_confirm_days_{days}_{amount}")
    b.button(text="◀️ Отмена", callback_data="extend_sub")
    b.adjust(1)
    if extend_msg_id:
        try:
            await bot.edit_message_text(
                f"🔄 <b>Подтверждение продления</b>\n\n"
                f"┌ 📅 Период: <b>{days} дн.</b>\n"
                f"├ 💸 Спишется: <b>{amount} ₽</b>\n"
                f"├ 💰 Остаток: <b>{bal - amount} ₽</b>\n"
                f"└ 📅 Новый срок до: `{new_exp}`\n\n"
                "Подтвердить?",
                chat_id=msg.chat.id, message_id=extend_msg_id,
                parse_mode=ParseMode.HTML,
                reply_markup=b.as_markup()
            )
        except Exception:
            pass
    await state.clear()

@dp.callback_query(F.data.startswith("extend_confirm_days_"))
async def cb_extend_confirm_days(cq: CallbackQuery):
    parts = cq.data.split("_")
    # extend_confirm_days_<days>_<amount>
    try:
        days = int(parts[3])
        amount = int(parts[4])
    except (ValueError, IndexError):
        await cq.answer("❌ Ошибка данных", show_alert=True)
        return

    uid = cq.from_user.id
    bal = get_balance(uid)

    if bal < amount:
        await cq.answer(f"❌ Нужно {amount} ₽, у вас {bal} ₽", show_alert=True)
        return
    if not subtract_balance(uid, amount):
        await cq.answer("❌ Ошибка списания", show_alert=True)
        return

    extend_hosting(uid, days=days)
    clear_warnings(uid)
    asyncio.create_task(process_referral_bonus(uid, days))

    h = get_hosting(uid)
    if h and h["status"] == "expired":
        asyncio.create_task(docker_start(uid))
        with db_connect() as conn:
            conn.execute("UPDATE hosting SET status = 'active' WHERE user_id = ?", (uid,))

    h = get_hosting(uid)
    await cq.message.edit_text(
        f"✅ <b>Подписка продлена на {days} дн.!</b>\n\n"
        f"<blockquote>📅 Новый срок до: <code>{h['expires_at']}</code>\n"
        f"💸 Списано: <b>{amount} ₽</b>\n"
        f"💰 Остаток: <b>{get_balance(uid)} ₽</b></blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("finance_menu")
    )
    await cq.answer("✅ Продлено!")

# ═══════════════════════════════════════════════════════════════════
#                         ХЭНДЛЕРЫ: ПОМОЩЬ
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "help")
async def cb_help(cq: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text=f"📩 Написать {ADMIN_CONTACT}",
             url=f"https://t.me/{ADMIN_CONTACT.lstrip('@')}")
    b.button(text="◀️ Назад", callback_data="menu")
    b.adjust(1)
    await cq.message.edit_text(
        "🆘 <b>Поддержка JokyHost</b>\n\n"
        f"<blockquote>📩 Администратор: {ADMIN_CONTACT}\n"
        f"📢 Канал: {CHANNEL_REQUIRED}\n"
        f"📜 Условия: <a href=\"{TERMS_LINK}\">GitHub</a></blockquote>\n\n"
        "🔹 <b>Как начать?</b>\n"
        "<blockquote>1. Пополните баланс\n"
        "2. Создайте сервер: введите API ID и Hash\n"
        "3. Авторизуйтесь через Web App\n"
        "4. Сервер запустится автоматически</blockquote>\n\n"
        "🔹 <b>Цены и ресурсы</b>\n"
        f"<blockquote>💰 {PRICE_PER_MONTH} ₽/мес · 1 CPU · 650 MB RAM\n"
        f"🌐 Сервер: <code>{SERVER_IP}</code></blockquote>",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=b.as_markup()
    )
    await cq.answer()

# ═══════════════════════════════════════════════════════════════════
#                         ХЭНДЛЕРЫ: ОТЗЫВЫ
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "leave_review")
async def cb_leave_review(cq: CallbackQuery, state: FSMContext):
    """Начало процесса оставления отзыва - выбор звёзд"""
    await state.set_state(ReviewStates.waiting_stars)
    
    await cq.message.edit_text(
        "⭐️ <b>Оставить отзыв</b>\n\n"
        "<blockquote>Выберите оценку:\n\n"
        "1 ⭐ — Плохо\n"
        "2 ⭐ — Ниже среднего\n"
        "3 ⭐ — Нормально\n"
        "4 ⭐ — Хорошо\n"
        "5 ⭐ — Отлично!</blockquote>\n\n"
        "Нажмите на нужное количество звёзд:",
        parse_mode=ParseMode.HTML,
        reply_markup=stars_kb()
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("stars_"), ReviewStates.waiting_stars)
async def cb_stars_selected(cq: CallbackQuery, state: FSMContext):
    """Пользователь выбрал количество звёзд"""
    stars = int(cq.data.split("_")[1])
    await state.update_data(review_stars=stars)
    await state.set_state(ReviewStates.waiting_text)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Отмена", callback_data="menu")
    
    await cq.message.edit_text(
        f"✍️ <b>Оставить отзыв</b>\n\n"
        f"Ваша оценка: <b>{stars} ⭐</b>\n\n"
        f"Теперь напишите ваш отзыв о сервисе JokyHost.\n\n"
        f"💬 Отправьте текст в чат:\n\n"
        f"_Ваше сообщение будет удалено после отправки на модерацию._",
        parse_mode=ParseMode.HTML,
        reply_markup=kb.as_markup()
    )
    await cq.answer()

@dp.message(ReviewStates.waiting_text, Command("cancel"))
async def review_cancel(msg: Message, state: FSMContext):
    """Отмена написания отзыва"""
    await state.clear()
    try:
        await msg.delete()
    except Exception:
        pass

@dp.message(ReviewStates.waiting_text)
async def review_text_handler(msg: Message, state: FSMContext):
    """Обработка текста отзыва с сохранением оценки"""
    user = msg.from_user
    review_text = msg.text or msg.caption or ""
    
    # Получаем выбранные звёзды
    data = await state.get_data()
    stars = data.get("review_stars", 5)
    
    # Удаляем сообщение пользователя с отзывом
    try:
        await msg.delete()
    except Exception as e:
        log.warning(f"Could not delete user message: {e}")
    
    if not review_text.strip():
        try:
            await bot.edit_message_text(
                "✍️ <b>Оставить отзыв</b>\n\n❌ Отзыв не может быть пустым. Попробуйте снова:",
                chat_id=msg.chat.id, message_id=msg.message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=back_kb("menu")
            )
        except Exception:
            pass
        await state.clear()
        return
    
    # Отправляем уведомление пользователю
    processing_msg = await msg.answer(
        "⏳ <b>Отзыв отправлен на модерацию...</b>",
        parse_mode=ParseMode.HTML
    )
    
    # Форматируем отзыв
    safe_review_text = review_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_name = (user.full_name or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Отправляем администратору
    admin_caption = (
        f"✍️ <b>Новый отзыв на модерации</b>\n\n"
        f"┌ 👤 ID: `{user.id}`\n"
        f"├ 📛 Имя: {safe_name}\n"
        f"├ 👤 @{user.username or 'нет'}\n"
        f"├ ⭐ Оценка: <b>{stars}/5</b>\n"
        f"└ 💬 <b>Текст:</b>\n{safe_review_text}"
    )
    
    # Сначала сохраняем в БД с временным admin_msg_id=0
    review_id = create_review(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
        text=review_text,
        stars=stars,
        msg_id=processing_msg.message_id,
        admin_msg_id=0
    )

    # Отправляем сообщение администратору СРАЗУ с кнопками
    admin_msg = await bot.send_message(
        ADMIN_ID,
        admin_caption,
        parse_mode=ParseMode.HTML,
        reply_markup=review_approve_kb(review_id) if review_id else None
    )

    # Обновляем admin_msg_id в БД
    if review_id and admin_msg:
        with db_connect() as conn:
            conn.execute(
                "UPDATE reviews SET admin_msg_id = ? WHERE id = ?",
                (admin_msg.message_id, review_id)
            )

    if review_id:
        
        await processing_msg.edit_text(
            f"✅ <b>Отзыв отправлен на модерацию!</b>\n\n"
            f"Ваша оценка: <b>{stars} ⭐</b>\n\n"
            f"После проверки он появится в канале. Спасибо! 🙏",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu")
        )
    else:
        await processing_msg.edit_text(
            "❌ <b>Ошибка при отправке отзыва</b>\n\n"
            "Пожалуйста, попробуйте позже.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("menu")
        )
    
    await state.clear()

@dp.callback_query(F.data.startswith("review_approve_"))
async def cb_review_approve(cq: CallbackQuery):
    """Админ подтверждает отзыв и публикует в канал"""
    if cq.from_user.id != ADMIN_ID:
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    
    review_id = int(cq.data.split("_")[2])
    
    review = get_review(review_id)
    if not review:
        await cq.answer("❌ Отзыв не найден.", show_alert=True)
        return
    
    approve_review(review_id)
    
    # sqlite3.Row не поддерживает .get() — конвертируем в dict
    review = dict(review)
    stars = review.get("stars") or 5
    safe_text = review['text'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_name = (review['full_name'] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    channel_text = (
        f"<b>{stars} ⭐</b>\n\n"
        f"👤 <b>{safe_name}</b>"
        + (f" (@{review['username']})" if review['username'] else "")
        + f"\n\n{safe_text}\n\n"
        f"<i>Отзыв опубликован через JokyHost</i>"
    )
    
    try:
        await bot.send_message(
            REVIEWS_CHANNEL,
            channel_text,
            message_thread_id=REVIEWS_THREAD_ID,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        log.info(f"Review {review_id} published to channel {REVIEWS_CHANNEL}")
    except Exception as e:
        log.error(f"Failed to post review to channel: {e}")
        await cq.answer(f"❌ Ошибка публикации: {str(e)[:50]}", show_alert=True)
        return
    
    try:
        await bot.send_message(
            review["user_id"],
            f"🎉 <b>Ваш отзыв опубликован!</b>\n\n{stars} ⭐\n\nСпасибо! 💙",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        log.warning(f"Could not notify user: {e}")
    
    if review["msg_id"]:
        try:
            await bot.edit_message_text(
                f"✅ <b>Ваш отзыв опубликован!</b> 🎉\n\n{stars} ⭐\n\nСпасибо!",
                chat_id=review["user_id"],
                message_id=review["msg_id"],
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    
    try:
        await cq.message.edit_text(
            f"{cq.message.text or '✍️ Отзыв'}\n\n✅ <b>Опубликовано ({stars} ⭐)</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    
    await cq.answer("✅ Опубликовано!")

@dp.callback_query(F.data.startswith("review_reject_"))
async def cb_review_reject(cq: CallbackQuery):
    if cq.from_user.id != ADMIN_ID:
        await cq.answer("❌ Нет доступа", show_alert=True)
        return

    review_id = int(cq.data.split("_")[2])
    review = get_review(review_id)
    if not review:
        await cq.answer("❌ Отзыв не найден")
        return

    reject_review(review_id)

    try:
        await bot.edit_message_text(
            "❌ <b>Ваш отзыв не прошёл модерацию.</b>\n\nПопробуйте написать иначе.",
            chat_id=review["user_id"],
            message_id=review["msg_id"],
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    await cq.message.edit_text(
        (cq.message.text or "✍️ Отзыв") + "\n\n❌ <b>Отклонено.</b>",
        parse_mode=ParseMode.HTML
    )
    await cq.answer("❌ Отклонено")

# ═══════════════════════════════════════════════════════════════════
#                         ХЭНДЛЕРЫ: АДМИН
# ═══════════════════════════════════════════════════════════════════
def admin_only(cq: CallbackQuery) -> bool:
    return cq.from_user.id == ADMIN_ID

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(cq: CallbackQuery):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    await cq.message.edit_text(
        "👑 <b>JokyHost — Панель администратора</b>\n\nВыберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_kb()
    )
    await cq.answer()

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(cq: CallbackQuery):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    users, hostings, active, pending, revenue = get_stats()
    now = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")

    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data="admin_stats")
    b.button(text="◀️ Назад",    callback_data="admin_panel")
    b.adjust(1)

    await cq.message.edit_text(
        f"📊 <b>Статистика JokyHost</b>\n\n"
        f"┌ 👥 Пользователей: <b>{users}</b>\n"
        f"├ ⚡️ Серверов всего: <b>{hostings}</b>\n"
        f"├ ✅ Активных: <b>{active}</b>\n"
        f"├ 💳 Ожидают оплаты: <b>{pending}</b>\n"
        f"├ 💰 Выручка: <b>{revenue} ₽</b>\n"
        f"└ 🕐 Обновлено: {now}",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await cq.answer()

@dp.callback_query(F.data == "admin_payments")
async def cb_admin_payments(cq: CallbackQuery):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    pays = get_pending_payments()
    if not pays:
        await cq.message.edit_text(
            "💳 <b>Заявки на оплату</b>\n\n📭 Нет заявок.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("admin_panel")
        )
        await cq.answer()
        return
    text = f"💳 <b>Ожидающие заявки ({len(pays)}):</b>\n\n"
    for p in pays:
        text += f"#{p['id']} | <code>{p['user_id']}</code> | <b>{p['amount']} ₽</b> | {p['created_at'][:16]}\n"
    await cq.message.edit_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=back_kb("admin_panel")
    )
    await cq.answer()

@dp.callback_query(F.data == "admin_hostings")
async def cb_admin_hostings(cq: CallbackQuery):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    hostings = get_all_hostings()
    if not hostings:
        await cq.message.edit_text(
            "📋 <b>Все серверы</b>\n\n📭 Серверов нет.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("admin_panel")
        )
        await cq.answer()
        return
    b = InlineKeyboardBuilder()
    status_icons = {"active": "🟢", "expired": "🔴", "pending": "⏳"}
    for h in hostings[:20]:
        icon = status_icons.get(h["status"], "❓")
        b.button(
            text=f"{icon} {h['user_id']} :{h['port']}",
            callback_data=f"adm_srv_panel_{h['user_id']}"
        )
    b.button(text="◀️ Назад", callback_data="admin_panel")
    b.adjust(1)
    await cq.message.edit_text(
        f"📋 <b>Все серверы ({len(hostings)}):</b>\n\nВыберите сервер для управления:",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("adm_srv_panel_"))
async def cb_adm_srv_panel(cq: CallbackQuery):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    target_uid = int(cq.data.split("_")[3])
    h = get_hosting(target_uid)
    if not h:
        await cq.answer("❌ Сервер не найден", show_alert=True)
        return
    container_status = await docker_container_status(target_uid)
    status_text = fmt_status(container_status)
    await cq.message.edit_text(
        f"🖥 <b>Сервер пользователя</b> `{target_uid}`\n\n"
        f"├ 🔌 Порт: <code>{h['port']}</code>\n"
        f"├ 📅 До: <code>{h['expires_at']}</code>\n"
        f"└ 🐳 Статус: {status_text}\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_server_manage_kb(target_uid)
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("adm_srv_start_"))
async def cb_adm_srv_start(cq: CallbackQuery):
    if not admin_only(cq): await cq.answer("❌", show_alert=True); return
    uid = int(cq.data.split("_")[3])
    await cq.answer("▶️ Запускаем...")
    ok = await docker_start(uid)
    await cq.message.edit_text(
        f"{'▶️ Сервер `' + str(uid) + '<code> запущен!' if ok else '❌ Ошибка запуска </code>' + str(uid) + '`'}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_server_manage_kb(uid)
    )

@dp.callback_query(F.data.startswith("adm_srv_stop_"))
async def cb_adm_srv_stop(cq: CallbackQuery):
    if not admin_only(cq): await cq.answer("❌", show_alert=True); return
    uid = int(cq.data.split("_")[3])
    await cq.answer("⏹ Останавливаем...")
    ok = await docker_stop(uid)
    await cq.message.edit_text(
        f"{'⏹ Сервер `' + str(uid) + '` остановлен.' if ok else '❌ Ошибка остановки `' + str(uid) + '`'}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_server_manage_kb(uid)
    )

@dp.callback_query(F.data.startswith("adm_srv_restart_"))
async def cb_adm_srv_restart(cq: CallbackQuery):
    if not admin_only(cq): await cq.answer("❌", show_alert=True); return
    uid = int(cq.data.split("_")[3])
    await cq.answer("🔁 Перезапускаем...")
    ok = await docker_restart(uid)
    await cq.message.edit_text(
        f"{'🔁 Сервер `' + str(uid) + '<code> перезапущен!' if ok else '❌ Ошибка рестарта </code>' + str(uid) + '`'}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_server_manage_kb(uid)
    )

@dp.callback_query(F.data.startswith("adm_srv_logs_"))
async def cb_adm_srv_logs(cq: CallbackQuery):
    if not admin_only(cq): await cq.answer("❌", show_alert=True); return
    uid = int(cq.data.split("_")[3])
    await cq.answer("📋 Загружаем логи...")
    logs = await docker_logs(uid, lines=40)
    truncated = logs[-3200:] if len(logs) > 3200 else logs
    truncated = html.escape(truncated)
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data=f"adm_srv_logs_{uid}")
    b.button(text="🤖 Диагностика AI", callback_data=f"fix_with_ai_{uid}_{ADMIN_ID}")
    b.button(text="◀️ Назад",    callback_data=f"adm_srv_panel_{uid}")
    b.adjust(1)
    await cq.message.edit_text(
        f"📋 <b>Логи</b> `{uid}` <b>(40 строк)</b>\n\n<pre>{truncated}</pre>",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )

@dp.callback_query(F.data == "admin_add_balance")
async def cb_admin_add_balance_start(cq: CallbackQuery, state: FSMContext):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    step_msg = await cq.message.edit_text(
        "➕ <b>Начисление баланса</b>\n\nВведите Telegram ID пользователя:",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("admin_panel")
    )
    await state.update_data(step_msg_id=step_msg.message_id, step_chat_id=cq.message.chat.id)
    await state.set_state(AdminStates.add_balance_uid)
    await cq.answer()

@dp.message(AdminStates.add_balance_uid, F.from_user.id == ADMIN_ID)
async def handler_add_balance_uid(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    try:
        uid = int(msg.text.strip())
        await state.update_data(target_uid=uid)
        await state.set_state(AdminStates.add_balance_amount)
        try:
            await bot.edit_message_text(
                f"➕ <b>Начисление баланса</b>\n\nПользователь: `{uid}`\n\nВведите сумму начисления (₽):",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            sent = await msg.answer(
                f"➕ <b>Начисление баланса</b>\n\nПользователь: `{uid}`\n\nВведите сумму (₽):",
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
            await state.update_data(step_msg_id=sent.message_id, step_chat_id=msg.chat.id)
    except ValueError:
        try:
            await bot.edit_message_text(
                "➕ <b>Начисление баланса</b>\n\n❌ Неверный ID. Введите числовой Telegram ID:",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            pass

@dp.message(AdminStates.add_balance_amount, F.from_user.id == ADMIN_ID)
async def handler_add_balance_amount(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    try:
        amount = int(msg.text.strip())
        uid = data["target_uid"]
        ensure_user(types.User(id=uid, is_bot=False, first_name=str(uid)))
        add_balance(uid, amount)
        new_bal = get_balance(uid)
        await state.clear()
        try:
            await bot.edit_message_text(
                f"✅ Начислено <b>{amount} ₽</b> пользователю <code>{uid}</code>.\n💎 Новый баланс: <b>{new_bal} ₽</b>",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=admin_kb()
            )
        except Exception:
            await msg.answer(
                f"✅ Начислено <b>{amount} ₽</b> пользователю <code>{uid}</code>.\n💎 Баланс: <b>{new_bal} ₽</b>",
                parse_mode=ParseMode.HTML, reply_markup=admin_kb()
            )
        try:
            await bot.send_message(uid,
                f"💎 <b>Пополнение баланса!</b>\n\n<blockquote>Администратор начислил <b>{amount} ₽</b> на ваш баланс.\n💰 Текущий баланс: <b>{new_bal} ₽</b></blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
    except ValueError:
        try:
            await bot.edit_message_text(
                f"➕ <b>Начисление баланса</b>\n\nПользователь: `{data.get('target_uid')}`\n\n❌ Введите числовую сумму (₽):",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            pass

@dp.callback_query(F.data == "admin_force_sub")
async def cb_admin_force_sub(cq: CallbackQuery, state: FSMContext):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    step_msg = await cq.message.edit_text(
        "🔧 <b>Выдать подписку</b>\n\nВведите ID пользователя:",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("admin_panel")
    )
    await state.update_data(step_msg_id=step_msg.message_id, step_chat_id=cq.message.chat.id)
    await state.set_state(AdminStates.force_sub_uid)
    await cq.answer()

@dp.message(AdminStates.force_sub_uid, F.from_user.id == ADMIN_ID)
async def handler_force_sub_uid(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    try:
        uid = int(msg.text.strip())
        await state.update_data(force_uid=uid)
        await state.set_state(AdminStates.force_sub_expires)
        try:
            await bot.edit_message_text(
                f"🔧 <b>Выдать подписку</b>\n\nПользователь: `{uid}`\n\n"
                "Введите дату истечения (<code>ГГГГ-ММ-ДД</code>):\nПример: <code>2025-12-31</code>",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            sent = await msg.answer(
                f"🔧 <b>Выдать подписку</b>\n\nПользователь: `{uid}`\n\nВведите дату (<code>ГГГГ-ММ-ДД</code>):",
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
            await state.update_data(step_msg_id=sent.message_id, step_chat_id=msg.chat.id)
    except ValueError:
        try:
            await bot.edit_message_text(
                "🔧 <b>Выдать подписку</b>\n\n❌ Неверный ID. Введите числовой Telegram ID:",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            pass

@dp.message(AdminStates.force_sub_expires, F.from_user.id == ADMIN_ID)
async def handler_force_sub_expires(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    try:
        datetime.strptime(msg.text.strip(), "%Y-%m-%d")
        uid = data["force_uid"]
        expires = msg.text.strip()

        (BASE_USERS_DIR / str(uid)).mkdir(parents=True, exist_ok=True)
        ensure_user(types.User(id=uid, is_bot=False, first_name=str(uid)))
        set_subscribed(uid)

        with db_connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hosting (user_id, port, status, created_at, expires_at)
                VALUES (?, 0, 'pending', ?, ?)
            """, (uid, datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"), expires))
            conn.execute("UPDATE users SET hosting_created = 0 WHERE user_id = ?", (uid,))

        await state.clear()
        try:
            await bot.edit_message_text(
                f"✅ Подписка выдана пользователю `{uid}<code> до </code>{expires}`.\n"
                f"ℹ️ Сервер нужно создать отдельно через бота.",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=admin_kb()
            )
        except Exception:
            await msg.answer(
                f"✅ Подписка выдана пользователю `{uid}<code> до </code>{expires}`.",
                parse_mode=ParseMode.HTML, reply_markup=admin_kb()
            )
        try:
            await bot.send_message(uid,
                f"🎉 <b>Доступ к JokyHost активирован!</b>\n\n"
                f"<blockquote>📅 Подписка до: <code>{expires}</code>\n\n"
                "Зайдите в бот и создайте сервер.</blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
    except ValueError:
        try:
            await bot.edit_message_text(
                f"🔧 <b>Выдать подписку</b>\n\nПользователь: `{data.get('force_uid')}`\n\n"
                "❌ Неверный формат. Используйте <code>ГГГГ-ММ-ДД</code>:",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            pass

@dp.callback_query(F.data == "admin_change_expiry")
async def cb_admin_change_expiry(cq: CallbackQuery, state: FSMContext):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    step_msg = await cq.message.edit_text(
        "📅 <b>Изменение срока подписки</b>\n\nВведите ID пользователя:",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("admin_panel")
    )
    await state.update_data(step_msg_id=step_msg.message_id, step_chat_id=cq.message.chat.id)
    await state.set_state(AdminStates.change_expiry_uid)
    await cq.answer()

@dp.message(AdminStates.change_expiry_uid, F.from_user.id == ADMIN_ID)
async def handler_change_expiry_uid(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    try:
        uid = int(msg.text.strip())
        h = get_hosting(uid)
        if not h:
            try:
                await bot.edit_message_text(
                    "📅 <b>Изменение срока подписки</b>\n\n❌ У пользователя нет сервера. Введите другой ID:",
                    chat_id=step_chat_id, message_id=step_msg_id,
                    parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
                )
            except Exception:
                pass
            return
        await state.update_data(expiry_uid=uid)
        await state.set_state(AdminStates.change_expiry_date)
        try:
            await bot.edit_message_text(
                f"📅 <b>Изменение срока подписки</b>\n\nПользователь: `{uid}`\n"
                f"Текущая дата: `{h['expires_at']}`\n\nВведите новую дату (<code>ГГГГ-ММ-ДД</code>):",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            sent = await msg.answer(
                f"Текущая дата: `{h['expires_at']}`\n\nВведите новую дату (<code>ГГГГ-ММ-ДД</code>):",
                parse_mode=ParseMode.HTML
            )
            await state.update_data(step_msg_id=sent.message_id, step_chat_id=msg.chat.id)
    except ValueError:
        try:
            await bot.edit_message_text(
                "📅 <b>Изменение срока подписки</b>\n\n❌ Неверный ID. Введите числовой Telegram ID:",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            pass

@dp.message(AdminStates.change_expiry_date, F.from_user.id == ADMIN_ID)
async def handler_change_expiry_date(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    uid = data.get("expiry_uid")
    try:
        datetime.strptime(msg.text.strip(), "%Y-%m-%d")
        new_date = msg.text.strip()
        update_hosting_expiry(uid, new_date)
        clear_warnings(uid)
        await state.clear()
        try:
            await bot.edit_message_text(
                f"✅ Срок пользователя `{uid}<code> изменён на </code>{new_date}`.",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=admin_kb()
            )
        except Exception:
            await msg.answer(
                f"✅ Срок пользователя `{uid}<code> изменён на </code>{new_date}`.",
                parse_mode=ParseMode.HTML, reply_markup=admin_kb()
            )
        try:
            await bot.send_message(uid,
                f"📅 <b>Срок подписки изменён.</b>\n\n<blockquote>Активна до: <code>{new_date}</code></blockquote>",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
    except ValueError:
        try:
            await bot.edit_message_text(
                f"📅 <b>Изменение срока подписки</b>\n\nПользователь: `{uid}`\n\n"
                "❌ Неверный формат. Используйте <code>ГГГГ-ММ-ДД</code>:",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            pass

@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(cq: CallbackQuery, state: FSMContext):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    step_msg = await cq.message.edit_text(
        "📢 <b>Рассылка</b>\n\nВведите текст сообщения (поддерживается Markdown):",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("admin_panel")
    )
    await state.update_data(step_msg_id=step_msg.message_id, step_chat_id=cq.message.chat.id)
    await state.set_state(AdminStates.broadcast_text)
    await cq.answer()

@dp.message(AdminStates.broadcast_text, F.from_user.id == ADMIN_ID)
async def handler_broadcast(msg: Message, state: FSMContext):
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    broadcast_text = msg.text or ""
    try:
        await msg.delete()
    except Exception:
        pass
    await state.clear()

    try:
        await bot.edit_message_text(
            "📢 <b>Рассылка запущена...</b>",
            chat_id=step_chat_id, message_id=step_msg_id,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        step_msg_id = None

    with db_connect() as conn:
        users = conn.execute("SELECT user_id FROM users WHERE subscribed = 1").fetchall()
    ok, fail = 0, 0
    for row in users:
        try:
            await bot.send_message(row["user_id"], broadcast_text, parse_mode=ParseMode.HTML)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)

    result_text = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"✅ Доставлено: <b>{ok}</b>\n"
        f"❌ Ошибок: <b>{fail}</b>"
    )
    if step_msg_id:
        try:
            await bot.edit_message_text(
                result_text, chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=admin_kb()
            )
        except Exception:
            await msg.answer(result_text, parse_mode=ParseMode.HTML, reply_markup=admin_kb())
    else:
        await msg.answer(result_text, parse_mode=ParseMode.HTML, reply_markup=admin_kb())

# ═══════════════════════════════════════════════════════════════════
#                     ХЭНДЛЕРЫ: АННИГИЛЯЦИЯ
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "admin_annihilate")
async def cb_admin_annihilate_start(cq: CallbackQuery, state: FSMContext):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    step_msg = await cq.message.edit_text(
        "☢️ <b>Аннигиляция пользователя</b>\n\n"
        "⚠️ Это действие <b>необратимо</b>!\n"
        "Будут удалены: Docker-контейнер, образ, файлы, все записи в БД.\n\n"
        "Введите Telegram ID пользователя:",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("admin_panel")
    )
    await state.update_data(step_msg_id=step_msg.message_id, step_chat_id=cq.message.chat.id)
    await state.set_state(AdminStates.annihilate_uid)
    await cq.answer()

@dp.message(AdminStates.annihilate_uid, F.from_user.id == ADMIN_ID)
async def handler_annihilate_uid(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass
    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)
    try:
        target_uid = int(msg.text.strip())
    except ValueError:
        try:
            await bot.edit_message_text(
                "☢️ <b>Аннигиляция</b>\n\n❌ Неверный ID. Введите числовой Telegram ID:",
                chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel")
            )
        except Exception:
            pass
        return

    user_row = get_user(target_uid)
    hosting_row = get_hosting(target_uid)

    user_info = ""
    if user_row:
        uname = f"@{user_row['username']}" if user_row['username'] else "нет"
        fname = user_row['full_name'] or "—"
        bal   = user_row['balance']
        user_info += f"👤 <b>{fname}</b> ({uname})\n💰 Баланс: {bal} ₽\n"
    else:
        user_info += "👤 Пользователь <b>не найден в БД</b>\n"

    if hosting_row:
        user_info += f"🖥 Сервер: порт `{hosting_row['port']}<code>, до </code>{hosting_row['expires_at']}`\n"
    else:
        user_info += "🖥 Сервер: <b>нет</b>\n"

    confirm_kb = InlineKeyboardBuilder()
    confirm_kb.button(text="💥 ДА, АННИГИЛИРОВАТЬ",  callback_data=f"annihilate_confirm_{target_uid}")
    confirm_kb.button(text="❌ Отмена",               callback_data="admin_panel")
    confirm_kb.adjust(1)

    await state.update_data(target_uid=target_uid)
    await state.set_state(AdminStates.annihilate_confirm)

    try:
        await bot.edit_message_text(
            f"☢️ <b>Аннигиляция</b> — подтверждение\n\n"
            f"ID: `{target_uid}`\n"
            f"{user_info}\n"
            f"❗️ Все данные будут уничтожены. Продолжить?",
            chat_id=step_chat_id, message_id=step_msg_id,
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_kb.as_markup()
        )
    except Exception:
        sent = await msg.answer(
            f"☢️ <b>Аннигиляция</b> — подтверждение\n\n"
            f"ID: `{target_uid}`\n"
            f"{user_info}\n"
            f"❗️ Все данные будут уничтожены. Продолжить?",
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_kb.as_markup()
        )
        await state.update_data(step_msg_id=sent.message_id, step_chat_id=msg.chat.id)

@dp.callback_query(F.data.startswith("annihilate_confirm_"))
async def cb_annihilate_confirm(cq: CallbackQuery, state: FSMContext):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    try:
        target_uid = int(cq.data.split("_")[2])
    except (IndexError, ValueError):
        await cq.answer("❌ Неверный ID", show_alert=True)
        return

    await state.clear()
    await cq.answer("☢️ Аннигилируем...", show_alert=False)

    results = []

    # 1. Останавливаем и удаляем Docker
    ok, err = await docker_delete(target_uid, keep_files=False, delete_all_files=True)
    if ok:
        results.append("✅ Docker-контейнер, образ и файлы — удалены")
    else:
        results.append(f"⚠️ Docker: {err or 'нет контейнера'}")

    # 2. Удаляем все данные из БД
    annihilate_user_data(target_uid)
    results.append("✅ Все записи в БД — удалены")

    # 3. Уведомляем пользователя (если получится)
    try:
        await bot.send_message(
            target_uid,
            "⛔ <b>Ваш аккаунт удалён.</b>\n\n<blockquote>Все данные были удалены администратором.</blockquote>"
        )
        results.append("✅ Пользователь уведомлён")
    except Exception:
        results.append("ℹ️ Пользователь не уведомлён (заблокировал бота)")

    result_text = "\n".join(results)
    try:
        await cq.message.edit_text(
            f"☢️ <b>Аннигиляция завершена</b>\n\n"
            f"ID: `{target_uid}`\n\n"
            f"{result_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("admin_panel")
        )
    except Exception:
        await cq.message.answer(
            f"☢️ <b>Аннигиляция завершена</b>\n\nID: `{target_uid}`\n\n{result_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("admin_panel")
        )

@dp.callback_query(F.data == "fix_containers")
async def cb_fix_containers(cq: CallbackQuery):
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    await cq.answer("⏳ Начинаю пересоздание контейнеров...", show_alert=False)
    await cq.message.edit_text(
        "🛠️ <b>Исправление контейнеров</b>\n\n⏳ Пожалуйста, подождите...",
        parse_mode=ParseMode.HTML
    )
    result = await asyncio.get_running_loop().run_in_executor(None, fix_all_containers)
    if isinstance(result, int):
        text = (
            f"🛠️ <b>Исправление контейнеров завершено</b>\n\n"
            f"✅ Пересоздано контейнеров: <b>{result}</b>"
        )
    else:
        text = f"🛠️ <b>Исправление контейнеров</b>\n\n❌ Ошибка:\n<code>{result}</code>"
    await cq.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb("admin_panel"))


@dp.callback_query(F.data == "admin_refresh_status")
async def cb_admin_refresh_status(cq: CallbackQuery):
    """Быстрое ручное обновление сообщения статуса в канале."""
    if not admin_only(cq):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return
    await cq.answer("⏳ Обновляю статус...", show_alert=False)
    await cq.message.edit_text(
        "📡 <b>Обновление статуса сервера...</b>\n\n⏳ Получение данных, подождите ~2 сек.",
        parse_mode=ParseMode.HTML
    )
    try:
        await update_status_channel_message()
        now_msk = datetime.now(MSK).strftime("%H:%M:%S")
        await cq.message.edit_text(
            f"✅ <b>Статус сервера обновлён!</b>\n\n"
            f"🕐 Время обновления: <b>{now_msk}</b> МСК\n"
            f"📡 Сообщение в канале обновлено.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("admin_panel")
        )
    except Exception as e:
        await cq.message.edit_text(
            f"❌ <b>Ошибка обновления</b>\n\n`{e}`",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("admin_panel")
        )


# ═══════════════════════════════════════════════════════════════════
#                     ХЭНДЛЕРЫ: ШАРИНГ ДОСТУПА
# ═══════════════════════════════════════════════════════════════════
@dp.callback_query(F.data == "sharing_menu")
async def cb_sharing_menu(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = cq.from_user.id
    shared = get_shared_users(uid)
    count = len(shared)
    my_access = get_shared_servers(uid)
    my_count = len(my_access)
    await cq.message.edit_text(
        "🤝 <b>Шаринг-панель</b>\n\n"
        f"<blockquote>👥 Выдано доступов к вашему серверу: <b>{count}</b>\n"
        f"🔗 Доступных чужих серверов: <b>{my_count}</b></blockquote>\n\n"
        "Вы можете выдать другому пользователю право запускать, останавливать, "
        "перезапускать и просматривать логи вашего сервера.",
        parse_mode=ParseMode.HTML,
        reply_markup=sharing_kb(uid)
    )
    await cq.answer()

@dp.callback_query(F.data == "sharing_list")
async def cb_sharing_list(cq: CallbackQuery):
    uid = cq.from_user.id
    shared = get_shared_users(uid)
    if not shared:
        await cq.message.edit_text(
            "👥 <b>Шаринг-панель — Список доступов</b>\n\n📭 Вы ещё никому не выдали доступ.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("sharing_menu")
        )
        await cq.answer()
        return
    lines = []
    for row in shared:
        lines.append(f"• `{row['shared_uid']}` (с {row['created_at'][:10]})")
    await cq.message.edit_text(
        "👥 <b>Пользователи с доступом к вашему серверу:</b>\n\n<blockquote>" + "\n".join(lines) + "</blockquote>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("sharing_menu")
    )
    await cq.answer()

@dp.callback_query(F.data == "sharing_add")
async def cb_sharing_add(cq: CallbackQuery, state: FSMContext):
    uid = cq.from_user.id
    if not user_has_hosting(uid):
        await cq.answer("❌ У вас нет сервера для шаринга", show_alert=True)
        return
    await state.set_state(SharingStates.waiting_uid_to_add)
    step_msg = await cq.message.edit_text(
        "➕ <b>Шаринг-панель — Выдать доступ</b>\n\n"
        "Введите Telegram ID пользователя, которому хотите выдать доступ:\n\n"
        "Пример: <code>123456789</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("sharing_menu")
    )
    await state.update_data(step_msg_id=step_msg.message_id, step_chat_id=cq.message.chat.id)
    await cq.answer()

@dp.message(SharingStates.waiting_uid_to_add)
async def sharing_get_uid_to_add(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass

    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)

    async def edit_step(text: str, kb=None, clear_state: bool = False):
        if clear_state:
            await state.clear()
        try:
            await bot.edit_message_text(
                text, chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML,
                reply_markup=kb or back_kb("sharing_menu")
            )
        except Exception:
            await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb or back_kb("sharing_menu"))

    try:
        target_uid = int(msg.text.strip())
        owner_id = msg.from_user.id
        if target_uid == owner_id:
            await edit_step(
                "➕ <b>Шаринг-панель — Выдать доступ</b>\n\n"
                "❌ Нельзя выдать доступ самому себе.\n\n"
                "Введите другой Telegram ID:"
            )
            return
        if has_shared_access(owner_id, target_uid):
            b = InlineKeyboardBuilder()
            b.button(text="◀️ Назад", callback_data="sharing_menu")
            await edit_step(
                f"➕ <b>Шаринг-панель — Выдать доступ</b>\n\n"
                f"ℹ️ Пользователь `{target_uid}` уже имеет доступ к вашему серверу.",
                kb=b.as_markup(), clear_state=True
            )
            return
        add_shared_access(owner_id, target_uid)
        b = InlineKeyboardBuilder()
        b.button(text="◀️ Назад в Шаринг-панель", callback_data="sharing_menu")
        await edit_step(
            f"✅ <b>Доступ выдан!</b>\n\n"
            f"Пользователь `{target_uid}` теперь может управлять вашим сервером.",
            kb=b.as_markup(), clear_state=True
        )
        try:
            accept_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять доступ", callback_data=f"sharing_accept_{owner_id}"),
                InlineKeyboardButton(text="❌ Отклонить",      callback_data=f"sharing_decline_{owner_id}"),
            ]])
            await bot.send_message(
                target_uid,
                f"🤝 <b>Шаринг — Новый доступ!</b>\n\n"
                f"<blockquote>Пользователь <code>{owner_id}</code> выдал вам доступ к своему серверу.</blockquote>\n\n"
                "Нажмите «✅ Принять доступ» или «❌ Отклонить».",
                parse_mode=ParseMode.HTML,
                reply_markup=accept_kb
            )
        except Exception:
            pass
    except ValueError:
        await edit_step(
            "➕ <b>Шаринг-панель — Выдать доступ</b>\n\n"
            "❌ Неверный формат. Введите числовой Telegram ID:\n\n"
            "Пример: <code>123456789</code>"
        )

@dp.callback_query(F.data == "sharing_remove")
async def cb_sharing_remove(cq: CallbackQuery, state: FSMContext):
    uid = cq.from_user.id
    shared = get_shared_users(uid)
    if not shared:
        await cq.answer("📭 Нет активных доступов для отзыва", show_alert=True)
        return
    await state.set_state(SharingStates.waiting_uid_to_remove)
    lines = "\n".join([f"• `{r['shared_uid']}`" for r in shared])
    step_msg = await cq.message.edit_text(
        f"➖ <b>Шаринг-панель — Отозвать доступ</b>\n\n"
        f"Пользователи с текущим доступом:\n{lines}\n\n"
        "Введите ID пользователя, у которого хотите отозвать доступ:",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("sharing_menu")
    )
    await state.update_data(step_msg_id=step_msg.message_id, step_chat_id=cq.message.chat.id)
    await cq.answer()

@dp.message(SharingStates.waiting_uid_to_remove)
async def sharing_get_uid_to_remove(msg: Message, state: FSMContext):
    try:
        await msg.delete()
    except Exception:
        pass

    data = await state.get_data()
    step_msg_id = data.get("step_msg_id")
    step_chat_id = data.get("step_chat_id", msg.chat.id)

    async def edit_step(text: str, kb=None, clear_state: bool = False):
        if clear_state:
            await state.clear()
        try:
            await bot.edit_message_text(
                text, chat_id=step_chat_id, message_id=step_msg_id,
                parse_mode=ParseMode.HTML,
                reply_markup=kb or back_kb("sharing_menu")
            )
        except Exception:
            await msg.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb or back_kb("sharing_menu"))

    try:
        target_uid = int(msg.text.strip())
        owner_id = msg.from_user.id
        if not has_shared_access(owner_id, target_uid):
            # Показываем актуальный список и просим ввести снова
            shared = get_shared_users(owner_id)
            lines = "\n".join([f"• `{r['shared_uid']}`" for r in shared]) if shared else "_(список пуст)_"
            await edit_step(
                f"➖ <b>Шаринг-панель — Отозвать доступ</b>\n\n"
                f"❌ У пользователя `{target_uid}` нет доступа к вашему серверу.\n\n"
                f"Пользователи с доступом:\n{lines}\n\n"
                "Введите корректный ID:",
                clear_state=not bool(shared)
            )
            return
        remove_shared_access(owner_id, target_uid)
        b = InlineKeyboardBuilder()
        b.button(text="◀️ Назад в Шаринг-панель", callback_data="sharing_menu")
        await edit_step(
            f"✅ <b>Доступ отозван!</b>\n\n"
            f"Пользователь `{target_uid}` больше не имеет доступа к вашему серверу.",
            kb=b.as_markup(), clear_state=True
        )
        try:
            await bot.send_message(
                target_uid,
                f"ℹ️ <b>Шаринг</b>\n\n<blockquote>Пользователь <code>{owner_id}</code> отозвал ваш доступ к своему серверу.</blockquote>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    except ValueError:
        await edit_step(
            "➖ <b>Шаринг-панель — Отозвать доступ</b>\n\n"
            "❌ Неверный формат. Введите числовой Telegram ID:\n\n"
            "Пример: <code>123456789</code>"
        )

@dp.callback_query(F.data == "sharing_my_access")
async def cb_sharing_my_access(cq: CallbackQuery):
    uid = cq.from_user.id
    servers = get_shared_servers(uid)
    if not servers:
        await cq.message.edit_text(
            "🔗 <b>Шаринг-панель — Чужие серверы</b>\n\n📭 Вам не выдан доступ ни к одному серверу.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb("sharing_menu")
        )
        await cq.answer()
        return
    await cq.message.edit_text(
        f"🔗 <b>Шаринг-панель — Доступные серверы ({len(servers)}):</b>\n\nВыберите сервер для управления:",
        parse_mode=ParseMode.HTML,
        reply_markup=shared_servers_kb(servers)
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("shared_manage_"))
async def cb_shared_manage(cq: CallbackQuery):
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    if not has_shared_access(owner_id, uid):
        await cq.answer("❌ У вас нет доступа к этому серверу", show_alert=True)
        return
    h = get_hosting(owner_id)
    if not h:
        await cq.answer("❌ Сервер не найден", show_alert=True)
        return
    container_status = await docker_container_status(owner_id)
    status_text = fmt_status(container_status)
    await cq.message.edit_text(
        f"🖥 *Шаринг-панель — Сервер #{owner_id}*\n\n"
        f"├ 🔌 Порт: <code>{h['port']}</code>\n"
        f"└ 🐳 Статус: {status_text}\n\n"
        "Доступные действия:",
        parse_mode=ParseMode.HTML,
        reply_markup=shared_manage_kb(owner_id)
    )
    await cq.answer()

@dp.callback_query(F.data.startswith("shared_start_"))
async def cb_shared_start(cq: CallbackQuery):
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    if not has_shared_access(owner_id, uid):
        await cq.answer("❌ Нет доступа", show_alert=True); return
    await cq.answer("▶️ Запускаем...")
    ok = await docker_start(owner_id)
    await cq.message.edit_text(
        f"{'▶️ <b>Сервер #' + str(owner_id) + ' запущен!</b>' if ok else '❌ <b>Ошибка запуска сервера #' + str(owner_id) + '</b>'}",
        parse_mode=ParseMode.HTML,
        reply_markup=shared_manage_kb(owner_id)
    )

@dp.callback_query(F.data.startswith("shared_stop_"))
async def cb_shared_stop(cq: CallbackQuery):
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    if not has_shared_access(owner_id, uid):
        await cq.answer("❌ Нет доступа", show_alert=True); return
    await cq.answer("⏹ Останавливаем...")
    ok = await docker_stop(owner_id)
    await cq.message.edit_text(
        f"{'⏹ <b>Сервер #' + str(owner_id) + ' остановлен.</b>' if ok else '❌ <b>Ошибка остановки сервера #' + str(owner_id) + '</b>'}",
        parse_mode=ParseMode.HTML,
        reply_markup=shared_manage_kb(owner_id)
    )

@dp.callback_query(F.data.startswith("shared_restart_"))
async def cb_shared_restart(cq: CallbackQuery):
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    if not has_shared_access(owner_id, uid):
        await cq.answer("❌ Нет доступа", show_alert=True); return
    await cq.answer("🔁 Перезапускаем...")
    ok = await docker_restart(owner_id)
    await cq.message.edit_text(
        f"{'🔁 <b>Сервер #' + str(owner_id) + ' перезапущен!</b>' if ok else '❌ <b>Ошибка перезапуска сервера #' + str(owner_id) + '</b>'}",
        parse_mode=ParseMode.HTML,
        reply_markup=shared_manage_kb(owner_id)
    )

@dp.callback_query(F.data.startswith("shared_logs_"))
async def cb_shared_logs(cq: CallbackQuery):
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    if not has_shared_access(owner_id, uid):
        await cq.answer("❌ Нет доступа", show_alert=True); return
    await cq.answer("📋 Загружаем логи...")
    logs = await docker_logs(owner_id, lines=30)
    truncated = logs[-2800:] if len(logs) > 2800 else logs
    truncated = html.escape(truncated)
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Обновить", callback_data=f"shared_logs_{owner_id}")
    b.button(text="🤖 Диагностика AI", callback_data=f"fix_with_ai_{owner_id}_{uid}")
    b.button(text="◀️ Назад",    callback_data=f"shared_manage_{owner_id}")
    b.adjust(1)
    await cq.message.edit_text(
        f"📋 *Шаринг-панель — Логи сервера #{owner_id}* (30 строк)\n\n<pre>{truncated}</pre>",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )

@dp.callback_query(F.data.startswith("sharing_accept_"))
async def cb_sharing_accept(cq: CallbackQuery):
    """Пользователь принимает доступ к чужому серверу"""
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    if not has_shared_access(owner_id, uid):
        await cq.answer("❌ Доступ уже отозван или не существует", show_alert=True)
        return
    await cq.message.edit_text(
        f"✅ <b>Доступ принят!</b>\n\n"
        f"Теперь вы можете управлять сервером `#{owner_id}` через «🤝 Шаринг-панель» → «🔗 Чужие серверы».",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("sharing_menu")
    )
    await cq.answer("✅ Принято!")
    try:
        await bot.send_message(
            owner_id,
            f"✅ <b>Шаринг-панель</b>\n\nПользователь `{uid}` принял доступ к вашему серверу.",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("sharing_decline_"))
async def cb_sharing_decline(cq: CallbackQuery):
    """Пользователь отклоняет доступ к чужому серверу"""
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    remove_shared_access(owner_id, uid)
    await cq.message.edit_text(
        f"🚫 <b>Доступ отклонён.</b>\n\nВы отклонили приглашение от `{owner_id}`.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("menu")
    )
    await cq.answer("🚫 Отклонено")
    try:
        await bot.send_message(
            owner_id,
            f"🚫 <b>Шаринг</b>\n\n<blockquote>Пользователь <code>{uid}</code> отклонил ваш доступ к серверу.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


@dp.callback_query(F.data == "sharing_leave_select")
async def cb_sharing_leave_select(cq: CallbackQuery):
    """Показать список серверов от которых можно отключиться"""
    uid = cq.from_user.id
    servers = get_shared_servers(uid)
    if not servers:
        await cq.answer("📭 Нет серверов для отключения", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    for row in servers:
        owner = row["owner_id"]
        b.button(text=f"🚪 Отключиться от сервера #{owner}", callback_data=f"sharing_leave_{owner}")
    b.button(text="◀️ Назад", callback_data="sharing_my_access")
    b.adjust(1)
    await cq.message.edit_text(
        "🚪 <b>Отключение от сервера</b>\n\nВыберите сервер, от которого хотите отключиться:",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup()
    )
    await cq.answer()


@dp.callback_query(F.data.startswith("sharing_leave_"))
async def cb_sharing_leave(cq: CallbackQuery):
    """Пользователь сам отключается от чужого сервера"""
    uid = cq.from_user.id
    owner_id = int(cq.data.split("_")[2])
    if not has_shared_access(owner_id, uid):
        await cq.answer("❌ Вы уже не имеете доступа к этому серверу", show_alert=True)
        return
    remove_shared_access(owner_id, uid)
    await cq.message.edit_text(
        f"✅ <b>Отключено!</b>\n\nВы успешно отключились от сервера `#{owner_id}`.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb("sharing_menu")
    )
    await cq.answer("✅ Отключено")
    try:
        await bot.send_message(
            owner_id,
            f"ℹ️ <b>Шаринг</b>\n\n<blockquote>Пользователь <code>{uid}</code> самостоятельно отключился от вашего сервера.</blockquote>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
#                         ИНЛАЙН РЕЖИМ
# ═══════════════════════════════════════════════════════════════════
@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    """
    Инлайн режим:
      @bot action          → выпадающее меню действий (start/stop/restart/logs/terminal)
      @bot exec <команда>  → выполнить команду в docker-контейнере пользователя
      @bot sub             → информация о подписке
      @bot (пусто)         → подсказка по командам
    """
    uid = query.from_user.id
    text = query.query.strip()
    text_lower = text.lower()
    results = []

    h = get_hosting(uid)
    has_server = user_has_hosting(uid)

    # ── exec <команда>: выполнить команду в контейнере пользователя ─
    if text_lower.startswith("exec"):
        cmd_text = text[4:].strip()  # всё после "exec"

        if not cmd_text:
            # написали только "exec" без команды — подсказка
            results = [InlineQueryResultArticle(
                id="iexec_hint",
                title="💻 exec — введите команду",
                description="Например: exec ls /app",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        "💻 <b>exec</b> — выполнить команду в контейнере\n\n"
                        "Продолжите ввод, например:\n"
                        "<code>exec ls /app</code>\n<code>exec ps aux</code>\n<code>exec cat /app/config.json</code>"
                    ),
                    parse_mode=ParseMode.HTML
                )
            )]
        elif not has_server:
            results = [InlineQueryResultArticle(
                id="iexec_noserver",
                title="❌ Нет активного сервера",
                description="У вас нет docker-контейнера",
                input_message_content=InputTextMessageContent(
                    message_text="❌ <b>У вас нет активного сервера для выполнения команд.</b>",
                    parse_mode=ParseMode.HTML
                )
            )]
        else:
            results = [InlineQueryResultArticle(
                id=f"iexec_{abs(hash(cmd_text + str(uid))) % 999999}",
                title="💻 Выполнить в контейнере",
                description=f"$ {cmd_text}",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"💻 <b>Терминал — контейнер <code>user_{uid}</code></b>\n\n"
                        f"<code>$ {cmd_text}</code>\n\n"
                        f"⏳ Нажмите кнопку для выполнения..."
                    ),
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="▶️ Выполнить",
                        callback_data=f"iexec_{uid}_{cmd_text[:55]}"
                    )
                ]])
            )]

    # ── пустой запрос: показать доступные команды как пункты меню ───
    elif text == "":
        bal = get_balance(uid)
        sub_desc = f"баланс {bal} ₽"
        if h:
            try:
                days_left = (datetime.strptime(h["expires_at"], "%Y-%m-%d").date() - datetime.now(MSK).date()).days
                sub_desc = f"{'активна' if days_left > 0 else 'истекла'} · {max(days_left,0)} дн. · {bal} ₽"
            except Exception:
                pass
        server_desc = f"старт / стоп / рестарт / логи · порт {h['port']}" if h else "старт / стоп / рестарт / логи"

        results = [
            InlineQueryResultArticle(
                id="hint_action",
                title="⚙️ action — управление сервером",
                description=server_desc,
                input_message_content=InputTextMessageContent(
                    message_text=(
                        "⚙️ <b>action</b> — управление сервером\n\n"
                        "Напишите <code>action</code> чтобы увидеть все действия:\n"
                        "▶️ Запустить · ⏹ Остановить · 🔁 Перезапустить · 📋 Логи"
                    ),
                    parse_mode=ParseMode.HTML
                )
            ),
            InlineQueryResultArticle(
                id="hint_exec",
                title="💻 exec — терминал контейнера",
                description="exec <команда> · например: exec ls /app",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        "💻 <b>exec</b> — выполнить команду в контейнере\n\n"
                        "Напишите <code>exec команда</code>, например:\n"
                        "<code>exec ls /app</code>\n<code>exec ps aux</code>\n<code>exec cat /app/config.json</code>"
                    ),
                    parse_mode=ParseMode.HTML
                )
            ),
            InlineQueryResultArticle(
                id="hint_sub",
                title="📊 sub — статус подписки",
                description=sub_desc,
                input_message_content=InputTextMessageContent(
                    message_text=(
                        "📊 <b>sub</b> — информация о подписке\n\n"
                        "Напишите <code>sub</code> чтобы получить статус подписки, "
                        "дату истечения и баланс."
                    ),
                    parse_mode=ParseMode.HTML
                )
            ),
        ]

    # ── action: управление своим сервером ───────────────────────────
    elif text_lower.startswith("action"):
        actions = [
            ("start",   "▶️ Запустить",     f"Запустить контейнер · порт {h['port']}" if h else "❌ Нет сервера"),
            ("stop",    "⏹ Остановить",     f"Остановить контейнер · порт {h['port']}" if h else "❌ Нет сервера"),
            ("restart", "🔁 Перезапустить", f"Перезапустить · порт {h['port']}" if h else "❌ Нет сервера"),
            ("logs",    "📋 Логи",          f"Последние 30 строк · порт {h['port']}" if h else "Логи контейнера"),
        ]
        # фильтр по подстроке после "action"
        sub = text_lower[6:].strip() if text_lower.startswith("action") else ""

        for action_id, action_label, desc in actions:
            if sub and not action_id.startswith(sub):
                continue
            if not has_server and action_id not in ("logs", "terminal"):
                desc = "❌ У вас нет сервера"

            results.append(InlineQueryResultArticle(
                id=f"iaction_{action_id}_{uid}",
                title=action_label,
                description=desc,
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"{action_label}\n\n"
                        f"👤 Пользователь: <code>{uid}</code>\n"
                        f"⏳ Нажмите кнопку для выполнения..."
                    ),
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=action_label,
                        callback_data=f"iaction_{action_id}_{uid}"
                    )
                ]])
            ))

    # ── sub: информация о подписке ──────────────────────────────────
    elif text_lower.startswith("sub"):
        bal = get_balance(uid)
        if h:
            try:
                days_left = (
                    datetime.strptime(h["expires_at"], "%Y-%m-%d").date()
                    - datetime.now(MSK).date()
                ).days
            except Exception:
                days_left = 0
            status_icon = "🟢" if days_left > 3 else ("🟡" if days_left > 0 else "🔴")
            sub_text = (
                f"📊 <b>Статус подписки JokyHost</b>\n\n"
                f"👤 ID: <code>{uid}</code>\n"
                f"├ {status_icon} Статус: <b>{'Активна' if days_left > 0 else 'Истекла'}</b>\n"
                f"├ 📅 До: <code>{h['expires_at']}</code>\n"
                f"├ ⏳ Осталось: <b>{max(days_left, 0)} дн.</b>\n"
                f"├ 🔌 Порт: <code>{h['port']}</code>\n"
                f"└ 💰 Баланс: <b>{bal} ₽</b>"
            )
            desc = f"{'Активна' if days_left > 0 else 'Истекла'} · {max(days_left,0)} дн. · {bal} ₽"
        else:
            sub_text = (
                f"📊 <b>Статус подписки JokyHost</b>\n\n"
                f"👤 ID: <code>{uid}</code>\n"
                f"├ ❌ Сервер: <b>не создан</b>\n"
                f"└ 💰 Баланс: <b>{bal} ₽</b>"
            )
            desc = f"Сервер не создан · баланс {bal} ₽"

        results.append(InlineQueryResultArticle(
            id=f"isub_{uid}",
            title="📊 Моя подписка",
            description=desc,
            input_message_content=InputTextMessageContent(
                message_text=sub_text,
                parse_mode=ParseMode.HTML
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Обновить", callback_data=f"iaction_sub_{uid}")
            ]])
        ))

    # ── подсказка по умолчанию (пустой запрос) ──────────────────────
    if not results:
        hint = (
            "⚡ <b>JokyHost — Инлайн управление</b>\n\n"
            "📌 <b>Команды:</b>\n"
            "• <code>action</code> — запуск / стоп / рестарт / логи / терминал\n"
            "• <code>exec команда</code> — выполнить команду в контейнере\n"
            "• <code>sub</code> — информация о подписке\n\n"
            f"👤 ID: <code>{uid}</code>"
        )
        results = [
            InlineQueryResultArticle(
                id="hint",
                title="⚡ JokyHost — управление",
                description="action · exec <cmd> · sub",
                input_message_content=InputTextMessageContent(
                    message_text=hint,
                    parse_mode=ParseMode.HTML
                )
            )
        ]

    await query.answer(results=results, cache_time=1, is_personal=True)


@dp.callback_query(F.data.startswith("iexec_"))
async def cb_inline_exec(cq: CallbackQuery):
    """Выполнение команды в docker-контейнере пользователя через инлайн."""
    inline_msg_id = cq.inline_message_id
    # формат: iexec_<uid>_<cmd>
    parts = cq.data.split("_", 2)
    if len(parts) < 3:
        await cq.answer("❌ Неверный формат", show_alert=True)
        return

    try:
        target_uid = int(parts[1])
    except ValueError:
        await cq.answer("❌ Неверный user_id", show_alert=True)
        return

    cmd_text = parts[2]

    # Только сам пользователь или админ
    if cq.from_user.id != target_uid and cq.from_user.id != ADMIN_ID:
        await cq.answer("❌ Это не ваш контейнер", show_alert=True)
        return

    if not user_has_hosting(target_uid):
        await cq.answer("❌ У пользователя нет активного сервера", show_alert=True)
        return

    await cq.answer("⏳ Выполняю...", show_alert=False)

    container_name = f"jh_user_{target_uid}"
    workdir = f"/home/users/{target_uid}"
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec",
            "--user", "nobody",
            "-w", workdir,
            container_name, "sh", "-c", cmd_text,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = (stdout + stderr).decode(errors="replace").strip()
            rc = proc.returncode
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            output = "⏱ Timeout — команда выполнялась слишком долго"
            rc = -1
    except Exception as e:
        output = f"❌ Ошибка: {e}"
        rc = -1

    output_safe = html.escape(output[:3200] or "(нет вывода)")
    rc_icon = "✅" if rc == 0 else "❌"
    new_text = (
        f"💻 <b>Терминал — <code>{container_name}</code></b>\n\n"
        f"<b>Команда:</b> <code>{cmd_text}</code>\n"
        f"<b>Статус:</b> {rc_icon} код <code>{rc}</code>\n\n"
        f"<b>Вывод:</b>\n<pre>{output_safe}</pre>"
    )

    try:
        await bot.edit_message_text(
            text=new_text,
            inline_message_id=inline_msg_id,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        log.error(f"iexec edit failed: {e}")
        await cq.answer("Готово (не удалось обновить сообщение)", show_alert=True)


@dp.callback_query(F.data.startswith("iaction_"))
async def cb_inline_action(cq: CallbackQuery):
    """
    Выполнение действия с сервером через инлайн.
    Редактирует именно то сообщение, из которого нажали кнопку.
    """
    inline_msg_id = cq.inline_message_id
    parts = cq.data.split("_")
    # iaction_<action>_<uid>
    if len(parts) < 3:
        await cq.answer("❌ Неверный формат", show_alert=True)
        return

    action = parts[1]
    try:
        uid = int(parts[2])
    except ValueError:
        await cq.answer("❌ Неверный user_id", show_alert=True)
        return

    # Только сам пользователь или админ
    if cq.from_user.id != uid and cq.from_user.id != ADMIN_ID:
        await cq.answer("❌ Это не ваш сервер", show_alert=True)
        return

    # Блокируем инлайн-управление если идёт релогин
    if uid in relogin_in_progress:
        await cq.answer("⚠️ Сервер на релогине, подождите завершения.", show_alert=True)
        return

    # ── sub: обновить информацию о подписке ──────────────────────────
    if action == "sub":
        # Сначала показываем «получение статуса» без лага
        try:
            await bot.edit_message_text(
                text="⏳ <b>Получение статуса...</b>",
                inline_message_id=inline_msg_id,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        h = get_hosting(uid)
        bal = get_balance(uid)

        if h:
            try:
                days_left = (
                    datetime.strptime(h["expires_at"], "%Y-%m-%d").date()
                    - datetime.now(MSK).date()
                ).days
            except Exception:
                days_left = 0
            status_icon = "🟢" if days_left > 3 else ("🟡" if days_left > 0 else "🔴")

            # Получаем статус Docker-контейнера
            container_status = await docker_container_status(uid)
            container_text   = fmt_status(container_status)

            sub_text = (
                f"📊 <b>Статус подписки JokyHost</b>\n\n"
                f"👤 ID: <code>{uid}</code>\n"
                f"├ {status_icon} Подписка: <b>{'Активна' if days_left > 0 else 'Истекла'}</b>\n"
                f"├ 📅 До: <code>{h['expires_at']}</code>\n"
                f"├ ⏳ Осталось: <b>{max(days_left, 0)} дн.</b>\n"
                f"├ 🐳 Контейнер: {container_text}\n"
                f"├ 🔌 Порт: <code>{h['port']}</code>\n"
                f"└ 💰 Баланс: <b>{bal} ₽</b>"
            )
        else:
            sub_text = (
                f"📊 <b>Статус подписки JokyHost</b>\n\n"
                f"👤 ID: <code>{uid}</code>\n"
                f"├ ❌ Сервер: <b>не создан</b>\n"
                f"└ 💰 Баланс: <b>{bal} ₽</b>"
            )
        try:
            await bot.edit_message_text(
                text=sub_text,
                inline_message_id=inline_msg_id,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"iaction_sub_{uid}")
                ]])
            )
        except Exception as e:
            log.error(f"iaction sub edit failed: {e}")
        await cq.answer("🔄 Обновлено")
        return

    if not user_has_hosting(uid) and action not in ("logs",):
        await cq.answer("❌ У пользователя нет сервера", show_alert=True)
        return

    await cq.answer("⏳ Выполняю...", show_alert=False)

    action_labels = {
        "start":   "▶️ Запуск",
        "stop":    "⏹ Остановка",
        "restart": "🔁 Перезапуск",
        "logs":    "📋 Логи",
    }
    label = action_labels.get(action, "❓ Действие")

    if action == "start":
        ok = await docker_start(uid)
        result_text = "🟢 <b>Сервер запущен!</b>" if ok else "❌ <b>Ошибка запуска</b>"
    elif action == "stop":
        ok = await docker_stop(uid)
        result_text = "🔴 <b>Сервер остановлен!</b>" if ok else "❌ <b>Ошибка остановки</b>"
    elif action == "restart":
        ok = await docker_restart(uid)
        result_text = "🔄 <b>Сервер перезапущен!</b>" if ok else "❌ <b>Ошибка перезапуска</b>"
    elif action == "terminal":
        # terminal через action — подсказка использовать exec
        try:
            await bot.edit_message_text(
                text=(
                    f"💻 <b>Терминал</b>\n\n"
                    f"👤 <code>{uid}</code>\n\n"
                    f"Для выполнения команды напишите в инлайне:\n"
                    f"<code>@bot exec команда</code>\n\n"
                    f"Пример: <code>@bot exec ls /app</code>"
                ),
                inline_message_id=inline_msg_id,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.error(f"iaction terminal edit failed: {e}")
            await cq.answer("💻 Используйте: @bot exec <команда>", show_alert=True)
        return
    elif action == "logs":
        raw_logs = await docker_logs(uid, lines=30)
        raw_logs = raw_logs[-2800:] if len(raw_logs) > 2800 else raw_logs
        raw_logs = html.escape(raw_logs)
        new_text = (
            f"📋 <b>Логи сервера</b> (последние 30 строк)\n"
            f"👤 <code>{uid}</code>\n\n"
            f"<pre>{raw_logs}</pre>"
        )
        try:
            await bot.edit_message_text(
                text=new_text,
                inline_message_id=inline_msg_id,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 Обновить логи", callback_data=f"iaction_logs_{uid}")
                ]])
            )
        except Exception as e:
            log.error(f"iaction logs edit failed: {e}")
            await cq.answer("Логи получены (не удалось обновить сообщение)", show_alert=True)
        return
    else:
        await cq.answer("❓ Неизвестное действие", show_alert=True)
        return

    new_text = (
        f"<b>{label}</b>\n\n"
        f"{result_text}\n\n"
        f"👤 Пользователь: <code>{uid}</code>"
    )
    try:
        await bot.edit_message_text(
            text=new_text,
            inline_message_id=inline_msg_id,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Обновить статус", callback_data=f"iaction_restart_{uid}")
            ]])
        )
    except Exception as e:
        log.error(f"iaction edit failed: {e}")
        await cq.answer(result_text.replace("*", ""), show_alert=True)


# ═══════════════════════════════════════════════════════════════════
#               ДИАГНОСТИКА AI — анализ логов и инструкция
# ═══════════════════════════════════════════════════════════════════

@dp.callback_query(F.data.startswith("fix_with_ai_"))
async def cb_fix_with_ai(cq: CallbackQuery):
    """
    Обработчик кнопки '🤖 Диагностика AI'.
    callback_data: fix_with_ai_<target_uid>_<initiator_uid>

    Анализирует логи через AI и показывает:
    - что за ошибка (понятным языком)
    - как исправить через кнопки бота (пошагово)
    Никаких команд не выполняет.
    """
    parts = cq.data.split("_")
    try:
        target_uid = int(parts[3])
    except (IndexError, ValueError):
        await cq.answer("❌ Неверный формат", show_alert=True)
        return

    me = cq.from_user.id
    is_admin = (me == ADMIN_ID)
    is_owner = (me == target_uid)
    is_shared = has_shared_access(target_uid, me)
    if not (is_admin or is_owner or is_shared):
        await cq.answer("❌ Нет доступа", show_alert=True)
        return

    await cq.answer("🔍 Анализирую логи...", show_alert=False)

    spinner = await cq.message.edit_text(
        "🤖 <b>Диагностика AI</b>\n\n"
        "⏳ Читаю логи и анализирую ошибки...\n"
        "Подождите 5–15 секунд.",
        parse_mode=ParseMode.HTML,
    )

    logs = await docker_logs(target_uid, lines=60)
    diagnosis = await ai_analyze_logs(logs)

    summary = diagnosis.get("summary", "Анализ не дал результата.")
    solution = diagnosis.get("solution", "")
    is_critical = diagnosis.get("critical", False)

    # Кнопки назад и к логам
    back_dest = (
        "manage_menu" if is_owner
        else (f"adm_srv_panel_{target_uid}" if is_admin
              else f"shared_manage_{target_uid}")
    )
    logs_dest = (
        "server_logs" if is_owner
        else (f"adm_srv_logs_{target_uid}" if is_admin
              else f"shared_logs_{target_uid}")
    )

    b = InlineKeyboardBuilder()
    b.button(text="📋 Логи", callback_data=logs_dest)
    b.button(text="◀️ Назад", callback_data=back_dest)
    b.adjust(1)

    if not is_critical and not solution:
        # Проблем нет
        await spinner.edit_text(
            "🤖 <b>Диагностика AI</b>\n\n"
            "✅ <b>Серьёзных проблем не обнаружено</b>\n\n"
            f"<blockquote>{html.escape(summary)}</blockquote>",
            parse_mode=ParseMode.HTML,
            reply_markup=b.as_markup(),
        )
        return

    severity_icon = "🔴" if is_critical else "🟡"

    solution_block = (
        f"\n\n🛠 <b>Как исправить через бот:</b>\n<blockquote>{html.escape(solution)}</blockquote>"
        if solution else ""
    )

    await spinner.edit_text(
        f"🤖 <b>Диагностика AI</b> {severity_icon}\n\n"
        f"📋 <b>Что случилось:</b>\n<blockquote>{html.escape(summary)}</blockquote>"
        f"{solution_block}",
        parse_mode=ParseMode.HTML,
        reply_markup=b.as_markup(),
    )





# ═══════════════════════════════════════════════════════════════════
#                            ТОЧКА ВХОДА
# ═══════════════════════════════════════════════════════════════════
async def main():
    print("=" * 60)
    print("  ⚡  JokyHost Bot v4.0 — Premium Style  |  Starting...")
    print(f"  💰  Цена: {PRICE_PER_MONTH} ₽/мес  |  Сервер: {SERVER_IP}")
    print(f"  📢  Канал: {CHANNEL_REQUIRED}")
    print(f"  🔐  Auth: https://{AUTH_DOMAIN}:{AUTH_PORT}")
    print("=" * 60)

    BASE_USERS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(exist_ok=True)

    # Регистрируем антиспам (первым — до проверки подписки)
    dp.message.middleware(_antispam)
    dp.callback_query.middleware(_antispam)

    # Регистрируем проверку подписки на канал
    dp.message.middleware(_channel_check)
    dp.callback_query.middleware(_channel_check)
    dp.inline_query.middleware(_channel_check)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    watcher = asyncio.create_task(expiry_watcher())
    status_watcher = asyncio.create_task(status_channel_watcher())
    log.info("🚀 Bot started polling")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "inline_query", "chosen_inline_result"])
    finally:
        watcher.cancel()
        status_watcher.cancel()
        for t in (watcher, status_watcher):
            try:
                await t
            except asyncio.CancelledError:
                pass
        await bot.session.close()
        log.info("Bot stopped gracefully.")

if __name__ == "__main__":
    asyncio.run(main())
