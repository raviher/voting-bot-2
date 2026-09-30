"""Safe Telegram session verification.

The original health check used a write probe (send a message to Saved Messages
and delete it again).  That is not a reliable liveness test: a valid account
can reject that write while its authorization is still usable.  This module
uses the read-only ``get_me`` request and reports every session as either
active or expired.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import io
import logging
import os
from collections.abc import Iterable
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from storage import get_all_user_ids, get_user, is_owner

logger = logging.getLogger(__name__)

API_ID = int(os.environ.get("PYROGRAM_API_ID", "0") or 0)
API_HASH = os.environ.get("PYROGRAM_API_HASH", "")
VERIFY_WORKERS = 5
VERIFY_TIMEOUT_SECONDS = 20
VERIFY_RETRIES = 3

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"

# These are authorization failures, not ordinary network/API failures.
# AUTH_KEY_DUPLICATED is deliberately excluded because it can be raised while
# another client is still releasing the same authorization key.
_EXPIRED_ERRORS = frozenset(
    {
        "AUTH_KEY_INVALID",
        "SESSION_REVOKED",
        "SESSION_EXPIRED",
        "USER_DEACTIVATED",
        "USER_DEACTIVATED_BAN",
        "ACCOUNT_BANNED",
        "USER_BANNED",
    }
)


def _extract_country_code(phone: str | None) -> str:
    """Best-effort country code for the report."""
    if not phone:
        return "N/A"
    digits = str(phone).lstrip("+")
    # A full international number is not enough to determine the exact
    # country in every case, so keep the original report's short prefix.
    return "+" + digits[:3] if len(digits) >= 3 else "+" + digits


def _is_expired_error(error: BaseException) -> bool:
    """Return True only for a definitive Telegram auth/deactivation error."""
    text = str(error).upper().replace(" ", "_").replace("-", "_")
    return any(marker in text for marker in _EXPIRED_ERRORS)


def _is_unregistered_key_error(error: BaseException) -> bool:
    """Detect the restart-sensitive error without exposing it to users."""
    return "AUTH_KEY_UNREGISTERED" in str(error).upper()


def _session_string(account: dict[str, Any]) -> str | None:
    """Read every session field used by phone, text, and ZIP imports."""
    candidates: Iterable[Any] = (
        account.get("session_string"),
        account.get("session"),
        account.get("identifier"),
    )
    for value in candidates:
        if not isinstance(value, str):
            continue
        value = value.strip()
        # ZIP/text imports store the exported session string in identifier.
        # Do not mistake a phone number or a display label for a session.
        if len(value) >= 20 and not value.startswith("+"):
            return value
    return None


async def _verify_session(session_string: str | None) -> tuple[str, dict[str, str]]:
    """Verify one session without sending or deleting any Telegram message."""
    info: dict[str, str] = {
        "name": "",
        "username": "",
        "phone": "",
        "tg_id": "",
        "error": "",
    }

    if not session_string:
        return STATUS_EXPIRED, {**info, "error": "no session string stored"}
    if not API_ID or not API_HASH:
        return STATUS_EXPIRED, {**info, "error": "Pyrogram credentials are not configured"}

    from pyrogram import Client

    # Use a stable, unique in-memory client name.  Reusing one name while
    # checking several accounts can make concurrent checks look like a
    # duplicated/revoked session even when the session is valid.
    client_name = (
        "session_health_"
        f"{hashlib.sha256(session_string.encode('utf-8')).hexdigest()[:16]}"
    )
    last_error = "could not connect"
    unregistered_key_seen = False

    for attempt in range(1, VERIFY_RETRIES + 1):
        try:
            async def verify_once() -> dict[str, str]:
                # in_memory=True prevents Pyrogram from rewriting or
                # invalidating the uploaded session file/string on disk.
                async with Client(
                    client_name,
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_string,
                    no_updates=True,
                    in_memory=True,
                ) as client:
                    me = await client.get_me()
                    full_name = " ".join(
                        part for part in (me.first_name, me.last_name) if part
                    ).strip()
                    return {
                        "name": full_name,
                        "username": f"@{me.username}" if me.username else "",
                        "phone": f"+{me.phone_number}" if me.phone_number else "",
                        "tg_id": str(me.id) if me.id else "",
                        "error": "",
                    }

            result = await asyncio.wait_for(
                verify_once(), timeout=VERIFY_TIMEOUT_SECONDS
            )
            return STATUS_ACTIVE, result
        except asyncio.TimeoutError:
            last_error = f"timed out (attempt {attempt}/{VERIFY_RETRIES})"
        except Exception as error:
            if _is_unregistered_key_error(error):
                # A single AUTH_KEY_UNREGISTERED can happen during a restart
                # or concurrent reconnect. Retry it, but do not leave a
                # permanently unregistered session looking active after all
                # retries have failed.
                unregistered_key_seen = True
                last_error = str(error) or "AUTH_KEY_UNREGISTERED"
            elif _is_expired_error(error):
                return STATUS_EXPIRED, {**info, "error": str(error)}
            else:
                # The health report has only two outcomes. If verification
                # cannot establish that a session is active after retries,
                # send it directly to the expired bucket.
                last_error = str(error) or error.__class__.__name__

        if attempt < VERIFY_RETRIES:
            await asyncio.sleep(min(attempt, 3))

    if unregistered_key_seen and last_error.upper().find("AUTH_KEY_UNREGISTERED") >= 0:
        return STATUS_EXPIRED, {
            **info,
            "error": (
                "Telegram reports that this session is no longer registered "
                f"after {VERIFY_RETRIES} verification attempts."
            ),
        }

    return STATUS_EXPIRED, {**info, "error": last_error}


def _account_identifier(account: dict[str, Any], index: int) -> str:
    return str(
        account.get("phone")
        or account.get("tg_id")
        or account.get("user_id")
        or account.get("name")
        or f"account #{index + 1}"
    )


def _account_index(user_id: int, account: dict[str, Any]) -> int | None:
    """Find an account again after storage returns a fresh JSON object."""
    accounts = get_user(user_id).get("accounts", [])
    for index, stored in enumerate(accounts):
        if stored is account:
            return index
        for field in ("identifier", "session_string", "session"):
            if (
                account.get(field)
                and stored.get(field) == account.get(field)
            ):
                return index
        if (
            account.get("tg_id")
            and str(stored.get("tg_id")) == str(account.get("tg_id"))
        ):
            return index
        if (
            account.get("phone")
            and str(stored.get("phone", "")).strip() == str(account.get("phone")).strip()
        ):
            return index
    return None


async def _verify_accounts(
    accounts: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any], str, dict[str, str]]]:
    semaphore = asyncio.Semaphore(VERIFY_WORKERS)
    results: list[tuple[str, dict[str, Any], str, dict[str, str]] | None] = [
        None
    ] * len(accounts)

    async def check(index: int, account: dict[str, Any]) -> None:
        async with semaphore:
            status, info = await _verify_session(_session_string(account))
            results[index] = (status, account, _account_identifier(account, index), info)

    await asyncio.gather(*(check(i, account) for i, account in enumerate(accounts)))
    return [result for result in results if result is not None]


async def _owner_query(update: Update) -> Any:
    query = update.callback_query
    user = update.effective_user
    if not user or not is_owner(user.id):
        if query:
            await query.answer("⛔ Owner only.", show_alert=True)
        return None
    if query:
        await query.answer()
    return query


def _report_line(number: int, user_id: int, account: dict[str, Any], info: dict[str, str], error: str = "") -> str:
    name = info.get("name") or account.get("name") or "N/A"
    username = info.get("username") or account.get("username") or "N/A"
    phone = info.get("phone") or account.get("phone") or "N/A"
    tg_id = info.get("tg_id") or account.get("tg_id") or "N/A"
    suffix = f" | Error: {error}" if error else ""
    return (
        f"{number}. UID {user_id} | TgID {tg_id} | {phone} "
        f"({ _extract_country_code(phone) }) | {username} | {name}{suffix}"
    )


async def session_health_check(
    update: Update | None = None, context: ContextTypes.DEFAULT_TYPE | None = None
) -> None:
    """Check all stored sessions and classify each one as active or expired."""
    query = await _owner_query(update)
    if query is None:
        return

    all_sessions: list[tuple[int, dict[str, Any]]] = []
    for user_id in get_all_user_ids():
        user = get_user(user_id)
        for account in user.get("accounts", []):
            all_sessions.append((int(user_id), account))

    if not all_sessions:
        await query.edit_message_text("ℹ️ No sessions found across any users.")
        return

    await query.edit_message_text(
        f"⏳ Checking {len(all_sessions)} sessions…\n"
        "Each session will be classified as active or expired."
    )

    # Verify each user's account list as a group while retaining the original
    # ordering for the report. This also avoids modifying accounts in place.
    grouped: dict[int, list[dict[str, Any]]] = {}
    for user_id, account in all_sessions:
        grouped.setdefault(user_id, []).append(account)

    checked: list[tuple[int, dict[str, Any], str, dict[str, str]]] = []
    for user_id, accounts in grouped.items():
        for status, account, identifier, info in await _verify_accounts(accounts):
            checked.append((user_id, account, status, {**info, "identifier": identifier}))

    from storage import set_account_status

    active: list[str] = []
    expired: list[str] = []
    active_count = expired_count = 0

    for user_id, account, status, info in checked:
        identifier = info["identifier"]
        if status == STATUS_ACTIVE:
            active_count += 1
            active.append(_report_line(active_count, user_id, account, info))
            # Repair a prior false "dead" result, but never override an
            # intentional user-disabled state.
            try:
                index = _account_index(user_id, account)
                current_status = account.get("status", STATUS_ACTIVE)
                if index is not None and current_status in {
                    "dead",
                    STATUS_EXPIRED,
                    "unverified",
                    "reauth_required",
                }:
                    set_account_status(user_id, index, STATUS_ACTIVE)
            except Exception:
                logger.exception("Could not restore active status for %s", identifier)
        elif status == STATUS_EXPIRED:
            expired_count += 1
            expired.append(
                _report_line(
                    expired_count, user_id, account, info, info.get("error", "expired")
                )
            )
            try:
                index = _account_index(user_id, account)
                if index is not None:
                    # Keep the stored account/ID visible. Telegram's auth
                    # failure invalidates the session, not the account record.
                    set_account_status(user_id, index, STATUS_EXPIRED)
            except Exception:
                logger.exception("Could not mark expired account %s", identifier)
        else:
            # Defensive normalization for legacy or future verifier results:
            # session health must never expose a third "review" state.
            expired_count += 1
            expired.append(
                _report_line(
                    expired_count,
                    user_id,
                    account,
                    info,
                    info.get("error", "expired"),
                )
            )
            try:
                index = _account_index(user_id, account)
                if index is not None:
                    set_account_status(user_id, index, STATUS_EXPIRED)
            except Exception:
                logger.exception("Could not normalize expired account %s", identifier)

    summary = (
        "🔬 Session Health\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Accounts: {len(checked)}\n"
        f"✅ Active: {active_count}\n\n"
        f"✅ Active Sessions — {active_count} accounts\n"
        f"🔴 Expired/Invalid Sessions — {expired_count} accounts"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗑 Remove All Expired", callback_data="remove_all_expired"
                )
            ],
            [InlineKeyboardButton("🔙 Owner Panel", callback_data="owner_panel")],
        ]
    )
    await query.edit_message_text(summary, reply_markup=keyboard)

    # Keep the detailed data available to the owner without putting session
    # strings in the report.
    if context and update and update.effective_chat:
        for title, lines, filename in (
            ("Active sessions", active, "active_sessions.txt"),
            ("Expired sessions", expired, "expired_sessions.txt"),
        ):
            if lines:
                document = io.BytesIO(("\n".join(lines) + "\n").encode("utf-8"))
                caption = (
                    f"✅ Active Sessions — {len(lines)} accounts"
                    if title == "Active sessions"
                    else f"🔴 Expired/Invalid Sessions — {len(lines)} accounts"
                )
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=document,
                    filename=filename,
                    caption=caption,
                )


async def remove_all_expired(
    update: Update | None = None, context: ContextTypes.DEFAULT_TYPE | None = None
) -> None:
    """Remove accounts classified as expired by a fresh health check."""
    query = await _owner_query(update)
    if query is None:
        return

    from storage import remove_account

    removed = 0
    for user_id in get_all_user_ids():
        accounts = get_user(user_id).get("accounts", [])
        results = await _verify_accounts(accounts)
        for index in sorted(
            (i for i, result in enumerate(results) if result[0] == STATUS_EXPIRED),
            reverse=True,
        ):
            remove_account(user_id, index)
            removed += 1
    await query.edit_message_text(f"🗑 Removed {removed} explicitly expired account(s).")