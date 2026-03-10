from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram import Update
import os
import asyncpg

# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

CHANNEL_USERNAME = '@rublefashion'
ADMIN_ID = 153113117

MAX_MESSAGES_TO_STORE = 70

# ─────────────────────────────────────────────
# Черновик поста
# ─────────────────────────────────────────────

draft = {
    "photo_id": None,
    "text": None,
    "links": []
}

user_messages = {}

# ─────────────────────────────────────────────
# База данных
# ─────────────────────────────────────────────

async def init_db(app):
    app.bot_data["db"] = await asyncpg.create_pool(DATABASE_URL)
    pool = app.bot_data["db"]
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog (
                id SERIAL PRIMARY KEY,
                url TEXT UNIQUE,
                name TEXT,
                display TEXT,
                photo_url TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS wishlists (
                user_id BIGINT,
                catalog_id INTEGER REFERENCES catalog(id),
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (user_id, catalog_id)
            )
        """)

async def close_db(app):
    await app.bot_data["db"].close()

async def db_save_catalog_item(pool, url, name, display, photo_url):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO catalog (url, name, display, photo_url)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (url) DO UPDATE SET name=$2, display=$3, photo_url=$4
            RETURNING id
        """, url, name, display or name, photo_url)
    return row["id"]

async def db_get_catalog_item_by_id(pool, item_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM catalog WHERE id = $1", item_id)
    return dict(row) if row else {}

async def db_get_wishlist(pool, user_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id, c.url, c.name, c.display, c.photo_url
            FROM wishlists w
            JOIN catalog c ON w.catalog_id = c.id
            WHERE w.user_id = $1
            ORDER BY w.created_at
        """, user_id)
    return [dict(r) for r in rows]

async def db_add_to_wishlist(pool, user_id, catalog_id):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO wishlists (user_id, catalog_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, user_id, catalog_id)

async def db_remove_from_wishlist(pool, user_id, catalog_id):
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM wishlists WHERE user_id = $1 AND catalog_id = $2",
            user_id, catalog_id
        )

async def db_clear_wishlist(pool, user_id):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM wishlists WHERE user_id = $1", user_id)

# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

async def record_bot_message(user_id, chat_id, message_id):
    if user_id not in user_messages:
        user_messages[user_id] = []
    user_messages[user_id].append((chat_id, message_id))
    if len(user_messages[user_id]) > MAX_MESSAGES_TO_STORE:
        user_messages[user_id].pop(0)

async def delete_user_messages(user_id, context):
    if user_id not in user_messages:
        return
    for chat_id, msg_id in user_messages[user_id]:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except:
            pass
    user_messages[user_id] = []

async def send_msg(update, context, text, reply_markup=None, disable_web_page_preview=False, parse_mode=None):
    if update.message:
        chat_id = update.effective_chat.id
        user_id = update.message.from_user.id
        msg = await update.message.reply_text(text, reply_markup=reply_markup, disable_notification=True, disable_web_page_preview=disable_web_page_preview, parse_mode=parse_mode)
    elif update.callback_query:
        chat_id = update.callback_query.message.chat_id
        user_id = update.callback_query.from_user.id
        msg = await update.callback_query.message.reply_text(text, reply_markup=reply_markup, disable_notification=True, disable_web_page_preview=disable_web_page_preview, parse_mode=parse_mode)
    else:
        return
    await record_bot_message(user_id, chat_id, msg.message_id)
    return msg

def make_buttons(links):
    # Используем короткий ID из базы вместо url — нет ограничения на длину ссылки
    buttons = [
        InlineKeyboardButton(f"❤️ {item['name'].split()[0]}", callback_data=f"save_{item['db_id']}")
        for item in links
    ]
    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i+2])
    return InlineKeyboardMarkup(rows)

def build_links_block(links):
    lines = []
    for item in links:
        display = item.get("display") or item["name"]
        lines.append(f"<a href='{item['url']}'>{display}</a>")
    return "\n".join(lines)

def draft_status():
    photo = "✅ фото загружено" if draft["photo_id"] else "❌ фото не загружено"
    text = "✅ текст добавлен" if draft["text"] else "❌ текст не добавлен"
    if draft["links"]:
        lines = []
        for i, l in enumerate(draft["links"]):
            display = l.get("display") or l["name"]
            photo_icon = " 🖼" if l.get("photo_url") else ""
            lines.append(f"  {i+1}. {display}{photo_icon} — {l['url']}")
        links = "✅ ссылки:\n" + "\n".join(lines)
    else:
        links = "❌ ссылки не добавлены"
    return f"{photo}\n{text}\n{links}"

# ─────────────────────────────────────────────
# Команды
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id == ADMIN_ID:
        text = (
            "Привет!\n\n"
            "📢 Создание поста:\n"
            "/newpost — начать новый пост (сбросить черновик)\n"
            "/status — посмотреть черновик\n"
            "/publish — опубликовать пост в канал\n\n"
            "Как создать пост:\n"
            "1. Отправь фото\n"
            "2. Добавь ссылки в формате:\n"
            "   название | url | текст для вишлиста\n"
            "   или с картинкой:\n"
            "   название | url | текст для вишлиста | url картинки\n\n"
            "   Ссылка может быть любой длины!\n\n"
            "3. Отправь текст поста — ссылки добавятся снизу автоматически\n"
            "4. Напиши /publish\n\n"
            "❤️ Вишлист:\n"
            "/wishlist — показать сохранённые товары\n"
            "/clearwishlist — очистить вишлист\n"
            "/clearscreen — удалить сообщения бота"
        )
    else:
        text = (
            "Привет! Нажимай на ❤️ под товарами в канале — они сохранятся в твой вишлист.\n\n"
            "/wishlist — показать сохранённые товары\n"
            "/clearwishlist — очистить вишлист\n"
            "/clearscreen — удалить сообщения бота"
        )
    await send_msg(update, context, text, disable_web_page_preview=True)

async def new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    draft["photo_id"] = None
    draft["text"] = None
    draft["links"] = []
    await send_msg(update, context,
        "Черновик сброшен ✅\n\n"
        "Отправь мне:\n"
        "1. Фото\n"
        "2. Ссылки в формате:\n"
        "   название | url | текст для вишлиста\n"
        "   или с картинкой:\n"
        "   название | url | текст для вишлиста | url картинки\n\n"
        "   Ссылка может быть любой длины!\n\n"
        "3. Текст поста — ссылки добавятся снизу автоматически\n"
        "4. /publish",
        disable_web_page_preview=True
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    await send_msg(update, context, f"Текущий черновик:\n\n{draft_status()}", disable_web_page_preview=True)

async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return

    if not draft["text"] and not draft["photo_id"]:
        await send_msg(update, context, "❌ Нет ни текста, ни фото. Добавь хотя бы что-то одно.")
        return

    pool = context.application.bot_data["db"]

    # Сохраняем ссылки в базу и получаем их ID
    for item in draft["links"]:
        db_id = await db_save_catalog_item(
            pool, item["url"], item["name"],
            item.get("display"), item.get("photo_url")
        )
        item["db_id"] = db_id

    keyboard = make_buttons(draft["links"]) if draft["links"] else None

    base_text = draft["text"] or ""
    links_block = build_links_block(draft["links"]) if draft["links"] else ""
    full_text = f"{base_text}\n\n{links_block}" if links_block else base_text

    try:
        if draft["photo_id"]:
            await context.bot.send_photo(
                chat_id=CHANNEL_USERNAME,
                photo=draft["photo_id"],
                caption=full_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
        else:
            await context.bot.send_message(
                chat_id=CHANNEL_USERNAME,
                text=full_text,
                parse_mode='HTML',
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        await send_msg(update, context, "Пост опубликован в канале ✅")
        draft["photo_id"] = None
        draft["text"] = None
        draft["links"] = []
    except Exception as e:
        await send_msg(update, context, f"Ошибка при публикации: {e}")

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return

    if update.message.photo:
        draft["photo_id"] = update.message.photo[-1].file_id
        await send_msg(update, context, f"Фото сохранено ✅\n\n{draft_status()}", disable_web_page_preview=True)
        return

    if update.message.text:
        text = update.message.text.strip()

        if "|" in text:
            parts = [p.strip() for p in text.split("|")]
            if len(parts) >= 2 and parts[1].startswith("http"):
                name = parts[0]
                url = parts[1]
                display = parts[2] if len(parts) >= 3 else None
                photo_url = parts[3] if len(parts) >= 4 else None

                draft["links"].append({"name": name, "url": url, "display": display, "photo_url": photo_url})
                await send_msg(update, context, f"Ссылка добавлена ✅\n\n{draft_status()}", disable_web_page_preview=True)
                return

        draft["text"] = text
        await send_msg(update, context, f"Текст сохранён ✅\n\n{draft_status()}", disable_web_page_preview=True)

# ─────────────────────────────────────────────
# Вишлист
# ─────────────────────────────────────────────

async def wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    pool = context.application.bot_data["db"]
    saved = await db_get_wishlist(pool, user_id)

    await delete_user_messages(user_id, context)

    if not saved:
        await send_msg(update, context, "Ваш вишлист пуст. Нажимайте ❤️ под товарами в канале!")
        return

    for item in saved:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Удалить из вишлиста", callback_data=f"del_{item['id']}")
        ]])
        display = item.get("display") or item.get("name") or ""
        photo_url = item.get("photo_url")

        if photo_url:
            caption = f"<b>{display}</b>\n{item['url']}" if display else item["url"]
            try:
                msg = await update.message.reply_photo(
                    photo=photo_url,
                    caption=caption,
                    parse_mode='HTML',
                    reply_markup=keyboard,
                    disable_notification=True
                )
                await record_bot_message(user_id, update.effective_chat.id, msg.message_id)
            except:
                text = f"<b>{display}</b>\n{item['url']}" if display else item["url"]
                await send_msg(update, context, text, reply_markup=keyboard, parse_mode='HTML')
        else:
            text = f"<b>{display}</b>\n{item['url']}" if display else item["url"]
            await send_msg(update, context, text, reply_markup=keyboard, parse_mode='HTML')

    await send_msg(update, context, f"Товаров в вишлисте: {len(saved)}", disable_web_page_preview=True)

async def clear_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    pool = context.application.bot_data["db"]
    await db_clear_wishlist(pool, user_id)
    await delete_user_messages(user_id, context)
    await send_msg(update, context, "Вишлист очищен ✅")

async def clear_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await delete_user_messages(user_id, context)
    await send_msg(update, context, "Экран очищен ✅")

# ─────────────────────────────────────────────
# Обработчик кнопок
# ─────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    pool = context.application.bot_data["db"]

    if data.startswith("save_"):
        catalog_id = int(data[len("save_"):])
        saved = await db_get_wishlist(pool, user_id)
        already = any(item["id"] == catalog_id for item in saved)

        if not already:
            await db_add_to_wishlist(pool, user_id, catalog_id)
            await query.answer(text="❤️ Сохранено в вишлист!", show_alert=False)
        else:
            await query.answer(text="Уже в вишлисте!", show_alert=False)

    elif data.startswith("del_"):
        catalog_id = int(data[len("del_"):])
        await db_remove_from_wishlist(pool, user_id, catalog_id)
        await query.answer(text="Удалено из вишлиста ✅", show_alert=False)
        try:
            await query.message.delete()
        except:
            pass

    else:
        await query.answer(text="Неизвестный запрос.", show_alert=True)

# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.post_init = init_db
    app.post_shutdown = close_db

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newpost", new_post))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("publish", publish))
    app.add_handler(CommandHandler("wishlist", wishlist))
    app.add_handler(CommandHandler("clearwishlist", clear_wishlist))
    app.add_handler(CommandHandler("clearscreen", clear_screen))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_admin_message))
    app.run_polling()

if __name__ == "__main__":
    main()

