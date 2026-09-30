"""
log_gc.py — Telegram Log Group Chat helper.

Call  await send_log(bot, text)  from any handler to forward an event
to the configured log channel (set via Admin → Bot Settings → 📋 Log GC).
"""
import html
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def send_log(bot, text: str, parse_mode: str = "HTML") -> None:
    """Send a formatted log message to the configured log channel (silently ignored if not set)."""
    from storage import get_log_channel
    channel_id = get_log_channel()
    if not channel_id:
        return
    try:
        await bot.send_message(chat_id=channel_id, text=text, parse_mode=parse_mode)
    except Exception as exc:
        logger.warning("Log GC send failed (channel %s): %s", channel_id, exc)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ── User Started ───────────────────────────────────────────────────────────────

def fmt_user_start(user_id: int, full_name: str, username: str | None) -> str:
    lines = ["<b>User Started</b>", html.escape(full_name)]
    if username:
        lines.append(f"@{html.escape(username)}")
    lines.append(f"<code>{user_id}</code>")
    return "\n".join(lines)


# kept for any legacy callers
def fmt_user_join(user_id: int, name: str, is_new: bool) -> str:
    return fmt_user_start(user_id, name, None)


# ── New Account Added ──────────────────────────────────────────────────────────

def fmt_account_added(owner_user_id: int, phone: str, account_name: str,
                      tg_username: str | None = None) -> str:
    uname = f"@{html.escape(tg_username)}" if tg_username else "@none"
    return (
        f"<b>New Account Added</b>\n\n"
        f"User: <a href='tg://user?id={owner_user_id}'>ID:{owner_user_id}</a>"
        f" (<code>{owner_user_id}</code>)\n"
        f"Phone: {html.escape(phone)}\n"
        f"Account: {html.escape(account_name)}\n"
        f"TG Username: {uname}"
    )


# ── Campaign Started ───────────────────────────────────────────────────────────

def fmt_campaign_start(
    user_id: int,
    full_name: str,
    username: str | None,
    camp_id: str,
    action_label: str,
    action_type: str,
    target: str,
    total: int,
    reactions: list | None = None,
    join_link: str | None = None,
) -> str:
    lines = [f"🚀 <b>New Campaign Started</b>\n"]

    # User info
    lines.append(f"👤 {html.escape(full_name)}")
    if username:
        lines.append(f"@{html.escape(username)}")
    lines.append(f"🆔 <code>{user_id}</code>")

    # Campaign info
    lines.append(f"📋 Campaign ID: <code>{camp_id}</code>")
    lines.append(f"⚡ Action: {action_label}")
    lines.append(f"📦 Accounts: {total}")

    # Target details
    react_actions = {"react", "react_vote", "react_view", "react_vote_view",
                     "vote", "vote_view", "view"}
    if action_type in react_actions and target and target != "N/A":
        lines.append(f"🔗 Post: {target}")
        m = re.search(r't\.me/([^/\s?+]+)', target)
        if m:
            lines.append(f"📢 Channel: @{m.group(1)}")

    if action_type == "bot_referral" and target and target != "N/A":
        lines.append(f"🤖 Bot Target: {html.escape(target)}")
        # Extract bot username from t.me link for a clean @mention
        m = re.search(r"t\.me/([A-Za-z0-9_]+)", target)
        if m:
            lines.append(f"👤 Bot: @{m.group(1)}")

    if action_type == "join":
        link = join_link or target
        if link and link != "N/A":
            lines.append(f"🔗 Join Link: {link}")
    elif join_link:
        lines.append(f"🔗 Join Link: {join_link}")

    if reactions and action_type in {"react", "react_vote", "react_view", "react_vote_view"}:
        lines.append(f"😊 Reaction: {''.join(reactions)}")

    return "\n".join(lines)


# ── Campaign Done (Completed / Paused / Stopped) ───────────────────────────────

