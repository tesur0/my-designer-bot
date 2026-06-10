import os
import re
import json
import base64
import random
import logging
import tempfile
import anthropic
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DATA_FILE = "/tmp/bot_data.json"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

USER_MODE: dict[int, str] = {}
USER_TONE: dict[int, str] = {}
DESIGN_IMAGE: dict[int, str] = {}
DESIGN_ANSWERS: dict[int, dict] = {}
DESIGN_QUESTIONS: dict[int, list] = {}
DESIGN_STEP: dict[int, int] = {}
DESIGN_VARIANTS: dict[int, list] = {}
BRIEF_ANSWERS: dict[int, dict] = {}
BRIEF_STEP: dict[int, int] = {}
BRIEF_VARIANTS: dict[int, list] = {}
TZ_SOURCE: dict[int, dict] = {}
TZ_PENDING: dict[int, dict] = {}

THINKING = [
    "⏳ Анализирую контекст...",
    "⏳ Собираю сильные аргументы...",
    "⏳ Формулирую варианты...",
    "⏳ Подбираю тон ответа...",
    "⏳ Навожу порядок в мыслях...",
]

WELCOME = (
    "✦ Привет!\n\n"
    "Я помогаю работать с клиентами быстрее.\n\n"
    "💬 Составлю ответ на любую ситуацию\n"
    "🎨 Аргументирую дизайн так, чтобы клиент понял\n\n"
    "🔎 Распознаю хаос в понятное ТЗ\n\n"
    "Что делаем?"
)

TZ_SYSTEM = """Ты — профессиональный проектный менеджер, бизнес-аналитик и арт-директор с опытом работы в дизайне, маркетинге и digital-проектах.

Твоя задача — превращать любой хаотичный ввод пользователя в понятное, структурированное техническое задание.

На вход могут поступать переписки с клиентом, скриншоты, заметки, сообщения из Telegram, референсы, изображения, документы или смешанный формат данных.

Запрещено просто пересказывать информацию.
Нужно выделить главное, убрать мусор, объединить повторяющиеся мысли и привести всё к понятной структуре.
Всегда анализируй материал как опытный менеджер проекта.

Правила:
- Не теряй важные детали.
- Не добавляй информацию от себя.
- Если данные противоречат друг другу — укажи это отдельно.
- Если клиент формулирует мысли эмоционально или хаотично — переведи их на профессиональный язык.
- Если информации мало — не придумывай, а формируй список уточняющих вопросов.
- Пиши кратко, структурированно и без воды.
- Результат должен выглядеть так, будто его подготовил сильный project manager.
- Не используй markdown-таблицы.
- Не используй markdown-заголовки с символом #.
- Не используй звёздочки для выделения.
- Используй аккуратные эмодзи в заголовках разделов, чтобы результат выглядел живее в Telegram."""

TONES = {
    "my": {
        "label": "🎨 Мой стиль",
        "prompt": """Пиши от лица дизайнера — живо, коротко, без воды и пафоса.
— Простой разговорный язык, короткие предложения
— Слова: "смотри", "по сути", "короче", "честно"
— Никаких клише: "уникальный подход", "новый уровень"
— Никаких эмодзи в тексте
— Дефис только как дефис, не тире
— Без звёздочек и форматирования
Главное: живо, по-человечески, без пафоса."""
    },
    "pro": {
        "label": "💼 Профессионально",
        "prompt": """Пиши чётко, структурированно и по делу. Деловой тон без лишних слов.
— Конкретные формулировки без воды
— Уважительно, но без лишней теплоты
— Факты и условия на первом месте
— Без разговорных слов и сленга
— Без эмодзи, звёздочек и форматирования
Главное: чётко, профессионально, по существу."""
    },
    "friendly": {
        "label": "🤝 Дружелюбно",
        "prompt": """Пиши тепло и располагающе, как к хорошему знакомому.
— Мягкий и дружелюбный тон
— Простой язык, без сухости
— Чуть больше эмпатии и заботы
— Без формализма, но уважительно
— Без звёздочек и форматирования
Главное: тепло, по-человечески, располагающе."""
    }
}

USER_TONE: dict[int, str] = {}  # user_id -> tone key

BRIEF_QS = [
    {"key": "situation", "q": "С чем нужно помочь?",
     "opts": [["🆕 Новый проект", "✏️ Правки"], ["💰 Цена", "⏰ Сроки"], ["📋 Другое"]]},
    {"key": "type", "q": "Какой тип проекта?",
     "opts": [["🎯 Креатив", "📊 Презентация"], ["✏️ Логотип", "💎 Брендинг"], ["📁 Другое"]]},
    {"key": "price", "q": "Какой бюджет или стоимость?",
     "opts": [["💵 До $100", "💵 $100–300"], ["💵 $300–500", "💵 $500+"]]},
    {"key": "deadline", "q": "Какие сроки?",
     "opts": [["⚡ 1–2 дня", "⏱ 3–5 дней"], ["📅 1–2 недели", "🧘 Дольше"]]},
    {"key": "revisions", "q": "Сколько правок включено?",
     "opts": [["1️⃣ 1 правка", "2️⃣ 2 правки"], ["3️⃣ 3 правки", "♾ Без лимита"]]},
    {"key": "prepay", "q": "Какая предоплата?",
     "opts": [["50%", "100%"], ["🤝 Без предоплаты"]]},
    {"key": "goal", "q": "Какой нужен результат ответа?",
     "opts": [["📋 Обозначить условия", "🤝 Закрыть сделку"], ["🔔 Напомнить о себе", "🚫 Отказать вежливо"]]},
]

