from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from handlers.utils import escape_md
from storage import (
    OWNER_ID, is_owner, get_all_user_ids, get_user, ban_user, unban_user,
    is_banned, get_banned_users, get_stats,
    get_user_account_limit, set_user_account_limit,
)
from keyboards import user_list_menu, user_detail_menu, back_button, cancel_button

PAGE_SIZE = 10

# Conversation state
USER_SET_LIMIT = 100


async def user_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    page = int(context.user_data.get("user_page", 0))
    await _show_user_list(query, context, page)


async def user_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    page = int(query.data.split("_")[-1])
    context.user_data["user_page"] = page
    await _show_user_list(query, context, page)


async def _show_user_list(query, context, page: int) -> None:
    all_uids = get_all_user_ids()
    total = len(all_uids)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    start = page * PAGE_SIZE
    page_uids = all_uids[start: start + PAGE_SIZE]

    banned = get_banned_users()
    banned_count = len(banned)

    summaries = []
    for uid in page_uids:
        # Fetch Telegram name (best-effort)
        name = ""
        try:
            chat = await context.bot.get_chat(int(uid))
            full = (chat.first_name or "")
            if chat.last_name:
                full += f" {chat.last_name}"
            if chat.username:
                full += f" (@{chat.username})"
            name = full.strip()
        except Exception:
            pass

        try:
            stats = get_stats(int(uid))
            summaries.append({
                "uid": uid,
                "name": name,
                "accounts": stats["total"],
                "campaigns": stats["campaigns"],
                "banned": int(uid) in banned,
            })
        except Exception:
            summaries.append({"uid": uid, "name": name, "accounts": 0, "campaigns": 0, "banned": False})

    text = (
        "👥 *USER MANAGEMENT*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Total users: *{total}*\n"
        f"🚫 Banned: *{banned_count}*\n\n"
        f"Page {page + 1}/{total_pages} — tap a user to manage:"
    )
    await query.edit_message_text(
        text,
        reply_markup=user_list_menu(summaries, page, total_pages),
        parse_mode="Markdown"
    )


async def user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    target_uid = int(query.data.split("_")[-1])
    page = int(context.user_data.get("user_page", 0))

    # Fetch Telegram name (best-effort)
    name_line = ""
    try:
        chat = await context.bot.get_chat(target_uid)
        full = (chat.first_name or "")
        if chat.last_name:
            full += f" {chat.last_name}"
        if chat.username:
            full += f" (@{chat.username})"
        full = full.strip()
        if full:
            name_line = f"👤 *Name:* {escape_md(full)}\n"
    except Exception:
        pass

    try:
        stats = get_stats(target_uid)
        banned = is_banned(target_uid)
        status = "🚫 Banned" if banned else "✅ Active"

        text = (
            "👤 *USER DETAILS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 *User ID:* `{target_uid}`\n"
            f"{name_line}"
            f"📌 *Status:* {status}\n\n"
            f"📦 *Accounts:* {stats['total']}\n"
            f"🟢 Active: {stats['active']}  🔴 Dead: {stats['dead']}\n"
            f"🚀 *Campaigns:* {stats['campaigns']}\n"
            f"⚡ *Total Actions:* {stats['actions']}"
        )
    except Exception:
        text = (
            "👤 *USER DETAILS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 *User ID:* `{target_uid}`\n"
            f"{name_line}"
            "⚠️ Could not load full stats for this user."
        )
        banned = is_banned(target_uid)

    has_limit = get_user_account_limit(target_uid) is not None
    await query.edit_message_text(
        text,
        reply_markup=user_detail_menu(
            target_uid,
            banned,
            page,
            has_limit=has_limit,
            is_primary=update.effective_user.id == OWNER_ID,
        ),
        parse_mode="Markdown"
    )


async def user_set_limit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    target_uid = int(query.data.replace("user_set_limit_", ""))
    context.user_data["limit_target_uid"] = target_uid

    current = get_user_account_limit(target_uid)
    current_str = "∞ Unlimited (global default)" if current is None else (
        "∞ Unlimited" if current == 0 else f"{current} accounts"
    )

    await query.edit_message_text(
        f"📊 *SET PERSONAL ACCOUNT LIMIT*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 User: `{target_uid}`\n"
        f"🔢 Current limit: *{current_str}*\n\n"
        "Send a number to set their personal account limit.\n"
        "Send `0` for *unlimited*.\n"
        "Send `reset` to remove the personal limit and use the global default.",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return USER_SET_LIMIT


async def user_set_limit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    raw = update.message.text.strip().lower()
    target_uid = context.user_data.get("limit_target_uid")
    if not target_uid:
        return ConversationHandler.END

    if raw == "reset":
        set_user_account_limit(target_uid, None)
        label = "reset to global default"
        new_val = None
    elif raw.isdigit():
        val = int(raw)
        set_user_account_limit(target_uid, val)
        label = "∞ Unlimited" if val == 0 else f"{val} accounts"
        new_val = val
    else:
        await update.message.reply_text(
            "⚠️ Send a number (e.g. `50`), `0` for unlimited, or `reset` to clear:",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return USER_SET_LIMIT

    page = int(context.user_data.get("user_page", 0))
    context.user_data.pop("limit_target_uid", None)

    await update.message.reply_text(
        f"✅ *Limit Updated!*\n\n"
        f"🆔 User `{target_uid}` — personal limit: *{label if new_val is not None else 'global default'}*",
        reply_markup=back_button(f"user_detail_{target_uid}"),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def user_remove_limit_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    target_uid = int(query.data.replace("user_remove_limit_", ""))
    set_user_account_limit(target_uid, None)
    await query.answer(f"✅ Personal limit removed for {target_uid}.", show_alert=True)
    await user_detail(update, context)


async def ban_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    target_uid = int(query.data.split("_")[-1])

    if target_uid == update.effective_user.id:
        await query.answer("⚠️ You can't ban yourself.", show_alert=True)
        return

    ban_user(target_uid)
    await query.answer(f"🚫 User {target_uid} has been banned.", show_alert=True)
    from handlers.log_gc import send_log, fmt_ban
    await send_log(context.bot, fmt_ban(update.effective_user.id, target_uid, "ban"))
    await user_detail(update, context)


async def unban_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    target_uid = int(query.data.split("_")[-1])
    unban_user(target_uid)
    await query.answer(f"✅ User {target_uid} has been unbanned.", show_alert=True)
    from handlers.log_gc import send_log, fmt_ban
    await send_log(context.bot, fmt_ban(update.effective_user.id, target_uid, "unban"))
    await user_detail(update, context)
