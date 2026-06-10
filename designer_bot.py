import os
import re
import base64
import logging
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

USER_MODE: dict[int, str] = {}
CONVERSATIONS: dict[int, list[dict]] = {}

# Для аргументации
DESIGN_IMAGE: dict[int, str] = {}       # base64 картинки
DESIGN_ANSWERS: dict[int, dict] = {}    # ответы на вопросы
DESIGN_QUESTIONS: dict[int, list] = {}  # вопросы сгенерированные AI
DESIGN_STEP: dict[int, int] = {}        # текущий шаг

ARTEM_STYLE = """Твоя задача — писать так, будто ты Артём, молодой диджитал-дизайнер с сильным чувством вкуса и опытом работы с клиентами.

Стиль:
— Простой разговорный язык, коротко и по делу.
— Короткие предложения. Никакой воды.
— Разговорные слова: "короче", "смотри", "по сути", "честно".
— Никаких клише: "уникальный подход", "выведите бизнес на новый уровень", "уверенное предложение от тех кто знает своё дело".
— Никаких эмодзи без необходимости.
— Текст должен звучать как живой человек, а не нейросеть.
— Всегда тире — а не дефис. НИКОГДА не пиши слова через дефис типа "крипто-сервис" — только слитно или раздельно.

Примеры фраз: "Смотри, тут задача была...", "Я пошёл по пути...", "Это работает потому что...", "По сути здесь важно..."

Главное: коротко, живо, без пафоса."""

BRIEF_SYSTEM = """Ты помогаешь дизайнеру Артёму сформулировать ответ клиенту. Задавай вопросы по одному.

Вопросы:
1. Что за ситуация — новый проект, правки, цена, сроки?
2. Какой тип проекта?
3. Сколько стоит?
4. Какие сроки?
5. Сколько правок включено?
6. Есть ли предоплата?
7. Что именно нужно сказать клиенту?

Когда собрал всё — напиши готовый ответ клиенту.

""" + ARTEM_STYLE


def clean_text(text: str) -> str:
    text = text.replace("**", "").replace("__", "")
    # Заменяем длинное тире на обычный дефис между словами
    text = text.replace(" — ", " - ")
    return text


def get_main_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 Ответить клиенту", callback_data="mode_brief"),
        InlineKeyboardButton("🎨 Аргументация клиенту", callback_data="mode_design")
    ]])


def get_back_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("← Главное меню", callback_data="back_main")
    ]])


def get_volume_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Коротко (3-5 строк)", callback_data="vol_short"),
        InlineKeyboardButton("Развёрнуто", callback_data="vol_long")
    ]])


def is_owner(user_id: int) -> bool:
    return OWNER_ID == 0 or user_id == OWNER_ID


async def start(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Нет доступа.")
        return
    USER_MODE[user_id] = ""
    CONVERSATIONS[user_id] = []
    await update.message.reply_photo(
        photo="https://i.ibb.co/VY7CY8mF/Frame-3.png",
        caption="Выбери что делаем 👇",
        reply_markup=get_main_keyboard()
    )


async def register(update: Update, context) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(f"Твой ID: {user_id}\n\nДобавь в Railway Variables:\nOWNER_ID = {user_id}")


async def handle_callback(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_owner(user_id):
        return
    data = query.data

    if data == "mode_brief":
        USER_MODE[user_id] = "brief"
        CONVERSATIONS[user_id] = []
        await query.edit_message_text("Окей, помогу составить ответ.\n\nЧто за ситуация?")

    elif data == "mode_design":
        USER_MODE[user_id] = "design_wait_photo"
        DESIGN_IMAGE[user_id] = ""
        DESIGN_ANSWERS[user_id] = {}
        DESIGN_QUESTIONS[user_id] = []
        DESIGN_STEP[user_id] = 0
        await query.edit_message_text("Прикрепи скрин дизайна 🖼")

    elif data == "back_main":
        USER_MODE[user_id] = ""
        CONVERSATIONS[user_id] = []
        await query.edit_message_text("Что делаем?", reply_markup=get_main_keyboard())

    elif data.startswith("dq_"):
        # Ответ на вопрос по дизайну
        answer = data[3:]
        step = DESIGN_STEP.get(user_id, 0)
        questions = DESIGN_QUESTIONS.get(user_id, [])
        answers = DESIGN_ANSWERS.get(user_id, {})

        if step < len(questions):
            answers[questions[step]["question"]] = answer
            DESIGN_ANSWERS[user_id] = answers
            DESIGN_STEP[user_id] = step + 1
            await _ask_next_design_question(query, user_id, context)

    elif data == "vol_short":
        DESIGN_ANSWERS.setdefault(user_id, {})["volume"] = "коротко (3-5 строк)"
        await query.edit_message_text("Генерирую аргументацию...")
        await _generate_argumentation(user_id, context, query.message.chat_id)

    elif data == "vol_long":
        DESIGN_ANSWERS.setdefault(user_id, {})["volume"] = "развёрнуто"
        await query.edit_message_text("Генерирую аргументацию...")
        await _generate_argumentation(user_id, context, query.message.chat_id)


async def _ask_next_design_question(query_or_message, user_id: int, context):
    step = DESIGN_STEP.get(user_id, 0)
    questions = DESIGN_QUESTIONS.get(user_id, [])

    if step >= len(questions):
        # Все вопросы заданы — спрашиваем объём
        if hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(
                "Какой объём аргументации?",
                reply_markup=get_volume_keyboard()
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="Какой объём аргументации?",
                reply_markup=get_volume_keyboard()
            )
        return

    q = questions[step]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f"dq_{opt}") for opt in row]
        for row in q["options"]
    ])

    text = q["question"]
    if hasattr(query_or_message, 'edit_message_text'):
        await query_or_message.edit_message_text(text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)