ADMIN_USERS_PER_PAGE = 8


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


def variants_text(title: str, variants: list) -> str:
    text = f"{title}\n\n"
    for i, variant in enumerate(variants, 1):
        text += f"{i}. {variant}\n\n"
    return text + "Выбери вариант ниже или обнови подборку."


def picked_variant_text(index: int, variant: str) -> str:
    return f"Вариант {index}\n\n{variant}"


def compact_short_tz(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    compact = "\n".join(lines[:12])
    if len(compact) > 950:
        compact = compact[:947].rstrip() + "..."
    return compact


async def send_long_message(context, chat_id, text, reply_markup=None):
    limit = 3800
    chunks = []
    rest = text.strip()

    while len(rest) > limit:
        split_at = rest.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = rest.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(rest[:split_at].strip())
        rest = rest[split_at:].strip()

    if rest:
        chunks.append(rest)

    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=markup)


async def transcribe_voice_message(update: Update, context) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    from openai import OpenAI

    media = update.message.voice or update.message.audio
    if not media:
        raise RuntimeError("No voice or audio file found")

    suffix = ".ogg"
    if update.message.audio and update.message.audio.file_name:
        suffix = Path(update.message.audio.file_name).suffix or ".mp3"

    tmp_path = ""
    try:
        tg_file = await context.bot.get_file(media.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name

        await tg_file.download_to_drive(tmp_path)

        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(tmp_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )

        return transcript.text.strip()
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Ответ клиенту", callback_data="mode_brief")],
        [InlineKeyboardButton("🎨 Аргументация дизайна", callback_data="mode_design")],
        [InlineKeyboardButton("🔎 Распознать ТЗ", callback_data="mode_tz")],
    ])


def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад в меню", callback_data="back_main")]
    ])


