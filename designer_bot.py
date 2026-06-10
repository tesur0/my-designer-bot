import os
import re
import json
import base64
import random
import logging
import anthropic
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATA_FILE = "/tmp/bot_data.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

USER_MODE: dict[int, str] = {}
DESIGN_IMAGE: dict[int, str] = {}
DESIGN_ANSWERS: dict[int, dict] = {}
DESIGN_QUESTIONS: dict[int, list] = {}
DESIGN_STEP: dict[int, int] = {}
DESIGN_VARIANTS: dict[int, list] = {}
BRIEF_ANSWERS: dict[int, dict] = {}
BRIEF_STEP: dict[int, int] = {}
BRIEF_VARIANTS: dict[int, list] = {}

THINKING = [
    "✦ Анализирую...",
    "✦ Смотрю на детали...",
    "✦ Собираю мысли...",
    "✦ Готовлю варианты...",
    "✦ Вникаю в дизайн...",
    "✦ Думаю как подать...",
]

WELCOME = (
    "✦ Привет!\n\n"
    "Я помогаю работать с клиентами быстрее.\n\n"
    "💬  Составлю ответ на любую ситуацию\n"
    "🎨  Аргументирую дизайн так, чтобы клиент понял\n\n"
    "Что делаем?"
)

ARTEM_STYLE = """Пиши от лица дизайнера — живо, коротко, без воды и пафоса.

Правила:
— Простой разговорный язык
— Короткие предложения
— Слова: "смотри", "по сути", "короче", "честно"
— Никаких клише: "уникальный подход", "новый уровень"
— Никаких эмодзи в тексте
— Дефис только как дефис, не тире
— Без звёздочек и форматирования

Главное: живо и по делу."""

BRIEF_QS = [
    {"key": "situation", "q": "Что за ситуация?",
     "opts": [["🆕 Новый проект", "✏️ Правки"], ["💰 Цена", "⏰ Сроки"], ["📋 Другое"]]},
    {"key": "type", "q": "Тип проекта?",
     "opts": [["🎯 Креатив", "📊 Презентация"], ["✏️ Логотип", "💎 Брендинг"], ["📁 Другое"]]},
    {"key": "price", "q": "Сколько стоит?",
     "opts": [["До $100", "$100–300"], ["$300–500", "$500+"]]},
    {"key": "deadline", "q": "Сроки?",
     "opts": [["1–2 дня", "3–5 дней"], ["1–2 недели", "Дольше"]]},
    {"key": "revisions", "q": "Правки включены?",
     "opts": [["1 правка", "2 правки"], ["3 правки", "Без лимита"]]},
    {"key": "prepay", "q": "Предоплата?",
     "opts": [["50%", "100%"], ["Без предоплаты"]]},
    {"key": "goal", "q": "Что нужно сказать клиенту?",
     "opts": [["📋 Обозначить условия", "🤝 Закрыть сделку"], ["🔔 Напомнить о себе", "🚫 Отказать вежливо"]]},
]


# ── Storage ───────────────────────────────────────────────────────────────────

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
    return "ART-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def is_owner(uid: int) -> bool:
    return OWNER_ID == 0 or uid == OWNER_ID


def is_allowed(uid: int) -> bool:
    if is_owner(uid):
        return True
    u = load_data()["users"].get(str(uid))
    return u is not None and u.get("active", False)


def clean(text: str) -> str:
    return text.replace("**", "").replace("__", "").replace("*", "")


# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬  Ответить клиенту", callback_data="mode_brief")],
        [InlineKeyboardButton("🎨  Аргументация клиенту", callback_data="mode_design")],
    ])


def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠  Главное меню", callback_data="back_main")]
    ])


def kb_after_pick():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️  К вариантам", callback_data="back_variants")],
        [InlineKeyboardButton("🏠  Главное меню", callback_data="back_main")],
    ])


def kb_after_brief_pick():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️  К вариантам", callback_data="back_brief_variants")],
        [InlineKeyboardButton("🏠  Главное меню", callback_data="back_main")],
    ])


