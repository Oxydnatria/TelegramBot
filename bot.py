import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ========== КОНФИГ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip()]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения!")
if not ADMIN_IDS:
    raise ValueError("ADMIN_IDS не задан в переменных окружения!")

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== БАЗА ДАННЫХ ==========
DB_PATH = '/app/data/arrests.db'

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arrests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tg_username TEXT,
            roblox_nick TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def add_arrest(user_id, tg_username, roblox_nick, start_date, end_date):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO arrests (user_id, tg_username, roblox_nick, start_date, end_date, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    ''', (user_id, tg_username, roblox_nick, start_date, end_date))
    conn.commit()
    conn.close()

def update_arrest(user_id, new_start_date, new_end_date):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE arrests 
        SET start_date = ?, end_date = ?, status = 'active'
        WHERE user_id = ? AND status = 'active'
    ''', (new_start_date, new_end_date, user_id))
    conn.commit()
    conn.close()

def update_roblox_nick(user_id, new_roblox_nick):
    """Обновляет Roblox ник в активной заявке"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE arrests 
        SET roblox_nick = ?
        WHERE user_id = ? AND status = 'active'
    ''', (new_roblox_nick, user_id))
    conn.commit()
    conn.close()

def get_active_arrest(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT roblox_nick, start_date, end_date FROM arrests 
        WHERE user_id = ? AND status = 'active'
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_all_active_arrests():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tg_username, roblox_nick, start_date, end_date FROM arrests 
        WHERE status = 'active'
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_user_arrest_by_id(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT roblox_nick, start_date, end_date FROM arrests 
        WHERE user_id = ? AND status = 'active'
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# ========== FSM СОСТОЯНИЯ ==========
class ArrestState(StatesGroup):
    waiting_for_roblox_nick = State()
    waiting_for_duration = State()
    waiting_for_new_duration = State()
    waiting_for_new_roblox_nick = State()  # новое состояние для смены ника

# ========== КЛАВИАТУРЫ ==========
def get_duration_keyboard():
    buttons = [
        [InlineKeyboardButton(text="1 день", callback_data="dur_1day")],
        [InlineKeyboardButton(text="2 дня", callback_data="dur_2days")],
        [InlineKeyboardButton(text="1 неделя", callback_data="dur_1week")],
        [InlineKeyboardButton(text="2 недели", callback_data="dur_2weeks")],
        [InlineKeyboardButton(text="3 недели", callback_data="dur_3weeks")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_change_keyboard():
    """Клавиатура для изменения данных существующего ареста"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оставить как есть", callback_data="keep")],
        [InlineKeyboardButton(text="🔄 Изменить срок ареста", callback_data="change")],
        [InlineKeyboardButton(text="🎮 Изменить Roblox ник", callback_data="change_nick")]
    ])

def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👑 Админ-панель")],
            [KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

# ========== УТИЛИТЫ ==========
def calculate_end_date(start_date_str, duration_key):
    start = datetime.strptime(start_date_str, "%Y-%m-%d")
    if duration_key == "dur_1day":
        end = start + timedelta(days=1)
    elif duration_key == "dur_2days":
        end = start + timedelta(days=2)
    elif duration_key == "dur_1week":
        end = start + timedelta(weeks=1)
    elif duration_key == "dur_2weeks":
        end = start + timedelta(weeks=2)
    elif duration_key == "dur_3weeks":
        end = start + timedelta(weeks=3)
    else:
        end = start
    return end.strftime("%Y-%m-%d")

# ========== ОТПРАВКА ВСЕМ АДМИНАМ ==========
async def notify_admins(bot, tg_username, roblox_nick, start_date, end_date, is_change=False, is_nick_change=False):
    if is_nick_change:
        action = "ИЗМЕНИЛ ROBOX НИК"
        text = (
            f"🎮 {action}\n"
            f"👤 TG: @{tg_username}\n"
            f"🎮 Новый Roblox ник: {roblox_nick}\n"
            f"📅 Арест с {start_date} по {end_date}"
        )
    else:
        action = "ИЗМЕНИЛ ЗАЯВКУ НА АРЕСТ" if is_change else "СОЗДАЛ ЗАЯВКУ НА АРЕСТ"
        text = (
            f"⛓️ {action}\n"
            f"👤 TG: @{tg_username}\n"
            f"🎮 Roblox: {roblox_nick}\n"
            f"📅 С {start_date} по {end_date}"
        )
    
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, text)

