import os
import asyncio
import zipfile
import io
import time
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from storage import (
    get_accounts, add_account, remove_account, toggle_account_status,
    is_account_duplicate, add_account_label, remove_account_label,
)
from keyboards import (
    accounts_menu, account_actions, account_labels_menu,
    account_delete_confirm_menu, back_button, cancel_button, add_account_method_menu,
)

logger = logging.getLogger(__name__)

ACCOUNT_METHOD, ACCOUNT_PHONE, ACCOUNT_OTP, ACCOUNT_2FA, ACCOUNT_SESSION, ACCOUNT_BULK, ACCOUNT_BULK_ZIP = range(7)
ACC_LABEL = 7   # extra state for label-add conversation

API_ID   = int(os.environ.get("PYROGRAM_API_ID") or os.environ.get("API_ID") or "0")
API_HASH = os.environ.get("PYROGRAM_API_HASH") or os.environ.get("API_HASH") or ""

VERIFY_WORKERS = 10        # parallel login workers for ZIP batch
PROGRESS_THROTTLE = 2.0    # min seconds between progress bar edits
SQLITE_MAGIC = b"SQLite format 3\x00"  # first 16 bytes of every SQLite3 file

# Keep interactive account checks aligned with the owner session-health
# report. These are Telegram authorization failures, not network timeouts.
_EXPIRED_SESSION_ERRORS = (
    "AUTH_KEY_INVALID",
    "SESSION_EXPIRED",
    "SESSION_REVOKED",
    "USER_DEACTIVATED",
    "USER_DEACTIVATED_BAN",
    "ACCOUNT_BANNED",
    "USER_BANNED",
)


def _is_expired_session_error(error: BaseException) -> bool:
    text = str(error).upper().replace(" ", "_").replace("-", "_")
    return any(marker in text for marker in _EXPIRED_SESSION_ERRORS)


def _stored_session_string(account: dict) -> str:
    """Return a usable session field, not a phone-number identifier."""
    for field in ("session_string", "session", "identifier"):
        value = account.get(field)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) >= 20 and not value.startswith("+"):
            return value
    return ""


# Pyrogram 2.0.106 SQLite session schema (verbatim from pyrogram/storage/sqlite_storage.py)
_PYROGRAM_SCHEMA = """
CREATE TABLE sessions (
    dc_id     INTEGER PRIMARY KEY,
    api_id    INTEGER,
    test_mode INTEGER,
    auth_key  BLOB,
    date      INTEGER NOT NULL,
    user_id   INTEGER,
    is_bot    INTEGER
);
CREATE TABLE peers (
    id             INTEGER PRIMARY KEY,
    access_hash    INTEGER,
    type           INTEGER NOT NULL,
    username       TEXT,
    phone_number   TEXT,
    last_update_on INTEGER NOT NULL DEFAULT (CAST(STRFTIME('%s', 'now') AS INTEGER))
);
CREATE TABLE version (
    number INTEGER PRIMARY KEY
);
CREATE INDEX idx_peers_id ON peers (id);
CREATE INDEX idx_peers_username ON peers (username);
CREATE INDEX idx_peers_phone_number ON peers (phone_number);
"""


def _prepare_session_file(session_bytes: bytes, dest_path: str) -> bool:
    """
    Write session data to dest_path (WITHOUT .session extension).
    Handles both Pyrogram and Telethon SQLite sessions.
    Telethon sessions are converted to a Pyrogram-compatible file.
    Returns True on success.
    """
    import sqlite3

    raw_path = dest_path + ".session"
    # Write raw bytes so we can inspect the schema
    with open(raw_path, "wb") as fh:
        fh.write(session_bytes)

    try:
        with sqlite3.connect(raw_path) as db:
            tables = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            is_telethon = "entities" in tables  # Telethon-specific table

            if not is_telethon:
                # Already Pyrogram — patch schema & version in-place
                db.executescript(_PYROGRAM_SCHEMA)
                db.execute("INSERT OR IGNORE INTO version VALUES (3)")
                db.commit()
                return True

            # Telethon: extract dc_id + auth_key from its sessions table
            row = db.execute(
                "SELECT dc_id, auth_key FROM sessions ORDER BY dc_id LIMIT 1"
            ).fetchone()
            if not row:
                logger.warning("Telethon session has no rows in sessions table")
                return False
            dc_id, auth_key = row
            if isinstance(auth_key, str):
                auth_key = auth_key.encode("latin-1")
            auth_key = bytes(auth_key)
    except Exception as e:
        logger.warning("Session inspect failed: %s", e)
        return False

    # Replace the Telethon file with a fresh Pyrogram-compatible one
    try:
        os.remove(raw_path)
        with sqlite3.connect(raw_path) as db:
            db.executescript(_PYROGRAM_SCHEMA)
            db.execute(
                "INSERT OR REPLACE INTO sessions "
                "(dc_id, api_id, test_mode, auth_key, date, user_id, is_bot) "
                "VALUES (?, ?, 0, ?, CAST(STRFTIME('%s', 'now') AS INTEGER), 1, 0)",
                (dc_id, API_ID, auth_key),
            )
            db.execute("INSERT OR REPLACE INTO version VALUES (3)")
            db.commit()
        logger.info("Converted Telethon session → Pyrogram (dc_id=%d)", dc_id)
        return True
    except Exception as e:
        logger.warning("Telethon→Pyrogram conversion failed: %s", e)
        return False


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _short(s: str) -> str:
    return s[:10] + "..." + s[-6:] if len(s) > 20 else s

def _bar(done: int, total: int, width: int = 10) -> str:
    filled = int(width * done / total) if total else 0
    return "█" * filled + "░" * (width - filled)


# ─── View / manage ───────────────────────────────────────────────────────────

