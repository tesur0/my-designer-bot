import os
import logging
import anthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8892738780:AAH8gp8l-c81Z9YwRd_Tv0YeMIDjJg1AYGg"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DESIGNER_USERNAME = "@artesignus"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище истории диалогов
CONVERSATIONS: dict[int, list[dict]] = {}
BRIEF_SENT: dict[int, bool] = {}

SYSTEM_PROMPT = """Ты — AI ассистент премиального digital-дизайнера.

Твоя задача — общаться с потенциальными клиентами в Telegram и помогать собирать понятный, структурированный бриф ДО того, как дизайнер подключится к диалогу.

ВАЖНО:
* Общайся естественно и по-человечески.
* Не разговаривай как корпорация или типичный AI-бот.
* Сообщения должны быть короткими, уверенными, современными и понятными.
* Не пиши огромные полотна текста.
* Не используй кринж AI-фразы.
* Стиль общения должен ощущаться как premium, calm, smart & efficient.

Твои цели:
1. Понять задачу клиента.
2. Собрать всю нужную информацию.
3. Уменьшить хаос в переписке.
4. Сэкономить время дизайнеру.
5. Определить качество клиента и возможные риски.
6. Подготовить структурированную выжимку для дизайнера.

Задавай вопросы постепенно, а не все сразу.

Информацию, которую нужно собрать:
* Что именно нужно разработать?
* Какая ниша/бизнес?
* Какая главная цель дизайна?
* Где будет использоваться дизайн?
* Есть ли референсы?
* Есть ли фирменные цвета/шрифты/гайдлайн?
* Готовы ли тексты и материалы?
* Какие сроки?
* На какой бюджет ориентируется клиент?
* Какая целевая аудитория?
* Какой стиль хочет клиент?
* Что точно НЕ должно быть в дизайне?

Правила поведения:
* Если клиент отвечает размыто — задавай уточняющие вопросы.
* Если клиент не понимает, чего хочет — помогай направлять его.
* Если клиент токсичный, хаотичный, неуважительный или хочет "срочно, дешево и премиально", internally помечай это как повышенный риск.
* Не груби клиенту и не спорь.
* Всегда сохраняй спокойный и профессиональный тон.

Когда ты решишь что информации достаточно (обычно после 6-10 сообщений), напиши клиенту что передаёшь информацию дизайнеру, и в конце своего сообщения добавь специальный блок (он будет скрыт от клиента):

===BRIEF_START===
ПРОЕКТ: [название/тип]
НИША: [бизнес клиента]
ЦЕЛЬ: [главная цель дизайна]
ПЛАТФОРМА: [где используется]
СТИЛЬ: [описание стиля]
РЕФЕРЕНСЫ: [есть/нет, описание]
МАТЕРИАЛЫ: [готовы/не готовы]
СРОК: [дедлайн]
БЮДЖЕТ: [ориентир клиента]
АУДИТОРИЯ: [целевая аудитория]
НЕ НУЖНО: [что не должно быть]

УРОВЕНЬ КЛИЕНТА: low / medium / high
РИСК: low / medium / high
БЮДЖЕТ КАТЕГОРИЯ: low-budget / mid-range / premium

ЗАМЕТКИ: [наблюдения о клиенте]

ВЫЖИМКА ДЛЯ ДИЗАЙНЕРА:
[2-3 предложения самого важного]
===BRIEF_END===

ВАЖНО:
Ты НЕ дизайнер.
Не обещай точную цену.
Не обещай точные сроки.
Не принимай финальные бизнес-решения.
Твоя задача — собрать, структурировать, уточнить и подготовить информацию для дизайнера."""


async def start(update: Update, context) -> None:
    user_id = update.effective_user.id
    CONVERSATIONS[user_id] = []
    BRIEF_SENT[user_id] = False
    await update.message.reply_text(
        "Привет! 👋\n\nЯ помогу собрать информацию о вашем проекте до того, как вы пообщаетесь с дизайнером.\n\nРасскажите — над чем хотите поработать?"
    )


async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "Клиент"
    user_text = update.message.text

    if not user_text:
        await update.message.reply_text("Пожалуйста, напишите текстом — голосовые и файлы пока не поддерживаются.")
        return

    if user_id not in CONVERSATIONS:
        CONVERSATIONS[user_id] = []
        BRIEF_SENT[user_id] = False

    # Добавляем сообщение в историю
    CONVERSATIONS[user_id].append({"role": "user", "content": user_text})

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=CONVERSATIONS[user_id]
        )
        response = message.content[0].text

        # Проверяем есть ли бриф в ответе
        if "===BRIEF_START===" in response and not BRIEF_SENT.get(user_id, False):
            # Разделяем ответ клиенту и бриф
            parts = response.split("===BRIEF_START===")
            client_message = parts[0].strip()
            brief_part = parts[1].split("===BRIEF_END===")[0].strip()

            # Отправляем клиенту только его часть
            await update.message.reply_text(client_message)

            # Отправляем бриф дизайнеру
            brief_message = f"📋 *Новый бриф от клиента*\n\n*Клиент:* {user_name}\n\n{brief_part}"
            try:
                await context.bot.send_message(
                    chat_id=DESIGNER_USERNAME,
                    text=brief_message,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить бриф дизайнеру: {e}")

            BRIEF_SENT[user_id] = True
            # Сохраняем только клиентскую часть в историю
            CONVERSATIONS[user_id].append({"role": "assistant", "content": client_message})
        else:
            # Обычный ответ
            await update.message.reply_text(response)
            CONVERSATIONS[user_id].append({"role": "assistant", "content": response})

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Что-то пошло не так. Попробуйте ещё раз.")


def main():
    if not ANTHROPIC_API_KEY:
        print("❌ ОШИБКА: Установи переменную окружения ANTHROPIC_API_KEY")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Клиентский бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