def fmt_campaign_done(
    user_id: int,
    full_name: str,
    camp_id: str,
    action_label: str,
    done: int,
    failed: int,
    total: int,
    elapsed: str,
    was_stopped: bool,
    was_paused: bool,
) -> str:
    esc_name = html.escape(full_name)
    if was_paused:
        return (
            f"⏸ <b>Campaign Paused</b>\n"
            f"📋 Campaign: <code>{camp_id}</code>\n"
            f"👤 User: {esc_name} (<code>{user_id}</code>)"
        )
    if was_stopped:
        return (
            f"⏹ <b>Campaign Stopped</b>\n"
            f"📋 Campaign: <code>{camp_id}</code>\n"
            f"👤 User: {esc_name} (<code>{user_id}</code>)"
        )
    pct = int(done / total * 100) if total > 0 else 0
    return (
        f"✅ <b>Campaign Completed</b>\n"
        f"📋 Campaign ID: <code>{camp_id}</code>\n"
        f"⚡ Action: {action_label}\n"
        f"👤 User: {esc_name} (<code>{user_id}</code>)\n\n"
        f"📊 <b>Results:</b>\n"
        f"✅ Success: {done}/{total} ({pct}%)\n"
        f"❌ Failed: {failed}/{total}\n"
        f"⏱ Time: {elapsed}"
    )


# ── Admin / moderation ─────────────────────────────────────────────────────────

def fmt_ban(admin_id: int, target_id: int, action: str) -> str:
    icon = "🚫" if action == "ban" else "✅"
    label = "User banned" if action == "ban" else "User unbanned"
    return (
        f"{icon} <b>{label}</b>\n"
        f"🎯 Target: <code>{target_id}</code>\n"
        f"👑 By: <code>{admin_id}</code>"
    )


def fmt_adv_grant(admin_id: int, target_id: int, limit: int) -> str:
    lbl = "∞ Unlimited" if limit == 0 else str(limit)
    return (
        f"🌐 <b>ADV access granted</b>\n"
        f"🎯 User: <code>{target_id}</code>\n"
        f"📦 Account limit: {lbl}\n"
        f"👑 By: <code>{admin_id}</code>"
    )


def fmt_adv_revoke(admin_id: int, target_id: int) -> str:
    return (
        f"🚫 <b>ADV access revoked</b>\n"
        f"🎯 User: <code>{target_id}</code>\n"
        f"👑 By: <code>{admin_id}</code>"
    )


def fmt_owner_added(admin_id: int, target_id: int) -> str:
    return (
        f"👑 <b>Co-owner added</b>\n"
        f"🎯 User: <code>{target_id}</code>\n"
        f"👑 By: <code>{admin_id}</code>"
    )


def fmt_owner_removed(admin_id: int, target_id: int) -> str:
    return (
        f"❌ <b>Co-owner removed</b>\n"
        f"🎯 User: <code>{target_id}</code>\n"
        f"👑 By: <code>{admin_id}</code>"
    )


def fmt_maintenance(admin_id: int, state: bool) -> str:
    icon, label = ("🔧", "ON") if state else ("✅", "OFF")
    return (
        f"{icon} <b>Maintenance mode {label}</b>\n"
        f"👑 By: <code>{admin_id}</code>"
    )


def fmt_paid_mode(admin_id: int, state: bool) -> str:
    icon, label = ("💎", "ON") if state else ("🆓", "OFF")
    return (
        f"{icon} <b>Paid mode {label}</b>\n"
        f"👑 By: <code>{admin_id}</code>"
    )


def fmt_error(error_type: str, preview: str) -> str:
    return (
        f"⚠️ <b>Bot Error</b>\n"
        f"<code>{error_type}: {preview}</code>"
    )


def fmt_bot_started(username: str) -> str:
    return (
        f"🟢 <b>Bot Started.</b>\n"
        f"🤖 @{username}\n"
        f"⏰ Bot is now online and polling.\n"
        f"🕐 {_ts()}"
    )
