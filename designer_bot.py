import os
import re
import json
import base64
import random
import logging
import anthropic
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATA_FILE = "/tmp/bot_data.json"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

USER_MODE: dict[int, str] = {}
CONVERSATIONS: dict[int, list[dict]] = {}
DESIGN_IMAGE: dict[int, str] = {}
DESIGN_ANSWERS: dict[int, dict] = {}
DESIGN_QUESTIONS: dict[int, list] = {}
DESIGN_STEP: dict[int, int] = {}
DESIGN_VARIANTS: dict[int, list] = {}

BRIEF_ANSWERS: dict[int, dict] = {}
BRIEF_STEP: dict[int, int] = {}
BRIEF_VARIANTS: dict[int, list] = {}

BRIEF_QUESTIONS = [
    {
        "key": "situation",
        "question": "Что за ситуация?",
        "options": [["Новый проект", "Правки"], ["Цена", "Сроки"], ["Другое"]]
    },
    {
        "key": "project_type",
        "question": "Тип проекта?",
        "options": [["Креатив", "Презентация"], ["Логотип", "Брендинг"], ["Другое"]]
    },
    {
        "key": "price",
        "question": "Сколько стоит работа?",
        "options": [["До $100", "$100-300"], ["$300-500", "Больше $500"]]
    },
    {
        "key": "deadline",
        "question": "Какие сроки?",
        "options": [["1-2 дня", "3-5 дней"], ["1-2 недели", "Больше"]]
    },
    {
        "key": "revisions",
        "question": "Сколько правок включено?",
        "options": [["1 правка", "2 правки"], ["3 правки", "Без ограничений"]]
    },
    {
        "key": "prepayment",
        "question": "Есть предоплата?",
        "options": [["50%", "100%"], ["Без предоплаты"]]
    },
    {
        "key": "message",
        "question": "Что нужно сказать клиенту?",
        "options": [["Обозначить условия", "Напомнить о себе"], ["Закрыть сделку", "Отказать вежливо"]]
    },
]

THINKING_PHRASES = [
    "Анализирую...",
    "Смотрю на детали...",
    "Думаю как подать лучше...",
    "Готовлю аргументы...",
    "Вникаю в дизайн...",
    "Собираю мысли...",
    "Разбираюсь...",
    "Готовлю красоту...",
]

WELCOME_TEXT = """Привет 👋

Я помогаю работать с клиентами быстрее и чище.

Составлю ответ на любую ситуацию и аргументирую дизайн так, чтобы клиент понял и согласился.

Что делаем?"""

ARTEM_STYLE = """Твоя задача — писать так, будто ты Артём, молодой диджитал-дизайнер с сильным чувством вкуса и опытом работы с клиентами.

Стиль:
— Простой разговорный язык, коротко и по делу.
— Короткие предложения. Никакой воды.
— Разговорные слова: "короче", "смотри", "по сути", "честно".
— Никаких клише: "уникальный подход", "выведите бизнес на новый уровень", "уверенное предложение от тех кто знает своё дело".
— Никаких эмодзи без необходимости.
— Текст должен звучать как живой человек, а не нейросеть.
— Используй дефис только как знак переноса. В тексте между словами всегда используй обычный дефис -, не тире.

Примеры фраз: "Смотри, тут задача была...", "Я пошёл по пути...", "Это работает потому что...", "По сути здесь важно..."

Главное: коротко, живо, без пафоса."""

BRIEF_SYSTEM = """Ты помогаешь дизайнеру сформулировать ответ клиенту. Задавай вопросы по одному.

Вопросы:
1. Что за ситуация - новый проект, правки, цена, сроки?
2. Какой тип проекта?
3. Сколько стоит?
4. Какие сроки?
5. Сколько правок включено?
6. Есть ли предоплата?
7. Что именно нужно сказать клиенту?

Когда собрал всё - напиши готовый ответ клиенту.

""" + ARTEM_STYLE


