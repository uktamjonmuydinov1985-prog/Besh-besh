import asyncio
import os
import sqlite3

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
ADMIN_ID = 8279536115
DB_NAME = "kino.db"

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

db = sqlite3.connect(DB_NAME, check_same_thread=False)
db.execute("""
CREATE TABLE IF NOT EXISTS movies (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    file_id TEXT NOT NULL
)
""")
db.execute("""
CREATE TABLE IF NOT EXISTS channels (
    username TEXT PRIMARY KEY
)
""")
db.commit()


class SaveMovie(StatesGroup):
    waiting_video = State()


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def get_channels():
    return [row[0] for row in db.execute(
        "SELECT username FROM channels ORDER BY username"
    ).fetchall()]


def channel_keyboard(channels):
    buttons = []
    for ch in channels:
        username = ch.lstrip("@")
        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {ch}",
                url=f"https://t.me/{username}"
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="✅ Obunani tekshirish",
            callback_data="check_subscription"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def missing_channels(user_id: int):
    missing = []
    for username in get_channels():
        try:
            member = await bot.get_chat_member(username, user_id)
            if member.status not in ("member", "administrator", "creator"):
                missing.append(username)
        except Exception:
            # Bot kanalga kira olmasa, uni o'tkazib yubormaymiz.
            missing.append(username)
    return missing


async def require_subscription(message: Message) -> bool:
    missing = await missing_channels(message.from_user.id)
    if not missing:
        return True

    await message.answer(
        "🎬 Kinolarni olish uchun quyidagi kanallarga obuna bo'ling:",
        reply_markup=channel_keyboard(missing)
    )
    return False


@dp.message(CommandStart())
async def start(message: Message):
    if not await require_subscription(message):
        return
    await message.answer(
        "🎬 <b>Kino bot</b>\n\n"
        "Kino kodini yuboring.\n"
        "Masalan: <code>123</code>"
    )


@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    missing = await missing_channels(callback.from_user.id)
    if missing:
        await callback.message.edit_text(
            "❌ Hali barcha kanallarga obuna bo'lmagansiz.",
            reply_markup=channel_keyboard(missing)
        )
    else:
        await callback.message.edit_text(
            "✅ Obuna tasdiqlandi!\n\nEndi kino kodini yuboring."
        )
    await callback.answer()


@dp.message(Command("addchannel"))
async def add_channel(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Foydalanish: <code>/addchannel @kanal</code>")
        return

    username = parts[1].strip()
    if not username.startswith("@"):
        username = "@" + username

    try:
        chat = await bot.get_chat(username)
        if chat.type != "channel":
            await message.answer("❌ Bu username kanalniki emas.")
            return
    except Exception:
        await message.answer(
            "❌ Kanal topilmadi. Username to'g'ri ekanini va bot kanalga "
            "admin qilib qo'yilganini tekshiring."
        )
        return

    db.execute("INSERT OR IGNORE INTO channels(username) VALUES (?)", (username,))
    db.commit()
    await message.answer(f"✅ Majburiy kanal qo'shildi: <b>{username}</b>")


@dp.message(Command("delchannel"))
async def delete_channel(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Foydalanish: <code>/delchannel @kanal</code>")
        return

    username = parts[1].strip()
    if not username.startswith("@"):
        username = "@" + username

    cur = db.execute("DELETE FROM channels WHERE username = ?", (username,))
    db.commit()

    if cur.rowcount:
        await message.answer(f"🗑 Kanal o'chirildi: <b>{username}</b>")
    else:
        await message.answer("❌ Bunday kanal majburiy ro'yxatda yo'q.")


@dp.message(Command("channels"))
async def list_channels(message: Message):
    if not is_admin(message.from_user.id):
        return

    channels = get_channels()
    if not channels:
        await message.answer("📭 Majburiy kanallar yo'q.")
        return

    text = "📢 <b>Majburiy kanallar:</b>\n\n"
    text += "\n".join(f"• {ch}" for ch in channels)
    await message.answer(text)


@dp.message(Command("save"))
async def save_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or "|" not in parts[1]:
        await message.answer(
            "Foydalanish:\n<code>/save KOD | Kino nomi</code>\n\n"
            "Keyin video yuboring."
        )
        return

    code, title = [x.strip() for x in parts[1].split("|", 1)]
    if not code or not title:
        await message.answer("❌ Kod va kino nomini kiriting.")
        return

    await state.update_data(code=code, title=title)
    await SaveMovie.waiting_video.set()
    await message.answer(
        f"🎬 <b>{title}</b>\n"
        f"🔑 Kod: <code>{code}</code>\n\n"
        "Endi video faylni yuboring."
    )


@dp.message(SaveMovie.waiting_video, F.video)
async def receive_video(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    code = data["code"]
    title = data["title"]
    file_id = message.video.file_id

    db.execute(
        "INSERT OR REPLACE INTO movies(code, title, file_id) VALUES (?, ?, ?)",
        (code, title, file_id)
    )
    db.commit()
    await state.clear()

    await message.answer(
        f"✅ Saqlandi!\n\n"
        f"🔑 Kod: <code>{code}</code>\n"
        f"🎬 Nomi: <b>{title}</b>"
    )


@dp.message(SaveMovie.waiting_video)
async def receive_wrong_type(message: Message):
    await message.answer("❗ Iltimos, video fayl yuboring.")


@dp.message(Command("list"))
async def list_movies(message: Message):
    if not is_admin(message.from_user.id):
        return

    rows = db.execute(
        "SELECT code, title FROM movies ORDER BY code"
    ).fetchall()

    if not rows:
        await message.answer("📭 Hali kino saqlanmagan.")
        return

    text = "🎬 <b>Kinolar:</b>\n\n"
    text += "\n".join(f"• <code>{code}</code> — {title}" for code, title in rows)
    await message.answer(text)


@dp.message(Command("delete"))
async def delete_movie(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Foydalanish: <code>/delete KOD</code>")
        return

    code = parts[1].strip()
    cur = db.execute("DELETE FROM movies WHERE code = ?", (code,))
    db.commit()

    if cur.rowcount:
        await message.answer(f"🗑 Kino o'chirildi: <code>{code}</code>")
    else:
        await message.answer("❌ Bunday kod topilmadi.")


@dp.message(F.text)
async def find_movie(message: Message):
    if not await require_subscription(message):
        return

    code = message.text.strip()
    row = db.execute(
        "SELECT title, file_id FROM movies WHERE code = ?",
        (code,)
    ).fetchone()

    if not row:
        await message.answer("❌ Bunday koddagi kino topilmadi.")
        return

    title, file_id = row
    await message.answer_video(
        video=file_id,
        caption=f"🎬 <b>{title}</b>\n🔑 Kod: <code>{code}</code>"
    )


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN topilmadi. Hostingda BOT_TOKEN environment variable qo'ying."
        )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
