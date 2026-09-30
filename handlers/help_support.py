from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from keyboards import back_button

DEVELOPER_URL = "https://t.me/YOU_KNOW_RAVI_XD"


async def help_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()

    text = (
        "How to Use Auto Voter\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "Step 1 — Add Accounts\n"
        "Add Account → Phone+OTP or Session String\n"
        "Bulk Sessions → paste many at once or upload .txt\n\n"
        "Step 2 — Run Campaign\n"
        "New Campaign → Choose Action → Post URL\n\n"
        "React — Add emoji reaction\n"
        "Vote — Click inline button\n"
        "React + Vote — Both together\n"
        "View — View the post\n"
        "React + Vote + View — All three\n"
        "Join Channel — Join a channel\n"
        "Leave Channel — Leave a channel\n"
        "Bulk DM — Send DM to a user\n\n"
        "Step 3 — Schedule (Optional)\n"
        "Schedule campaigns for later\n\n"
        "Supported Post URLs:\n"
        "<code>https://t.me/channel/123</code>\n"
        "<code>https://t.me/c/1234567890/123</code>\n\n"
        "Commands:\n"
        "<code>/start  /help  /stats  /me</code>\n"
        "<code>/accounts  /campaigns  /admin</code>\n"
        "<code>/cancel  — end any active conversation</code>\n\n"
        "<i>Developed by</i> <b>@YOU_KNOW_RAVI_XD</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💻 Developer", url=DEVELOPER_URL, style="success")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu", style="primary")],
    ])

    if query:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Contact Support", url=DEVELOPER_URL, style="success")],
        [InlineKeyboardButton("👨‍💻 Developer", url=DEVELOPER_URL, style="success")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu", style="primary")],
    ])

    text = (
        "📞 *Support*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "Need help? Tap the button below to contact support.\n\n"
        "📧 *Response time:* Usually within 24 hours\n\n"
        "For faster support, please include:\n"
        "• Your User ID (see My Profile)\n"
        "• A description of the issue\n"
        "• Any relevant screenshots\n\n"
        "Use /start anytime to return to the main menu."
    )

    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
