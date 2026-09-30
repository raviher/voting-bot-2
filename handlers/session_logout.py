"""Primary-owner flow for revoking other Telegram-device sessions."""

import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from handlers.utils import escape_md
from keyboards import back_button
from storage import OWNER_ID, append_audit_log, get_user


LOGOUT_COUNT = 200
LOGOUT_CONFIRM = 201


def _cancel_keyboard(target_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "Cancel",
            callback_data=f"user_logout_cancel_{target_uid}",
            style="primary",
        )
    ]])


def _confirm_keyboard(target_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🚪 Confirm Logout",
            callback_data=f"user_logout_confirm_{target_uid}",
            style="danger",
        ),
        InlineKeyboardButton(
            "Cancel",
            callback_data=f"user_logout_cancel_{target_uid}",
            style="primary",
        ),
    ]])


def _account_label(account: dict, index: int) -> str:
    name = account.get("name") or account.get("username") or f"Account {index + 1}"
    username = account.get("username")
    suffix = f" ({username})" if username and username not in str(name) else ""
    return f"{index + 1}. {escape_md(str(name) + suffix)}"


async def user_logout_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask how many selected accounts should be logged out on other devices."""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Primary owner only.", show_alert=True)
        return ConversationHandler.END

    try:
        target_uid = int(query.data.replace("user_logout_start_", "", 1))
    except (TypeError, ValueError):
        await query.answer("⚠️ Invalid user.", show_alert=True)
        return ConversationHandler.END

    accounts = get_user(target_uid).get("accounts", [])
    if not accounts:
        await query.edit_message_text(
            f"⚠️ User `{target_uid}` has no accounts.",
            reply_markup=back_button(f"user_detail_{target_uid}"),
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    context.user_data["logout_target_uid"] = target_uid
    await query.edit_message_text(
        "🚪 *LOG OUT ACCOUNTS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"User: `{target_uid}`\n"
        f"Available accounts: *{len(accounts)}*\n\n"
        "Send how many accounts to log out on other devices. The first N accounts in this "
        "user's account list will be selected, then you can review them "
        "before confirmation.\n\n"
        "✅ RAVI's bot session will stay connected.\n"
        "⚠️ All other Telegram sessions for those accounts—including the "
        "user's phone and other devices—will be logged out.\n\n"
        f"Send a number from *1* to *{len(accounts)}*:",
        reply_markup=_cancel_keyboard(target_uid),
        parse_mode="Markdown",
    )
    return LOGOUT_COUNT


async def user_logout_count_receive(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Validate the requested count and show the exact accounts for review."""
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END

    target_uid = context.user_data.get("logout_target_uid")
    if not target_uid:
        return ConversationHandler.END

    try:
        count = int(update.message.text.strip())
    except (TypeError, ValueError):
        await update.message.reply_text(
            "⚠️ Please send a whole number.",
            reply_markup=_cancel_keyboard(target_uid),
        )
        return LOGOUT_COUNT

    accounts = get_user(target_uid).get("accounts", [])
    if count < 1 or count > len(accounts):
        await update.message.reply_text(
            f"⚠️ Enter a number from 1 to {len(accounts)}.",
            reply_markup=_cancel_keyboard(target_uid),
        )
        return LOGOUT_COUNT

    context.user_data["logout_count"] = count
    selected = accounts[:count]
    names = "\n".join(_account_label(account, i) for i, account in enumerate(selected))
    await update.message.reply_text(
        "⚠️ *CONFIRM ACCOUNT LOGOUT*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Selected *{count}* account(s) for user `{target_uid}`:\n"
        f"{names}\n\n"
        "After confirmation, Telegram will log these accounts out from all "
        "other devices. RAVI's current bot session will stay connected. "
        "This cannot be undone from the bot.",
        reply_markup=_confirm_keyboard(target_uid),
        parse_mode="Markdown",
    )
    return LOGOUT_CONFIRM


async def user_logout_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Log selected accounts out from all other Telegram devices."""
    query = update.callback_query
    await query.answer("Logging out selected accounts...", show_alert=False)

    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Primary owner only.", show_alert=True)
        return ConversationHandler.END

    try:
        target_uid = int(query.data.replace("user_logout_confirm_", "", 1))
    except (TypeError, ValueError):
        await query.answer("⚠️ Invalid user.", show_alert=True)
        return ConversationHandler.END

    if context.user_data.get("logout_target_uid") != target_uid:
        await query.edit_message_text(
            "⚠️ This logout request expired. Please start again.",
            reply_markup=back_button(f"user_detail_{target_uid}"),
        )
        return ConversationHandler.END

    count = int(context.user_data.get("logout_count", 0))
    accounts = get_user(target_uid).get("accounts", [])
    selected = accounts[:count]

    api_id = int(os.environ.get("PYROGRAM_API_ID", "0") or "0")
    api_hash = os.environ.get("PYROGRAM_API_HASH", "").strip()
    successful = []
    failed = []

    if not api_id or not api_hash:
        failed = [(i, "Pyrogram API credentials are not configured") for i in range(count)]
    else:
        from pyrogram import Client
        from pyrogram.raw.functions.auth import ResetAuthorizations

        for index, account in enumerate(selected):
            identifier = account.get("identifier")
            label = account.get("name") or account.get("username") or f"Account {index + 1}"
            if not isinstance(identifier, str) or len(identifier.strip()) < 20:
                failed.append((index, f"{label}: no valid stored session"))
                continue

            try:
                async with Client(
                    f"logout_{target_uid}_{index}",
                    api_id=api_id,
                    api_hash=api_hash,
                    session_string=identifier.strip(),
                    no_updates=True,
                    in_memory=True,
                ) as client:
                    # Telegram keeps the current authorization (RAVI) and
                    # terminates every other authorization for this account.
                    await client.invoke(ResetAuthorizations())
                successful.append(str(label))
            except Exception as exc:
                failed.append((index, f"{label}: {type(exc).__name__}"))

    append_audit_log(
        OWNER_ID,
        "logout_other_device_sessions",
        f"target_user_id={target_uid}; requested={count}; "
        f"successful={len(successful)}; failed={len(failed)}",
    )

    lines = [
        "✅ *OTHER-DEVICE LOGOUT COMPLETE*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"User: `{target_uid}`",
        f"✅ Revoked: *{len(successful)}*",
        f"⚠️ Failed: *{len(failed)}*",
        "",
        "_The RAVI bot session stayed connected; other Telegram devices were logged out._",
    ]
    if failed:
        lines.extend(["", "*Failed accounts:*"])
        lines.extend(f"• {escape_md(reason)}" for _, reason in failed[:8])
        if len(failed) > 8:
            lines.append(f"• …and {len(failed) - 8} more")

    context.user_data.pop("logout_target_uid", None)
    context.user_data.pop("logout_count", None)
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=back_button(f"user_detail_{target_uid}"),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def user_logout_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    await query.answer("Logout cancelled.")
    try:
        target_uid = int(query.data.replace("user_logout_cancel_", "", 1))
    except (TypeError, ValueError):
        target_uid = 0

    context.user_data.pop("logout_target_uid", None)
    context.user_data.pop("logout_count", None)
    await query.edit_message_text(
        "✅ Logout cancelled.",
        reply_markup=back_button(f"user_detail_{target_uid}"),
    )
    return ConversationHandler.END