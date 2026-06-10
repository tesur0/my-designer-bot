import asyncio
import base64
import io
import logging
import os
import random
import re
from dataclasses import dataclass, field

import anthropic
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or os.getenv("TELEGRAM_TOKEN")
    or "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

MAX_HISTORY_MESSAGES = 20
PHOTO_BATCH_DELAY = 5
MAX_IMAGE_SIDE = 1800
JPEG_QUALITY = 86

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
dp = Dispatcher()

CHAT_HISTORY: dict[int, list[dict[str, str]]] = {}
PHOTO_BATCHES: dict[int, dict] = {}


@dataclass
class RoleplayState:
    scenario: str
    turns: int = 0
    messages: list[dict[str, str]] = field(default_factory=list)


ROLEPLAYS: dict[int, RoleplayState] = {}

THINKING = [
    "Разбираю переписку...",
    "Смотрю, кто держит рамку...",
    "Ищу точки, где теряются деньги...",
    "Собираю нормальный ответ...",
    "Проверяю, где клиент может слиться...",
]

SCENARIOS = [
    "Владелец сети детейлинг-центров в Дубае. 3 точки, открывает 4-ю. Пришёл по рекомендации. Торгуется жёстко. Средний чек $400, 40-60 заявок в месяц с Instagram.",
    "Арбитражная команда из Украины. Есть брендбук, нужен новый стиль для соцсетей. Клиент профессиональный, проверяет экспертизу и быстро уходит, если не видит уровня.",
    "Стартап без бюджета. Денег мало, хочет побольше за поменьше. Давит на скидку и просит по дружбе.",
    "Эксперт с личным блогом. Женщина 35+, свой бизнес, хочет упаковку Instagram. Не знает, чего хочет, меняет решения и затягивает ответы.",
    "Владелец премиум-ресторана в Тбилиси. Нужен ребрендинг: логотип, меню, соцсети. Бюджет есть, но он проверяет, почему так дорого.",
    "IT-компания. Нужна упаковка HR-бренда для найма. Корпоративный клиент, формальный тон, длинное согласование.",
    "Бьюти-бренд. Запуск новой косметики. Основательница насмотрена на Pinterest и навязывает свой стиль. Нужно удержать экспертную позицию.",
]

SYSTEM_PROMPT = """Ты - жёсткий, прямой тренер по продажам и клиентской коммуникации для digital-дизайнера Артёма.

Контекст:
Артёму 22 года, у него 5+ лет опыта, он живёт в Грузии.
Он делает брендинг, логотипы, упаковку Instagram/Telegram, лендинги, AI-дизайн и рекламные креативы.
Его цель - стать премиум-дизайнером, работать с дорогими клиентами, растить личный бренд и студию.

Главные ошибки, которые ты отслеживаешь:
1. Отдаёт рамку клиенту вместо своей позиции.
2. Называет цену слишком рано или слишком низко.
3. Навешивает задачу на клиента вместо того, чтобы снять её.
4. Боится озвучить своё видение.
5. Обесценивает допработу.
6. Выпрашивает одобрение.
7. Не держит границы по времени.
8. Не считывает мягкий отказ.

Как отвечать:
- Если это вопрос "что ответить" - дай 2-3 готовых варианта от мягкого до жёсткого и коротко объясни логику.
- Если это переписка - найди слабые места, покажи "было -> как лучше", дай следующий ход.
- Если это длинный диалог - разбери, кто вёл разговор, где потеряны деньги, где можно поднять чек или продать допуслугу.
- Если Артём хочет назвать цену, сначала проверь, спросил ли он про бизнес, масштаб, заявки и средний чек. Если нет - останови и дай вопросы.

Правила тона:
- Без мотивационных фраз.
- Без "ты молодец" и пустой поддержки.
- Если сильно - скажи "сильно" и почему.
- Если слабо - скажи прямо.
- Не соглашайся автоматически.
- Пиши по-русски, украинский понимай спокойно.
- Без markdown-таблиц.
- Не используй длинное тире. Только обычный дефис.
- Не пиши как ИИ. Пиши как живой строгий наставник.

Ключевые принципы:
1. Цену называй пакетом и сверху, не поэлементно и снизу.
2. Никакой цифры, пока не задал вопросы про бизнес.
3. Приходи с позицией: "вижу так..." вместо "какие референсы нравятся?"
4. Привязывай цену к окупаемости клиента.
5. Снимай задачу с клиента. Максимум 3 коротких вопроса.
6. Допработа = отдельная цена до выполнения.
7. Информируй, не проси разрешения.
8. Один фоллоу-ап с достоинством, не тревожные пинги."""