async def my_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)
    query = update.callback_query
    if query:
        await query.answer()

    if not accounts:
        text = (
            "✅ *My Accounts*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "No accounts yet.\nPress 🤖 Add Account to get started."
        )
    else:
        active = sum(1 for a in accounts if a.get("status") == "active")
        frozen = sum(1 for a in accounts if a.get("status") in ("frozen", "banned"))
        dead   = len(accounts) - active - frozen
        frozen_line = f"   🧊 Frozen/Banned: {frozen}" if frozen else ""
        PAGE_SIZE = 8
        total_pages = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
        page_info = f"   📄 Page {page + 1}/{total_pages}" if total_pages > 1 else ""
        text = (
            "✅ *My Accounts*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"🟢 Active: {active}   🔴 Dead: {dead}{frozen_line}   📦 Total: {len(accounts)}{page_info}\n\n"
            "Select an account to manage it:"
        )

    markup = accounts_menu(accounts, page=page)
    if query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def accounts_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle prev/next page buttons for the accounts list."""
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[-1])
    await my_accounts(update, context, page=page)


async def account_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    accounts = get_accounts(update.effective_user.id)
    if index >= len(accounts):
        await query.edit_message_text("Account not found.", reply_markup=back_button("my_accounts"))
        return
    acc = accounts[index]
    _status_display = {
        "active": "🟢 Active",
        "frozen": "🧊 Frozen",
        "banned": "🚫 Banned",
        "dead":   "🔴 Dead",
        "expired": "🔴 Expired",
        "reauth_required": "🟠 Re-login required",
    }
    status_icon = _status_display.get(acc.get("status", ""), "🔴 Dead")
    method_label = {"phone": "📱 Phone+OTP", "session": "✅ Session", "bulk": "📦 Bulk"}.get(acc.get("method",""), acc.get("method",""))
    ident = acc.get("identifier", "N/A")

    # Throttle visibility
    throttle_line = ""
    throttled_until = acc.get("throttled_until", 0)
    if throttled_until and time.time() < throttled_until:
        remaining = int(throttled_until - time.time())
        throttle_line = f"\n⏳ *Rate limited:* {remaining}s remaining"

    # Consecutive failures
    failures = acc.get("consecutive_failures", 0)
    failures_line = f"\n⚠️ *Consecutive failures:* {failures}" if failures >= 1 else ""

    # Per-account success / fail counters
    sc = acc.get("success_count", 0)
    fc = acc.get("fail_count", 0)
    stats_line = f"\n📊 *Actions:* ✅ {sc} success  ❌ {fc} failed" if (sc or fc) else ""

    # Last-used timestamp
    last_used_ts = acc.get("last_used")
    if last_used_ts:
        from datetime import datetime as _dt
        last_used_str = _dt.fromtimestamp(last_used_ts).strftime("%Y-%m-%d %H:%M")
        last_used_line = f"\n🕐 *Last used:* {last_used_str}"
    else:
        last_used_line = ""

    # Session expiry warning: flag accounts added > 30 days ago
    expiry_line = ""
    added_str = acc.get("added", "")
    if added_str:
        try:
            from datetime import datetime as _dt, timedelta as _td
            added_dt = _dt.strptime(added_str[:16], "%Y-%m-%d %H:%M")
            if (_dt.now() - added_dt) > _td(days=30):
                expiry_line = "\n⚠️ *Session added >30 days ago — consider refreshing.*"
        except Exception:
            pass

    # Labels
    labels = acc.get("labels", [])
    labels_line = f"\n🏷 *Labels:* {', '.join(labels)}" if labels else ""

    text = (
        "📄 *Account Details*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"👤 *Name:* {acc.get('name','N/A')}\n"
        f"🔗 *ID:* `{_short(ident)}`\n"
        f"🔌 *Method:* {method_label}\n"
        f"📌 *Status:* {status_icon}"
        f"{throttle_line}"
        f"{failures_line}"
        f"{stats_line}"
        f"{last_used_line}"
        f"{labels_line}"
        f"{expiry_line}\n"
        f"📅 *Added:* {acc.get('added','N/A')}"
    )
    await query.edit_message_text(
        text,
        reply_markup=account_actions(index, acc.get("status", "active"), labels=labels),
        parse_mode="Markdown",
    )


async def bulk_health_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick-scan all accounts in parallel and show a summary."""
    query = update.callback_query
    await query.answer("🔍 Running bulk health check…", show_alert=False)
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)
    if not accounts:
        await query.answer("No accounts to check.", show_alert=True)
        return

    _API_ID   = int(os.environ.get("PYROGRAM_API_ID",  "0") or "0")
    _API_HASH = os.environ.get("PYROGRAM_API_HASH", "") or ""

    if not _API_ID or not _API_HASH:
        await query.edit_message_text(
            "⚠️ Pyrogram credentials not configured.",
            reply_markup=back_button("my_accounts"),
        )
        return

    total = len(accounts)
    prog = await query.edit_message_text(
        f"🔍 *Bulk Health Check*\n\n"
        f"Checking {total} account(s)…  0 / {total} done",
        parse_mode="Markdown",
    )

    from pyrogram import Client
    from storage import set_account_status
    import hashlib

    active = dead = errors = 0
    newly_dead = []
    sem = asyncio.Semaphore(8)
    lock = asyncio.Lock()
    done_count = [0]

    async def check_one(idx: int, acc: dict) -> None:
        nonlocal active, dead, errors
        identifier = _stored_session_string(acc)
        if not identifier:
            async with lock:
                errors += 1
                done_count[0] += 1
            return
        try:
            async with sem:
                client_name = (
                    f"hc_{user_id}_{idx}_"
                    f"{hashlib.sha256(identifier.encode('utf-8')).hexdigest()[:12]}"
                )
                async with Client(client_name, api_id=_API_ID, api_hash=_API_HASH,
                                  session_string=identifier, no_updates=True, in_memory=True) as c:
                    await asyncio.wait_for(c.get_me(), timeout=10)
            async with lock:
                active += 1
                if acc.get("status") in {
                    "dead",
                    "expired",
                    "unverified",
                    "reauth_required",
                }:
                    set_account_status(user_id, idx, "active")
                done_count[0] += 1
        except Exception as e:
            err = str(e).upper()
            async with lock:
                if (
                    "AUTH_KEY_UNREGISTERED" not in err
                    and _is_expired_session_error(e)
                ):
                    dead += 1
                    if acc.get("status") != "reauth_required":
                        newly_dead.append(acc.get("name", "?"))
                        set_account_status(user_id, idx, "reauth_required")
                else:
                    errors += 1
                done_count[0] += 1
            # throttle progress updates
            if done_count[0] % 5 == 0 or done_count[0] == total:
                try:
                    await prog.edit_text(
                        f"🔍 *Bulk Health Check*\n\n"
                        f"Checking {total} account(s)…  {done_count[0]} / {total} done",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

    tasks = [check_one(i, acc) for i, acc in enumerate(accounts)]
    await asyncio.gather(*tasks)

    dead_names = "\n".join(f"• {n}" for n in newly_dead[:10]) if newly_dead else "None"
    await prog.edit_text(
        f"✅ *Bulk Health Check Complete*\n\n"
        f"🟢 Active: {active}  🔴 Dead: {dead}  ⚠️ Errors: {errors}\n"
        f"📦 Total checked: {total}\n\n"
        + (f"🔴 *Newly marked dead:*\n{dead_names}" if newly_dead else ""),
        reply_markup=back_button("my_accounts"),
        parse_mode="Markdown",
    )


async def account_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show confirmation prompt before deleting account."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    accounts = get_accounts(update.effective_user.id)
    name = accounts[index].get("name", f"Account {index+1}") if index < len(accounts) else "?"
    await query.edit_message_text(
        f"⚠️ *Delete Account?*\n\n`{name}`\n\nThis cannot be undone.",
        reply_markup=account_delete_confirm_menu(index),
        parse_mode="Markdown",
    )


async def account_health_single(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a quick health check on a single account."""
    query = update.callback_query
    await query.answer("🔍 Checking...", show_alert=False)
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)
    if index >= len(accounts):
        await query.answer("Account not found.", show_alert=True)
        return

    acc = accounts[index]
    identifier = _stored_session_string(acc)
    if not identifier:
        await query.answer("No session string found.", show_alert=True)
        return

    await query.edit_message_text(
        f"🔍 *Checking account…*\n\n👤 {acc.get('name','?')}",
        parse_mode="Markdown"
    )

    try:
        from pyrogram import Client
        _API_ID = int(os.environ.get("PYROGRAM_API_ID", "0") or "0")
        _API_HASH = os.environ.get("PYROGRAM_API_HASH", "") or ""
        if not _API_ID or not _API_HASH:
            await query.edit_message_text(
                "⚠️ Pyrogram credentials not configured.",
                reply_markup=account_actions(index, acc.get("status", "active"))
            )
            return
        import asyncio
        import hashlib
        client_name = (
            f"hc_single_{user_id}_{index}_"
            f"{hashlib.sha256(identifier.encode('utf-8')).hexdigest()[:12]}"
        )
        async with Client(client_name, api_id=_API_ID, api_hash=_API_HASH,
                          session_string=identifier, no_updates=True, in_memory=True) as c:
            me = await asyncio.wait_for(c.get_me(), timeout=10)
        name = me.first_name or acc.get("name", "?")
        result_text = f"✅ *Account Active*\n\n👤 {name}\n📌 Session is valid."
        new_status = "active"
    except Exception as e:
        err = str(e).upper()
        if (
            "AUTH_KEY_UNREGISTERED" not in err
            and _is_expired_session_error(e)
        ):
            result_text = (
                "🟠 *Re-login Required*\n\n"
                f"👤 {acc.get('name','?')}\n"
                "Telegram no longer accepts this session. "
                "Add the account again with Phone + OTP + 2FA."
            )
            new_status = "reauth_required"
        elif "AUTH_KEY_UNREGISTERED" in err:
            result_text = (
                "🟠 *Re-login Required*\n\n"
                f"👤 {acc.get('name','?')}\n"
                "Telegram no longer recognizes this user session. "
                "Add the account again with Phone + OTP + 2FA."
            )
            new_status = acc.get("status", "active")
        else:
            result_text = f"⚠️ *Check Failed*\n\n👤 {acc.get('name','?')}\n`{str(e)[:80]}`"
            new_status = acc.get("status", "active")

    # Update status if changed
    from storage import set_account_status
    if new_status != acc.get("status"):
        set_account_status(user_id, index, new_status)

    await query.edit_message_text(
        result_text,
        reply_markup=account_actions(index, new_status),
        parse_mode="Markdown"
    )


async def account_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    new_status = toggle_account_status(update.effective_user.id, index)
    if new_status:
        icon = "🟢" if new_status == "active" else "🔴"
        await query.answer(f"{icon} Status → {new_status}", show_alert=True)
    await account_view(update, context)


async def account_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    if remove_account(update.effective_user.id, index):
        await query.answer("🗑 Deleted", show_alert=True)
    await my_accounts(update, context)


# ─── Add account ─────────────────────────────────────────────────────────────

async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    await query.edit_message_text(
        "➕ *Add Telegram Account*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "How would you like to add an account?",
        reply_markup=add_account_method_menu(),
        parse_mode="Markdown"
    )
    return ACCOUNT_METHOD


async def add_account_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    method = query.data.replace("acc_method_", "")
    context.user_data["acc_method"] = method

    if method == "phone":
        if not API_ID or not API_HASH:
            await query.edit_message_text(
                "⚠️ Pyrogram API credentials not configured.",
                reply_markup=cancel_button()
            )
            return ConversationHandler.END
        await query.edit_message_text(
            "📱 *Enter Phone Number*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "International format: `+12345678900`",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ACCOUNT_PHONE

    elif method == "session":
        await query.edit_message_text(
            "🔑 *Session String*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "Paste your *Pyrogram session string* below:",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ACCOUNT_SESSION

    elif method == "bulk":
        await query.edit_message_text(
            "📦 *Bulk Sessions*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "You can:\n"
            "• Paste session strings one per line, OR\n"
            "• 📎 *Upload a ZIP file* containing `.session` / `.txt` files\n\n"
            "_(If uploading ZIP: bot will ask for 2FA once for all accounts)_",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ACCOUNT_BULK

    return ACCOUNT_METHOD


# ─── Phone + OTP + 2FA ───────────────────────────────────────────────────────

async def add_account_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from pyrogram import Client

    phone = update.message.text.strip()
    if not phone.startswith("+") or not phone[1:].replace(" ", "").isdigit():
        await update.message.reply_text(
            "⚠️ Invalid format. Use: `+12345678900`",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ACCOUNT_PHONE

    # Block before sending OTP — no point burning an OTP on a duplicate account
    if is_account_duplicate(phone=phone):
        await update.message.reply_text(
            f"⚠️ *Account already exists in the bot.*\n\n"
            f"📱 `{phone}` is already added and cannot be added again until it is expired or removed.",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ACCOUNT_PHONE

    context.user_data["acc_phone"] = phone

    # Show a live "Sending…" status while the API call is in flight
    status_msg = await update.message.reply_text(
        f"📡 Sending OTP to `{phone}`…",
        parse_mode="Markdown"
    )

    if not API_ID or not API_HASH:
        await status_msg.delete()
        await update.message.reply_text(
            "⚠️ Phone login is not configured. Set PYROGRAM_API_ID and "
            "PYROGRAM_API_HASH, then restart the bot.",
            reply_markup=cancel_button(),
        )
        return ACCOUNT_PHONE

    client = Client(
        f"login_{update.effective_user.id}",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
        no_updates=True,
    )
    try:
        # Keep connect() inside the same error handler as send_code(). A
        # connection failure previously escaped here and showed only a generic
        # bot error, making it look like Telegram never sent the OTP.
        await client.connect()
        sent = await client.send_code(phone)
        context.user_data["pyro_client"] = client
        context.user_data["pyro_phone_code_hash"] = sent.phone_code_hash
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        err = str(e)
        if "PHONE_NUMBER_INVALID" in err:
            msg = "⚠️ Invalid phone number. Try again:"
        elif "FLOOD_WAIT" in err:
            import re; w = re.search(r"FLOOD_WAIT_(\d+)", err)
            msg = f"⏳ Flood wait {w.group(1) if w else '?'}s. Try later."
        else:
            msg = f"❌ Failed: `{err}`"
        await status_msg.delete()
        await update.message.reply_text(msg, reply_markup=cancel_button(), parse_mode="Markdown")
        return ACCOUNT_PHONE

    # Replace the "Sending…" message with the final styled prompt
    from telegram import ForceReply
    await status_msg.delete()
    await update.message.reply_text(
        f"✅ *OTP sent to* `{phone}`!\n\n"
        f"📩 Check Telegram/SMS for the code.\n"
        f"Reply with the code below:",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    await update.message.reply_text(
        "Enter your OTP code:",
        reply_markup=ForceReply(selective=True, input_field_placeholder="e.g. 12345"),
    )
    return ACCOUNT_OTP


async def add_account_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
    otp = update.message.text.strip().replace(" ", "")
    client = context.user_data.get("pyro_client")
    phone = context.user_data.get("acc_phone", "")
    hash_ = context.user_data.get("pyro_phone_code_hash", "")
    if not client:
        await update.message.reply_text("⚠️ Session expired. Start over.", reply_markup=cancel_button())
        return ConversationHandler.END
    try:
        await client.sign_in(phone, hash_, otp)
        return await _finish_login(update, context, client)
    except SessionPasswordNeeded:
        await update.message.reply_text(
            "🔐 *2FA Required*\n\nEnter your 2FA password:",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ACCOUNT_2FA
    except PhoneCodeInvalid:
        await update.message.reply_text("❌ Wrong code. Try again:", reply_markup=cancel_button())
        return ACCOUNT_OTP
    except PhoneCodeExpired:
        await client.disconnect(); context.user_data.pop("pyro_client", None)
        await update.message.reply_text("⏰ Code expired. Start over.", reply_markup=cancel_button())
        return ConversationHandler.END
    except Exception as e:
        await client.disconnect(); context.user_data.pop("pyro_client", None)
        await update.message.reply_text(f"❌ `{e}`", reply_markup=cancel_button(), parse_mode="Markdown")
        return ConversationHandler.END


async def add_account_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from pyrogram.errors import PasswordHashInvalid
    password = update.message.text.strip()
    client = context.user_data.get("pyro_client")
    if not client:
        await update.message.reply_text("⚠️ Session expired. Start over.", reply_markup=cancel_button())
        return ConversationHandler.END
    try:
        await client.check_password(password)
        return await _finish_login(update, context, client)
    except PasswordHashInvalid:
        await update.message.reply_text("❌ Wrong 2FA password. Try again:", reply_markup=cancel_button())
        return ACCOUNT_2FA
    except Exception as e:
        await client.disconnect(); context.user_data.pop("pyro_client", None)
        await update.message.reply_text(f"❌ `{e}`", reply_markup=cancel_button(), parse_mode="Markdown")
        return ConversationHandler.END


async def _finish_login(update: Update, context: ContextTypes.DEFAULT_TYPE, client) -> int:
    user_id = update.effective_user.id
    phone = context.user_data.get("acc_phone", "unknown")
    try:
        me = await client.get_me()
        name = me.first_name or phone
        username = f"@{me.username}" if me.username else phone
        session_string = await client.export_session_string()
    except Exception as e:
        await update.message.reply_text(f"❌ Export failed: `{e}`", reply_markup=cancel_button(), parse_mode="Markdown")
        return ConversationHandler.END
    finally:
        try: await client.disconnect()
        except Exception: pass

    if is_account_duplicate(tg_id=me.id, phone=phone):
        for k in ["acc_method", "acc_phone", "pyro_client", "pyro_phone_code_hash"]:
            context.user_data.pop(k, None)
        await update.message.reply_text(
            f"⚠️ *Account already exists in the bot.*\n\n"
            f"👤 {name}  📱 `{phone}`\n\n"
            "This account is already added and cannot be added again until it is expired or removed.",
            parse_mode="Markdown"
        )
        from handlers.start import start_handler
        await start_handler(update, context)
        return ConversationHandler.END

    add_account(user_id, {
        "name": name, "username": username, "phone": phone,
        "tg_id": me.id,
        "identifier": session_string, "method": "phone",
        "status": "active", "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    for k in ["acc_method", "acc_phone", "pyro_client", "pyro_phone_code_hash"]:
        context.user_data.pop(k, None)

    from handlers.log_gc import send_log, fmt_account_added
    raw_uname = me.username  # None or string without @
    await send_log(context.bot, fmt_account_added(user_id, phone, name, raw_uname))

    await update.message.reply_text(
        f"✅ *Account Added!*\n\n👤 {name}  📱 `{phone}`\n🔗 {username}\n📌 🟢 Active\n\n"
        "Ready to run campaigns.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add Another", callback_data="add_account", style="success"),
            InlineKeyboardButton("🔙 Back", callback_data="my_accounts", style="primary"),
        ]]),
    )
    return ConversationHandler.END


# ─── Session string (manual paste) ───────────────────────────────────────────

async def add_account_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session = update.message.text.strip()
    user_id = update.effective_user.id
    if len(session) < 20:
        await update.message.reply_text("⚠️ Too short. Paste the full session string:", reply_markup=cancel_button())
        return ACCOUNT_SESSION

    await update.message.reply_text("🔍 Verifying session...")
    try:
        from pyrogram import Client
        verify_name = f"verify_{update.effective_user.id}"
        async with Client(verify_name, api_id=API_ID, api_hash=API_HASH, session_string=session, no_updates=True, in_memory=True) as c:
            me = await c.get_me()
            name = me.first_name or "Account"
            username = f"@{me.username}" if me.username else name
    except EOFError:
        await update.message.reply_text(
            "❌ *Session string rejected by Pyrogram.*\n\n"
            "This usually means:\n"
            "• It was generated with a *different API ID/Hash* than this bot uses\n"
            "• It is a *Telethon* session string (incompatible format)\n"
            "• It is truncated or corrupted\n\n"
            "Only paste session strings generated with *this bot's* API credentials.",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ACCOUNT_SESSION
    except Exception as e:
        err = str(e)
        msg = "❌ *Session expired/invalid.* Generate a new one:" if any(x in err for x in ["AUTH_KEY", "SESSION"]) else f"❌ `{err}`\n\nTry again:"
        await update.message.reply_text(msg, reply_markup=cancel_button(), parse_mode="Markdown")
        return ACCOUNT_SESSION

    phone = f"+{me.phone_number}" if me.phone_number else ""

    if is_account_duplicate(tg_id=me.id, phone=phone):
        context.user_data.pop("acc_method", None)
        await update.message.reply_text(
            f"⚠️ *Account already exists in the bot.*\n\n"
            f"👤 {name}  🔗 {username}\n\n"
            "This account is already added and cannot be added again until it is expired or removed.",
            parse_mode="Markdown"
        )
        from handlers.start import start_handler
        await start_handler(update, context)
        return ConversationHandler.END

    add_account(user_id, {
        "name": name, "username": username, "phone": phone, "tg_id": me.id,
        "identifier": session,
        "method": "session", "status": "active", "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    context.user_data.pop("acc_method", None)

    from handlers.log_gc import send_log, fmt_account_added
    raw_uname = me.username  # None or string without @
    await send_log(context.bot, fmt_account_added(user_id, phone or "", name, raw_uname))

    await update.message.reply_text(
        f"✅ *Session Added!*\n\n👤 {name}  🔗 {username}\n📌 🟢 Active",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add Another", callback_data="add_account", style="success"),
            InlineKeyboardButton("🔙 Back", callback_data="my_accounts", style="primary"),
        ]]),
    )
    return ConversationHandler.END


# ─── Bulk: text paste ─────────────────────────────────────────────────────────

async def add_account_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle both text-paste and ZIP file upload."""

    # ── ZIP file uploaded ──────────────────────────────────────────────────
    if update.message.document:
        doc = update.message.document
        fname = doc.file_name or ""
        lower_fname = fname.lower()
        is_zip = lower_fname.endswith(".zip")
        is_plain = lower_fname.endswith((".session", ".txt", ".text"))

        if not (is_zip or is_plain):
            await update.message.reply_text(
                "⚠️ Please upload a `.zip` file, a `.session`/`.txt` file, or paste session strings as text.",
                reply_markup=cancel_button()
            )
            return ACCOUNT_BULK

        status_msg = await update.message.reply_text(
            "📥 Downloading ZIP..." if is_zip else "📥 Downloading file..."
        )
        try:
            tg_file = await context.bot.get_file(doc.file_id)
            raw = await tg_file.download_as_bytearray()
        except Exception as e:
            await status_msg.edit_text(f"❌ Download failed: `{e}`", parse_mode="Markdown")
            return ACCOUNT_BULK

        # Extract sessions from ZIP or a single .session/.txt file.
        # Each entry: {"type": "file", "data": bytes}  — SQLite .session file
        #             {"type": "string", "data": str}   — plain text session string
        sessions = []
        zip_string_sessions = []
        combined_string_sessions = []
        if is_zip:
            try:
                with zipfile.ZipFile(io.BytesIO(bytes(raw))) as zf:
                    for name in zf.namelist():
                        if name.startswith("__MACOSX") or name.endswith("/"):
                            continue
                        ext = os.path.splitext(name)[1].lower()
                        if ext == ".session":
                            data = zf.read(name)
                            if data[:16] == SQLITE_MAGIC:
                                # Binary SQLite session file — handle as file
                                sessions.append({"type": "file", "data": data})
                            else:
                                # Text session strings inside a .session file
                                for line in data.decode("utf-8", errors="ignore").splitlines():
                                    line = line.strip()
                                    if len(line) >= 50:
                                        zip_string_sessions.append(line)
                        elif ext in (".txt", ".text", ""):
                            try:
                                for line in zf.read(name).decode("utf-8", errors="ignore").splitlines():
                                    line = line.strip()
                                    if len(line) >= 50:
                                        if os.path.basename(name).lower() == "session_ids.txt":
                                            combined_string_sessions.append(line)
                                        else:
                                            zip_string_sessions.append(line)
                            except Exception:
                                continue
                # Prefer the combined export when it is present. The ZIP also
                # contains compatibility .session copies for external tools,
                # but importing those as well would process every account
                # multiple times.
                selected_strings = (
                    combined_string_sessions
                    if combined_string_sessions
                    else zip_string_sessions
                )
                sessions.extend(
                    {"type": "string", "data": line}
                    for line in selected_strings
                )
            except zipfile.BadZipFile:
                await status_msg.edit_text("❌ Invalid ZIP file. Please try again.", reply_markup=cancel_button())
                return ACCOUNT_BULK
        else:
            file_bytes = bytes(raw)
            if lower_fname.endswith(".session") and file_bytes[:16] == SQLITE_MAGIC:
                # Single SQLite session file uploaded directly
                sessions.append({"type": "file", "data": file_bytes})
            else:
                try:
                    for line in file_bytes.decode("utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if len(line) >= 50:
                            sessions.append({"type": "string", "data": line})
                except Exception as e:
                    await status_msg.edit_text(f"❌ Could not read file: `{e}`", parse_mode="Markdown")
                    return ACCOUNT_BULK

        if not sessions:
            await status_msg.edit_text(
                "⚠️ No sessions found in the file.\n\n"
                "Accepted formats:\n"
                "• `.session` SQLite files (Pyrogram)\n"
                "• `.txt` files with session strings (one per line)\n"
                "• ZIP containing any of the above",
                reply_markup=cancel_button()
            )
            return ACCOUNT_BULK

        # Store for processing
        context.user_data["bulk_zip_sessions"] = sessions
        context.user_data["bulk_zip_status_id"] = status_msg.message_id

        file_count   = sum(1 for s in sessions if s["type"] == "file")
        string_count = sum(1 for s in sessions if s["type"] == "string")
        found_line   = (
            f"📂 *{file_count} .session file(s)*" if file_count and not string_count else
            f"📝 *{string_count} session string(s)*" if string_count and not file_count else
            f"📂 *{file_count} file(s)* + 📝 *{string_count} string(s)*"
        )
        await status_msg.edit_text(
            f"📦 *Found {len(sessions)} account(s)*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"{found_line}\n\n"
            "🔐 Do your accounts have *2FA (Two-Factor Authentication)*?\n\n"
            "• If yes → type your shared 2FA password\n"
            "• If no → send `skip`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⏭ Skip (No 2FA)", callback_data="bulk_zip_skip_2fa", style="primary")
            ]])
        )
        return ACCOUNT_BULK_ZIP

    # ── Plain text paste ────────────────────────────────────────────────────
    user_id = update.effective_user.id
    text = update.message.text or ""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    added = skipped = duplicate = 0
    for line in lines:
        if len(line) >= 20:
            if is_account_duplicate(identifier=line):
                duplicate += 1
            else:
                add_account(user_id, {
                    "name": f"Bulk #{added + 1}", "identifier": line,
                    "method": "bulk", "status": "active",
                    "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
                added += 1
        else:
            skipped += 1

    dup_line = f"\n🔁 Duplicates skipped: {duplicate}" if duplicate else ""
    context.user_data.pop("acc_method", None)
    await update.message.reply_text(
        f"✅ *Bulk Import Done!*\n\n📦 Added: {added}\n⚠️ Skipped (too short): {skipped}{dup_line}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add Another", callback_data="add_account", style="success"),
            InlineKeyboardButton("🔙 Back", callback_data="my_accounts", style="primary"),
        ]]),
    )
    return ConversationHandler.END