def kb_after_pick():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← К вариантам", callback_data="back_variants")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_after_brief_pick():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← К вариантам", callback_data="back_brief_variants")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_design_variants():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Вариант 1", callback_data="pick_0"),
         InlineKeyboardButton("Вариант 2", callback_data="pick_1"),
         InlineKeyboardButton("Вариант 3", callback_data="pick_2")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_design")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_brief_variants():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Вариант 1", callback_data="bpick_0"),
         InlineKeyboardButton("Вариант 2", callback_data="bpick_1"),
         InlineKeyboardButton("Вариант 3", callback_data="bpick_2")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_brief")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_brief_q(opts, step=0):
    rows = []
    for row in opts:
        for option in row:
            rows.append([InlineKeyboardButton(option, callback_data=f"bq_{option}")])
    rows.append([InlineKeyboardButton("✍️ Написать свой вариант", callback_data="bq_custom")])
    rows.append([InlineKeyboardButton("✨ Пропустить и собрать самому", callback_data="bq_skip_all")])
    if step > 0:
        rows.append([InlineKeyboardButton("← Назад", callback_data="bq_back")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_design_q(opts, step=0):
    rows = []
    for row in opts:
        for option in row:
            rows.append([InlineKeyboardButton(option, callback_data=f"dq_{option}")])
    rows.append([InlineKeyboardButton("✨ Определи сам", callback_data="dq_auto")])
    if step > 0:
        rows.append([InlineKeyboardButton("← Назад", callback_data="dq_back")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_tone():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 Мой стиль", callback_data="tone_my")],
        [InlineKeyboardButton("💼 Профессионально", callback_data="tone_pro")],
        [InlineKeyboardButton("🤝 Дружелюбно", callback_data="tone_friendly")],
        [InlineKeyboardButton("← Назад", callback_data="tone_back")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_volume():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Коротко", callback_data="vol_short")],
        [InlineKeyboardButton("📄 Развёрнуто", callback_data="vol_long")],
        [InlineKeyboardButton("← Назад", callback_data="back_design_volume")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_custom_back(callback_data):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("← Назад", callback_data=callback_data)],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_tz_input():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_tz_format():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Краткая выжимка", callback_data="tz_format_short")],
        [InlineKeyboardButton("📄 Подробнее", callback_data="tz_format_full")],
        [InlineKeyboardButton("← Отправить другой материал", callback_data="mode_tz")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def kb_after_tz():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Улучшить ТЗ", callback_data="tz_improve")],
        [InlineKeyboardButton("📝 Кратко", callback_data="tz_format_short"),
         InlineKeyboardButton("📄 Подробнее", callback_data="tz_format_full")],
        [InlineKeyboardButton("🔎 Распознать новое ТЗ", callback_data="mode_tz")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")],
    ])


def admin_stats(data):
    users = data.get("users", {})
    keys = data.get("keys", {})
    active_users = sum(1 for info in users.values() if info.get("active"))
    blocked_users = len(users) - active_users
    unused_keys = sum(1 for key in keys.values() if not key.get("used"))
    used_keys = len(keys) - unused_keys

    return {
        "users": len(users),
        "active_users": active_users,
        "blocked_users": blocked_users,
        "keys": len(keys),
        "unused_keys": unused_keys,
        "used_keys": used_keys,
    }


def admin_home_text(data):
    stats = admin_stats(data)
    return (
        "🔧 Админ-панель\n\n"
        f"👥 Пользователи: {stats['users']}\n"
        f"✅ Активные: {stats['active_users']}\n"
        f"⛔ Отключены: {stats['blocked_users']}\n\n"
        f"🔑 Ключи: {stats['keys']}\n"
        f"🟢 Свободные: {stats['unused_keys']}\n"
        f"⚪ Использованные: {stats['used_keys']}"
    )


def admin_users_text(data, page=0):
    users = sorted(
        data.get("users", {}).items(),
        key=lambda item: item[1].get("name", item[0]).lower()
    )
    total_pages = max(1, (len(users) + ADMIN_USERS_PER_PAGE - 1) // ADMIN_USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    if not users:
        return "👥 Пользователи\n\nПока никто не активировал ключ."

    start = page * ADMIN_USERS_PER_PAGE
    visible_users = users[start:start + ADMIN_USERS_PER_PAGE]
    lines = [
        "👥 Пользователи",
        f"Страница {page + 1}/{total_pages}",
        "",
    ]

    for index, (uid, info) in enumerate(visible_users, start + 1):
        icon = "✅" if info.get("active") else "⛔"
        name = info.get("name", uid)
        lines.append(f"{index}. {icon} {name} — {uid}")

    return "\n".join(lines)


def admin_keys_text(data):
    keys = [k for k, v in data.get("keys", {}).items() if not v.get("used")]
    stats = admin_stats(data)

    if not keys:
        keys_text = "нет свободных ключей"
    else:
        keys_text = "\n".join(f"`{key}`" for key in keys[-20:])
        if len(keys) > 20:
            keys_text += f"\n\nПоказаны последние 20 из {len(keys)} свободных ключей."

    return (
        "🔑 Ключи доступа\n\n"
        f"Свободные: {stats['unused_keys']}\n"
        f"Использованные: {stats['used_keys']}\n\n"
        f"{keys_text}"
    )


def kb_admin_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users_0")],
        [InlineKeyboardButton("🔑 Ключи доступа", callback_data="admin_keys")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_home")],
    ])


def kb_admin_users(data, page=0):
    rows = []
    users = sorted(
        data.get("users", {}).items(),
        key=lambda item: item[1].get("name", item[0]).lower()
    )
    total_pages = max(1, (len(users) + ADMIN_USERS_PER_PAGE - 1) // ADMIN_USERS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * ADMIN_USERS_PER_PAGE
    visible_users = users[start:start + ADMIN_USERS_PER_PAGE]

    for uid, info in visible_users:
        name = info.get("name", uid)
        icon = "✅" if info.get("active") else "❌"
        label = "Отключить" if info.get("active") else "Включить"
        rows.append([
            InlineKeyboardButton(f"{icon} {name}", callback_data="noop"),
            InlineKeyboardButton(label, callback_data=f"admin_toggle_{page}_{uid}")
        ])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("←", callback_data=f"admin_users_{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("→", callback_data=f"admin_users_{page + 1}"))
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("🔑 Ключи", callback_data="admin_keys"),
        InlineKeyboardButton("← Меню", callback_data="admin_home")
    ])
    return InlineKeyboardMarkup(rows)


def kb_admin_keys():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕  1", callback_data="admin_gen_keys_1"),
            InlineKeyboardButton("➕  5", callback_data="admin_gen_keys_5"),
            InlineKeyboardButton("➕  10", callback_data="admin_gen_keys_10"),
        ],
        [
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users_0"),
            InlineKeyboardButton("← Меню", callback_data="admin_home"),
        ],
    ])


# ── AI helpers ────────────────────────────────────────────────────────────────

async def gen_design_variants(user_id, context, chat_id, refresh=False):
    img = DESIGN_IMAGE.get(user_id, "")
    ans = DESIGN_ANSWERS.get(user_id, {})
    volume = ans.get("volume", "коротко")
    ctx = "\n".join(f"- {k}: {v}" for k, v in ans.items() if k not in ("volume", "_current_opts"))
    seed = f"вариация {random.randint(1000,9999)}" if refresh else "старт"
    tone = TONES.get(USER_TONE.get(user_id, "my"), TONES["my"])

    system = f"""Напиши ровно 3 разных варианта аргументации дизайна. Каждый — другой акцент и подача.
Объём: {volume}. Контекст: {ctx}
Верни ТОЛЬКО JSON без markdown: ["вариант1","вариант2","вариант3"]
{tone}"""

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

        await context.bot.send_message(
            chat_id=chat_id,
            text=variants_text("Готово. 3 варианта аргументации:", variants),
            reply_markup=kb_design_variants()
        )
    except Exception as e:
        logger.error(f"gen_design error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Не получилось собрать аргументацию. Попробуй обновить варианты или начать заново.",
            reply_markup=kb_back_main()
        )


async def gen_brief_variants(user_id, context, chat_id, refresh=False):
    ans = BRIEF_ANSWERS.get(user_id, {})
    ctx = "\n".join(f"- {k}: {v}" for k, v in ans.items())
    seed = f"вариация {random.randint(1000,9999)}" if refresh else "старт"
    tone = TONES.get(USER_TONE.get(user_id, "my"), TONES["my"])

    system = f"""Напиши ровно 3 разных варианта ответа клиенту. Каждый — другой подача.
Данные: {ctx}
Верни ТОЛЬКО JSON без markdown: ["вариант1","вариант2","вариант3"]
{tone}"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1500, system=system,
            messages=[{"role": "user", "content": f"3 варианта ответа клиенту. {seed}"}]
        )
        raw = re.sub(r'```json|```', '', msg.content[0].text.strip()).strip()
        variants = [clean(v) for v in json.loads(raw)]
        BRIEF_VARIANTS[user_id] = variants

        await context.bot.send_message(
            chat_id=chat_id,
            text=variants_text("Готово. 3 варианта ответа:", variants),
            reply_markup=kb_brief_variants()
        )
    except Exception as e:
        logger.error(f"gen_brief error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Не получилось собрать ответ. Попробуй обновить варианты или начать заново.",
            reply_markup=kb_back_main()
        )


def tz_format_prompt(format_type):
    if format_type == "short":
        return """Сделай УЛЬТРА-КРАТКУЮ выжимку. Это НЕ ТЗ и НЕ подробный разбор.

Жёсткие правила:
- максимум 8 строк всего;
- максимум 900 символов;
- не расписывай детали;
- не делай длинные списки;
- не используй больше 2 пунктов в одном разделе;
- пиши как быстрый конспект для дизайнера.

📝 Краткая выжимка

🎯 Хочет:
одна короткая строка

📦 Имеем:
1-2 коротких пункта: формат / заголовок / CTA / референс / продукт

✅ Нужно:
1-2 главные задачи

🎨 Визуально:
2-4 слова про стиль

❓ Уточнить:
1 самый важный вопрос

Если информации нет — пиши "не указано". Без символа #."""

    return """Сделай подробное структурированное ТЗ.

Формат строго такой:

📌 Проект
Кратко опиши, что именно требуется сделать.

🎯 Основная задача
Опиши главную цель клиента простым и понятным языком.

✅ Что необходимо выполнить
Составь список конкретных задач.

💬 Важные пожелания клиента
Выпиши все пожелания, требования и ограничения.

🎨 Визуальное направление
Определи стиль, настроение, ассоциации и желаемое впечатление от результата.

📎 Материалы от клиента
Перечисли всё, что клиент уже предоставил.

🧩 Чего не хватает
Определи, какой информации недостаточно для полноценной работы.

❓ Вопросы для уточнения
Составь список вопросов, которые необходимо задать клиенту.

⚠️ Потенциальные риски
Укажи противоречия, неопределенности и моменты, которые могут вызвать проблемы в работе.

📄 Итоговое ТЗ
Собери финальное чистое техническое задание в профессиональном виде, готовое для передачи дизайнеру или исполнителю.

Пиши структурированно, но без лишнего текста. Без символа #."""


def tz_improve_prompt():
    return """Сделай не ТЗ, а сообщение клиенту от лица Артема — дизайнера.

Задача: трушно, спокойно и профессионально объяснить клиенту, как можно улучшить ТЗ, чтобы результат получился сильнее.

Формат:

✨ Как можно усилить ТЗ
Короткое вступление от лица дизайнера.

💡 Что я бы предложил добавить
Список конкретных идей и улучшений.

🎯 Что это даст
Коротко объясни пользу для результата: яснее креатив, точнее визуал, меньше правок, понятнее CTA и т.д.

❓ Что нужно уточнить
Список вопросов клиенту.

📝 Сообщение клиенту
Готовый текст, который Артем может отправить клиенту.

Тон: живой, уверенный, без канцелярита, без пафоса. Пиши от первого лица дизайнера. Не добавляй факты от себя. Если данных мало, предлагай уточнения."""


async def gen_tz(user_id, context, chat_id, text="", image_data="", format_type="full"):
    content = []
    if image_data:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}
        })
    content.append({
        "type": "text",
        "text": (
            f"{tz_format_prompt(format_type)}\n\n"
            "Проанализируй материал и подготовь результат в выбранном формате.\n\n"
            f"Материал пользователя:\n{text.strip() if text.strip() else 'Материал передан изображением.'}"
        )
    })

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=700 if format_type == "short" else 3500,
            system=TZ_SYSTEM,
            messages=[{"role": "user", "content": content}]
        )
        result = clean(msg.content[0].text.strip())
        if format_type == "short":
            result = compact_short_tz(result)
        TZ_SOURCE[user_id] = {"text": text, "image": image_data, "format": format_type, "result": result}
        TZ_PENDING[user_id] = {"text": text, "image": image_data}
        USER_MODE[user_id] = ""
        await send_long_message(context, chat_id, result, reply_markup=kb_after_tz())
    except Exception as e:
        logger.error(f"gen_tz error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Не получилось собрать ТЗ. Попробуй отправить материал текстом или более чётким скрином.",
            reply_markup=kb_tz_input()
        )


