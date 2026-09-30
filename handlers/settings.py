from telegram import Update
from telegram.ext import ContextTypes
from storage import get_settings, update_settings, get_cooldown_minutes, set_cooldown_minutes
from keyboards import settings_menu, language_menu, timezone_menu, speed_menu, cooldown_menu, SPEED_LABELS


async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()

    settings = get_settings(user_id)
    text = (
        "⚙️ *SETTINGS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Manage your bot preferences below:"
    )
    await query.edit_message_text(text, reply_markup=settings_menu(settings), parse_mode="Markdown")


async def toggle_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    query = update.callback_query
    settings = get_settings(user_id)
    current = settings.get("notifications", True)
    update_settings(user_id, "notifications", not current)
    new_val = "ON 🔔" if not current else "OFF 🔕"
    await query.answer(f"Notifications {new_val}", show_alert=True)
    await settings_handler(update, context)


async def language_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "🌐 *SELECT LANGUAGE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose your preferred language:"
    )
    await query.edit_message_text(text, reply_markup=language_menu(), parse_mode="Markdown")


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    lang_code = query.data.split("_")[-1]
    lang_names = {"en": "English", "ru": "Russian", "es": "Spanish", "de": "German"}
    user_id = update.effective_user.id
    update_settings(user_id, "language", lang_code)
    await query.answer(f"Language set to {lang_names.get(lang_code, lang_code)}", show_alert=True)
    await settings_handler(update, context)


async def timezone_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "🕐 *SELECT TIMEZONE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose your timezone:"
    )
    await query.edit_message_text(text, reply_markup=timezone_menu(), parse_mode="Markdown")


async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    tz = query.data[3:]
    user_id = update.effective_user.id
    update_settings(user_id, "timezone", tz)
    await query.answer(f"Timezone set to {tz}", show_alert=True)
    await settings_handler(update, context)


async def speed_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = get_settings(user_id)
    current = settings.get("speed", "slow")

    lines = [
        "⚡ *SPEED SETTING*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        "Controls how fast accounts run during a campaign.\n",
        "🐢 *Slow* — 1 worker · 12–20 s delay · safest",
        "🚶 *Normal* — 2 workers · 6–12 s delay · balanced",
        "🐇 *Fast* — 3 workers · 4–8 s delay · higher risk",
        "⚡ *Ultra* — max 3 workers · 2–5 s delay · highest risk",
        "🧠 *Smart* — 3 workers · 3–7 s *random* delay · fast-safe default\n",
        "⏱ *Estimated time for 100 accounts (React+Vote+View):*",
        "🐢 Slow → ~25–40 min",
        "🚶 Normal → ~14–24 min",
        "🐇 Fast → ~9–16 min",
        "⚡ Ultra → ~6–12 min",
        "🧠 Smart → ~8–14 min\n",
        "🧠 *Smart is recommended* — every account also rests",
        "for at least 5 minutes before it can be used again.",
        "_Fast/Ultra carry higher FloodWait and restriction risk._",
    ]
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=speed_menu(current),
        parse_mode="Markdown",
    )


async def set_speed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    speed_key = query.data.split("_", 1)[1]   # "speed_fast" → "fast"
    user_id = update.effective_user.id
    update_settings(user_id, "speed", speed_key)
    label = SPEED_LABELS.get(speed_key, speed_key)
    await query.answer(f"Speed set to {label}", show_alert=True)
    await speed_select(update, context)


async def cooldown_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    current = get_cooldown_minutes(user_id)
    text = (
        "⏱ *ACCOUNT COOLDOWN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Cooldown prevents an account from being used again "
        "before a set amount of time has passed since its last run.\n\n"
        "🚫 *Off* — no custom cooldown, but the 5-minute safety rest remains.\n"
        "⏱ *5–360 min* — accounts are skipped if used more recently.\n\n"
        "_Useful to reduce Telegram flood detection and account wear._"
    )
    await query.edit_message_text(
        text,
        reply_markup=cooldown_menu(current),
        parse_mode="Markdown",
    )


async def set_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: cooldown_<minutes>"""
    query = update.callback_query
    user_id = update.effective_user.id
    minutes = int(query.data.split("_")[-1])
    set_cooldown_minutes(user_id, minutes)
    if minutes == 0:
        label = "Off"
    elif minutes < 60:
        label = f"{minutes} min"
    else:
        label = f"{minutes // 60} hour(s)"
    await query.answer(f"⏱ Cooldown set to {label}", show_alert=True)
    await cooldown_select(update, context)