# ─── Bulk ZIP: receive 2FA or "skip" ────────────────────────────────────────

async def add_account_bulk_zip_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inline button — no 2FA."""
    query = update.callback_query
    await query.answer()
    context.user_data["bulk_zip_2fa"] = None
    await _process_bulk_zip(update, context, via_query=True)
    return ConversationHandler.END


async def add_account_bulk_zip_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Text message — 2FA password or 'skip'."""
    text = update.message.text.strip()
    context.user_data["bulk_zip_2fa"] = None if text.lower() == "skip" else text
    await _process_bulk_zip(update, context, via_query=False)
    return ConversationHandler.END


async def _process_bulk_zip(update: Update, context: ContextTypes.DEFAULT_TYPE, via_query: bool) -> None:
    """Connect all sessions in parallel, show live progress bar."""
    from pyrogram import Client
    from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid

    sessions = context.user_data.pop("bulk_zip_sessions", [])
    two_fa   = context.user_data.pop("bulk_zip_2fa", None)
    user_id  = update.effective_user.id
    total    = len(sessions)

    # Send progress message
    async def _send(text: str):
        if via_query:
            return await update.callback_query.message.reply_text(text, parse_mode="Markdown")
        else:
            return await update.message.reply_text(text, parse_mode="Markdown")

    prog_msg = await _send(
        f"⚙️ *Logging in {total} accounts...*\n\n"
        f"`[{'░' * 10}]` 0/{total}\n"
        f"✅ 0  ❌ 0  ⏳ {total}"
    )

    # Shared state
    success_list  = []
    failed_list   = []
    done_count    = [0]
    lock          = asyncio.Lock()
    last_edit     = [0.0]

    async def update_progress():
        now = time.time()
        if now - last_edit[0] < PROGRESS_THROTTLE:
            return
        last_edit[0] = now
        d = done_count[0]
        s, f = len(success_list), len(failed_list)
        bar = _bar(d, total)
        try:
            await prog_msg.edit_text(
                f"⚙️ *Logging in {total} accounts...*\n\n"
                f"`[{bar}]` {d}/{total}\n"
                f"✅ {s}  ❌ {f}  ⏳ {total - d}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    semaphore = asyncio.Semaphore(VERIFY_WORKERS)

    async def _do_login(idx: int, client_kwargs: dict):
        """Open a Pyrogram client and verify the session.
        Returns (session_string, me, error_str) — error_str is None on success."""
        try:
            async with Client(**client_kwargs) as c:
                me = await c.get_me()
                exported = await c.export_session_string()
                return exported, me, None
        except SessionPasswordNeeded:
            if not two_fa:
                return None, None, "2FA required but no password given"
            try:
                async with Client(**client_kwargs) as c:
                    await c.check_password(two_fa)
                    me = await c.get_me()
                    exported = await c.export_session_string()
                    return exported, me, None
            except Exception as e:
                return None, None, f"2FA failed: {type(e).__name__}: {e}"
        except Exception as e:
            return None, None, f"{type(e).__name__}: {e}"

    async def login_one(idx: int, entry: dict):
        async with semaphore:
            import tempfile
            session_string = None
            me = None

            err_msg = None
            if entry["type"] == "file":
                try:
                    with tempfile.TemporaryDirectory() as tmpdir:
                        sess_path = os.path.join(tmpdir, f"acc_{user_id}_{idx}")
                        if not _prepare_session_file(entry["data"], sess_path):
                            err_msg = "could not prepare session file"
                        else:
                            session_string, me, err_msg = await _do_login(
                                idx,
                                dict(name=sess_path, api_id=API_ID, api_hash=API_HASH, no_updates=True),
                            )
                except Exception as e:
                    err_msg = f"temp-dir error: {e}"
            else:
                raw_session = entry["data"]
                session_string, me, err_msg = await _do_login(
                    idx,
                    dict(name=f"bulk_{user_id}_{idx}", api_id=API_ID, api_hash=API_HASH,
                         session_string=raw_session, no_updates=True, in_memory=True),
                )
            if session_string and me:
                _phone = f"+{me.phone_number}" if me.phone_number else ""
                if is_account_duplicate(tg_id=me.id, phone=_phone):
                    failed_list.append((idx + 1, f"duplicate — already exists in bot (tg_id {me.id})"))
                else:
                    name = me.first_name or f"Account {idx+1}"
                    username = f"@{me.username}" if me.username else name
                    phone = f"+{me.phone_number}" if me.phone_number else ""
                    success_list.append({
                        "name": name, "username": username, "phone": phone,
                        "tg_id": me.id,
                        "identifier": session_string, "method": "bulk",
                        "status": "active",
                        "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
            else:
                failed_list.append((idx + 1, err_msg or "unknown error"))

            async with lock:
                done_count[0] += 1
            await update_progress()

    await asyncio.gather(*[login_one(i, s) for i, s in enumerate(sessions)])

    # Save all successful accounts
    for acc in success_list:
        add_account(user_id, acc)

    # Final message
    s, f = len(success_list), len(failed_list)
    bar = _bar(total, total)
    lines = [
        "✅ *Bulk Login Complete!*",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n",
        f"`[{bar}]` {total}/{total}\n",
        f"✅ *Logged in:* {s}",
        f"❌ *Failed:* {f}",
        f"📦 *Total:* {total}",
    ]
    if failed_list:
        if len(failed_list) >= 4:
            lines.append("\n📎 *Full error report sent as document below.*")
        else:
            lines.append("\n⚠️ *Failure reasons:*")
            for num, reason in failed_list:
                lines.append(f"• #{num}: `{reason}`")
    try:
        await prog_msg.edit_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        pass

    # Send full failure list as a file when failures >= 4
    if len(failed_list) >= 4:
        import io
        file_content = "\n".join(f"#{num}: {reason}" for num, reason in failed_list)
        await prog_msg.reply_document(
            document=io.BytesIO(file_content.encode("utf-8")),
            filename="session_login_errors.txt",
            caption=f"⚠️ {len(failed_list)} session login failures",
        )

    context.user_data.pop("acc_method", None)
    await prog_msg.reply_text(
        "What would you like to do next?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("➕ Add Another", callback_data="add_account", style="success"),
            InlineKeyboardButton("🔙 Back", callback_data="my_accounts", style="primary"),
        ]]),
    )


