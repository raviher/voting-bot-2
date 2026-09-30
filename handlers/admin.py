from html import escape as escape_html

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from handlers.utils import escape_md
from storage import (
    OWNER_ID, is_owner, get_owner_ids, add_owner_id, remove_owner_id,
    get_all_user_ids, get_banned_users,
    get_required_channels, set_required_channels, clear_required_channels,
    get_account_limit, set_account_limit,
    get_adv_access_users, grant_adv_access, revoke_adv_access, get_adv_access_limit,
    get_maintenance_mode, set_maintenance_mode,
    get_paid_mode, set_paid_mode,
    get_owner_username, set_owner_username,
    get_global_stats,
    get_per_user_camp_limit, set_per_user_camp_limit,
    get_auto_remove_threshold, set_auto_remove_threshold,
    get_audit_log,
    get_log_channel, set_log_channel, clear_log_channel,
    get_global_cooldown_minutes, set_global_cooldown_minutes,
)
from keyboards import (
    owner_panel_menu, owner_panel_menu_with_channel,
    adv_access_list_menu, owners_list_menu, back_button, cancel_button,
    bot_settings_menu, global_cooldown_menu,
)

# Conversation states
(GRANT_ADV_ID, GRANT_ADV_LIMIT, SET_CHANNEL, SET_LIMIT, SET_ADV_USER_LIMIT,
 SET_OWNER_USERNAME, ADD_OWNER_ID, OWNER_MSG_STATE,
 SET_CAMP_LIMIT, SET_AUTO_REMOVE, SET_LOG_CHANNEL, RESTORE_FILE) = range(12)


def _owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_owner(user_id):
            if update.callback_query:
                await update.callback_query.answer("⛔ Owner only.", show_alert=True)
            else:
                await update.message.reply_text("⛔ This action is restricted to the bot owner.")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id

    if query:
        await query.answer()

    if not is_owner(user_id):
        if query:
            await query.answer("⛔ Owner only.", show_alert=True)
        else:
            await update.message.reply_text("⛔ This command is restricted to the bot owner.")
        return

    stats       = get_global_stats()
    adv_users   = get_adv_access_users()
    banned_count = len(get_banned_users())

    import uptime
    text = (
        "<b>👑 OWNER PANEL</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"👥 <b>Users:</b> {stats['users']}\n"
        f"📦 <b>Accounts:</b> {stats['accounts']}  ·  <b>Active:</b> {stats['active']}\n"
        f"🚀 <b>Campaigns:</b> {stats['campaigns']}  ·  <b>Running:</b> {stats['running']}\n"
        f"⚡ <b>Total Actions:</b> {stats['actions']}\n"
        f"📌 <b>ADV Access:</b> {len(adv_users)}  ·  🚫 <b>Banned:</b> {banned_count}\n"
        f"🕐 <b>Uptime:</b> {escape_html(str(uptime.get_uptime_str()))}\n"
    )

    markup = owner_panel_menu(is_primary=user_id == OWNER_ID)
    if query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


# ─── ADV Access Management ────────────────────────────────────────────────────

async def view_adv_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    stats     = get_global_stats()
    total_active = stats["active"]
    adv_users = get_adv_access_users()

    if not adv_users:
        await query.edit_message_text(
            "🌐 *Delegated Adv Campaign Access*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"📦 *Total active accounts in bot:* {total_active}\n\n"
            "_Grant users access to run Adv Campaign using your accounts, "
            "with a limit on how many they can use._\n\n"
            "No users have been granted ADV access yet.\n"
            "Use ➕ Grant Access to add one.",
            reply_markup=adv_access_list_menu(adv_users, {}),
            parse_mode="Markdown"
        )
        return

    # Fetch Telegram names for each ADV user (best-effort)
    names: dict[str, str] = {}
    for uid_str in adv_users:
        try:
            chat = await context.bot.get_chat(int(uid_str))
            full = (chat.first_name or "")
            if chat.last_name:
                full += f" {chat.last_name}"
            if chat.username:
                full += f" (@{chat.username})"
            names[uid_str] = full.strip() or uid_str
        except Exception:
            names[uid_str] = uid_str

    lines = [
        "🌐 *Delegated Adv Campaign Access*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"📦 *Total active accounts in bot:* {total_active}\n\n"
        "_Grant users access to run Adv Campaign using your accounts, "
        "with a limit on how many they can use._\n\n"
        "*Users with access:*"
    ]
    for uid_str, limit in adv_users.items():
        lbl = "∞ Unlimited" if int(limit) == 0 else f"max {limit} accounts"
        display = names.get(uid_str, uid_str)
        lines.append(f"• `{uid_str}` — {escape_md(display)} — {lbl}")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=adv_access_list_menu(adv_users, names),
        parse_mode="Markdown"
    )