# ── Хранилище данных ──────────────────────────────────────────────────────────

def load_data() -> dict:
    try:
        if Path(DATA_FILE).exists():
            return json.loads(Path(DATA_FILE).read_text())
    except Exception:
        pass
    return {"keys": {}, "users": {}}


def save_data(data: dict):
    try:
        Path(DATA_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"Save error: {e}")


def generate_key() -> str:
    import string
    chars = string.ascii_uppercase + string.digits
    return "ART-" + "".join(random.choices(chars, k=8))


# ── Клавиатуры ────────────────────────────────────────────────────────────────

def get_bottom_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("💬 Ответить клиенту"), KeyboardButton("🎨 Аргументация")],
            [KeyboardButton("🗑 Очистить")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Отвечаем клиенту", callback_data="mode_brief")],
        [InlineKeyboardButton("🎨 Аргументация клиенту", callback_data="mode_design")]
    ])


def get_back_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("← Главное меню", callback_data="back_main")
    ]])


def get_variants_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="pick_0"),
            InlineKeyboardButton("2", callback_data="pick_1"),
            InlineKeyboardButton("3", callback_data="pick_2"),
        ],
        [InlineKeyboardButton("🔄 Обновить варианты", callback_data="refresh_variants")]
    ])


def get_brief_variants_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1", callback_data="bpick_0"),
            InlineKeyboardButton("2", callback_data="bpick_1"),
            InlineKeyboardButton("3", callback_data="bpick_2"),
        ],
        [InlineKeyboardButton("🔄 Обновить варианты", callback_data="brefresh")]
    ])


def get_brief_question_keyboard(options: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(opt, callback_data=f"bq_{opt}") for opt in row] for row in options]
    rows.append([InlineKeyboardButton("✍️ Опишу сам", callback_data="bq_custom")])
    return InlineKeyboardMarkup(rows)


def get_volume_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Коротко (3-5 строк)", callback_data="vol_short"),
        InlineKeyboardButton("Развёрнуто", callback_data="vol_long")
    ]])


def get_admin_keyboard(data: dict):
    buttons = []
    users = data.get("users", {})
    for uid, info in users.items():
        name = info.get("name", uid)
        status = "✅" if info.get("active") else "❌"
        buttons.append([
            InlineKeyboardButton(f"{status} {name}", callback_data=f"noop"),
            InlineKeyboardButton("Отключить" if info.get("active") else "Включить",
                                 callback_data=f"toggle_{uid}")
        ])
    buttons.append([InlineKeyboardButton("➕ Создать ключ", callback_data="gen_key")])
    return InlineKeyboardMarkup(buttons)


# ── Утилиты ───────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    return text.replace("**", "").replace("__", "")


def is_owner(user_id: int) -> bool:
    return OWNER_ID == 0 or user_id == OWNER_ID