async def _generate_argumentation(user_id: int, context, chat_id: int):
    image_data = DESIGN_IMAGE.get(user_id, "")
    answers = DESIGN_ANSWERS.get(user_id, {})
    volume = answers.get("volume", "коротко")

    answers_text = "\n".join([f"— {k}: {v}" for k, v in answers.items() if k != "volume"])

    system = f"""Ты пишешь аргументацию к дизайну от лица дизайнера Артёма для клиента.

Объём: {volume}.

Контекст из ответов дизайнера:
{answers_text}

""" + ARTEM_STYLE

    messages = [{
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}
            },
            {
                "type": "text",
                "text": f"Напиши аргументацию к этому дизайну. Объём: {volume}. Дополнительный контекст:\n{answers_text}"
            }
        ]
    }]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=system,
            messages=messages
        )
        response = clean_text(message.content[0].text)
        await context.bot.send_message(chat_id=chat_id, text=response, reply_markup=get_back_keyboard())
    except Exception as e:
        logger.error(f"Error generating argumentation: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Что-то пошло не так, попробуй снова.")


async def handle_photo(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return

    mode = USER_MODE.get(user_id, "")

    # Режим аргументации — ждём фото дизайна
    if mode == "design_wait_photo":
        thinking_msg = await update.message.reply_text("Анализирую...")

        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        DESIGN_IMAGE[user_id] = image_data

        # Анализируем дизайн и генерируем вопросы
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=500,
                system="""Ты анализируешь дизайн и генерируешь 2-3 уточняющих вопроса для дизайнера.

Верни ТОЛЬКО JSON такого формата (без markdown, без пояснений):
[
  {
    "question": "Вопрос?",
    "options": [["Вариант 1", "Вариант 2"], ["Вариант 3"]]
  }
]

Вопросы должны быть конкретными под этот дизайн. Варианты — короткие, 1-3 слова. Максимум 2 варианта в ряду.""",
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}
                        },
                        {"type": "text", "text": "Сгенерируй уточняющие вопросы для аргументации этого дизайна."}
                    ]
                }]
            )

            import json
            raw = message.content[0].text.strip()
            raw = re.sub(r'```json|```', '', raw).strip()
            questions = json.loads(raw)
            DESIGN_QUESTIONS[user_id] = questions
            DESIGN_STEP[user_id] = 0
            USER_MODE[user_id] = "design_questions"

        except Exception as e:
            logger.error(f"Error analyzing design: {e}")
            DESIGN_QUESTIONS[user_id] = []
            DESIGN_STEP[user_id] = 0
            USER_MODE[user_id] = "design_questions"

        # Удаляем "Анализирую..."
        try:
            await thinking_msg.delete()
        except Exception:
            pass

        await _ask_next_design_question(update.message, user_id, context)
        return

    # Обычный режим — фото как контекст
    if not mode:
        await update.message.reply_text("Выбери что делаем 👇", reply_markup=get_main_keyboard())
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
    caption = update.message.caption or "Скрин переписки"

    user_content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
        {"type": "text", "text": caption}
    ]

    CONVERSATIONS[user_id].append({"role": "user", "content": user_content})
    history = CONVERSATIONS[user_id][-10:]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=BRIEF_SYSTEM,
            messages=history
        )
        response = clean_text(message.content[0].text)
        CONVERSATIONS[user_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response, reply_markup=get_back_keyboard())
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй снова.")


async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return

    user_text = update.message.text
    if not user_text:
        return

    mode = USER_MODE.get(user_id, "")

    if not mode or mode == "design_wait_photo":
        await update.message.reply_text("Выбери что делаем 👇", reply_markup=get_main_keyboard())
        return

    if mode == "design_questions":
        await update.message.reply_text("Используй кнопки для ответа 👆")
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []

    CONVERSATIONS[user_id].append({"role": "user", "content": user_text})
    history = CONVERSATIONS[user_id][-20:]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=BRIEF_SYSTEM,
            messages=history
        )
        response = clean_text(message.content[0].text)
        CONVERSATIONS[user_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response, reply_markup=get_back_keyboard())
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй снова.")


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

    print("🤖 Личный ассистент запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