# ─── Check Account Status ─────────────────────────────────────────────────────

async def check_account_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check only this user's accounts and report active/expired results."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)

    if not accounts:
        await query.edit_message_text(
            "ℹ️ You have no accounts to check.",
            reply_markup=accounts_menu([]),
        )
        return

    total = len(accounts)
    await query.edit_message_text(
        f"🔍 *Checking {total} account(s)...*\n\n"
        "This may take a moment. Please wait.",
        parse_mode="Markdown",
    )

    # Share the owner Session Health verifier so every status check uses the
    # same two outcomes, retries, and error handling.
    from handlers.session_health import _verify_session

    async def _verify(session_str: str | None) -> tuple[str, dict[str, str]]:
        try:
            return await _verify_session(session_str)
        except Exception as error:
            # Keep the user-facing result two-state even for an unexpected
            # verifier failure.
            return "expired", {"error": str(error) or error.__class__.__name__}

    semaphore = asyncio.Semaphore(5)
    results: list[tuple[str, dict[str, str]]] = [
        ("expired", {"error": "not checked"}) for _ in accounts
    ]

    async def _check_one(idx: int, acc: dict) -> None:
        async with semaphore:
            try:
                result = await asyncio.wait_for(
                    _verify(_stored_session_string(acc)),
                    timeout=75,
                )
            except asyncio.TimeoutError:
                result = ("expired", {"error": "verification timed out"})
            results[idx] = result

    await asyncio.gather(*[_check_one(i, a) for i, a in enumerate(accounts)])

    # Persist updated statuses
    from storage import set_account_status
    active_lines: list[str] = []
    expired_lines: list[str] = []

    def _report_line(
        number: int,
        account: dict,
        status: str,
        info: dict[str, str],
    ) -> str:
        name = info.get("name") or account.get("name") or "N/A"
        username = info.get("username") or account.get("username") or "N/A"
        phone = info.get("phone") or account.get("phone") or "N/A"
        tg_id = info.get("tg_id") or account.get("tg_id") or "N/A"
        error = (
            f" | Error: {info.get('error')}"
            if status == "expired" and info.get("error")
            else ""
        )
        return (
            f"{number}. Name: {name} | Username: {username} | "
            f"Phone: {phone} | Telegram ID: {tg_id}{error}"
        )

    for idx, (status, info) in enumerate(results):
        status = "active" if status == "active" else "expired"
        set_account_status(user_id, idx, status)
        if status == "active":
            active_lines.append(
                _report_line(len(active_lines) + 1, accounts[idx], status, info)
            )
        else:
            expired_lines.append(
                _report_line(len(expired_lines) + 1, accounts[idx], status, info)
            )

    active_c = len(active_lines)
    expired_c = len(expired_lines)

    await query.edit_message_text(
        "✅ *Status Check Complete!*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"🟢 Active: {active_c}\n"
        f"🔴 Expired: {expired_c}\n\n"
        "Account list has been updated. Sending the status ZIP…",
        reply_markup=accounts_menu(get_accounts(user_id)),
        parse_mode="Markdown",
    )

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as report_zip:
        report_zip.writestr(
            "active_accounts.txt",
            (
                "Active accounts\n"
                "================\n\n"
                + ("\n".join(active_lines) if active_lines else "No active accounts.\n")
                + "\n"
            ),
        )
        report_zip.writestr(
            "expired_accounts.txt",
            (
                "Expired accounts\n"
                "================\n\n"
                + (
                    "\n".join(expired_lines)
                    if expired_lines
                    else "No expired accounts.\n"
                )
                + "\n"
            ),
        )
        report_zip.writestr(
            "README.txt",
            "This report contains account status details only. Session strings are not included.\n",
        )
    archive.seek(0)

    if update.effective_chat:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=archive,
            filename=f"account_status_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            caption=f"📦 Account status: {active_c} active, {expired_c} expired.",
        )


