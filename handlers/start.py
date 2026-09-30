import html
from telegram import Update
from telegram.ext import ContextTypes
from storage import get_stats, is_owner, has_adv_access, user_exists
from keyboards import main_menu


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "there"
    is_new = not user_exists(user_id)
    stats = get_stats(user_id)

    active = stats["active"]
    dead   = stats["dead"]
    total  = stats["total"]

    if total == 0:
        account_line = "⚠️ No accounts added yet."
    else:
        account_line = f"🟢 Active: {active}   🔴 Dead: {dead}   📦 Total: {total}"

    safe_name = html.escape(first_name)
    text = (
        f"<b>Welcome back, {safe_name}!</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "<b>Auto Voter</b>\n"
        "<i>Telegram Automation Bot</i>\n\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "<code>React • Vote • View • Join • DM</code>\n"
        "<i>Fast, reliable &amp; smart Telegram automation</i>\n\n"
        f"{account_line}\n\n"
        "Choose an option:\n\n"
        "<i>Developed by</i> <b>@YOU_KNOW_RAVI_XD</b>"
    )

    keyboard = main_menu(user_id=user_id)

    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
        # Log every /start command (not main-menu button presses)
        from handlers.log_gc import send_log, fmt_user_start
        await send_log(context.bot, fmt_user_start(user_id, user.full_name or first_name, user.username))
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