async def gen_tz_improvements(user_id, context, chat_id):
    source = TZ_SOURCE.get(user_id) or TZ_PENDING.get(user_id)
    if not source:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Сначала распознай ТЗ, а потом я предложу, как его улучшить.",
            reply_markup=kb_tz_input()
        )
        return

    text = source.get("text", "")
    image_data = source.get("image", "")
    result = source.get("result", "")
    content = []
    if image_data:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}
        })
    content.append({
        "type": "text",
        "text": (
            f"{tz_improve_prompt()}\n\n"
            f"Исходный материал:\n{text.strip() if text.strip() else 'Материал был передан изображением.'}\n\n"
            f"Последнее распознанное ТЗ:\n{result.strip() if result.strip() else 'ТЗ ещё не сформировано текстом.'}"
        )
    })

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2500,
            system=TZ_SYSTEM,
            messages=[{"role": "user", "content": content}]
        )
        answer = clean(msg.content[0].text.strip())
        await send_long_message(context, chat_id, answer, reply_markup=kb_after_tz())
    except Exception as e:
        logger.error(f"gen_tz_improvements error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Не получилось подготовить идеи по улучшению ТЗ. Попробуй ещё раз.",
            reply_markup=kb_after_tz()
        )


async def ask_design_q(target, user_id, context):
    step = DESIGN_STEP.get(user_id, 0)
    qs = DESIGN_QUESTIONS.get(user_id, [])

    if step >= len(qs):
        text = "📐 Формат аргументации\n\nВыбери, насколько подробно объяснить дизайн клиенту."
        kb = kb_volume()
        if hasattr(target, 'edit_message_text'):
            await target.edit_message_text(text, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)
        return

    q = qs[step]
    # Сохраняем варианты и используем индексы в callback_data
    all_opts = [opt for row in q["options"] for opt in row]
    DESIGN_ANSWERS.setdefault(user_id, {})["_current_opts"] = all_opts

    rows = []
    idx = 0
    for row in q["options"]:
        for opt in row:
            rows.append([InlineKeyboardButton(opt, callback_data=f"dqi_{idx}")])
            idx += 1
    rows.append([InlineKeyboardButton("✨ Определи сам", callback_data="dq_auto")])
    rows.append([InlineKeyboardButton("⏭ Пропустить вопросы", callback_data="dq_skip_all")])
    if step > 0:
        rows.append([InlineKeyboardButton("← Назад", callback_data="dq_back")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")])
    kb = InlineKeyboardMarkup(rows)
    text = f"🎨 Вопрос {step + 1}/{len(qs)}\n\n{q['question']}\n\nМожно выбрать вариант или написать свой."

    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)


async def ask_brief_q(target, user_id, context):
    step = BRIEF_STEP.get(user_id, 0)

    if step >= len(BRIEF_QS):
        # Спрашиваем тон перед генерацией
        text = "🎭 Тон ответа\n\nВыбери, как должно звучать сообщение клиенту."
        if hasattr(target, 'edit_message_text'):
            await target.edit_message_text(text, reply_markup=kb_tone())
        else:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=kb_tone())
        USER_MODE[user_id] = "brief_tone"
        return

    q = BRIEF_QS[step]
    text = f"💬 Вопрос {step + 1}/{len(BRIEF_QS)}\n\n{q['q']}"
    kb = kb_brief_q(q["opts"], step)

    if hasattr(target, 'edit_message_text'):
        await target.edit_message_text(text, reply_markup=kb)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        USER_MODE[uid] = "waiting_key"
        await update.message.reply_text(
            "Доступ по ключу\n\nОтправь ключ доступа, который выдал администратор.",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    USER_MODE[uid] = ""
    await update.message.reply_text(WELCOME, reply_markup=kb_main())


async def admin_cmd(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_owner(uid):
        return
    data = load_data()
    await update.message.reply_text(
        admin_home_text(data),
        reply_markup=kb_admin_home()
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
    if d == "admin_home" and is_owner(uid):
        data = load_data()
        await q.edit_message_text(
            admin_home_text(data),
            reply_markup=kb_admin_home()
        )
        return

    if d.startswith("admin_users_") and is_owner(uid):
        page = int(d[12:])
        data = load_data()
        await q.edit_message_text(
            admin_users_text(data, page),
            reply_markup=kb_admin_users(data, page)
        )
        return

    if d == "admin_keys" and is_owner(uid):
        data = load_data()
        await q.edit_message_text(
            admin_keys_text(data),
            reply_markup=kb_admin_keys(), parse_mode="Markdown"
        )
        return

    if d.startswith("admin_gen_keys_") and is_owner(uid):
        data = load_data()
        data.setdefault("keys", {})
        count = int(d[15:])

        keys = []
        for _ in range(count):
            key = generate_key()
            while key in data["keys"]:
                key = generate_key()
            data["keys"][key] = {"used": False}
            keys.append(key)

        save_data(data)
        keys_text = "\n".join(f"`{key}`" for key in keys)
        await q.edit_message_text(
            f"Ключи созданы\n\n{keys_text}\n\nОтправь их пользователям для входа.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔑 Все ключи", callback_data="admin_keys")],
                [InlineKeyboardButton("← Меню", callback_data="admin_home")]
            ]),
            parse_mode="Markdown"
        )
        return

    if d.startswith("admin_toggle_") and is_owner(uid):
        parts = d.split("_", 3)
        page = int(parts[2])
        target_uid = parts[3]
        data = load_data()
        if target_uid in data["users"]:
            data["users"][target_uid]["active"] = not data["users"][target_uid].get("active", True)
            save_data(data)
        await q.edit_message_text(
            admin_users_text(data, page),
            reply_markup=kb_admin_users(data, page)
        )
        return

    if not is_allowed(uid):
        await q.edit_message_text("Нет доступа. Отправь ключ доступа через /start.")
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
        await q.edit_message_text(
            "Аргументация дизайна\n\nПрикрепи скрин дизайна. Я задам пару вопросов и соберу варианты объяснения для клиента.",
            reply_markup=kb_back_main()
        )

    elif d == "mode_tz":
        USER_MODE[uid] = "tz_wait_input"
        TZ_SOURCE[uid] = {}
        TZ_PENDING[uid] = {}
        await q.edit_message_text(
            "🔎 Распознать ТЗ\n\n"
            "Пришли хаотичное описание, переписку, заметки или скрин. "
            "Я выделю главное и соберу понятное техническое задание.",
            reply_markup=kb_tz_input()
        )

    elif d == "tz_improve":
        await q.edit_message_text(random.choice(THINKING))
        await gen_tz_improvements(uid, context, q.message.chat_id)

    elif d.startswith("tz_format_"):
        pending = TZ_PENDING.get(uid) or TZ_SOURCE.get(uid)
        if not pending:
            USER_MODE[uid] = "tz_wait_input"
            await q.edit_message_text(
                "🔎 Распознать ТЗ\n\nПришли материал ещё раз, а потом выбери формат результата.",
                reply_markup=kb_tz_input()
            )
            return

        format_type = "short" if d == "tz_format_short" else "full"
        await q.edit_message_text(random.choice(THINKING))
        await gen_tz(
            uid,
            context,
            q.message.chat_id,
            text=pending.get("text", ""),
            image_data=pending.get("image", ""),
            format_type=format_type
        )

    elif d == "bq_back":
        step = max(0, BRIEF_STEP.get(uid, 0) - 1)
        BRIEF_STEP[uid] = step
        BRIEF_ANSWERS.get(uid, {}).pop(BRIEF_QS[step]["key"], None)
        USER_MODE[uid] = "brief_q"
        await ask_brief_q(q, uid, context)

    elif d == "bq_cancel_custom":
        USER_MODE[uid] = "brief_q"
        await ask_brief_q(q, uid, context)

    elif d == "dq_back":
        step = max(0, DESIGN_STEP.get(uid, 0) - 1)
        qs = DESIGN_QUESTIONS.get(uid, [])
        DESIGN_STEP[uid] = step
        if step < len(qs):
            DESIGN_ANSWERS.get(uid, {}).pop(qs[step]["question"], None)
        USER_MODE[uid] = "design_q"
        await ask_design_q(q, uid, context)

    elif d == "back_design_volume":
        qs = DESIGN_QUESTIONS.get(uid, [])
        if qs:
            current_step = DESIGN_STEP.get(uid, 0)
            DESIGN_STEP[uid] = len(qs) - 1 if current_step >= len(qs) else max(0, current_step)
            DESIGN_ANSWERS.get(uid, {}).pop(qs[DESIGN_STEP[uid]]["question"], None)
            USER_MODE[uid] = "design_q"
            await ask_design_q(q, uid, context)
        else:
            USER_MODE[uid] = "design_wait_photo"
            await q.edit_message_text(
                "🎨 Аргументация дизайна\n\nПрикрепи скрин дизайна. Я задам пару вопросов и соберу варианты объяснения для клиента.",
                reply_markup=kb_back_main()
            )

    elif d == "tone_back":
        mode = USER_MODE.get(uid, "")
        if mode == "brief_tone":
            current_step = BRIEF_STEP.get(uid, 0)
            BRIEF_STEP[uid] = max(0, min(current_step, len(BRIEF_QS) - 1))
            BRIEF_ANSWERS.get(uid, {}).pop(BRIEF_QS[BRIEF_STEP[uid]]["key"], None)
            USER_MODE[uid] = "brief_q"
            await ask_brief_q(q, uid, context)
        elif mode == "design_tone":
            USER_MODE[uid] = "design_q"
            await q.edit_message_text(
                "📐 Формат аргументации\n\nВыбери, насколько подробно объяснить дизайн клиенту.",
                reply_markup=kb_volume()
            )
        else:
            await q.edit_message_text(WELCOME, reply_markup=kb_main())

    # Brief questions
    elif d.startswith("bq_"):
        answer = d[3:]
        if answer == "skip_all":
            await q.edit_message_text("🎭 Тон ответа\n\nВыбери, как должно звучать сообщение клиенту.", reply_markup=kb_tone())
            USER_MODE[uid] = "brief_tone"
        elif answer == "custom":
            USER_MODE[uid] = "brief_custom"
            step = BRIEF_STEP.get(uid, 0)
            hint = BRIEF_QS[step]["q"] if step < len(BRIEF_QS) else "Опиши:"
            await q.edit_message_text(
                f"✍️ {hint}\n\nНапиши свой вариант одним сообщением.",
                reply_markup=kb_custom_back("bq_cancel_custom")
            )
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
            await q.edit_message_text(picked_variant_text(idx + 1, variants[idx]), reply_markup=kb_after_brief_pick())

    elif d == "back_brief_variants":
        variants = BRIEF_VARIANTS.get(uid, [])
        if variants:
            await q.edit_message_text(
                variants_text("Готово. 3 варианта ответа:", variants),
                reply_markup=kb_brief_variants()
            )

    elif d == "refresh_brief":
        await q.edit_message_text(random.choice(THINKING))
        await gen_brief_variants(uid, context, q.message.chat_id, refresh=True)

    # Design questions
    elif d.startswith("dqi_"):
        # Ответ по индексу
        idx = int(d[4:])
        opts = DESIGN_ANSWERS.get(uid, {}).get("_current_opts", [])
        answer = opts[idx] if idx < len(opts) else "авто"
        step = DESIGN_STEP.get(uid, 0)
        qs = DESIGN_QUESTIONS.get(uid, [])
        ans = DESIGN_ANSWERS.get(uid, {})
        if step < len(qs):
            ans[qs[step]["question"]] = answer
            DESIGN_ANSWERS[uid] = ans
            DESIGN_STEP[uid] = step + 1
            await ask_design_q(q, uid, context)

    elif d.startswith("dq_"):
        answer = d[3:]
        if answer == "skip_all":
            await q.edit_message_text(
                "Формат аргументации\n\nВыбери, насколько подробно объяснить дизайн клиенту.",
                reply_markup=kb_volume()
            )
        else:
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
        await q.edit_message_text("🎭 Тон аргументации\n\nВыбери, как должно звучать объяснение.", reply_markup=kb_tone())
        USER_MODE[uid] = "design_tone"

    elif d == "vol_long":
        DESIGN_ANSWERS.setdefault(uid, {})["volume"] = "развёрнуто"
        await q.edit_message_text("🎭 Тон аргументации\n\nВыбери, как должно звучать объяснение.", reply_markup=kb_tone())
        USER_MODE[uid] = "design_tone"

    elif d.startswith("tone_"):
        tone_key = d[5:]
        USER_TONE[uid] = tone_key
        mode = USER_MODE.get(uid, "")
        await q.edit_message_text(random.choice(THINKING))
        if mode == "design_tone":
            await gen_design_variants(uid, context, q.message.chat_id)
        elif mode == "brief_tone":
            await gen_brief_variants(uid, context, q.message.chat_id)

    # Design variants
    elif d.startswith("pick_"):
        idx = int(d[5:])
        variants = DESIGN_VARIANTS.get(uid, [])
        if idx < len(variants):
            await q.edit_message_text(picked_variant_text(idx + 1, variants[idx]), reply_markup=kb_after_pick())

    elif d == "back_variants":
        variants = DESIGN_VARIANTS.get(uid, [])
        if variants:
            await q.edit_message_text(
                variants_text("Готово. 3 варианта аргументации:", variants),
                reply_markup=kb_design_variants()
            )

    elif d == "refresh_design":
        await q.edit_message_text(random.choice(THINKING))
        await gen_design_variants(uid, context, q.message.chat_id, refresh=True)