def kb_design_variants():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data="pick_0"),
         InlineKeyboardButton("2", callback_data="pick_1"),
         InlineKeyboardButton("3", callback_data="pick_2")],
        [InlineKeyboardButton("🔄  Обновить варианты", callback_data="refresh_design")],
        [InlineKeyboardButton("🏠  Главное меню", callback_data="back_main")],
    ])


def kb_brief_variants():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data="bpick_0"),
         InlineKeyboardButton("2", callback_data="bpick_1"),
         InlineKeyboardButton("3", callback_data="bpick_2")],
        [InlineKeyboardButton("🔄  Обновить варианты", callback_data="refresh_brief")],
        [InlineKeyboardButton("🏠  Главное меню", callback_data="back_main")],
    ])


def kb_brief_q(opts):
    rows = [[InlineKeyboardButton(o, callback_data=f"bq_{o}") for o in row] for row in opts]
    rows.append([InlineKeyboardButton("✍️  Опишу сам", callback_data="bq_custom")])
    return InlineKeyboardMarkup(rows)


def kb_design_q(opts):
    rows = [[InlineKeyboardButton(o, callback_data=f"dq_{o}") for o in row] for row in opts]
    rows.append([InlineKeyboardButton("🎯  Определи сам", callback_data="dq_auto")])
    return InlineKeyboardMarkup(rows)


def kb_volume():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝  Коротко (3–5 строк)", callback_data="vol_short")],
        [InlineKeyboardButton("📄  Развёрнуто", callback_data="vol_long")],
    ])


def kb_admin(data):
    rows = []
    for uid, info in data.get("users", {}).items():
        name = info.get("name", uid)
        icon = "✅" if info.get("active") else "❌"
        label = "Отключить" if info.get("active") else "Включить"
        rows.append([
            InlineKeyboardButton(f"{icon}  {name}", callback_data="noop"),
            InlineKeyboardButton(label, callback_data=f"toggle_{uid}")
        ])
    rows.append([InlineKeyboardButton("➕  Создать ключ", callback_data="gen_key")])
    return InlineKeyboardMarkup(rows)


# ── AI helpers ────────────────────────────────────────────────────────────────

async def gen_design_variants(user_id, context, chat_id, refresh=False):
    img = DESIGN_IMAGE.get(user_id, "")
    ans = DESIGN_ANSWERS.get(user_id, {})
    volume = ans.get("volume", "коротко")
    ctx = "\n".join(f"- {k}: {v}" for k, v in ans.items() if k != "volume")
    seed = f"вариация {random.randint(1000,9999)}" if refresh else "старт"

    system = f"""Напиши ровно 3 разных варианта аргументации дизайна. Каждый — другой акцент и подача.
Объём: {volume}. Контекст: {ctx}
Верни ТОЛЬКО JSON без markdown: ["вариант1","вариант2","вариант3"]
{ARTEM_STYLE}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=2000, system=system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}},
                {"type": "text", "text": f"3 варианта аргументации. {seed}"}
            ]}]
        )
        raw = re.sub(r'```json|```', '', msg.content[0].text.strip()).strip()
        variants = [clean(v) for v in json.loads(raw)]
        DESIGN_VARIANTS[user_id] = variants

        text = "✦ Готово — 3 варианта:\n\n"
        for i, v in enumerate(variants, 1):
            text += f"{i}.\n{v}\n\n"
        text += "Выбери вариант или обнови:"

        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb_design_variants())
    except Exception as e:
        logger.error(f"gen_design error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Что-то пошло не так, попробуй снова.", reply_markup=kb_back_main())


async def gen_brief_variants(user_id, context, chat_id, refresh=False):
    ans = BRIEF_ANSWERS.get(user_id, {})
    ctx = "\n".join(f"- {k}: {v}" for k, v in ans.items())
    seed = f"вариация {random.randint(1000,9999)}" if refresh else "старт"

    system = f"""Напиши ровно 3 разных варианта ответа клиенту. Каждый — другой тон и подача.
