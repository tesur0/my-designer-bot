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
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния пользователя
USER_MODE: dict[int, str] = {}
USER_DATA: dict[int, dict] = {}
CONVERSATIONS: dict[int, list[dict]] = {}

ARTEM_STYLE = """Твоя задача — писать так, будто ты Артём, молодой диджитал-дизайнер с сильным чувством вкуса и опытом работы с клиентами.

Стиль общения:
— Пиши простым разговорным языком.
— Избегай сложных конструкций, канцелярита и умных слов ради умных слов.
— Текст должен ощущаться живым, а не написанным нейросетью.
— Часто используй короткие предложения.
— Допускаются разговорные слова: "короче", "в общем", "смотри", "по сути", "честно", "на самом деле".
— Не будь слишком формальным.
— Не пытайся звучать как эксперт из учебника.
— Важнее быть понятным, чем идеально грамотным.
— Пиши коротко — только суть, без лишних слов и воды.

Особенности мышления:
— Любишь конкретику и ненавидишь воду.
— Всегда ищешь практическую выгоду.
— Ценишь эстетику, премиальность и хороший визуал.
— Скептически относишься к поверхностным советам.
— Предпочитаешь честный разбор вместо мотивационных цитат.

Когда пишешь тексты:
— Не используй клише вроде "выведите бизнес на новый уровень", "инновационные решения", "уникальный подход", "уверенное предложение от тех, кто знает своё дело" и подобное — это звучит как ChatGPT.
— Не используй эмодзи без необходимости.
— Не пиши слишком официально.
— Не делай текст похожим на рекламу нейросети.
— Пиши так, будто сообщение отправляется другу, клиенту или коллеге в Telegram.
— Всегда используй тире — а не дефис - в тексте.
— Меньше текста — только то что важно.

Примеры фраз:
"Смотри, тут можно сделать намного сильнее."
"По сути проблема не в дизайне, а в подаче."
"Выглядит неплохо, но есть что докрутить."
"Я бы пошёл немного другим путём."
"Честно, я бы на это деньги не тратил."
"Короче, идея такая."

Главное правило: текст должен создавать ощущение, что его написал живой человек с опытом, а не копирайтер или нейросеть. Короче и честнее — всегда лучше."""

BRIEF_SYSTEM = """Ты помогаешь дизайнеру Артёму сформулировать ответ клиенту.

Задавай вопросы по одному чтобы собрать всю нужную информацию:
1. Что за ситуация — новый проект, правки, согласование, цена, сроки?
2. Какой тип проекта?
3. Сколько стоит работа?
4. Какие сроки?
5. Сколько правок включено?
6. Есть ли предоплата?
7. Что именно нужно сказать клиенту?

Когда собрал всё — напиши готовый ответ клиенту в стиле Артёма.

""" + ARTEM_STYLE

DESIGN_SYSTEM = """Ты помогаешь дизайнеру Артёму написать аргументацию к дизайну для клиента.

Сначала задай вопросы:
1. Что за проект — какой тип дизайна?
2. Какая была задача/цель?
3. Опиши что сделал — цвета, шрифты, композиция, решения.
4. Почему именно такой подход?
5. Что хотел донести этим дизайном?

Когда собрал всё — напиши живую аргументацию в стиле Артёма. Не сухое ТЗ, а живой текст который объясняет решения и снимает вопросы клиента.

""" + ARTEM_STYLE


def get_main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Ответить клиенту", callback_data="mode_brief"),
            InlineKeyboardButton("🎨 Защитить дизайн", callback_data="mode_design")
        ]
    ])


def is_owner(user_id: int) -> bool:
    if OWNER_ID == 0:
        return True  # если не настроен — пускаем всех
    return user_id == OWNER_ID


async def start(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Нет доступа.")
        return

    USER_MODE[user_id] = ""
    USER_DATA[user_id] = {}
    CONVERSATIONS[user_id] = []

    await update.message.reply_text(
        "Привет 👋\n\nЧто делаем?",
        reply_markup=get_main_keyboard()
    )


async def register(update: Update, context) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"Твой ID: {user_id}\n\nДобавь в Railway Variables:\nOWNER_ID = {user_id}"
    )


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
        await query.edit_message_text(
            "Окей, помогу составить ответ клиенту.\n\nЧто за ситуация?"
        )

    elif data == "mode_design":
        USER_MODE[user_id] = "design"
        CONVERSATIONS[user_id] = []
        await query.edit_message_text(
            "Окей, напишем аргументацию к дизайну.\n\nЧто за проект?"
        )

    elif data == "back_main":
        USER_MODE[user_id] = ""
        CONVERSATIONS[user_id] = []
        await query.edit_message_text(
            "Что делаем?",
            reply_markup=get_main_keyboard()
        )


async def handle_photo(update: Update, context) -> None:
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    mode = USER_MODE.get(user_id, "")
    if not mode:
        await update.message.reply_text(
            "Выбери что делаем 👇",
            reply_markup=get_main_keyboard()
        )
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []

    # Скачиваем фото и конвертируем в base64
    import base64
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")

    caption = update.message.caption or "Скрин переписки с клиентом"

    # Формируем сообщение с картинкой
    user_content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image_data
            }
        },
        {
            "type": "text",
            "text": caption
        }
    ]

    CONVERSATIONS[user_id].append({"role": "user", "content": user_content})
    history = CONVERSATIONS[user_id][-10:]
    system = BRIEF_SYSTEM if mode == "brief" else DESIGN_SYSTEM

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=system,
            messages=history
        )
        response = message.content[0].text
        # Убираем markdown звёздочки
        response = response.replace("**", "").replace("__", "")
        CONVERSATIONS[user_id].append({"role": "assistant", "content": response})

        back_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("← Главное меню", callback_data="back_main")]
        ])
        await update.message.reply_text(response, reply_markup=back_keyboard)

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

    if not mode:
        await update.message.reply_text(
            "Выбери что делаем 👇",
            reply_markup=get_main_keyboard()
        )
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []

    CONVERSATIONS[user_id].append({"role": "user", "content": user_text})
    history = CONVERSATIONS[user_id][-20:]

    system = BRIEF_SYSTEM if mode == "brief" else DESIGN_SYSTEM

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=system,
            messages=history
        )
        response = message.content[0].text
        # Убираем markdown звёздочки
        response = response.replace("**", "").replace("__", "")
        CONVERSATIONS[user_id].append({"role": "assistant", "content": response})

        back_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("← Главное меню", callback_data="back_main")]
        ])

        await update.message.reply_text(response, reply_markup=back_keyboard)

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