async def handle_photo(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    mode = USER_MODE.get(uid, "")

    if mode == "tz_wait_input":
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        img_data = base64.standard_b64encode(bytes(file_bytes)).decode("utf-8")
        caption = update.message.caption or ""

        TZ_PENDING[uid] = {"text": caption, "image": img_data}
        USER_MODE[uid] = "tz_choose_format"
        await update.message.reply_text(
            "Материал получил.\n\nКак подготовить результат?",
            reply_markup=kb_tz_format()
        )
        return

    if mode != "design_wait_photo":
        await update.message.reply_text("Сначала выбери режим в главном меню.", reply_markup=kb_main())
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
            system="""Ты помогаешь дизайнеру аргументировать работу клиенту.
Посмотри на дизайн и задай 2 вопроса которые помогут написать убедительную аргументацию.
Вопросы должны быть про: цель дизайна, целевую аудиторию, стиль, настроение, контекст использования.
НЕ спрашивай про: технические детали, текст на картинке, даты, цифры, названия.
Варианты ответов должны быть короткими (2-4 слова) и релевантными.
Верни ТОЛЬКО JSON без markdown и пояснений:
[{"question":"Вопрос?","options":[["Вариант А","Вариант Б"],["Вариант В"]]}]""",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}},
                {"type": "text", "text": "Задай 2 вопроса для аргументации этого дизайна."}
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
            await update.message.reply_text(f"Доступ открыт\n\n{WELCOME}", reply_markup=kb_main())
        else:
            await update.message.reply_text("Ключ не подошёл. Проверь написание или попроси новый ключ у администратора.")
        return

    if not is_allowed(uid):
        USER_MODE[uid] = "waiting_key"
        await update.message.reply_text("Отправь ключ доступа, чтобы продолжить.")
        return

    if mode == "design_wait_photo":
        await update.message.reply_text(
            "Пришли скрин дизайна изображением. После этого я задам уточняющие вопросы.",
            reply_markup=kb_back_main()
        )
        return

    if not mode:
        await update.message.reply_text(WELCOME, reply_markup=kb_main())
        return

    if mode == "tz_wait_input":
        TZ_PENDING[uid] = {"text": text, "image": ""}
        USER_MODE[uid] = "tz_choose_format"
        await update.message.reply_text(
            "Материал получил.\n\nКак подготовить результат?",
            reply_markup=kb_tz_format()
        )
        return

    if mode == "tz_choose_format":
        await update.message.reply_text(
            "Выбери формат кнопкой ниже.",
            reply_markup=kb_tz_format()
        )
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
        await update.message.reply_text("Выбери вариант кнопкой или нажми «Написать свой вариант».")
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


