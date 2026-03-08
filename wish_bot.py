from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram import Update
import os
import json

# ─────────────────────────────────────────────
# НАСТРОЙКИ
# ─────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN")

CHANNEL_USERNAME = '@rublefashion'
WISHLIST_BOT_USERNAME = "@wishlist_tut_bot"
ADMIN_ID = 153113117

MAX_MESSAGES_TO_STORE = 70
WISHLIST_FILE = "wishlists.json"
CATALOG_FILE = "catalog.json"

# ─────────────────────────────────────────────
# Черновик поста
# ─────────────────────────────────────────────

draft = {
    "photo_id": None,
    "text": None,
    "links": []
}

# ─────────────────────────────────────────────
# Хранение данных
# ─────────────────────────────────────────────

user_messages = {}

def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_wishlists():
    data = load_json(WISHLIST_FILE)
    return {int(k): v for k, v in data.items()}

def save_wishlists(data):
    save_json(WISHLIST_FILE, data)

def load_catalog():
    return load_json(CATALOG_FILE)

def save_catalog(data):
    save_json(CATALOG_FILE, data)

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
        return 0
    count = 0
    for chat_id, msg_id in user_messages[user_id]:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            count += 1
        except:
            pass
    user_messages[user_id] = []
    return count

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
    buttons = [
        InlineKeyboardButton(f"❤️ {item['name'].split()[0]}", callback_data=f"save_{item['url']}")
        for item in links
    ]
    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i+2])
    return InlineKeyboardMarkup(rows)

def build_links_block(links):
    """Собирает блок гиперссылок для текста поста."""
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
            "   например:\n"
            "   шуба | https://zarina.ru/... | Шуба Zarina | https://фото.jpg\n\n"
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

    # Сохраняем данные в каталог
    catalog = load_catalog()
    for item in draft["links"]:
        catalog[item["url"]] = {
            "name": item["name"],
            "display": item.get("display") or item["name"],
            "photo_url": item.get("photo_url")
        }
    save_catalog(catalog)

    keyboard = make_buttons(draft["links"]) if draft["links"] else None

    # Собираем текст: основной текст + блок гиперссылок снизу
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

# ─────────────────────────────────────────────
# Обработчик входящих сообщений от админа
# ─────────────────────────────────────────────

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

                cb = f"save_{url}"
                if len(cb) > 64:
                    await send_msg(update, context,
                        f"⚠️ Ссылка слишком длинная ({len(url)} симв.), максимум 57.\n"
                        "Сократи ссылку и отправь снова.",
                        disable_web_page_preview=True
                    )
                    return

                draft["links"].append({"name": name, "url": url, "display": display, "photo_url": photo_url})
                await send_msg(update, context, f"Ссылка добавлена ✅\n\n{draft_status()}", disable_web_page_preview=True)
                return

        draft["text"] = text
        await send_msg(update, context, f"Текст сохранён ✅\n\n{draft_status()}", disable_web_page_preview=True)

# ─────────────────────────────────────────────
# Команды вишлиста
# ─────────────────────────────────────────────

async def wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    wishlists = load_wishlists()
    saved = wishlists.get(user_id, [])

    await delete_user_messages(user_id, context)

    if not saved:
        await send_msg(update, context, "Ваш вишлист пуст. Нажимайте ❤️ под товарами в канале!")
        return

    for i, item in enumerate(saved):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Удалить из вишлиста", callback_data=f"del_{i}")
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
    wishlists = load_wishlists()
    wishlists.pop(user_id, None)
    save_wishlists(wishlists)
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
    wishlists = load_wishlists()
    catalog = load_catalog()

    if data.startswith("save_"):
        url = data[len("save_"):]
        catalog_item = catalog.get(url, {})
        display = catalog_item.get("display", "")
        name = catalog_item.get("name", "")
        photo_url = catalog_item.get("photo_url")

        if user_id not in wishlists:
            wishlists[user_id] = []

        already = any(item["url"] == url for item in wishlists[user_id])
        if not already:
            wishlists[user_id].append({"name": name, "url": url, "display": display, "photo_url": photo_url})
            save_wishlists(wishlists)
            await query.answer(text="❤️ Сохранено в вишлист!", show_alert=False)
        else:
            await query.answer(text="Уже в вишлисте!", show_alert=False)

    elif data.startswith("del_"):
        idx = int(data[len("del_"):])
        items = wishlists.get(user_id, [])
        if 0 <= idx < len(items):
            items.pop(idx)
            wishlists[user_id] = items
            save_wishlists(wishlists)
            await query.answer(text="Удалено из вишлиста ✅", show_alert=False)
            try:
                await query.message.delete()
            except:
                pass
        else:
            await query.answer(text="Товар не найден.", show_alert=True)

    else:
        await query.answer(text="Неизвестный запрос.", show_alert=True)

# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
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
