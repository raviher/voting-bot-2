from telegram.ext import ContextTypes
from storage import get_all_user_ids, get_user, get_owner_ids


async def send_daily_health_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    total_accounts = 0
    active_accounts = 0
    expired_accounts = 0
    total_campaigns = 0
    total_users = 0

    for uid_str in get_all_user_ids():
        try:
            user = get_user(int(uid_str))
        except Exception:
            continue

        total_users += 1
        accounts = user.get("accounts", [])
        campaigns = user.get("campaigns", [])

        for acc in accounts:
            total_accounts += 1
            status = acc.get("status", "active")
            if status == "active":
                active_accounts += 1
            else:
                expired_accounts += 1

        total_campaigns += len(campaigns)

    if expired_accounts == 0:
        health_line = "✅ All accounts are healthy!"
    elif expired_accounts / total_accounts < 0.1 if total_accounts > 0 else False:
        health_line = f"⚠️ {expired_accounts} account(s) need attention."
    else:
        health_line = f"🚨 {expired_accounts} accounts are expired/dead — action needed!"

    text = (
        "🏥 *Daily Health Check Report*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "📊 *Summary:*\n"
        f"✅ Active: {active_accounts}\n"
        f"❌ Expired: {expired_accounts}\n"
        f"👥 Total: {total_accounts}\n\n"
        f"👤 Bot Users: {total_users}\n"
        f"🚀 Total Campaigns: {total_campaigns}\n\n"
        f"{health_line}"
    )

    for owner_id in get_owner_ids():
        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception:
            pass