Данные: {ctx}
Верни ТОЛЬКО JSON без markdown: ["вариант1","вариант2","вариант3"]
{ARTEM_STYLE}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1500, system=system,
            messages=[{"role": "user", "content": f"3 варианта ответа клиенту. {seed}"}]
        )
        raw = re.sub(r'```json|```', '', msg.content[0].text.strip()).strip()
        variants = [clean(v) for v in json.loads(raw)]
        BRIEF_VARIANTS[user_id] = variants

        text = "✦ Готово — 3 варианта:\n\n"
        for i, v in enumerate(variants, 1):
            text += f"{i}.\n{v}\n\n"
        text += "Выбери вариант или обнови:"

        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb_brief_variants())
    except Exception as e:
        logger.error(f"gen_brief error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Что-то пошло не так, попробуй снова.", reply_markup=kb_back_main())


async def ask_design_q(target, user_id, context):
    step = DESIGN_STEP.get(user_id, 0)
    qs = DESIGN_QUESTIONS.get(user_id, [])

    if step >= len(qs):
        text = "📐  Какой объём аргументации?"
        kb = kb_volume()
        if hasattr(target, 'edit_message_text'):
            await target.edit_message_text(text, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)
        return

    q = qs[step]
    rows = [[InlineKeyboardButton(o, callback_data=f"dq_{o}") for o in row] for row in q["options"]]
    rows.append([InlineKeyboardButton("🎯  Определи сам", callback_data="dq_auto")])
    kb = InlineKeyboardMarkup(rows)
    text = q["question"] + "\n\n(или напиши свой вариант)"

    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)


async def ask_brief_q(target, user_id, context):
    step = BRIEF_STEP.get(user_id, 0)

    if step >= len(BRIEF_QS):
        chat_id = target.message.chat_id if hasattr(target, 'edit_message_text') else user_id
        thinking = random.choice(THINKING)
        if hasattr(target, 'edit_message_text'):
            await target.edit_message_text(thinking)
        else:
            await context.bot.send_message(chat_id=user_id, text=thinking)
        await gen_brief_variants(user_id, context, chat_id)
        return

    q = BRIEF_QS[step]
    text = q["q"]
    kb = kb_brief_q(q["opts"])

    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        USER_MODE[uid] = "waiting_key"
        await update.message.reply_text("Привет 👋\n\nВведите ключ доступа 🔑")
        return
    USER_MODE[uid] = ""
    await update.message.reply_text(WELCOME, reply_markup=kb_main())


