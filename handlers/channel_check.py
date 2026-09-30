from telegram import Update
from telegram.ext import ContextTypes
from storage import get_required_channels
from keyboards import force_join_menu


def is_channel_member(member) -> bool:
    """Return True only for a confirmed Telegram channel member."""
    status = getattr(member, "status", "")
    if status in ("member", "administrator", "creator"):
        return True
    # A restricted ChatMember is only a member when Telegram explicitly says so.
    return status == "restricted" and bool(getattr(member, "is_member", False))


def _join_text(channels: list) -> str:
    channel_lines = "\n".join(f"• {c}" for c in channels)
    return (
        "*Join Required*\n\n"
        "You must join our channel(s) to use this bot.\n\n"
        f"*Channels:*\n{channel_lines}\n\n"
        "_After joining all channels, tap ✅ I Joined_"
    )


async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if user is a member of all required channels (or none are required).
    Returns False and sends the join prompt if the user is missing any of them.
    """
    channels = get_required_channels()
    if not channels:
        return True

    user = update.effective_user
    if not user:
        return True

    missing = []
    verification_failed = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user.id)
            if not is_channel_member(member):
                missing.append(channel)
        except Exception:
            # Never treat an unavailable membership lookup as permission.
            missing.append(channel)
            verification_failed.append(channel)

    if not missing:
        return True

    text = _join_text(channels)
    if verification_failed:
        text += (
            "\n\n⚠️ Membership could not be verified for: "
            + ", ".join(verification_failed)
            + "\nThe bot must be able to access the channel to verify membership."
        )

    if update.message:
        await update.message.reply_text(text, reply_markup=force_join_menu(channels), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.answer("⚠️ You must join all required channels first!", show_alert=True)
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=force_join_menu(channels),
                parse_mode="Markdown",
            )
        except Exception:
            # Some Telegram clients/messages cannot be edited. Always provide
            # a new prompt so the user can still see the channel join button.
            await update.callback_query.message.reply_text(
                text,
                reply_markup=force_join_menu(channels),
                parse_mode="Markdown",
            )

    return False


async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    channels = get_required_channels()

    if not channels:
        await query.answer()
        from handlers.start import start_handler
        await start_handler(update, context)
        return

    user_id = update.effective_user.id
    missing = []
    verification_failed = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if not is_channel_member(member):
                missing.append(channel)
        except Exception:
            missing.append(channel)
            verification_failed.append(channel)

    if not missing:
        await query.answer("✅ Verified! Welcome!", show_alert=True)
        from handlers.start import start_handler
        await start_handler(update, context)
    else:
        if verification_failed:
            text = (
                _join_text(channels)
                + "\n\n⚠️ Membership could not be verified for: "
                + ", ".join(verification_failed)
                + "\nThe bot must be able to access the channel to verify membership."
            )
            await query.answer(
                "⚠️ Membership could not be verified. Please try again later.",
                show_alert=True,
            )
        else:
            text = _join_text(channels)
            await query.answer(
                f"❌ You haven't joined {', '.join(missing)} yet. Please join and try again.",
                show_alert=True,
            )
        try:
            await query.edit_message_text(
                text,
                reply_markup=force_join_menu(channels),
                parse_mode="Markdown",
            )
        except Exception:
            await query.message.reply_text(
                text,
                reply_markup=force_join_menu(channels),
                parse_mode="Markdown",
            )
