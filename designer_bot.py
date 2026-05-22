import os
import logging
import anthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DESIGNER_USERNAME = "@artesignus"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

CONVERSATIONS: dict[int, list[dict]] = {}
BRIEF_SENT: dict[int, bool] = {}
REFERENCES: dict[int, list[str]] = {}

SYSTEM_PROMPT = """Ты — ассистент для сбора информации о проекте. Ты работаешь на дизайнера и общаешься с его потенциальными клиентами.

ТВОЯ ЕДИНСТВЕННАЯ ЗАДАЧА — собрать информацию и передать дизайнеру. Ты НЕ принимаешь решения, НЕ обсуждаешь цены, НЕ оцениваешь реалистичность запроса, НЕ даёшь советов клиенту.

Стиль: короткие сообщения, по-человечески, спокойно. Никаких звёздочек и markdown.

Собери по очереди (по одному вопросу за раз):
1. Что нужно сделать?
2. Какой бизнес/ниша?
3. Где будет использоваться дизайн?
4. Какая цель дизайна?
5. Есть ли референсы или примеры?
6. Есть ли фирменный стиль, цвета, шрифты?
7. Готовы ли тексты и материалы?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть в дизайне?

Правила:
- Задавай по одному вопросу
- Если ответ размытый — уточни
- Никогда не комментируй бюджет, сроки или реалистичность — просто фиксируй
- Никаких звёздочек (*) в тексте — только чистый текст и эмодзи по смыслу

Когда собрал всю информацию, скажи клиенту:
"Отлично, всё понятно ✅ Передаю информацию дизайнеру — он свяжется с вами в ближайшее время."

И добавь в конце:
===BRIEF_START===
🎨 ПРОЕКТ: [тип работы]
🏢 НИША: [бизнес]
📱 ПЛАТФОРМА: [где используется]
🎯 ЦЕЛЬ: [цель дизайна]
🖼 РЕФЕРЕНСЫ: [есть/нет, что именно]
✏️ ФИРМ.СТИЛЬ: [есть/нет]
📁 МАТЕРИАЛЫ: [готовы/не готовы]
⏰ ДЕДЛАЙН: [срок]
💰 БЮДЖЕТ: [что сказал клиент]
🚫 НЕ НУЖНО: [что не должно быть]

👤 УРОВЕНЬ КЛИЕНТА: low / medium / high
⚠️ РИСК: low / medium / high
💎 БЮДЖЕТ КАТЕГОРИЯ: low-budget / mid-range / premium

📝 ЗАМЕТКИ: [наблюдения — только факты]
⚡️ ВЫЖИМКА: [2-3 предложения самого важного]
===BRIEF_END==="""


async def start(update: Update, context) -> None:
    user_id = update.effective_user.id
    CONVERSATIONS[user_id] = []
    BRIEF_SENT[user_id] = False
    REFERENCES[user_id] = []
    await update.message.reply_text(
        "Привет! 👋\n\nЯ помогу передать информацию о вашем проекте дизайнеру.\n\nРасскажите — что нужно сделать?"
    )


async def handle_photo(update: Update, context) -> None:
    user_id = update.effective_user.id

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []
        BRIEF_SENT[user_id] = False
        REFERENCES[user_id] = []

    if BRIEF_SENT.get(user_id, False):
        await update.message.reply_text("Дизайнер уже получил вашу информацию и скоро свяжется 🙌")
        return

    caption = update.message.caption or ""
    ref_note = f"[референс: {caption}]" if caption else "[референс: фото]"

    if user_id not in REFERENCES:
        REFERENCES[user_id] = []
    REFERENCES[user_id].append(ref_note)

    CONVERSATIONS[user_id].append({
        "role": "user",
        "content": f"Отправил фото референса. {caption}"
    })

    await update.message.reply_text("Референс принял 👍 Продолжаем.")


async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Клиент"
    username = update.effective_user.username or ""
    user_text = update.message.text

    if not user_text:
        await update.message.reply_text("Напишите текстом, пожалуйста.")
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []
        BRIEF_SENT[user_id] = False
        REFERENCES[user_id] = []

    if BRIEF_SENT.get(user_id, False):
        await update.message.reply_text("Дизайнер уже получил вашу информацию и скоро свяжется 🙌")
        return

    CONVERSATIONS[user_id].append({"role": "user", "content": user_text})
    history = CONVERSATIONS[user_id][-20:]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=history
        )
        response = message.content[0].text

        if "===BRIEF_START===" in response:
            parts = response.split("===BRIEF_START===")
            client_message = parts[0].strip()
            brief_part = parts[1].split("===BRIEF_END===")[0].strip()

            # Добавляем референсы если были
            refs = REFERENCES.get(user_id, [])
            if refs:
                brief_part += f"\n\n🖼 ФАЙЛЫ РЕФЕРЕНСОВ: {len(refs)} фото отправлено в чате"

            await update.message.reply_text(client_message)

            contact = f"@{username}" if username else user_name
            brief_message = f"📋 Новый бриф\n\n👤 Клиент: {contact}\n\n{brief_part}"

            try:
                await context.bot.send_message(
                    chat_id=DESIGNER_USERNAME,
                    text=brief_message
                )
            except Exception as e:
                logger.error(f"Не удалось отправить бриф: {e}")

            BRIEF_SENT[user_id] = True
            CONVERSATIONS[user_id].append({"role": "assistant", "content": client_message})
        else:
            await update.message.reply_text(response)
            CONVERSATIONS[user_id].append({"role": "assistant", "content": response})

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуйте снова.")


def main():
    if not ANTHROPIC_API_KEY:
        print("❌ ОШИБКА: Установи ANTHROPIC_API_KEY")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