async def admin_cmd(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_owner(uid):
        return
    data = load_data()
    keys = [f"`{k}`" for k, v in data.get("keys", {}).items() if not v.get("used")]
    keys_text = "\n".join(keys) if keys else "нет активных ключей"
    await update.message.reply_text(
        f"🔧  Панель управления\n\nАктивные ключи:\n{keys_text}",
        reply_markup=kb_admin(data), parse_mode="Markdown"
    )


async def register_cmd(update: Update, context) -> None:
    uid = update.effective_user.id
    await update.message.reply_text(
        f"Твой ID: `{uid}`\n\nДобавь в Railway Variables:\nOWNER_ID = {uid}",
        parse_mode="Markdown"
    )


async def handle_callback(update: Update, context) -> None:
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    d = q.data

    if d == "noop":
        return

    # Admin actions
    if d == "gen_key" and is_owner(uid):
        data = load_data()
        key = generate_key()
        data["keys"][key] = {"used": False}
        save_data(data)
        await q.edit_message_text(
            f"✅  Ключ создан:\n\n`{key}`\n\nОтправь пользователю.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="back_admin")]]),
            parse_mode="Markdown"
        )
        return

    if d.startswith("toggle_") and is_owner(uid):
        target_uid = d[7:]
        data = load_data()
        if target_uid in data["users"]:
            data["users"][target_uid]["active"] = not data["users"][target_uid].get("active", True)
            save_data(data)
        await q.edit_message_text("🔧  Панель управления", reply_markup=kb_admin(data))
        return

    if d == "back_admin" and is_owner(uid):
        data = load_data()
        await q.edit_message_text("🔧  Панель управления", reply_markup=kb_admin(data))
        return

    if not is_allowed(uid):
        await q.edit_message_text("Нет доступа.")
        return

    # Main navigation
    if d == "back_main":
        USER_MODE[uid] = ""
        await q.edit_message_text(WELCOME, reply_markup=kb_main())

    elif d == "mode_brief":
        USER_MODE[uid] = "brief_q"
        BRIEF_ANSWERS[uid] = {}
        BRIEF_STEP[uid] = 0
        await ask_brief_q(q, uid, context)

    elif d == "mode_design":
        USER_MODE[uid] = "design_wait_photo"
        DESIGN_IMAGE[uid] = ""
        DESIGN_ANSWERS[uid] = {}
        DESIGN_QUESTIONS[uid] = []
        DESIGN_STEP[uid] = 0
        await q.edit_message_text("🖼  Прикрепи скрин дизайна")

    # Brief questions
    elif d.startswith("bq_"):
        answer = d[3:]
        if answer == "custom":
            USER_MODE[uid] = "brief_custom"
            step = BRIEF_STEP.get(uid, 0)
            hint = BRIEF_QS[step]["q"] if step < len(BRIEF_QS) else "Опиши:"
            await q.edit_message_text(f"{hint}\n\n✍️  Напиши свой вариант:")
        else:
            step = BRIEF_STEP.get(uid, 0)
            ans = BRIEF_ANSWERS.get(uid, {})
            if step < len(BRIEF_QS):
                ans[BRIEF_QS[step]["key"]] = answer
                BRIEF_ANSWERS[uid] = ans
                BRIEF_STEP[uid] = step + 1
                await ask_brief_q(q, uid, context)

    # Brief variants
    elif d.startswith("bpick_"):
        idx = int(d[6:])
        variants = BRIEF_VARIANTS.get(uid, [])
        if idx < len(variants):
            await q.edit_message_text(f"✦ Вариант {idx+1}:\n\n{variants[idx]}", reply_markup=kb_after_brief_pick())

    elif d == "back_brief_variants":
        variants = BRIEF_VARIANTS.get(uid, [])
        if variants:
            text = "✦ Готово — 3 варианта:\n\n"
            for i, v in enumerate(variants, 1):
                text += f"{i}.\n{v}\n\n"
            text += "Выбери вариант или обнови:"
            await q.edit_message_text(text, reply_markup=kb_brief_variants())

    elif d == "refresh_brief":
        await q.edit_message_text(random.choice(THINKING))
        await gen_brief_variants(uid, context, q.message.chat_id, refresh=True)

    # Design questions
    elif d.startswith("dq_"):
        answer = d[3:]
        step = DESIGN_STEP.get(uid, 0)
        qs = DESIGN_QUESTIONS.get(uid, [])
        ans = DESIGN_ANSWERS.get(uid, {})
        if step < len(qs):
            ans[qs[step]["question"]] = answer
            DESIGN_ANSWERS[uid] = ans
            DESIGN_STEP[uid] = step + 1
            await ask_design_q(q, uid, context)

    elif d == "vol_short":
        DESIGN_ANSWERS.setdefault(uid, {})["volume"] = "коротко (3–5 строк)"
        await q.edit_message_text(random.choice(THINKING))
        await gen_design_variants(uid, context, q.message.chat_id)

    elif d == "vol_long":
        DESIGN_ANSWERS.setdefault(uid, {})["volume"] = "развёрнуто"
        await q.edit_message_text(random.choice(THINKING))
        await gen_design_variants(uid, context, q.message.chat_id)

    # Design variants
    elif d.startswith("pick_"):
        idx = int(d[5:])
        variants = DESIGN_VARIANTS.get(uid, [])
        if idx < len(variants):
            await q.edit_message_text(f"✦ Вариант {idx+1}:\n\n{variants[idx]}", reply_markup=kb_after_pick())

    elif d == "back_variants":
        variants = DESIGN_VARIANTS.get(uid, [])
        if variants:
            text = "✦ Готово — 3 варианта:\n\n"
            for i, v in enumerate(variants, 1):
                text += f"{i}.\n{v}\n\n"
            text += "Выбери вариант или обнови:"
            await q.edit_message_text(text, reply_markup=kb_design_variants())

    elif d == "refresh_design":
        await q.edit_message_text(random.choice(THINKING))
        await gen_design_variants(uid, context, q.message.chat_id, refresh=True)


async def handle_photo(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    mode = USER_MODE.get(uid, "")

    if mode != "design_wait_photo":
        await update.message.reply_text("Выбери режим сначала 👇", reply_markup=kb_main())
        return

    thinking_msg = await update.message.reply_text(random.choice(THINKING))

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    img_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
    DESIGN_IMAGE[uid] = img_data

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=500,
            system='Анализируй дизайн и дай 2-3 вопроса. Верни ТОЛЬКО JSON без markdown: [{"question":"?","options":[["A","B"]]}]',
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}},
                {"type": "text", "text": "Вопросы для аргументации."}
            ]}]
        )
        raw = re.sub(r'```json|```', '', msg.content[0].text.strip()).strip()
        DESIGN_QUESTIONS[uid] = json.loads(raw)
    except Exception as e:
        logger.error(f"Photo analyze error: {e}")
        DESIGN_QUESTIONS[uid] = []

    DESIGN_STEP[uid] = 0
    USER_MODE[uid] = "design_q"

    try:
        await thinking_msg.delete()
    except Exception:
        pass

    await ask_design_q(update.message, uid, context)