# ========== ПРОВЕРКА АДМИНА ==========
def is_admin(user_id):
    return user_id in ADMIN_IDS

# ========== ХЕНДЛЕРЫ ==========
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_admin(user_id):
        await message.answer(
            "👑 Привет, Админ!\nЯ бот для управления арестами в RobloxHouse.",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "⛓️ Привет! Я бот для оформления арестов в RobloxHouse.",
            reply_markup=get_main_keyboard()
        )
    
    existing = get_active_arrest(user_id)
    if existing:
        roblox_nick, start_date, end_date = existing
        await message.answer(
            f"⚠️ Ты уже под арестом:\n🎮 {roblox_nick}\n📅 {start_date} → {end_date}\n\nЧто хочешь сделать?",
            reply_markup=get_change_keyboard()
        )
        await state.set_state(ArrestState.waiting_for_new_duration)
        await state.update_data(old_roblox_nick=roblox_nick)
    else:
        await message.answer("Напиши свой ник в Roblox:")
        await state.set_state(ArrestState.waiting_for_roblox_nick)

@dp.message(F.text == "❓ Помощь")
async def help_button(message: types.Message):
    user_id = message.from_user.id
    if is_admin(user_id):
        await message.answer(
            "📌 *Команды:*\n"
            "/start — оформить арест\n"
            "👑 Админ-панель — просмотр активных арестов\n"
            "/help — это сообщение\n\n"
            "Админы получают уведомления о всех новых арестах и изменениях.",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "📌 *Команды:*\n"
            "/start — оформить арест\n"
            "/help — это сообщение",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

@dp.message(F.text == "👑 Админ-панель")
async def admin_panel_button(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ-панели.", reply_markup=get_main_keyboard())
        return
    
    arrests = get_all_active_arrests()
    if not arrests:
        await message.answer("📭 Активных арестов нет.", reply_markup=get_admin_keyboard())
        return

    text = "⛓️ *Активные аресты:*\n\n"
    for tg_username, roblox_nick, start_date, end_date in arrests:
        text += f"• @{tg_username} | {roblox_nick} | {start_date} → {end_date}\n"
    
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=get_admin_keyboard())

@dp.message(ArrestState.waiting_for_roblox_nick)
async def get_roblox_nick(message: types.Message, state: FSMContext):
    roblox_nick = message.text.strip()
    if not roblox_nick:
        await message.answer("Ник не может быть пустым. Напиши ник в Roblox:")
        return
    await state.update_data(roblox_nick=roblox_nick, tg_username=message.from_user.username or "нет_username")
    await message.answer("⛓️ Выбери срок ареста:", reply_markup=get_duration_keyboard())
    await state.set_state(ArrestState.waiting_for_duration)

@dp.callback_query(ArrestState.waiting_for_duration, F.data.startswith("dur_"))
async def choose_duration(callback: types.CallbackQuery, state: FSMContext):
    duration_key = callback.data
    data = await state.get_data()
    roblox_nick = data["roblox_nick"]
    tg_username = data["tg_username"]
    user_id = callback.from_user.id

    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = calculate_end_date(start_date, duration_key)

    add_arrest(user_id, tg_username, roblox_nick, start_date, end_date)

    if is_admin(user_id):
        reply_markup = get_admin_keyboard()
    else:
        reply_markup = get_main_keyboard()
    
    await callback.message.edit_text(
        f"⛓️ Ты под арестом с {start_date} по {end_date}\n"
        f"🎮 Roblox: {roblox_nick}\nАдмины уведомлены."
    )
    await callback.message.answer("Что дальше?", reply_markup=reply_markup)
    await notify_admins(bot, tg_username, roblox_nick, start_date, end_date, is_change=False)
    await state.clear()
    await callback.answer()

# Обработка изменения ника
@dp.callback_query(ArrestState.waiting_for_new_duration, F.data == "change_nick")
async def change_nick_request(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🎮 Напиши новый Roblox ник:")
    await state.set_state(ArrestState.waiting_for_new_roblox_nick)
    await callback.answer()

@dp.message(ArrestState.waiting_for_new_roblox_nick)
async def update_roblox_nick_handler(message: types.Message, state: FSMContext):
    new_nick = message.text.strip()
    if not new_nick:
        await message.answer("Ник не может быть пустым. Напиши новый Roblox ник:")
        return
    
    user_id = message.from_user.id
    tg_username = message.from_user.username or "нет_username"
    
    # Получаем старые данные
    old_data = get_active_arrest(user_id)
    if not old_data:
        await message.answer("❌ Ошибка: нет активного ареста для изменения.")
        await state.clear()
        return
    
    old_nick, start_date, end_date = old_data
    
    # Обновляем ник в БД
    update_roblox_nick(user_id, new_nick)
    
    # Получаем обновлённые данные
    new_data = get_active_arrest(user_id)
    
    if is_admin(user_id):
        reply_markup = get_admin_keyboard()
    else:
        reply_markup = get_main_keyboard()
    
    await message.answer(
        f"✅ Roblox ник изменён!\n"
        f"Старый ник: {old_nick}\n"
        f"Новый ник: {new_nick}\n\n"
        f"Ты всё ещё под арестом с {start_date} по {end_date}",
        reply_markup=reply_markup
    )
    
    # Уведомляем админов об изменении ника
    await notify_admins(bot, tg_username, new_nick, start_date, end_date, is_nick_change=True)
    await state.clear()

@dp.callback_query(ArrestState.waiting_for_new_duration, F.data == "change")
async def change_duration(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("⛓️ Выбери новый срок ареста:", reply_markup=get_duration_keyboard())
    await state.set_state(ArrestState.waiting_for_duration)
    await callback.answer()

@dp.callback_query(ArrestState.waiting_for_new_duration, F.data == "keep")
async def keep_duration(callback: types.CallbackQuery, state: FSMContext):
    if is_admin(callback.from_user.id):
        reply_markup = get_admin_keyboard()
    else:
        reply_markup = get_main_keyboard()
    
    await callback.message.edit_text("Ок, срок ареста остался без изменений.")
    await callback.message.answer("Что дальше?", reply_markup=reply_markup)
    await state.clear()
    await callback.answer()

@dp.callback_query(ArrestState.waiting_for_duration, F.data.startswith("dur_"))
async def change_duration_submit(callback: types.CallbackQuery, state: FSMContext):
    duration_key = callback.data
    user_id = callback.from_user.id

    existing = get_active_arrest(user_id)
    if not existing:
        await callback.message.edit_text("Ошибка: нет активного ареста для изменения.")
        await state.clear()
        await callback.answer()
        return

    old_roblox_nick, old_start, old_end = existing
    new_start = datetime.now().strftime("%Y-%m-%d")
    new_end = calculate_end_date(new_start, duration_key)

    update_arrest(user_id, new_start, new_end)

    tg_username = callback.from_user.username or "нет_username"
    new_data = get_user_arrest_by_id(user_id)
    
    if is_admin(user_id):
        reply_markup = get_admin_keyboard()
    else:
        reply_markup = get_main_keyboard()
    
    if new_data:
        roblox_nick, start_date, end_date = new_data
        await callback.message.edit_text(
            f"🔄 Срок ареста изменён!\nТеперь: {start_date} → {end_date}\n🎮 {roblox_nick}"
        )
        await callback.message.answer("Что дальше?", reply_markup=reply_markup)
        await notify_admins(bot, tg_username, roblox_nick, start_date, end_date, is_change=True)

    await state.clear()
    await callback.answer()

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет доступа.", reply_markup=get_main_keyboard())
        return
    
    arrests = get_all_active_arrests()
    if not arrests:
        await message.answer("📭 Активных арестов нет.", reply_markup=get_admin_keyboard())
        return

    text = "⛓️ *Активные аресты:*\n\n"
    for tg_username, roblox_nick, start_date, end_date in arrests:
        text += f"• @{tg_username} | {roblox_nick} | {start_date} → {end_date}\n"
    
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], parse_mode="Markdown")
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=get_admin_keyboard())

@dp.message(Command("help"))
async def help_command(message: types.Message):
    user_id = message.from_user.id
    if is_admin(user_id):
        await message.answer(
            "📌 *Команды:*\n"
            "/start — оформить арест\n"
            "👑 Админ-панель — просмотр активных арестов\n"
            "/admin — тоже самое что и кнопка\n"
            "/help — это сообщение\n\n"
            "Админы получают уведомления о всех новых арестах и изменениях.",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "📌 *Команды:*\n"
            "/start — оформить арест\n"
            "/help — это сообщение",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

async def main():
    print("Бот запущен...")
    print(f"Админы: {ADMIN_IDS}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())