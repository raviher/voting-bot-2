from telegram import Update
from telegram.ext import ContextTypes
from storage import get_profile, update_profile, get_stats
from keyboards import back_button
from datetime import datetime
from handlers.utils import escape_md


async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    query = update.callback_query
    if query:
        await query.answer()

    tg_user = update.effective_user
    profile = get_profile(user_id)
    stats = get_stats(user_id)

    if not profile.get("joined"):
        update_profile(user_id, {"joined": datetime.now().strftime("%Y-%m-%d")})
        profile = get_profile(user_id)

    username = f"@{tg_user.username}" if tg_user.username else "Not set"
    full_name = tg_user.full_name or "Unknown"

    text = (
        "👤 *MY PROFILE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *Name:* {escape_md(full_name)}\n"
        f"🔗 *Username:* {escape_md(username)}\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"📅 *Joined:* {profile.get('joined', 'N/A')}\n\n"
        "📊 *Your Summary:*\n"
        f"   📦 Accounts: {stats['total']}\n"
        f"   🟢 Active: {stats['active']}\n"
        f"   🚀 Campaigns: {stats['campaigns']}\n"
        f"   ⚡ Total Actions: {stats['actions']}"
    )

    markup = back_button("main_menu")
    if query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