ROLEPLAY_SYSTEM = """Ты играешь роль клиента в тренировке продаж для digital-дизайнера Артёма.

Правила:
- Будь реалистичным клиентом.
- Торгуйся, проверяй экспертизу, иногда сомневайся и дави на скидку.
- Не помогай Артёму слишком явно.
- Цель тренировки - довести разговор до предоплаты.
- После каждых 3 сообщений Артёма выйди из роли, дай короткий разбор: что сильно, что слабо, что сказать дальше. Потом вернись в роль клиента.
- Без длинного тире. Только обычный дефис."""

RULES_TEXT = """8 принципов, которые надо держать в голове:

1. Цену называй пакетом и сверху, не "от $100".
2. Не называй цифру до вопросов про бизнес, масштаб, заявки и средний чек.
3. Приходи с позицией: "вижу так", а не "что вам нравится".
4. Привязывай цену к окупаемости клиента, не к своим часам.
5. Снимай задачу с клиента. Максимум 3 коротких вопроса.
6. Всё сверх пакета - отдельная цена до выполнения.
7. По срокам информируй, а не проси разрешения.
8. Один нормальный фоллоу-ап. Без тревожных пингов."""

HELP_TEXT = """Я тренер по продажам для дизайнера.

Что можно прислать:
- вопрос клиента и "что ответить?"
- скрин переписки
- длинный диалог для разбора
- пересланные сообщения

Команды:
/start - короткая инструкция
/help - что умею
/rules - 8 принципов коммуникации
/roleplay - тренировка с клиентом
/stop - остановить тренировку

Если отправляешь несколько скринов подряд, кидай их один за другим. Я подожду 5 секунд и разберу всё вместе."""


def clean(text: str) -> str:
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remember(chat_id: int, role: str, content: str) -> None:
    history = CHAT_HISTORY.setdefault(chat_id, [])
    history.append({"role": role, "content": content.strip()})
    del history[:-MAX_HISTORY_MESSAGES]


def history_text(chat_id: int) -> str:
    history = CHAT_HISTORY.get(chat_id, [])[-MAX_HISTORY_MESSAGES:]
    if not history:
        return "Истории пока нет."

    lines = []
    for item in history:
        speaker = "Артём" if item["role"] == "user" else "Бот"
        lines.append(f"{speaker}: {item['content']}")
    return "\n".join(lines)


def image_to_base64(raw: bytes) -> str:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return base64.b64encode(output.getvalue()).decode("utf-8")


async def send_long(message: Message, text: str) -> None:
    text = clean(text)
    limit = 3900
    parts = []
    while len(text) > limit:
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        parts.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        parts.append(text)

    for part in parts:
        await message.answer(part)


async def call_claude(system: str, user_content, max_tokens: int = 2500) -> str:
    if not client:
        return "ANTHROPIC_API_KEY не задан. Добавь ключ в переменные окружения Railway."

    for attempt in range(3):
        try:
            response = await asyncio.to_thread(
                client.messages.create,
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            return clean(response.content[0].text)
        except Exception as exc:
            logger.error("Claude error, attempt %s: %s", attempt + 1, exc)
            if attempt == 2:
                return "Сервис временно недоступен, попробуй через минуту."
            await asyncio.sleep(0.8 * (2 ** attempt))

    return "Сервис временно недоступен, попробуй через минуту."


async def analyze_text(chat_id: int, text: str) -> str:
    prompt = f"""Контекст последних сообщений:
{history_text(chat_id)}

Новый ввод Артёма:
{text}

Разбери ситуацию и дай конкретный следующий ход."""
    return await call_claude(SYSTEM_PROMPT, prompt)


async def analyze_images(chat_id: int, images: list[str], captions: list[str]) -> str:
    content = []
    for image in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image,
            },
        })

    caption_text = "\n".join(c for c in captions if c.strip()).strip()
    content.append({
        "type": "text",
        "text": f"""На скринах переписка с клиентом.

Сначала распознай текст, потом разбери коммуникацию:
- кто ведёт разговор
- где Артём теряет рамку, деньги или уверенность
- что надо ответить следующим сообщением
- дай 2-3 варианта ответа и коротко объясни, почему так

Контекст последних сообщений:
{history_text(chat_id)}

Подпись к скринам:
{caption_text if caption_text else "нет"}""",
    })
    return await call_claude(SYSTEM_PROMPT, content, max_tokens=3500)


async def roleplay_reply(chat_id: int, user_text: str) -> str:
    state = ROLEPLAYS[chat_id]
    state.turns += 1
    state.messages.append({"role": "user", "content": user_text})
    state.messages = state.messages[-12:]

    mode = "Продолжай играть клиента."
    if state.turns % 3 == 0:
        mode = "Сейчас выйди из роли, дай короткий разбор сообщения Артёма, затем вернись в роль клиента и ответь ему."

    transcript = "\n".join(
        f"{'Артём' if m['role'] == 'user' else 'Клиент'}: {m['content']}"
        for m in state.messages
    )
    prompt = f"""Сценарий клиента:
{state.scenario}

Диалог:
{transcript}

Задача:
{mode}"""
    answer = await call_claude(ROLEPLAY_SYSTEM, prompt, max_tokens=1800)
    state.messages.append({"role": "assistant", "content": answer})
    state.messages = state.messages[-12:]
    return answer