async def handle_unsupported_input(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    mode = USER_MODE.get(uid, "")
    if mode == "tz_wait_input":
        await update.message.reply_text(
            "Пока я лучше всего работаю с текстом и скринами.\n\n"
            "Если это голосовое или документ, пришли короткую расшифровку, текст из файла или скрин содержимого.",
            reply_markup=kb_tz_input()
        )
    else:
        await update.message.reply_text("Выбери режим в главном меню.", reply_markup=kb_main())


async def handle_voice(update: Update, context) -> None:
    uid = update.effective_user.id
    if not is_allowed(uid):
        return

    mode = USER_MODE.get(uid, "")
    if mode != "tz_wait_input":
        await update.message.reply_text(
            "Голосовое можно распознать в режиме «🔎 Распознать ТЗ».",
            reply_markup=kb_main()
        )
        return

    thinking_msg = await update.message.reply_text("🎧 Распознаю голосовое...")

    try:
        transcript = await transcribe_voice_message(update, context)
        if not transcript:
            raise RuntimeError("Empty transcript")

        TZ_PENDING[uid] = {"text": f"Расшифровка голосового сообщения:\n{transcript}", "image": ""}
        USER_MODE[uid] = "tz_choose_format"
        await update.message.reply_text(
            "Голосовое распознал.\n\nКак подготовить результат?",
            reply_markup=kb_tz_format()
        )
    except RuntimeError as e:
        logger.error(f"voice_transcribe config error: {e}")
        await update.message.reply_text(
            "Не получилось распознать голосовое.\n\n"
            "Проверь, что в Railway Variables добавлен OPENAI_API_KEY, или пришли текст/скрин.",
            reply_markup=kb_tz_input()
        )
    except Exception as e:
        logger.error(f"voice_transcribe error: {e}")
        await update.message.reply_text(
            "Не получилось распознать голосовое. Попробуй отправить его ещё раз или пришли текстом.",
            reply_markup=kb_tz_input()
        )
    finally:
        try:
            await thinking_msg.delete()
        except Exception:
            pass


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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_unsupported_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
