"""
Slash-command shortcuts so users can quickly reach any section
without tapping through the inline keyboard.
"""
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from storage import get_stats, get_accounts, get_campaigns, get_schedules, get_broadcasts, is_owner
from keyboards import main_menu, back_button


# ── /cancel ───────────────────────────────────────────────────────────────────

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Exit any active conversation and return to main menu."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ *Cancelled.* Returning to main menu.",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id=update.effective_user.id),
    )
    return ConversationHandler.END


# ── /stats ────────────────────────────────────────────────────────────────────

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show personal stats as a command reply."""
    user_id = update.effective_user.id
    stats = get_stats(user_id)
    campaigns = get_campaigns(user_id)
    schedules = get_schedules(user_id)
    broadcasts = get_broadcasts(user_id)

    active_camps = sum(1 for c in campaigns if c.get("active"))
    total_actions = sum(c.get("actions", 0) for c in campaigns)
    enabled_scheds = sum(1 for s in schedules if s.get("enabled", True))

    total = stats["total"]
    active = stats["active"]
    if total == 0:
        health = "⚪ No data"
        health_pct = ""
    elif active == 0:
        health = "⚠️ No active accounts"
        health_pct = ""
    else:
        pct = int(100 * active / total)
        health = "🟢 Healthy" if pct >= 80 else ("⚠️ Degraded" if pct >= 40 else "🔴 Critical")
        health_pct = f" ({pct}%)"

    text = (
        "📊 *MY STATS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 *ACCOUNTS*\n"
        f"   🟢 Active: {active}  🔴 Dead: {stats['dead']}  📦 Total: {total}\n"
        f"   ❤️ Health: {health}{health_pct}\n\n"
        "🚀 *CAMPAIGNS*\n"
        f"   ✅ Active: {active_camps}  📁 Total: {stats['campaigns']}\n"
        f"   ⚡ Total Actions: {total_actions}\n\n"
        "⏰ *SCHEDULES*\n"
        f"   ✅ Enabled: {enabled_scheds}  📋 Total: {len(schedules)}\n\n"
        "📣 *BROADCASTS*\n"
        f"   📨 Total Sent: {len(broadcasts)}\n\n"
        "🟢 *Bot Status:* Online & Ready"
    )
    await update.message.reply_text(text, reply_markup=back_button("main_menu"), parse_mode="Markdown")


# ── /me ───────────────────────────────────────────────────────────────────────

async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show profile as a command reply."""
    user_id = update.effective_user.id
    tg_user = update.effective_user
    stats = get_stats(user_id)

    from storage import get_profile, update_profile
    from datetime import datetime as _dt
    profile = get_profile(user_id)
    if not profile.get("joined"):
        update_profile(user_id, {"joined": _dt.now().strftime("%Y-%m-%d")})
        profile = get_profile(user_id)

    username = f"@{tg_user.username}" if tg_user.username else "Not set"
    full_name = tg_user.full_name or "Unknown"

    text = (
        "👤 *MY PROFILE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *Name:* {full_name}\n"
        f"🔗 *Username:* {username}\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"📅 *Joined:* {profile.get('joined', 'N/A')}\n\n"
        "📊 *Your Summary:*\n"
        f"   📦 Accounts: {stats['total']}\n"
        f"   🟢 Active: {stats['active']}\n"
        f"   🚀 Campaigns: {stats['campaigns']}\n"
        f"   ⚡ Total Actions: {stats['actions']}"
    )
    await update.message.reply_text(text, reply_markup=back_button("main_menu"), parse_mode="Markdown")


# ── /accounts ─────────────────────────────────────────────────────────────────

async def accounts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Jump straight to accounts list."""
    from keyboards import accounts_menu
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)
    if not accounts:
        text = (
            "✅ *My Accounts*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "No accounts yet.\nPress ➕ Add New Account to get started."
        )
    else:
        active = sum(1 for a in accounts if a.get("status") == "active")
        dead = len(accounts) - active
        text = (
            "✅ *My Accounts*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"🟢 Active: {active}  🔴 Dead: {dead}  📦 Total: {len(accounts)}\n\n"
            "Select an account to manage it:"
        )
    await update.message.reply_text(text, reply_markup=accounts_menu(accounts), parse_mode="Markdown")


# ── /campaigns ────────────────────────────────────────────────────────────────

async def campaigns_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Jump straight to campaigns list."""
    from keyboards import campaigns_menu
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)
    if not campaigns:
        text = (
            "🎯 *My Campaigns*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "No campaigns yet.\nPress 🚀 New Campaign to create one."
        )
    else:
        total_actions = sum(c.get("actions", 0) for c in campaigns)
        text = (
            "🎯 *My Campaigns*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"📊 Total: {len(campaigns)} campaigns | {total_actions} actions\n\n"
            "Select a campaign to manage it:"
        )
    await update.message.reply_text(text, reply_markup=campaigns_menu(campaigns), parse_mode="Markdown")


# ── /admin ────────────────────────────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick owner-panel access for owners."""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⛔ This command is restricted to bot owners.")
        return

    from storage import get_global_stats, get_adv_access_users, get_banned_users, OWNER_ID
    from keyboards import owner_panel_menu
    import uptime

    stats = get_global_stats()
    adv_users = get_adv_access_users()
    banned_count = len(get_banned_users())

    text = (
        "👑 *OWNER PANEL*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"👥 *Users:* {stats['users']}\n"
        f"📦 *Accounts:* {stats['accounts']}  ·  *Active:* {stats['active']}\n"
        f"🚀 *Campaigns:* {stats['campaigns']}  ·  *Running:* {stats['running']}\n"
        f"⚡ *Total Actions:* {stats['actions']}\n"
        f"📌 *ADV Access:* {len(adv_users)}  ·  🚫 *Banned:* {banned_count}\n"
        f"🕐 *Uptime:* {uptime.get_uptime_str()}"
    )
    await update.message.reply_text(
        text,
        reply_markup=owner_panel_menu(is_primary=user_id == OWNER_ID),
        parse_mode="Markdown",
    )