async def grant_adv_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    await query.edit_message_text(
        "➕ *GRANT ADV ACCESS*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "Step 1 — Send the *Telegram User ID* of the person you want to grant ADV access.\n\n"
        "💡 They can find their ID via @userinfobot on Telegram.",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return GRANT_ADV_ID


async def grant_adv_receive_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    raw = update.message.text.strip()
    if not raw.lstrip("-").isdigit():
        await update.message.reply_text(
            "⚠️ That doesn't look like a valid user ID. Please send a numeric ID (e.g. `123456789`).",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return GRANT_ADV_ID

    target_id = int(raw)
    if is_owner(target_id):
        await update.message.reply_text(
            "⚠️ That's your own owner ID — you already have full access.",
            reply_markup=cancel_button()
        )
        return GRANT_ADV_ID

    context.user_data["grant_adv_target"] = target_id
    current = get_adv_access_limit(target_id)
    current_str = ""
    if current >= 0:
        current_str = f"\n_Current limit: {'∞ Unlimited' if current == 0 else f'{current} IDs'}_\n"

    await update.message.reply_text(
        f"✅ User ID: `{target_id}`\n{current_str}\n"
        "Step 2 — How many account IDs can this user use for ADV campaigns?\n\n"
        "Send a number (e.g. `50`).\nSend `0` to allow *unlimited* IDs.",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return GRANT_ADV_LIMIT


async def grant_adv_receive_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text(
            "⚠️ Please send a valid number (e.g. `50` or `0` for unlimited):",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return GRANT_ADV_LIMIT

    target_id = context.user_data.get("grant_adv_target")
    if not target_id:
        return ConversationHandler.END

    limit = int(raw)
    grant_adv_access(target_id, limit)
    lbl = "∞ Unlimited" if limit == 0 else f"{limit} IDs"

    await update.message.reply_text(
        f"✅ *ADV Access Granted!*\n\n"
        f"🆔 User `{target_id}` can now run ADV campaigns using *{lbl}*.\n\n"
        "They will see a *📌 Adv Campaign* button in their main menu.",
        reply_markup=back_button("owner_panel"),
        parse_mode="Markdown"
    )
    context.user_data.pop("grant_adv_target", None)
    from handlers.log_gc import send_log, fmt_adv_grant
    await send_log(context.bot, fmt_adv_grant(update.effective_user.id, target_id, limit))
    return ConversationHandler.END


async def revoke_adv_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    # callback_data = "adv_revoke_{uid_str}"
    uid_str = query.data.replace("adv_revoke_", "")
    revoke_adv_access(int(uid_str))
    await query.answer(f"🗑 ADV access revoked for {uid_str}.", show_alert=True)
    from handlers.log_gc import send_log, fmt_adv_revoke
    await send_log(context.bot, fmt_adv_revoke(update.effective_user.id, int(uid_str)))
    await view_adv_users(update, context)


async def adv_set_limit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    # callback_data = "adv_set_limit_{uid_str}"
    uid_str = query.data.replace("adv_set_limit_", "")
    target_id = int(uid_str)
    context.user_data["adv_set_limit_target"] = target_id

    current = get_adv_access_limit(target_id)
    current_str = "∞ Unlimited" if current == 0 else f"{current} IDs"

    await query.edit_message_text(
        f"📊 *SET ADV LIMIT*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"🆔 User: `{target_id}`\n"
        f"🔢 Current limit: *{current_str}*\n\n"
        "Send a new number of IDs this user can use.\n"
        "Send `0` for *unlimited*.",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return SET_ADV_USER_LIMIT


async def adv_set_limit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text(
            "⚠️ Send a valid number or `0` for unlimited:",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return SET_ADV_USER_LIMIT

    target_id = context.user_data.get("adv_set_limit_target")
    if not target_id:
        return ConversationHandler.END

    limit = int(raw)
    grant_adv_access(target_id, limit)
    lbl = "∞ Unlimited" if limit == 0 else f"{limit} IDs"

    await update.message.reply_text(
        f"✅ *Limit updated!*\n\n"
        f"🆔 User `{target_id}` — ADV access: *{lbl}*",
        reply_markup=back_button("adv_access_list"),
        parse_mode="Markdown"
    )
    context.user_data.pop("adv_set_limit_target", None)
    return ConversationHandler.END


# ─── Channel & global limit ───────────────────────────────────────────────────

async def set_req_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    current = get_required_channels()
    current_line = (
        f"📢 *Current:* {', '.join(escape_md(channel) for channel in current)}\n\n"
        if current else ""
    )

    await query.edit_message_text(
        "📢 *SET REQUIRED CHANNEL(S)*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"{current_line}"
        "Send the channel username(s) or link(s) that all users must join before using the bot.\n"
        "Send one per line (or comma-separated) to require multiple channels. "
        "This replaces the current list.\n\n"
        "Examples:\n"
        "`@mychannel`\n"
        "`@mychannel, @mysecondchannel`\n"
        "`https://t.me/mychannel`\n\n"
        "⚠️ Make sure this bot is an *admin* of every channel so it can verify members.",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return SET_CHANNEL


async def set_req_channel_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    raw = update.message.text.strip()
    parts = [p.strip() for chunk in raw.split(",") for p in chunk.split("\n")]
    channels = [p for p in parts if p]

    if not channels:
        await update.message.reply_text(
            "⚠️ No valid channels found. Please send at least one channel username or link.",
            reply_markup=cancel_button()
        )
        return SET_CHANNEL

    set_required_channels(channels)
    saved = get_required_channels()

    await update.message.reply_text(
        f"✅ *Required Channel(s) Set!*\n\n"
        f"📢 Channels:\n"
        + "\n".join(f"• {escape_md(channel)}" for channel in saved)
        + "\n\n"
        "All users must now join these channels before using the bot.",
        reply_markup=back_button("owner_panel"),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def clear_req_channel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    clear_required_channels()
    await query.answer("✅ Channel requirement removed.", show_alert=True)
    await owner_panel(update, context)


async def set_limit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END
    current = get_account_limit()
    current_label = "∞ Unlimited" if current == 0 else f"{current} accounts per user"
    await query.edit_message_text(
        "📊🟡 *SET ACCOUNT LIMIT*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"🔢 *Current limit:* {current_label}\n\n"
        "Send a number to set how many accounts each user can add.\n"
        "Send `0` to allow *unlimited* accounts.\n\n"
        "💡 Example: `50` means each user can add up to 50 accounts.",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return SET_LIMIT


async def set_limit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text(
            "⚠️ Please send a valid number (e.g. `50` or `0` for unlimited):",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return SET_LIMIT
    limit = int(raw)
    set_account_limit(limit)
    label = "∞ Unlimited" if limit == 0 else f"{limit} accounts per user"
    await update.message.reply_text(
        f"✅ *Account Limit Updated!*\n\n"
        f"📊 New limit: *{label}*\n\n"
        "All new account additions will be checked against this limit.",
        reply_markup=back_button("owner_panel"),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def set_log_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END
    current = get_log_channel()
    current_line = f"📋 *Current:* `{current}`\n\n" if current else ""
    await query.edit_message_text(
        "📋 *SET LOG GROUP CHANNEL*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"{current_line}"
        "Forward any message from your log group/channel here, or send its *Chat ID* directly.\n\n"
        "💡 Add the bot as admin in the group/channel first.\n"
        "Example: `-1001234567890`",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return SET_LOG_CHANNEL


async def set_log_channel_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    # Support forwarded messages (extract chat id) or plain text id
    msg = update.message
    if msg.forward_origin or getattr(msg, "forward_from_chat", None):
        chat = getattr(msg, "forward_from_chat", None) or getattr(msg.forward_origin, "chat", None)
        if chat:
            channel_id = chat.id
        else:
            await msg.reply_text("⚠️ Couldn't read chat from forwarded message. Send the Chat ID directly:", reply_markup=cancel_button())
            return SET_LOG_CHANNEL
    else:
        raw = msg.text.strip().lstrip("@")
        if not raw.lstrip("-").isdigit():
            await msg.reply_text(
                "⚠️ Invalid ID. Send a numeric chat ID (e.g. `-1001234567890`) or forward a message from the group:",
                reply_markup=cancel_button(), parse_mode="Markdown",
            )
            return SET_LOG_CHANNEL
        channel_id = int(raw)

    # Test that the bot can send to it
    try:
        test = await context.bot.send_message(
            chat_id=channel_id,
            text="✅ <b>Log GC connected!</b>\n\nBot events will be logged here.",
            parse_mode="HTML",
        )
    except Exception as exc:
        await msg.reply_text(
            f"❌ Could not send to `{channel_id}`:\n`{str(exc)[:200]}`\n\n"
            "Make sure the bot is an admin in that group/channel.",
            reply_markup=cancel_button(), parse_mode="Markdown",
        )
        return SET_LOG_CHANNEL

    set_log_channel(channel_id)
    await msg.reply_text(
        f"✅ *Log GC Set!*\n\n📋 Chat ID: `{channel_id}`\n\nAll bot events will now be forwarded there.",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def clear_log_channel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    clear_log_channel()
    await query.answer("✅ Log GC cleared.", show_alert=True)
    await bot_settings_panel(update, context)


async def db_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dump the entire PostgreSQL database via psycopg2 and send as a .sql file."""
    query = update.callback_query
    await query.answer("⏳ Generating backup…", show_alert=False)

    import io
    import os
    import psycopg2
    import psycopg2.extras
    from datetime import datetime, timezone

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        await query.answer("⚠️ DATABASE_URL not set.", show_alert=True)
        return

    await query.edit_message_text(
        "💾 *Database Backup*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "⏳ Generating backup… please wait.",
        parse_mode="Markdown",
    )

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        lines = []
        lines.append("-- Database backup generated by bot")
        lines.append(f"-- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        lines.append("SET client_encoding = 'UTF8';")
        lines.append("SET standard_conforming_strings = on;")
        lines.append("")

        # Get all user tables
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        tables = [row[0] for row in cur.fetchall()]

        for table in tables:
            lines.append(f"-- Table: {table}")

            # Get column names
            cur.execute(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
            """, (table,))
            columns = [row[0] for row in cur.fetchall()]
            col_list = ", ".join(f'"{c}"' for c in columns)

            # Get rows
            cur.execute(f'SELECT * FROM public."{table}"')
            rows = cur.fetchall()

            if rows:
                import json as _json
                for row in rows:
                    vals = []
                    for v in row:
                        if v is None:
                            vals.append("NULL")
                        elif isinstance(v, bool):
                            vals.append("TRUE" if v else "FALSE")
                        elif isinstance(v, (int, float)):
                            vals.append(str(v))
                        elif isinstance(v, (dict, list)):
                            # JSONB — serialize as proper JSON, not Python repr
                            escaped = _json.dumps(v, ensure_ascii=False).replace("'", "''")
                            vals.append(f"'{escaped}'")
                        else:
                            escaped = str(v).replace("'", "''")
                            vals.append(f"'{escaped}'")
                    val_list = ", ".join(vals)
                    lines.append(
                        f'INSERT INTO public."{table}" ({col_list}) '
                        f'VALUES ({val_list}) ON CONFLICT DO NOTHING;'
                    )
            else:
                lines.append(f"-- (no rows in {table})")
            lines.append("")

        cur.close()
        conn.close()

        sql_bytes = "\n".join(lines).encode("utf-8")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"db_backup_{ts}.sql"
        size_kb = len(sql_bytes) / 1024

        await query.message.reply_document(
            document=io.BytesIO(sql_bytes),
            filename=filename,
            caption=(
                f"💾 *Database Backup*\n"
                f"📅 `{ts} UTC`\n"
                f"📦 Size: `{size_kb:.1f} KB`\n\n"
                "To restore:\n"
                "`psql $DATABASE_URL < db_backup.sql`"
            ),
            parse_mode="Markdown",
        )
        await query.edit_message_text(
            "✅ *Backup complete!*\n\n"
            f"📦 `{filename}` sent above.\n\n"
            "Download and keep it safe — it contains all accounts, campaigns, schedules and settings.",
            reply_markup=back_button("bot_settings"),
            parse_mode="Markdown",
        )
    except Exception as exc:
        await query.edit_message_text(
            f"❌ *Backup error:* `{str(exc)[:200]}`",
            reply_markup=back_button("bot_settings"),
            parse_mode="Markdown",
        )


async def db_restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt the primary owner to upload a .sql backup file."""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Primary owner only.", show_alert=True)
        return ConversationHandler.END

    await query.edit_message_text(
        "📥 *Restore Database Backup*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "⚠️ *Warning:* Restoring will re-apply all INSERT statements from the backup file.\n"
        "Existing rows with the same primary key are kept (ON CONFLICT DO NOTHING).\n\n"
        "📎 Send your `.sql` backup file now, or press Cancel.",
        reply_markup=back_button("bot_settings"),
        parse_mode="Markdown",
    )
    return RESTORE_FILE


async def db_restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the .sql file and execute it against the database."""
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END

    import io
    import os
    import psycopg2

    doc = update.message.document
    if not doc:
        await update.message.reply_text(
            "⚠️ Please send a `.sql` file.",
            reply_markup=back_button("bot_settings"),
            parse_mode="Markdown",
        )
        return RESTORE_FILE

    if not doc.file_name.lower().endswith(".sql"):
        await update.message.reply_text(
            "❌ Only `.sql` files are accepted. Please send a valid backup file.",
            reply_markup=back_button("bot_settings"),
            parse_mode="Markdown",
        )
        return RESTORE_FILE

    status_msg = await update.message.reply_text(
        "⏳ *Restoring backup…* please wait.",
        parse_mode="Markdown",
    )

    try:
        tg_file = await doc.get_file()
        buf = io.BytesIO()
        await tg_file.download_to_memory(buf)
        sql_text = buf.getvalue().decode("utf-8")

        db_url = os.environ.get("DATABASE_URL", "")
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        cur = conn.cursor()

        # ── pg_dump-aware parser ───────────────────────────────────────────
        # Handles:
        #   • \restrict / \unrestrict and any other psql \ meta-commands → skip
        #   • COPY table (...) FROM stdin; blocks  → cur.copy_expert()
        #   • All other multi-line SQL statements  → cur.execute()
        executed = 0
        copy_sql = None          # COPY command header
        copy_buf = None          # StringIO collecting COPY data rows
        stmt_buf = []            # accumulates a multi-line SQL statement

        def _flush_stmt(cur, buf_lines):
            """Join accumulated lines, strip trailing ;, execute."""
            stmt = "\n".join(buf_lines).strip().rstrip(";").strip()
            if stmt:
                cur.execute(stmt)
                return 1
            return 0

        for raw_line in sql_text.splitlines():
            line = raw_line.rstrip("\r")

            # ── Inside a COPY data block ───────────────────────────────────
            if copy_buf is not None:
                if line == "\\.":
                    # End of COPY block — flush to DB
                    copy_buf.seek(0)
                    cur.copy_expert(copy_sql, copy_buf)
                    executed += 1
                    copy_buf = None
                    copy_sql = None
                else:
                    copy_buf.write(line + "\n")
                continue

            # ── Skip blank lines and SQL comments ─────────────────────────
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                # A blank line between statements — flush any pending stmt
                if stmt_buf:
                    try:
                        executed += _flush_stmt(cur, stmt_buf)
                    except Exception:
                        pass  # DDL that doesn't apply is OK to skip
                    stmt_buf = []
                continue

            # ── Skip psql meta-commands (\restrict, \set, \connect, etc.) ─
            if stripped.startswith("\\"):
                continue

            # ── Detect start of a COPY … FROM stdin block ─────────────────
            upper = stripped.upper()
            if upper.startswith("COPY ") and "FROM STDIN" in upper:
                # Flush any accumulated SQL first
                if stmt_buf:
                    try:
                        executed += _flush_stmt(cur, stmt_buf)
                    except Exception:
                        pass
                    stmt_buf = []
                copy_sql = stripped  # keep the full COPY … FROM STDIN; line
                copy_buf = io.StringIO()
                continue

            # ── Normal SQL — accumulate until line ends with ; ─────────────
            stmt_buf.append(line)
            if stripped.endswith(";"):
                try:
                    executed += _flush_stmt(cur, stmt_buf)
                except Exception:
                    pass  # skip un-applicable DDL (e.g. already exists)
                stmt_buf = []

        # Flush any trailing statement without a final semicolon
        if stmt_buf:
            try:
                executed += _flush_stmt(cur, stmt_buf)
            except Exception:
                pass

        conn.commit()
        cur.close()
        conn.close()

        await status_msg.edit_text(
            f"✅ *Restore Complete!*\n\n"
            f"📄 File: `{doc.file_name}`\n"
            f"📊 Statements executed: `{executed}`\n\n"
            "All data has been restored successfully.",
            reply_markup=back_button("bot_settings"),
            parse_mode="Markdown",
        )
    except Exception as exc:
        await status_msg.edit_text(
            f"❌ *Restore failed:*\n`{str(exc)[:300]}`",
            reply_markup=back_button("bot_settings"),
            parse_mode="Markdown",
        )

    return ConversationHandler.END


async def bot_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    maintenance = get_maintenance_mode()
    paid_mode = get_paid_mode()
    channels = get_required_channels()
    owner_username = get_owner_username()
    channel_label = (
        ", ".join(escape_html(str(channel)) for channel in channels)
        if channels else "Not Set"
    )

    text = (
        "<b>⚙️ BOT SETTINGS</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"🛠 <b>Maintenance:</b> {'ON 🟢' if maintenance else 'OFF 🔴'}\n"
        f"📢 <b>FSub Channel(s):</b> {channel_label}\n"
        f"💎 <b>Paid Mode:</b> {'ON 🟢' if paid_mode else 'OFF 🔴'}\n"
        f"👤 <b>Owner:</b> {escape_html(str(owner_username)) if owner_username else 'Not Set'}\n\n"
        "<i>Paid Mode ON → free users see a purchase popup on action buttons.</i>"
    )
    limit = get_account_limit()
    log_ch = get_log_channel()
    global_cd = get_global_cooldown_minutes()
    try:
        await query.edit_message_text(
            text,
            reply_markup=bot_settings_menu(maintenance, paid_mode, channels, owner_username, limit, is_primary=(user_id == OWNER_ID), log_channel=log_ch, global_cooldown=global_cd),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            raise


async def global_cooldown_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show global cooldown picker (owner only)."""
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    current = get_global_cooldown_minutes()
    _CD_LABELS = {0: "Off", 5: "5 min", 15: "15 min", 30: "30 min",
                  60: "1 hour", 120: "2 hours", 360: "6 hours", 720: "12 hours"}
    cur_label = _CD_LABELS.get(current, f"{current} min") if current else "Off"
    await query.edit_message_text(
        "⏱ *Global Cooldown*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"Currently: *{cur_label}*\n\n"
        "Set a cooldown that applies to *all users*. After each campaign run, "
        "accounts cannot be reused until this time has passed.\n\n"
        "_When set, this overrides each user's personal cooldown setting._",
        reply_markup=global_cooldown_menu(current),
        parse_mode="Markdown"
    )


async def set_global_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: global_cooldown_<minutes>"""
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    minutes = int(query.data.split("_")[-1])
    set_global_cooldown_minutes(minutes)
    _CD_LABELS = {0: "Off", 5: "5 min", 15: "15 min", 30: "30 min",
                  60: "1 hour", 120: "2 hours", 360: "6 hours", 720: "12 hours"}
    label = _CD_LABELS.get(minutes, f"{minutes} min") if minutes else "Off"
    await query.answer(f"⏱ Global cooldown set to {label}.", show_alert=True)
    await global_cooldown_select(update, context)


async def toggle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    new_state = not get_maintenance_mode()
    set_maintenance_mode(new_state)
    await query.answer(f"🛠 Maintenance mode {'enabled' if new_state else 'disabled'}.", show_alert=True)
    from handlers.log_gc import send_log, fmt_maintenance
    await send_log(context.bot, fmt_maintenance(update.effective_user.id, new_state))
    await bot_settings_panel(update, context)


async def toggle_paid_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    new_state = not get_paid_mode()
    set_paid_mode(new_state)
    await query.answer(f"💎 Paid mode {'enabled' if new_state else 'disabled'}.", show_alert=True)
    from handlers.log_gc import send_log, fmt_paid_mode
    await send_log(context.bot, fmt_paid_mode(update.effective_user.id, new_state))
    await bot_settings_panel(update, context)


async def set_owner_username_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    current = get_owner_username()
    current_line = (
        f"👤 <b>Current:</b> {escape_html(str(current))}\n\n"
        if current else ""
    )

    await query.edit_message_text(
        "<b>👤 SET OWNER USERNAME</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"{current_line}"
        "Send the Telegram @username users should contact "
        "(e.g. for support or to buy paid access).\n\n"
        "Example: <code>@YOU_KNOW_RAVI_XD</code>",
        reply_markup=cancel_button(),
        parse_mode="HTML"
    )
    return SET_OWNER_USERNAME


async def set_owner_username_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    username = update.message.text.strip()
    set_owner_username(username)
    saved = get_owner_username()

    await update.message.reply_text(
        f"✅ <b>Owner Username Updated!</b>\n\n👤 {escape_html(str(saved))}",
        reply_markup=back_button("bot_settings"),
        parse_mode="HTML"
    )
    return ConversationHandler.END


# ─── Co-owner Management ──────────────────────────────────────────────────────

async def view_owners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    owner_ids = get_owner_ids()
    names: dict[int, str] = {}
    for uid in owner_ids:
        try:
            chat = await context.bot.get_chat(uid)
            full = (chat.first_name or "")
            if chat.last_name:
                full += f" {chat.last_name}"
            if chat.username:
                full += f" (@{chat.username})"
            names[uid] = full.strip() or str(uid)
        except Exception:
            names[uid] = str(uid)

    lines = [
        "👑 *CO-OWNERS*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"Total owners: *{len(owner_ids)}*\n\n"
        "_Co-owners have full access to the Owner Panel._\n"
    ]
    for uid in owner_ids:
        lines.append(f"• `{uid}` — {escape_md(names.get(uid, str(uid)))}")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=owners_list_menu(owner_ids, OWNER_ID, names),
        parse_mode="Markdown",
    )


async def add_owner_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    await query.edit_message_text(
        "👑 *ADD CO-OWNER*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "Send the *Telegram User ID* of the person to grant owner access.\n\n"
        "💡 They can find their ID via @userinfobot on Telegram.",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return ADD_OWNER_ID


async def add_owner_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id != OWNER_ID:
        return ConversationHandler.END

    raw = update.message.text.strip()
    if not raw.lstrip("-").isdigit():
        await update.message.reply_text(
            "⚠️ That doesn't look like a valid user ID. Please send a numeric ID (e.g. `123456789`).",
            reply_markup=cancel_button(), parse_mode="Markdown",
        )
        return ADD_OWNER_ID

    target_id = int(raw)
    if is_owner(target_id):
        await update.message.reply_text(
            "⚠️ That user is already an owner.",
            reply_markup=back_button("owners_list"),
        )
        return ConversationHandler.END

    add_owner_id(target_id)
    await update.message.reply_text(
        f"✅ *Co-owner Added!*\n\n"
        f"🆔 `{target_id}` now has full Owner Panel access.\n\n"
        "They will see the ❤️ *Owner Panel* button in their main menu.",
        reply_markup=back_button("owners_list"),
        parse_mode="Markdown",
    )
    from handlers.log_gc import send_log, fmt_owner_added
    await send_log(context.bot, fmt_owner_added(update.effective_user.id, target_id))
    return ConversationHandler.END


async def remove_owner_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Owner only.", show_alert=True)
        return

    uid_str = query.data.replace("owner_remove_", "")
    target_id = int(uid_str)

    if target_id == OWNER_ID:
        await query.answer("⛔ The primary owner cannot be removed.", show_alert=True)
        return

    removed = remove_owner_id(target_id)
    if removed:
        await query.answer(f"✅ Owner {uid_str} removed.", show_alert=True)
        from handlers.log_gc import send_log, fmt_owner_removed
        await send_log(context.bot, fmt_owner_removed(update.effective_user.id, target_id))
    else:
        await query.answer(f"⚠️ User {uid_str} was not an owner.", show_alert=True)
    await view_owners(update, context)


async def owner_msg_users_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start conversation: owner composes a message to broadcast to all bot users."""
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END

    total_users = len(get_all_user_ids())
    await query.edit_message_text(
        "📣 *MESSAGE ALL USERS*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"📊 Will be sent to *{total_users}* registered user(s).\n\n"
        "Type the message you want to send:\n"
        "_(Supports Markdown formatting)_",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return OWNER_MSG_STATE


async def owner_msg_users_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the message and broadcast it to all users."""
    import logging
    _log = logging.getLogger(__name__)
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("⚠️ Empty message. Try again:", reply_markup=cancel_button())
        return OWNER_MSG_STATE

    user_ids = get_all_user_ids()
    sent = failed = 0
    status_msg = await update.message.reply_text(
        f"📣 Sending to {len(user_ids)} users…"
    )

    for uid_str in user_ids:
        try:
            await context.bot.send_message(
                chat_id=int(uid_str),
                text=f"📣 *Message from Owner*\n\n{text}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception as e:
            _log.debug("Could not send to %s: %s", uid_str, e)
            failed += 1

    await status_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"📤 Sent: {sent}   ❌ Failed: {failed}"
        f"\n_(Failed = user blocked the bot or never started it)_",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
    from handlers.start import start_handler
    await start_handler(update, context)
    return ConversationHandler.END


# ─── Per-user campaign limit ──────────────────────────────────────────────────

async def set_per_user_camp_limit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END
    current = get_per_user_camp_limit()
    label = "∞ Unlimited" if current == 0 else f"{current} campaigns per user"
    await query.edit_message_text(
        "🎯 *SET CAMPAIGN LIMIT*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"🔢 *Current limit:* {label}\n\n"
        "Send a number to limit how many campaigns each user can create.\n"
        "Send `0` for *unlimited*.\n\n"
        "💡 Example: `10` means each user can have up to 10 campaigns.",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return SET_CAMP_LIMIT


async def set_per_user_camp_limit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text(
            "⚠️ Please send a valid number (e.g. `10` or `0` for unlimited):",
            reply_markup=cancel_button(), parse_mode="Markdown",
        )
        return SET_CAMP_LIMIT
    limit = int(raw)
    set_per_user_camp_limit(limit)
    label = "∞ Unlimited" if limit == 0 else f"{limit} campaigns per user"
    await update.message.reply_text(
        f"✅ *Campaign Limit Updated!*\n\n📊 New limit: *{label}*",
        reply_markup=back_button("owner_panel"),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─── Auto-remove threshold ────────────────────────────────────────────────────

async def set_auto_remove_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return ConversationHandler.END
    current = get_auto_remove_threshold()
    label = "Disabled" if current == 0 else f"Remove after {current} consecutive failures"
    await query.edit_message_text(
        "🗑 *AUTO-REMOVE DEAD ACCOUNTS*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"⚙️ *Current:* {label}\n\n"
        "Accounts with N or more consecutive failures are automatically deleted after a campaign run.\n\n"
        "Send a number (e.g. `5`) or `0` to disable auto-remove:",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return SET_AUTO_REMOVE


async def set_auto_remove_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text(
            "⚠️ Please send a valid number (e.g. `5` or `0` to disable):",
            reply_markup=cancel_button(), parse_mode="Markdown",
        )
        return SET_AUTO_REMOVE
    threshold = int(raw)
    set_auto_remove_threshold(threshold)
    label = "Disabled" if threshold == 0 else f"Remove after {threshold} consecutive failures"
    await update.message.reply_text(
        f"✅ *Auto-Remove Updated!*\n\n🗑 {label}",
        reply_markup=back_button("owner_panel"),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─── Audit log ────────────────────────────────────────────────────────────────

async def view_audit_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    log = get_audit_log(50)
    if not log:
        await query.edit_message_text(
            "📋 *AUDIT LOG*\n\nNo entries yet.",
            reply_markup=back_button("owner_panel"),
            parse_mode="Markdown",
        )
        return
    lines = []
    for entry in reversed(log[-20:]):
        lines.append(
            f"🕐 `{entry.get('ts','')}` — "
            f"user `{entry.get('user_id','')}` — "
            f"{entry.get('action','')} {entry.get('details','')}"
        )
    await query.edit_message_text(
        "📋 *AUDIT LOG* _(last 20 entries)_\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        + "\n".join(lines),
        reply_markup=back_button("owner_panel"),
        parse_mode="Markdown",
    )
