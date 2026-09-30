from telegram import Update
from telegram.ext import ContextTypes
from storage import get_stats, get_accounts, get_campaigns, get_schedules, get_broadcasts
from keyboards import back_button


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    query = update.callback_query
    if query:
        await query.answer()

    stats = get_stats(user_id)
    campaigns = get_campaigns(user_id)
    schedules = get_schedules(user_id)
    broadcasts = get_broadcasts(user_id)

    active_camps = sum(1 for c in campaigns if c.get("active"))
    total_actions = sum(c.get("actions", 0) for c in campaigns)
    enabled_scheds = sum(1 for s in schedules if s.get("enabled", True))
    total_scheds = len(schedules)

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
        f"   🟢 Active: {active}\n"
        f"   🔴 Dead: {stats['dead']}\n"
        f"   📦 Total: {total}\n"
        f"   ❤️ Health: {health}{health_pct}\n\n"
        "🚀 *CAMPAIGNS*\n"
        f"   ✅ Active: {active_camps}\n"
        f"   📁 Total: {stats['campaigns']}\n"
        f"   ⚡ Total Actions: {total_actions}\n\n"
        "⏰ *SCHEDULES*\n"
        f"   ✅ Enabled: {enabled_scheds}\n"
        f"   📋 Total: {total_scheds}\n\n"
        "📣 *BROADCASTS*\n"
        f"   📨 Total Sent: {len(broadcasts)}\n\n"
        "🟢 *Bot Status:* Online & Ready\n"
        "💾 *Storage:* Active"
    )

    markup = back_button("main_menu")
    if query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