# ─── Cancel ───────────────────────────────────────────────────────────────────

async def add_account_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    client = context.user_data.pop("pyro_client", None)
    if client:
        try: await client.disconnect()
        except Exception: pass
    for k in ["acc_method","acc_phone","pyro_phone_code_hash","bulk_zip_sessions","bulk_zip_2fa","bulk_zip_status_id"]:
        context.user_data.pop(k, None)
    from handlers.start import start_handler
    await start_handler(update, context)
    return ConversationHandler.END


# ─── Account Labels ────────────────────────────────────────────────────────────

async def account_labels_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current labels for an account + add/remove options. Pattern: acc_labels_<index>"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    index = int(query.data.split("_")[-1])
    accounts = get_accounts(user_id)
    if index >= len(accounts):
        await query.edit_message_text("Account not found.", reply_markup=back_button("my_accounts"))
        return
    acc = accounts[index]
    labels = acc.get("labels", [])
    name = acc.get("name", f"Account {index+1}")
    label_text = "\n".join(f"  🏷 {l}" for l in labels) if labels else "  _No labels yet_"
    text = (
        f"🏷 *Labels for {name}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{label_text}\n\n"
        "Labels help you group accounts and filter campaigns.\n"
        "Tap ➕ Add Label to add one, or ✖ Remove to delete."
    )
    await query.edit_message_text(
        text,
        reply_markup=account_labels_menu(index, labels),
        parse_mode="Markdown",
    )