def is_allowed(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    data = load_data()
    user = data["users"].get(str(user_id))
    return user is not None and user.get("active", False)


# ── Хендлеры ─────────────────────────────────────────────────────────────────

async def start(update: Update, context) -> None:
    user_id = update.effective_user.id

    if is_owner(user_id):
        USER_MODE[user_id] = ""
        CONVERSATIONS[user_id] = []
        await update.message.reply_text("👋", reply_markup=get_bottom_keyboard())
        await update.message.reply_text(WELCOME_TEXT, reply_markup=get_main_keyboard())
        return

    data = load_data()
    user = data["users"].get(str(user_id))

    if user and user.get("active"):
        USER_MODE[user_id] = ""
        CONVERSATIONS[user_id] = []
        await update.message.reply_text("👋", reply_markup=get_bottom_keyboard())
        await update.message.reply_text(WELCOME_TEXT, reply_markup=get_main_keyboard())
    else:
        USER_MODE[user_id] = "waiting_key"
        await update.message.reply_text("Привет 👋\n\nВведите ключ доступа 🔑")


async def admin(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    data = load_data()
    keys = data.get("keys", {})
    active_keys = [f"`{k}`" for k, v in keys.items() if not v.get("used")]
    keys_text = "\n".join(active_keys) if active_keys else "нет активных ключей"
    await update.message.reply_text(
        f"👤 Админ панель\n\nАктивные ключи:\n{keys_text}",
        reply_markup=get_admin_keyboard(data),
        parse_mode="Markdown"
    )


async def register(update: Update, context) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"Твой ID: `{user_id}`\n\nДобавь в Railway Variables:\nOWNER_ID = {user_id}",
        parse_mode="Markdown"
    )


async def handle_callback(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data_str = query.data

    if data_str == "noop":
        return

    if data_str == "gen_key" and is_owner(user_id):
        data = load_data()
        key = generate_key()
        data["keys"][key] = {"used": False}
        save_data(data)
        await query.edit_message_text(
            f"✅ Новый ключ создан:\n\n`{key}`\n\nОтправь его пользователю.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← Назад", callback_data="back_admin")
            ]]),
            parse_mode="Markdown"
        )
        return

    if data_str.startswith("toggle_") and is_owner(user_id):
        uid = data_str.replace("toggle_", "")
        data = load_data()
        if uid in data["users"]:
            data["users"][uid]["active"] = not data["users"][uid].get("active", True)
            save_data(data)
        await query.edit_message_text(
            "👤 Админ панель",
            reply_markup=get_admin_keyboard(data)
        )
        return

    if data_str == "back_admin" and is_owner(user_id):
        data = load_data()
        await query.edit_message_text(
            "👤 Админ панель",
            reply_markup=get_admin_keyboard(data)
        )
        return

    if not is_allowed(user_id):
        await query.edit_message_text("Нет доступа.")
        return

    if data_str == "mode_brief":
        USER_MODE[user_id] = "brief_questions"
        BRIEF_ANSWERS[user_id] = {}
        BRIEF_STEP[user_id] = 0
        q = BRIEF_QUESTIONS[0]
        await query.edit_message_text(
            q["question"],
            reply_markup=get_brief_question_keyboard(q["options"])
        )

    elif data_str == "mode_design":
        USER_MODE[user_id] = "design_wait_photo"
        DESIGN_IMAGE[user_id] = ""
        DESIGN_ANSWERS[user_id] = {}
        DESIGN_QUESTIONS[user_id] = []
        DESIGN_STEP[user_id] = 0
        await query.edit_message_text("Прикрепи скрин дизайна 🖼")

    elif data_str == "back_main":
        USER_MODE[user_id] = ""
        CONVERSATIONS[user_id] = []
        await query.edit_message_text(WELCOME_TEXT, reply_markup=get_main_keyboard())

    elif data_str.startswith("dq_"):
        answer = data_str[3:]
        step = DESIGN_STEP.get(user_id, 0)
        questions = DESIGN_QUESTIONS.get(user_id, [])
        answers = DESIGN_ANSWERS.get(user_id, {})
        if step < len(questions):
            answers[questions[step]["question"]] = answer
            DESIGN_ANSWERS[user_id] = answers
            DESIGN_STEP[user_id] = step + 1
            await _ask_next_design_question(query, user_id, context)

    elif data_str == "vol_short":
        DESIGN_ANSWERS.setdefault(user_id, {})["volume"] = "коротко (3-5 строк)"
        await query.edit_message_text(random.choice(THINKING_PHRASES))
        await _generate_argumentation(user_id, context, query.message.chat_id)

    elif data_str == "vol_long":
        DESIGN_ANSWERS.setdefault(user_id, {})["volume"] = "развёрнуто"
        await query.edit_message_text(random.choice(THINKING_PHRASES))
        await _generate_argumentation(user_id, context, query.message.chat_id)

    elif data_str.startswith("pick_"):
        idx = int(data_str.replace("pick_", ""))
        variants = DESIGN_VARIANTS.get(user_id, [])
        if idx < len(variants):
            await query.edit_message_text(variants[idx], reply_markup=get_back_keyboard())

    elif data_str == "refresh_variants":
        await query.edit_message_text(random.choice(THINKING_PHRASES))
        await _generate_argumentation(user_id, context, query.message.chat_id, refresh=True)

    elif data_str.startswith("bq_"):
        answer = data_str[3:]
        if answer == "custom":
            USER_MODE[user_id] = "brief_custom_input"
            step = BRIEF_STEP.get(user_id, 0)
            q = BRIEF_QUESTIONS[step] if step < len(BRIEF_QUESTIONS) else None
            hint = q["question"] if q else "Опиши своими словами:"
            await query.edit_message_text(f"{hint}\n\nНапиши свой вариант:")
        else:
            step = BRIEF_STEP.get(user_id, 0)
            answers = BRIEF_ANSWERS.get(user_id, {})
            if step < len(BRIEF_QUESTIONS):
                answers[BRIEF_QUESTIONS[step]["key"]] = answer
                BRIEF_ANSWERS[user_id] = answers
                BRIEF_STEP[user_id] = step + 1
                await _ask_next_brief_question(query, user_id, context)

    elif data_str.startswith("bpick_"):
        idx = int(data_str.replace("bpick_", ""))
        variants = BRIEF_VARIANTS.get(user_id, [])
        if idx < len(variants):
            await query.edit_message_text(variants[idx], reply_markup=get_back_keyboard())

    elif data_str == "brefresh":
        await query.edit_message_text(random.choice(THINKING_PHRASES))
        await _generate_brief_response(user_id, context, query.message.chat_id, refresh=True)


