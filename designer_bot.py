import os
import logging
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DESIGNER_CHAT_ID: int = int(os.getenv("DESIGNER_CHAT_ID", "0"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

CONVERSATIONS: dict[int, list[dict]] = {}
BRIEF_SENT: dict[int, bool] = {}
REFERENCES: dict[int, list[str]] = {}
USER_CATEGORY: dict[int, str] = {}

SYSTEM_PROMPTS = {
    "creatives_target": """Ты — ассистент дизайнера. Клиент хочет креативы для таргетированной рекламы.

Собери по очереди (один вопрос за раз):
1. Какой бизнес/продукт рекламируем?
2. Какая цель рекламы — продажи, подписки, трафик?
3. Какая площадка — Instagram, Facebook, TikTok, ВКонтакте?
4. Сколько креативов нужно?
5. Есть ли фирменный стиль, цвета, логотип?
6. Есть ли референсы или примеры которые нравятся?
7. Готовы ли тексты для баннеров?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть в дизайне?""",

    "creatives_stories": """Ты — ассистент дизайнера. Клиент хочет креативы для сторис.

Собери по очереди (один вопрос за раз):
1. Какой бизнес/продукт?
2. Цель сторис — продажи, охват, вовлечённость?
3. Сколько сторис нужно?
4. Есть ли фирменный стиль, цвета, логотип?
5. Есть ли референсы?
6. Готовы ли тексты?
7. Нужна ли анимация?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть?""",

    "creatives_banner": """Ты — ассистент дизайнера. Клиент хочет баннер.

Собери по очереди (один вопрос за раз):
1. Где будет размещён баннер?
2. Какой размер нужен?
3. Какой бизнес/продукт?
4. Цель баннера?
5. Есть ли фирменный стиль?
6. Есть ли референсы?
7. Готовы ли тексты?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть?""",

    "creatives_other": """Ты — ассистент дизайнера. Клиент хочет креатив.

Собери по очереди (один вопрос за раз):
1. Что именно нужно сделать?
2. Какой бизнес/продукт?
3. Где будет использоваться?
4. Цель дизайна?
5. Есть ли фирменный стиль?
6. Есть ли референсы?
7. Готовы ли материалы?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть?""",

    "presentation": """Ты — ассистент дизайнера. Клиент хочет презентацию.

Собери по очереди (один вопрос за раз):
1. Для чего презентация — питч инвесторам, клиентам, внутренняя?
2. Сколько слайдов примерно?
3. Какой бизнес/тема?
4. Есть ли фирменный стиль, цвета?
5. Есть ли референсы?
6. Готов ли контент — тексты, данные, графики?
7. Нужна ли анимация?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть?""",

    "logo": """Ты — ассистент дизайнера. Клиент хочет логотип.

Собери по очереди (один вопрос за раз):
1. Это новый логотип или редизайн существующего?
2. Какой бизнес/ниша?
3. Какие ценности должен передавать логотип?
4. Какой стиль нравится — минимализм, детализация, другое?
5. Есть ли референсы?
6. Какие цвета нравятся или не нравятся?
7. Где будет использоваться логотип?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть?""",

    "branding": """Ты — ассистент дизайнера. Клиент хочет брендинг.

Собери по очереди (один вопрос за раз):
1. Что входит в задачу — фирменный стиль, гайдлайн, упаковка, всё вместе?
2. Какой бизнес/ниша?
3. Есть ли уже логотип?
4. Какие ценности и характер бренда?
5. Какой стиль нравится?
6. Есть ли референсы?
7. Какая целевая аудитория?
8. Какой дедлайн?
9. Какой бюджет?
10. Что точно НЕ должно быть?"""
}

BRIEF_SUFFIX = """

Правила поведения:
- Задавай по одному вопросу
- Если ответ размытый — уточни
- Никогда не комментируй бюджет или сроки — просто фиксируй
- Никаких звёздочек (*) — только чистый текст и эмодзи по смыслу
- Стиль: коротко, по-человечески, спокойно

Когда собрал всю информацию, скажи:
"Отлично, всё понятно ✅ Передаю информацию дизайнеру — он свяжется с вами в ближайшее время."

И добавь:
===BRIEF_START===
🎨 ПРОЕКТ: [тип работы]
🏢 НИША: [бизнес]
📱 ПЛАТФОРМА: [где используется]
🎯 ЦЕЛЬ: [цель дизайна]
🖼 РЕФЕРЕНСЫ: [есть/нет]
✏️ ФИРМ.СТИЛЬ: [есть/нет]
📁 МАТЕРИАЛЫ: [готовы/не готовы]
⏰ ДЕДЛАЙН: [срок]
💰 БЮДЖЕТ: [что сказал клиент]
🚫 НЕ НУЖНО: [что не должно быть]

👤 УРОВЕНЬ КЛИЕНТА: low / medium / high
⚠️ РИСК: low / medium / high
💎 БЮДЖЕТ КАТЕГОРИЯ: low-budget / mid-range / premium

📝 ЗАМЕТКИ: [наблюдения]
⚡️ ВЫЖИМКА: [2-3 предложения самого важного]
===BRIEF_END==="""


def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 Креативы", callback_data="cat_creatives"),
         InlineKeyboardButton("📊 Презентация", callback_data="cat_presentation")],
        [InlineKeyboardButton("✏️ Логотип", callback_data="cat_logo"),
         InlineKeyboardButton("💎 Брендинг", callback_data="cat_branding")]
    ])