async def account_label_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for add-label conversation. Pattern: acc_lbl_add_<index>"""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    context.user_data["label_acc_index"] = index
    accounts = get_accounts(update.effective_user.id)
    name = accounts[index].get("name", f"Account {index+1}") if index < len(accounts) else "?"
    await query.edit_message_text(
        f"🏷 *Add Label to {name}*\n\n"
        "Type a short label name (e.g. `fast`, `group-a`, `premium`).\n\n"
        "Max 32 characters. Labels are stored in lowercase.",
        parse_mode="Markdown",
    )
    return ACC_LABEL


async def account_label_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the label text and save it."""
    user_id = update.effective_user.id
    index = context.user_data.get("label_acc_index", 0)
    label = update.message.text.strip().lower()[:32]
    if not label:
        await update.message.reply_text("Label cannot be empty. Try again or /cancel.")
        return ACC_LABEL
    success = add_account_label(user_id, index, label)
    if success:
        await update.message.reply_text(f"✅ Label `{label}` added!", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠️ Could not add label (account not found or label too long).")
    # Show the labels menu again
    accounts = get_accounts(user_id)
    labels = accounts[index].get("labels", []) if index < len(accounts) else []
    from keyboards import account_labels_menu
    await update.message.reply_text(
        "🏷 Label saved. Here are the current labels:",
        reply_markup=account_labels_menu(index, labels),
    )
    return ConversationHandler.END


async def account_label_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a label. Pattern: acc_lbl_rm_<index>_<label_safe>"""
    query = update.callback_query
    user_id = update.effective_user.id
    # acc_lbl_rm_<index>_<label_safe> — split carefully
    parts = query.data.split("_", 4)   # ['acc', 'lbl', 'rm', '<index>', '<label>']
    if len(parts) < 5:
        await query.answer("Invalid action.", show_alert=True)
        return
    index = int(parts[3])
    label = parts[4].replace("_", " ")   # restore spaces if any
    remove_account_label(user_id, index, label)
    await query.answer(f"✖ Removed: {label}")
    # Refresh labels view
    accounts = get_accounts(user_id)
    labels = accounts[index].get("labels", []) if index < len(accounts) else []
    name = accounts[index].get("name", f"Account {index+1}") if index < len(accounts) else "?"
    label_text = "\n".join(f"  🏷 {l}" for l in labels) if labels else "  _No labels yet_"
    await query.edit_message_text(
        f"🏷 *Labels for {name}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{label_text}\n\n"
        "Labels help you group accounts and filter campaigns.",
        reply_markup=account_labels_menu(index, labels),
        parse_mode="Markdown",
    )