async def _ask_next_design_question(query_or_message, user_id: int, context):
    step = DESIGN_STEP.get(user_id, 0)
    questions = DESIGN_QUESTIONS.get(user_id, [])

    if step >= len(questions):
        text = "Какой объём аргументации?"
        keyboard = get_volume_keyboard()
        if hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(text, reply_markup=keyboard)
        else:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        return

    q = questions[step]
    rows = [[InlineKeyboardButton(opt, callback_data=f"dq_{opt}") for opt in row] for row in q["options"]]
    rows.append([InlineKeyboardButton("🎯 Определи сам", callback_data="dq_auto")])
    keyboard = InlineKeyboardMarkup(rows)
    text = q["question"] + "\n\n(или напиши свой вариант)"

    if hasattr(query_or_message, 'edit_message_text'):
        await query_or_message.edit_message_text(text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)


async def _generate_argumentation(user_id: int, context, chat_id: int, refresh: bool = False):
    image_data = DESIGN_IMAGE.get(user_id, "")
    answers = DESIGN_ANSWERS.get(user_id, {})
    volume = answers.get("volume", "коротко")
    answers_text = "\n".join([f"- {k}: {v}" for k, v in answers.items() if k != "volume"])

    system = f"""Ты пишешь аргументацию к дизайну от лица дизайнера для клиента.
Объём: {volume}.
Контекст: {answers_text}

Сгенерируй РОВНО 3 разных варианта аргументации. Каждый должен отличаться по подаче и акцентам.
Верни ТОЛЬКО JSON без markdown:
["вариант 1", "вариант 2", "вариант 3"]

""" + ARTEM_STYLE

    seed = f"вариация {random.randint(1000,9999)}" if refresh else "основная генерация"
    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
            {"type": "text", "text": f"Напиши 3 варианта. Объём: {volume}. Контекст:\n{answers_text}\n{seed}"}
        ]
    }]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(model="claude-sonnet-4-5", max_tokens=2000, system=system, messages=messages)
        raw = re.sub(r'```json|```', '', message.content[0].text.strip()).strip()
        variants = json.loads(raw)
        variants = [clean_text(v) for v in variants]
        DESIGN_VARIANTS[user_id] = variants

        preview = ""
        for i, v in enumerate(variants, 1):
            short = v[:120] + "..." if len(v) > 120 else v
            preview += f"*{i}.*\n{short}\n\n"

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Готово, вот 3 варианта:\n\n{preview}Выбери или обнови:",
            reply_markup=get_variants_keyboard(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Что-то пошло не так, попробуй снова.")


async def _ask_next_brief_question(query_or_message, user_id: int, context):
    step = BRIEF_STEP.get(user_id, 0)

    if step >= len(BRIEF_QUESTIONS):
        USER_MODE[user_id] = "brief_generating"
        text = random.choice(THINKING_PHRASES)
        chat_id = user_id
        if hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(text)
            chat_id = query_or_message.message.chat_id
        else:
            msg = await context.bot.send_message(chat_id=user_id, text=text)
            chat_id = msg.chat_id
        await _generate_brief_response(user_id, context, chat_id)
        return

    q = BRIEF_QUESTIONS[step]
    text = q["question"]
    keyboard = get_brief_question_keyboard(q["options"])

    if hasattr(query_or_message, 'edit_message_text'):
        await query_or_message.edit_message_text(text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)


async def _generate_brief_response(user_id: int, context, chat_id: int, refresh: bool = False):
    answers = BRIEF_ANSWERS.get(user_id, {})
    answers_text = "\n".join([f"- {k}: {v}" for k, v in answers.items()])
    seed = f"вариация {random.randint(1000,9999)}" if refresh else "основная генерация"

    system = f"""Ты пишешь ответ клиенту от лица дизайнера.

Данные:
{answers_text}

Сгенерируй РОВНО 3 разных варианта ответа клиенту. Каждый отличается по тону и подаче.
Верни ТОЛЬКО JSON без markdown:
["вариант 1", "вариант 2", "вариант 3"]

""" + ARTEM_STYLE

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": f"Напиши 3 варианта ответа клиенту. {seed}"}]
        )
        raw = re.sub(r'```json|```', '', message.content[0].text.strip()).strip()
        variants = json.loads(raw)
        variants = [clean_text(v) for v in variants]
        BRIEF_VARIANTS[user_id] = variants

        preview = ""
        for i, v in enumerate(variants, 1):
            short = v[:120] + "..." if len(v) > 120 else v
            preview += f"*{i}.*\n{short}\n\n"

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Готово, вот 3 варианта:\n\n{preview}Выбери или обнови:",
            reply_markup=get_brief_variants_keyboard(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error brief: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Что-то пошло не так, попробуй снова.")


async def handle_photo(update: Update, context) -> None:
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        return

    mode = USER_MODE.get(user_id, "")

    if mode == "design_wait_photo":
        thinking_msg = await update.message.reply_text(random.choice(THINKING_PHRASES))

        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        DESIGN_IMAGE[user_id] = image_data

        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            message = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=500,
                system="""Анализируй дизайн и сгенерируй 2-3 уточняющих вопроса.
Верни ТОЛЬКО JSON без markdown:
[{"question": "Вопрос?", "options": [["Вариант 1", "Вариант 2"], ["Вариант 3"]]}]
Вопросы конкретные под этот дизайн. Варианты короткие, 1-3 слова. Максимум 2 в ряду.""",
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": "Сгенерируй вопросы для аргументации."}
                ]}]
            )
            raw = re.sub(r'```json|```', '', message.content[0].text.strip()).strip()
            DESIGN_QUESTIONS[user_id] = json.loads(raw)
            DESIGN_STEP[user_id] = 0
            USER_MODE[user_id] = "design_questions"
        except Exception as e:
            logger.error(f"Error analyzing: {e}")
            DESIGN_QUESTIONS[user_id] = []
            DESIGN_STEP[user_id] = 0
            USER_MODE[user_id] = "design_questions"

        try:
            await thinking_msg.delete()
        except Exception:
            pass

        await _ask_next_design_question(update.message, user_id, context)
        return

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

    CONVERSATIONS[user_id].append({"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
        {"type": "text", "text": caption}
    ]})

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1000, system=BRIEF_SYSTEM,
            messages=CONVERSATIONS[user_id][-10:]
        )
        response = clean_text(message.content[0].text)
        CONVERSATIONS[user_id].append({"role": "assistant", "content": response})
        await update.message.reply_text(response, reply_markup=get_back_keyboard())
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй снова.")


