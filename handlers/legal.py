"""Short provider and privacy notices available inside Telegram."""
from repositories.user_repository import get_user


PRIVACY = {
    "ru": (
        "<b>Конфиденциальность</b>\n\n"
        "Бот получает от Telegram ваш Telegram ID, сообщения и отправленные фотографии. "
        "Фото и описание блюда хранятся только в памяти процесса до 30 минут и удаляются "
        "после отмены или завершения операции.\n\n"
        "Для распознавания фото или текст передаются Google Gemini. Для подбора продукта "
        "Gemini получает распознанное блюдо и сокращённые карточки FatSecret без OAuth-токенов "
        "и Telegram ID. Interactions-запрос отправляется с store=False; это не отменяет "
        "обработку и возможное хранение Google для безопасности или согласно настройкам проекта.\n\n"
        "FatSecret получает OAuth-подпись, выбранный продукт, порцию, количество, приём пищи и дату "
        "только после нажатия «Записать в FatSecret». В SQLite хранятся язык, OAuth-токены FatSecret, "
        "дата подключения, статус доступа, дневной счётчик и короткие технические маркеры записи. "
        "OAuth-токены хранятся до отключения FatSecret. Бот не может обещать удаление копий у Telegram, "
        "Google или FatSecret.\n\n"
        "Google: <a href=\"https://ai.google.dev/gemini-api/terms\">условия Gemini API</a> · "
        "<a href=\"https://policies.google.com/privacy\">политика Google</a>\n"
        "FatSecret: <a href=\"https://platform.fatsecret.com/terms\">условия API</a> · "
        "<a href=\"https://www.fatsecret.com/Default.aspx?pa=priv\">политика конфиденциальности</a>"
    ),
    "en": (
        "<b>Privacy</b>\n\n"
        "The bot receives your Telegram ID, messages and submitted photos from Telegram. A meal photo "
        "and description remain only in process memory for up to 30 minutes and are removed after "
        "cancellation or completion.\n\n"
        "The photo or text is sent to Google Gemini for recognition. For product matching, Gemini "
        "receives the recognized meal and shortened FatSecret cards without OAuth tokens or Telegram ID. "
        "The Interactions request uses store=False; this does not disable Google's safety processing or "
        "storage controlled by project settings and provider terms.\n\n"
        "FatSecret receives the OAuth signature, selected product, serving, quantity, meal and date only "
        "after you press Save to FatSecret. SQLite stores language, FatSecret OAuth tokens, connection date, "
        "access status, the daily counter and short write-operation markers. OAuth tokens remain until you "
        "disconnect FatSecret. The bot cannot promise deletion of copies held by Telegram, Google or FatSecret.\n\n"
        "Google: <a href=\"https://ai.google.dev/gemini-api/terms\">Gemini API terms</a> · "
        "<a href=\"https://policies.google.com/privacy\">Google privacy policy</a>\n"
        "FatSecret: <a href=\"https://platform.fatsecret.com/terms\">API terms</a> · "
        "<a href=\"https://www.fatsecret.com/Default.aspx?pa=priv\">privacy policy</a>"
    ),
}

TERMS = {
    "ru": (
        "<b>Условия использования</b>\n\n"
        "Сервис предназначен для пользователей 18 лет и старше. Отправляя блюдо на анализ, вы "
        "разрешаете передать фото или описание в Gemini. Используя данные FatSecret, вы соглашаетесь "
        "с <a href=\"https://platform.fatsecret.com/terms\">условиями FatSecret Platform API</a>.\n\n"
        "Распознавание, подбор продукта, масса и КБЖУ являются оценкой и могут быть неточными. "
        "Проверяйте результат перед записью и сведения на упаковке продукта. Бот не предоставляет "
        "медицинские, диетологические или диагностические рекомендации."
    ),
    "en": (
        "<b>Terms of use</b>\n\n"
        "This service is for users aged 18 and over. By submitting a meal for analysis, you allow the "
        "photo or description to be sent to Gemini. By using FatSecret data, you agree to the "
        "<a href=\"https://platform.fatsecret.com/terms\">fatsecret Platform API Terms</a>.\n\n"
        "Recognition, product selection, mass and macros are estimates and may be inaccurate. Check the "
        "result before saving and refer to the product package. The bot does not provide medical, dietary "
        "or diagnostic advice."
    ),
}


def _language(update):
    user = get_user(update.effective_user.id)
    return user.language if user and user.language in ("ru", "en") else "ru"


async def privacy_notice(update, context):
    await update.effective_message.reply_text(
        PRIVACY[_language(update)], parse_mode="HTML", disable_web_page_preview=True)


async def terms_notice(update, context):
    await update.effective_message.reply_text(
        TERMS[_language(update)], parse_mode="HTML", disable_web_page_preview=True)