async def handle_message(update: Update, context) -> None:
    uid = update.effective_user.id
    text = update.message.text
    if not text:
        return

    mode = USER_MODE.get(uid, "")

    if mode == "waiting_key":
        data = load_data()
        key = text.strip().upper()
        if key in data["keys"] and not data["keys"][key].get("used"):
            data["keys"][key]["used"] = True
            name = update.effective_user.first_name or str(uid)
            data["users"][str(uid)] = {"active": True, "name": name, "key": key}
            save_data(data)
            USER_MODE[uid] = ""
            await update.message.reply_text(f"✅  Доступ открыт!\n\n{WELCOME}", reply_markup=kb_main())
        else:
            await update.message.reply_text("❌  Неверный ключ. Попробуй снова или обратись к администратору.")
        return

    if not is_allowed(uid):
        USER_MODE[uid] = "waiting_key"
        await update.message.reply_text("Введите ключ доступа 🔑")
        return

    if not mode or mode == "design_wait_photo":
        await update.message.reply_text(WELCOME, reply_markup=kb_main())
        return

    if mode == "design_q":
        step = DESIGN_STEP.get(uid, 0)
        qs = DESIGN_QUESTIONS.get(uid, [])
        ans = DESIGN_ANSWERS.get(uid, {})
        if step < len(qs):
            ans[qs[step]["question"]] = text
            DESIGN_ANSWERS[uid] = ans
            DESIGN_STEP[uid] = step + 1
            await ask_design_q(update.message, uid, context)
        return

    if mode == "brief_q":
        await update.message.reply_text("Используй кнопки или нажми ✍️ Опишу сам")
        return

    if mode == "brief_custom":
        step = BRIEF_STEP.get(uid, 0)
        ans = BRIEF_ANSWERS.get(uid, {})
        if step < len(BRIEF_QS):
            ans[BRIEF_QS[step]["key"]] = text
            BRIEF_ANSWERS[uid] = ans
            BRIEF_STEP[uid] = step + 1
            USER_MODE[uid] = "brief_q"
            await ask_brief_q(update.message, uid, context)
        return


def main():
    if not ANTHROPIC_API_KEY:
        print("❌ Установи ANTHROPIC_API_KEY")
        return
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("register", register_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