async def final_roleplay_review(chat_id: int) -> str:
    state = ROLEPLAYS.get(chat_id)
    if not state:
        return "Ролевая игра не запущена."

    transcript = "\n".join(
        f"{'Артём' if m['role'] == 'user' else 'Клиент'}: {m['content']}"
        for m in state.messages
    )
    prompt = f"""Сценарий:
{state.scenario}

Диалог:
{transcript}

Дай финальный разбор:
- где Артём держал рамку
- где просел
- где можно было поднять чек
- какое следующее сообщение было бы сильным"""
    return await call_claude(SYSTEM_PROMPT, prompt, max_tokens=1800)


@dp.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Тренер по продажам для дизайнера.\n\n"
        "Кидай вопрос клиента, переписку текстом или скрин. Я разберу, где теряется рамка, деньги и что ответить.\n\n"
        "Для тренировки напиши /roleplay."
    )


@dp.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(HELP_TEXT)


@dp.message(Command("rules"))
async def rules_cmd(message: Message) -> None:
    await message.answer(RULES_TEXT)


@dp.message(Command("roleplay"))
async def roleplay_cmd(message: Message) -> None:
    chat_id = message.chat.id
    scenario = random.choice(SCENARIOS)
    ROLEPLAYS[chat_id] = RoleplayState(scenario=scenario)

    opener = await call_claude(
        ROLEPLAY_SYSTEM,
        f"""Запусти ролевую игру.

Сценарий:
{scenario}

Напиши первое сообщение от лица клиента. Коротко, естественно, как в Telegram.""",
        max_tokens=700,
    )
    ROLEPLAYS[chat_id].messages.append({"role": "assistant", "content": opener})
    await message.answer(f"Ролевая игра запущена.\n\nСценарий: {scenario}\n\n{opener}")


@dp.message(Command("stop"))
async def stop_cmd(message: Message) -> None:
    chat_id = message.chat.id
    if chat_id not in ROLEPLAYS:
        await message.answer("Ролевая игра сейчас не запущена.")
        return

    review = await final_roleplay_review(chat_id)
    ROLEPLAYS.pop(chat_id, None)
    await send_long(message, review)


@dp.message(F.photo)
async def photo_handler(message: Message, bot: Bot) -> None:
    chat_id = message.chat.id
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    buffer = io.BytesIO()
    await bot.download_file(file.file_path, buffer)

    batch = PHOTO_BATCHES.setdefault(chat_id, {"images": [], "captions": [], "task": None, "message": message})
    batch["images"].append(image_to_base64(buffer.getvalue()))
    batch["captions"].append(message.caption or "")
    batch["message"] = message

    if batch.get("task"):
        batch["task"].cancel()

    batch["task"] = asyncio.create_task(process_photo_batch(chat_id))
    await message.answer("Скрин принял. Если есть ещё - кидай сразу, подожду 5 секунд.")


async def process_photo_batch(chat_id: int) -> None:
    try:
        await asyncio.sleep(PHOTO_BATCH_DELAY)
        batch = PHOTO_BATCHES.pop(chat_id, None)
        if not batch:
            return

        message = batch["message"]
        status = await message.answer(random.choice(THINKING))
        answer = await analyze_images(chat_id, batch["images"], batch["captions"])
        remember(chat_id, "user", f"Отправил {len(batch['images'])} скрин(ов) переписки.")
        remember(chat_id, "assistant", answer)
        await send_long(message, answer)
        try:
            await status.delete()
        except Exception:
            pass
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.error("photo batch error: %s", exc)


@dp.message(F.text)
async def text_handler(message: Message) -> None:
    chat_id = message.chat.id
    text = message.text.strip()
    if not text:
        return

    if chat_id in ROLEPLAYS:
        status = await message.answer(random.choice(THINKING))
        answer = await roleplay_reply(chat_id, text)
        await send_long(message, answer)
        try:
            await status.delete()
        except Exception:
            pass
        return

    status = await message.answer(random.choice(THINKING))
    answer = await analyze_text(chat_id, text)
    remember(chat_id, "user", text)
    remember(chat_id, "assistant", answer)
    await send_long(message, answer)
    try:
        await status.delete()
    except Exception:
        pass


@dp.message()
async def fallback_handler(message: Message) -> None:
    await message.answer("Пришли текст, пересланное сообщение или скрин переписки. Документы и голосовые пока лучше переслать текстом.")


async def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    bot = Bot(token=TELEGRAM_TOKEN)
    logger.info("Sales coach bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