async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text
    if not user_text:
        return

    mode = USER_MODE.get(user_id, "")

    # Ввод ключа доступа
    if mode == "waiting_key":
        data = load_data()
        key = user_text.strip().upper()
        if key in data["keys"] and not data["keys"][key].get("used"):
            data["keys"][key]["used"] = True
            name = update.effective_user.first_name or str(user_id)
            data["users"][str(user_id)] = {"active": True, "name": name, "key": key}
            save_data(data)
            USER_MODE[user_id] = ""
            await update.message.reply_text(
                f"✅ Доступ открыт!\n\n{WELCOME_TEXT}",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text("❌ Неверный ключ. Попробуй ещё раз или обратись к администратору.")
        return

    if not is_allowed(user_id):
        USER_MODE[user_id] = "waiting_key"
        await update.message.reply_text("Введите ключ доступа 🔑")
        return

    # Обработка нижних кнопок
    if user_text == "🗑 Очистить":
        USER_MODE[user_id] = ""
        CONVERSATIONS[user_id] = []
        BRIEF_ANSWERS[user_id] = {}
        DESIGN_ANSWERS[user_id] = {}
        await update.message.reply_text(WELCOME_TEXT, reply_markup=get_main_keyboard())
        return

    if user_text == "💬 Ответить клиенту":
        USER_MODE[user_id] = "brief_questions"
        BRIEF_ANSWERS[user_id] = {}
        BRIEF_STEP[user_id] = 0
        q = BRIEF_QUESTIONS[0]
        await update.message.reply_text(q["question"], reply_markup=get_brief_question_keyboard(q["options"]))
        return

    if user_text == "🎨 Аргументация":
        USER_MODE[user_id] = "design_wait_photo"
        DESIGN_IMAGE[user_id] = ""
        DESIGN_ANSWERS[user_id] = {}
        DESIGN_QUESTIONS[user_id] = []
        DESIGN_STEP[user_id] = 0
        await update.message.reply_text("Прикрепи скрин дизайна 🖼")
        return

    if not mode or mode == "design_wait_photo":
        await update.message.reply_text("Выбери что делаем 👇", reply_markup=get_main_keyboard())
        return

    if mode == "design_questions":
        step = DESIGN_STEP.get(user_id, 0)
        questions = DESIGN_QUESTIONS.get(user_id, [])
        answers = DESIGN_ANSWERS.get(user_id, {})
        if step < len(questions):
            answers[questions[step]["question"]] = user_text
            DESIGN_ANSWERS[user_id] = answers
            DESIGN_STEP[user_id] = step + 1
            await _ask_next_design_question(update.message, user_id, context)
        return

    if mode == "brief_questions":
        await update.message.reply_text("Используй кнопки или нажми ✍️ Опишу сам")
        return

    if mode == "brief_custom_input":
        step = BRIEF_STEP.get(user_id, 0)
        answers = BRIEF_ANSWERS.get(user_id, {})
        if step < len(BRIEF_QUESTIONS):
            answers[BRIEF_QUESTIONS[step]["key"]] = user_text
            BRIEF_ANSWERS[user_id] = answers
            BRIEF_STEP[user_id] = step + 1
            USER_MODE[user_id] = "brief_questions"
            await _ask_next_brief_question(update.message, user_id, context)
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []

    CONVERSATIONS[user_id].append({"role": "user", "content": user_text})

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1000, system=BRIEF_SYSTEM,
            messages=CONVERSATIONS[user_id][-20:]
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
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
