import os
import logging
import anthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

COLLECTING = 0

SESSION_DATA: dict[int, list[str]] = {}

SYSTEM_PROMPT = """Ты — ассистент диджитал дизайнера-фрилансера. 
Твоя задача — принять хаотичный дамп информации о проекте (текст, голосовые расшифровки, описания скринов) 
и структурировать его в три чётких блока.

Отвечай ТОЛЬКО на русском языке. Формат ответа строго такой:

---
📋 БРИФ
• Клиент / проект: [название или описание]
• Задача: [что нужно сделать]
• Аудитория: [для кого]
• Референсы / стиль: [если есть]
• Дедлайн: [если упомянут]
• Бюджет: [если упомянут]
• Доп. детали: [всё остальное важное]

---
📐 ТЗ (техническое задание)
[Чёткий список задач для дизайнера, пронумерованный. Конкретно: что делать, в каком формате, какие экраны/страницы/элементы]

---
💰 СМЕТА
[Примерный список работ с оценкой часов. Формат:
• Название работы — X–Y часов
Итого: X–Y часов]

---
❓ ВОПРОСЫ КЛИЕНТУ
[Список уточняющих вопросов, которые нужно задать перед стартом. Если всё понятно — напиши "Достаточно информации для старта."]
---

Если информации очень мало — заполни что можешь и выдели вопросами всё недостающее."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    SESSION_DATA[user_id] = []
    await update.message.reply_text(
        "👋 Привет! Я твой бот-ассистент.\n\n"
        "Скидывай всё что есть по проекту — текст, голосовые, описания скринов, ссылки — в любом виде и порядке.\n\n"
        "Когда закончишь — напиши /generate и я выдам бриф, ТЗ и смету.\n\n"
        "Начинай! 👇"
    )
    return COLLECTING


async def collect_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id not in SESSION_DATA:
        SESSION_DATA[user_id] = []

    # Handle voice messages
    if update.message.voice:
        await update.message.reply_text("🎤 Голосовые пока не поддерживаются автоматически — перепиши текстом или скинь расшифровку.")
        return COLLECTING

    # Handle photos
    if update.message.photo:
        caption = update.message.caption or ""
        SESSION_DATA[user_id].append(f"[Скрин/изображение]{': ' + caption if caption else ''}")
        await update.message.reply_text("🖼 Скрин сохранён. Продолжай!")
        return COLLECTING

    # Handle text
    if update.message.text and not update.message.text.startswith("/"):
        SESSION_DATA[user_id].append(update.message.text)
        count = len(SESSION_DATA[user_id])
        if count == 1:
            await update.message.reply_text("✅ Принято! Скидывай ещё или /generate чтобы получить документы.")
        else:
            await update.message.reply_text(f"✅ Добавлено ({count} блоков). Ещё или /generate?")

    return COLLECTING


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    data = SESSION_DATA.get(user_id, [])

    if not data:
        await update.message.reply_text("❌ Ты ещё ничего не скинул! Сначала опиши проект.")
        return COLLECTING

    await update.message.reply_text("⏳ Генерирую бриф, ТЗ и смету...")

    raw_input = "\n\n---\n\n".join(data)

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"Вот информация по проекту:\n\n{raw_input}"}
            ]
        )
        result = message.content[0].text

        # Split if too long for Telegram (4096 char limit)
        if len(result) > 4000:
            parts = [result[i:i+4000] for i in range(0, len(result), 4000)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(result)

        # Clear session
        SESSION_DATA[user_id] = []
        await update.message.reply_text(
            "✨ Готово! Сессия очищена.\n\nДля нового проекта — /start"
        )

    except Exception as e:
        logger.error(f"Anthropic error: {e}")
        await update.message.reply_text(
            "❌ Ошибка при генерации. Проверь ANTHROPIC_API_KEY и попробуй снова.\n/start"
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    SESSION_DATA.pop(user_id, None)
    await update.message.reply_text("❌ Сессия отменена. /start чтобы начать заново.")
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📖 Как пользоваться:\n\n"
        "1. /start — начать новый проект\n"
        "2. Скидывай всё о проекте в любом виде\n"
        "3. /generate — получить бриф + ТЗ + смету\n"
        "4. /cancel — отменить текущую сессию\n\n"
        "Бот принимает текст и описания скринов."
    )


def main():
    if not ANTHROPIC_API_KEY:
        print("❌ ОШИБКА: Установи переменную окружения ANTHROPIC_API_KEY")
        print("   export ANTHROPIC_API_KEY='sk-ant-...'")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            COLLECTING: [
                MessageHandler(filters.ALL & ~filters.COMMAND, collect_message),
                CommandHandler("generate", generate),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("generate", generate))

    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