def get_creatives_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Для таргета", callback_data="sub_creatives_target"),
         InlineKeyboardButton("📱 Для сторис", callback_data="sub_creatives_stories")],
        [InlineKeyboardButton("🖼 Баннер", callback_data="sub_creatives_banner"),
         InlineKeyboardButton("🔧 Другое", callback_data="sub_creatives_other")]
    ])


CATEGORY_NAMES = {
    "creatives_target": "Креативы для таргета",
    "creatives_stories": "Креативы для сторис",
    "creatives_banner": "Баннер",
    "creatives_other": "Креатив",
    "presentation": "Презентация",
    "logo": "Логотип",
    "branding": "Брендинг"
}

async def register(update: Update, context) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"✅ Твой chat_id: {user_id}\n\nДобавь в Railway Variables:\nDESIGNER_CHAT_ID = {user_id}"
    )



async def start(update: Update, context) -> None:
    user_id = update.effective_user.id
    CONVERSATIONS[user_id] = []
    BRIEF_SENT[user_id] = False
    REFERENCES[user_id] = []
    USER_CATEGORY[user_id] = ""

    await update.message.reply_text(
        "Привет! 👋\n\nЯ помогу передать информацию о вашем проекте дизайнеру.\n\nЧто нужно сделать?",
        reply_markup=get_main_keyboard()
    )


async def handle_callback(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []
        BRIEF_SENT[user_id] = False
        REFERENCES[user_id] = []

    if data == "cat_creatives":
        await query.edit_message_text(
            "Какой тип креатива?",
            reply_markup=get_creatives_keyboard()
        )
        return

    # Определяем категорию
    if data.startswith("sub_"):
        category = data.replace("sub_", "")
    elif data.startswith("cat_"):
        category = data.replace("cat_", "")
    else:
        return

    USER_CATEGORY[user_id] = category
    category_name = CATEGORY_NAMES.get(category, "Проект")

    # Первый вопрос от бота
    system = SYSTEM_PROMPTS.get(category, SYSTEM_PROMPTS["creatives_other"]) + BRIEF_SUFFIX

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": f"Я выбрал: {category_name}"}]
        )
        first_question = message.content[0].text
        CONVERSATIONS[user_id] = [
            {"role": "user", "content": f"Я выбрал: {category_name}"},
            {"role": "assistant", "content": first_question}
        ]
        await query.edit_message_text(f"Отлично, {category_name.lower()} 👌\n\n{first_question}")
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text(f"Отлично, {category_name.lower()} 👌\n\nРасскажите подробнее о проекте.")


async def handle_photo(update: Update, context) -> None:
    user_id = update.effective_user.id
    if user_id not in REFERENCES:
        REFERENCES[user_id] = []
    caption = update.message.caption or ""
    REFERENCES[user_id].append(f"[фото референс{': ' + caption if caption else ''}]")
    CONVERSATIONS.setdefault(user_id, []).append({
        "role": "user", "content": f"Отправил фото референса. {caption}"
    })
    await update.message.reply_text("Референс принял 👍 Продолжаем.")


async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Клиент"
    username = update.effective_user.username or ""
    user_text = update.message.text

    if not user_text:
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []
        BRIEF_SENT[user_id] = False
        REFERENCES[user_id] = []
        USER_CATEGORY[user_id] = ""
        await update.message.reply_text(
            "Привет! 👋 Что нужно сделать?",
            reply_markup=get_main_keyboard()
        )
        return

    if BRIEF_SENT.get(user_id, False):
        await update.message.reply_text("Дизайнер уже получил вашу информацию и скоро свяжется 🙌")
        return

    if not USER_CATEGORY.get(user_id):
        await update.message.reply_text(
            "Выберите тип проекта 👇",
            reply_markup=get_main_keyboard()
        )
        return

    CONVERSATIONS[user_id].append({"role": "user", "content": user_text})
    history = CONVERSATIONS[user_id][-20:]
    category = USER_CATEGORY.get(user_id, "creatives_other")
    system = SYSTEM_PROMPTS.get(category, SYSTEM_PROMPTS["creatives_other"]) + BRIEF_SUFFIX

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=system,
            messages=history
        )
        response = message.content[0].text

        if "===BRIEF_START===" in response:
            parts = response.split("===BRIEF_START===")
            client_message = parts[0].strip()
            brief_part = parts[1].split("===BRIEF_END===")[0].strip()

            refs = REFERENCES.get(user_id, [])
            if refs:
                brief_part += f"\n\n🖼 ФАЙЛЫ: {len(refs)} референс(ов) в чате"

            await update.message.reply_text(client_message)

            contact = f"@{username}" if username else user_name
            category_name = CATEGORY_NAMES.get(category, "Проект")
            brief_message = (
                f"🔔 Новая заявка!\n\n"
                f"👤 Клиент: {contact}\n"
                f"🗂 Тип: {category_name}\n\n"
                f"──────────────────\n\n"
                f"{brief_part}\n\n"
                f"──────────────────\n"
                f"💬 Написать клиенту: tg://user?id={user_id}"
            )

            try:
                await context.bot.send_message(
                    chat_id=DESIGNER_CHAT_ID,
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
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
