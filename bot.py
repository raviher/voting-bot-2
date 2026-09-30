import logging
import logging.handlers
import os
import sys
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)
from telegram.ext import ApplicationHandlerStop

from handlers.start import start_handler
from handlers.accounts import (
    my_accounts, account_view, account_toggle, account_delete,
    account_delete_confirm, account_health_single,
    add_account_start, add_account_method, add_account_phone, add_account_otp,
    add_account_2fa, add_account_session, add_account_bulk,
    add_account_bulk_zip_skip, add_account_bulk_zip_2fa, add_account_cancel,
    check_account_status, accounts_page,
    account_labels_view, account_label_add_start, account_label_receive, account_label_remove,
    ACCOUNT_METHOD, ACCOUNT_PHONE, ACCOUNT_OTP, ACCOUNT_2FA,
    ACCOUNT_SESSION, ACCOUNT_BULK, ACCOUNT_BULK_ZIP, ACC_LABEL,
)
from handlers.campaigns import (
    my_campaigns, campaign_view, campaign_delete, campaign_delete_confirm,
    campaign_run, campaign_run_confirm, campaign_clone, campaign_stop, campaign_pause, campaign_resume,
    campaign_retry_failed,
    new_campaign_start, camp_get_action, camp_get_target, camp_get_dm_message, campaign_cancel,
    camp_reaction_mode, camp_toggle_react, camp_react_done, camp_get_join_link,
    camp_btn_choice, camp_btn_num_text,
    camp_acct_choice, camp_acct_text,
    campaign_label_filter, campaign_label_set, campaign_label_clear,
    campaign_rename_start, campaign_rename_receive,
    CAMP_ACTION, CAMP_TARGET, CAMP_DM_MESSAGE, CAMP_REACT, CAMP_JOIN_LINK, CAMP_BTN_NUM, CAMP_ACCT_COUNT,
    CAMP_RENAME,
)
from handlers.queue import queue_menu, queue_add, queue_remove, queue_clear, queue_start
from handlers.templates import templates_menu, template_save, template_use, template_delete
from handlers.schedule import (
    schedule_menu, schedule_view, schedule_delete, schedule_delete_confirm, schedule_toggle,
    schedule_dryrun, schedule_toggle_oneshot,
    add_schedule_start, sch_get_name, sch_get_time, sch_get_action, sch_pick_campaign, schedule_cancel,
    sch_days_toggle, sch_days_all, sch_days_done, sch_jitter_pick,
    SCH_NAME, SCH_TIME, SCH_ACTION, SCH_CAMP_PICK, SCH_DAYS, SCH_JITTER,
)
from handlers.stats import my_stats
from handlers.settings import (
    settings_handler, toggle_notifications, language_select,
    set_language, timezone_select, set_timezone,
    speed_select, set_speed, cooldown_select, set_cooldown,
)
from handlers.profile import my_profile
from handlers.help_support import help_guide, support
from handlers.export import (
    export_home, export_accounts, export_campaigns,
    export_schedules, export_broadcasts, export_run_logs, export_all,
    export_user_sessions, export_user_sessions_confirm,
)
from handlers.import_csv import (
    import_home, import_accounts_start, import_campaigns_start,
    handle_import_file, import_cancel, IMPORT_FILE,
)
from handlers.session_logout import (
    LOGOUT_COUNT, LOGOUT_CONFIRM,
    user_logout_cancel, user_logout_confirm, user_logout_count_receive,
    user_logout_start,
)
from handlers.admin import (
    owner_panel, admin_cancel,
    view_adv_users, grant_adv_start, grant_adv_receive_id, grant_adv_receive_limit,
    revoke_adv_pick, adv_set_limit_start, adv_set_limit_receive,
    set_req_channel_start, set_req_channel_receive, clear_req_channel_action,
    set_limit_start, set_limit_receive,
    bot_settings_panel, toggle_maintenance, toggle_paid_mode,
    global_cooldown_select, set_global_cooldown,
    set_owner_username_start, set_owner_username_receive,
    view_owners, add_owner_start, add_owner_receive, remove_owner_action,
    owner_msg_users_start, owner_msg_users_send,
    db_backup,
    db_restore_start, db_restore_receive,
    set_log_channel_start, set_log_channel_receive, clear_log_channel_action,
    GRANT_ADV_ID, GRANT_ADV_LIMIT, SET_CHANNEL, SET_LIMIT, SET_ADV_USER_LIMIT,
    SET_OWNER_USERNAME, ADD_OWNER_ID, OWNER_MSG_STATE, SET_LOG_CHANNEL, RESTORE_FILE,
)
from handlers.adv_campaign import (
    adv_campaign_home, adv_campaign_command, adv_camp_get_action, adv_camp_get_target,
    adv_action_command, adv_reaction_mode_command, adv_reaction_command,
    adv_react_done_command, adv_button_command, adv_accounts_command,
    adv_camp_get_dm_msg, adv_camp_get_join_link, adv_campaign_cancel,
    adv_reaction_mode, adv_toggle_react, adv_react_done,
    adv_btn_choice, adv_btn_num_text,
    adv_acct_choice, adv_acct_text,
    adv_stop, adv_pause, adv_stop_command, adv_pause_command,
    ADV_ACTION, ADV_TARGET, ADV_DM_MESSAGE, ADV_REACT, ADV_JOIN_LINK, ADV_BTN_NUM, ADV_ACCT_COUNT,
)
from handlers.user_mgmt import (
    user_management, user_list_page, user_detail,
    ban_user_action, unban_user_action,
)
from handlers.broadcast import (
    broadcast_home, bcast_pick_target, bcast_custom_targets, bcast_compose,
    bcast_confirm, broadcast_history, bcast_view, bcast_delete, bcast_cancel,
    BCAST_MESSAGE, BCAST_CUSTOM_TARGETS,
)
from handlers.channel_check import check_channel_membership, check_joined_callback
from handlers.health_check import send_daily_health_report
from handlers.session_health import session_health_check, remove_all_expired

def _setup_logging() -> logging.Logger:
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    # Rotating file handler — 5 MB per file, keep last 5 files
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "bot.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_handler)
    # Telegram HTTP request URLs contain the bot token. Keep transport logs
    # quiet so credentials never appear in workflow or file logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return logging.getLogger(__name__)


logger = _setup_logging()


def _validate_env() -> None:
    """Fail fast on startup if critical credentials are missing."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set — cannot start.")
        sys.exit(1)

    api_id = os.environ.get("PYROGRAM_API_ID", "").strip()
    api_hash = os.environ.get("PYROGRAM_API_HASH", "").strip()
    if not api_id or api_id == "0" or not api_hash:
        logger.warning(
            "PYROGRAM_API_ID / PYROGRAM_API_HASH are not set. "
            "Phone-login and session-verification features will not work."
        )


async def _run_due_schedules(context) -> None:
    """Check every minute for schedules whose HH:MM matches the current time in the user's timezone."""
    import re
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    import storage
    from runner import execute_campaign

    now_utc = datetime.now(timezone.utc)

    for uid_str in storage.get_all_user_ids():
        try:
            user_id = int(uid_str)
            schedules = storage.get_schedules(user_id)
            campaigns = storage.get_campaigns(user_id)
        except Exception:
            continue

        # Convert current time to user's configured timezone for comparison
        tz_str = storage.get_settings(user_id).get("timezone", "UTC")
        try:
            now_local = now_utc.astimezone(ZoneInfo(tz_str))
        except (ZoneInfoNotFoundError, Exception):
            now_local = now_utc
        current_hhmm = now_local.strftime("%H:%M")

        for sch in schedules:
            # Skip disabled schedules
            if not sch.get("enabled", True):
                continue

            time_str = sch.get("time", "").strip()
            # Only handle simple HH:MM / H:MM patterns
            if not re.fullmatch(r"\d{1,2}:\d{2}", time_str):
                continue
            # Zero-pad hours so "9:00" == "09:00"
            h, m = time_str.split(":")
            if f"{int(h):02d}:{m}" != current_hhmm:
                continue

            # Resolve campaign: prefer stable campaign_id, then fall back to
            # legacy name-based matching for schedules created before IDs existed.
            campaign_id = sch.get("campaign_id")
            action = sch.get("action", "").strip()
            camp_index: int | None = None

            if campaign_id:
                for i, camp in enumerate(campaigns):
                    if camp.get("id") == campaign_id:
                        camp_index = i
                        break
                if camp_index is None:
                    logger.info(
                        "Schedule '%s' (user %s): campaign_id '%s' no longer exists",
                        sch.get("name"), uid_str, campaign_id,
                    )
                    continue
            else:
                # Legacy: try "campaign:N" index pattern, then name substring
                num_match = re.search(r"campaign[:\s]+(\d+)", action, re.IGNORECASE)
                if num_match:
                    camp_index = int(num_match.group(1))
                else:
                    for i, camp in enumerate(campaigns):
                        if camp.get("name", "").lower() in action.lower():
                            camp_index = i
                            break

                if camp_index is None or camp_index >= len(campaigns):
                    logger.info(
                        "Schedule '%s' (user %s): cannot resolve campaign from action '%s'",
                        sch.get("name"), uid_str, action,
                    )
                    continue

            logger.info(
                "Executing schedule '%s' → campaign[%d] for user %s",
                sch.get("name"), camp_index, uid_str,
            )
            try:
                await execute_campaign(
                    campaigns[camp_index],
                    storage.get_accounts(user_id),
                    user_id,
                    camp_index,
                )
            except Exception as exc:
                logger.error(
                    "Schedule '%s' failed for user %s: %s",
                    sch.get("name"), uid_str, exc,
                )


def main() -> None:
    _validate_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")

    async def post_init(application: Application) -> None:
        from handlers.log_gc import send_log, fmt_bot_started
        try:
            # This deployment uses long polling.  Explicitly remove any
            # webhook left by an earlier Railway deployment before the
            # updater calls getUpdates; otherwise Telegram rejects polling
            # with a Conflict error and no callback queries reach handlers.
            await application.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Telegram webhook cleared; starting long polling")
            me = await application.bot.get_me()
            await send_log(application.bot, fmt_bot_started(me.username or me.first_name))
        except Exception:
            logger.exception("Telegram startup check failed")
            raise

    app = Application.builder().token(token).post_init(post_init).build()

    # ── /cancel command: ends any active conversation and returns to main menu ──
    async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.clear()
        await update.message.reply_text(
            "❌ *Cancelled.* Use /start to return to the main menu.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    _cancel_fallback = CommandHandler(["cancel", "adv_cancel"], cancel_command)

    add_account_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_account_start, pattern="^add_account$")],
        states={
            ACCOUNT_METHOD: [
                CallbackQueryHandler(add_account_method, pattern="^acc_method_(phone|session|bulk)$"),
            ],
            ACCOUNT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_phone)],
            ACCOUNT_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_otp)],
            ACCOUNT_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_2fa)],
            ACCOUNT_SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_session)],
            ACCOUNT_BULK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_bulk),
                MessageHandler(filters.Document.ALL, add_account_bulk),
            ],
            ACCOUNT_BULK_ZIP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_bulk_zip_2fa),
                CallbackQueryHandler(add_account_bulk_zip_skip, pattern="^bulk_zip_skip_2fa$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(add_account_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    new_campaign_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(new_campaign_start, pattern="^new_campaign$")],
        states={
            CAMP_ACTION: [
                CallbackQueryHandler(camp_get_action, pattern="^camp_action_.+$"),
            ],
            CAMP_REACT: [
                CallbackQueryHandler(camp_reaction_mode, pattern=r"^camp_reaction_(simple|premium)$"),
                CallbackQueryHandler(camp_toggle_react, pattern=r"^camp_react_\d+$"),
                CallbackQueryHandler(camp_react_done,   pattern="^camp_react_done$"),
            ],
            CAMP_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, camp_get_target)],
            CAMP_DM_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, camp_get_dm_message)],
            CAMP_JOIN_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, camp_get_join_link),
                CallbackQueryHandler(camp_get_join_link, pattern="^camp_skip_join$"),
            ],
            CAMP_BTN_NUM: [
                CallbackQueryHandler(camp_btn_choice, pattern=r"^camp_btn_(\d+|other)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, camp_btn_num_text),
            ],
            CAMP_ACCT_COUNT: [
                CallbackQueryHandler(camp_acct_choice, pattern="^camp_acct_all$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, camp_acct_text),
            ],
        },
        fallbacks=[CallbackQueryHandler(campaign_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    add_schedule_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_schedule_start, pattern="^add_schedule$")],
        states={
            SCH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sch_get_name)],
            SCH_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sch_get_time)],
            SCH_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, sch_get_action)],
            SCH_CAMP_PICK: [CallbackQueryHandler(sch_pick_campaign, pattern=r"^sch_pick_camp_\d+$")],
            SCH_DAYS: [
                CallbackQueryHandler(sch_days_toggle, pattern=r"^sch_days_toggle_\d+$"),
                CallbackQueryHandler(sch_days_all,    pattern="^sch_days_all$"),
                CallbackQueryHandler(sch_days_done,   pattern="^sch_days_done$"),
            ],
            SCH_JITTER: [
                CallbackQueryHandler(sch_jitter_pick, pattern=r"^sch_jitter_\d+$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(schedule_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    broadcast_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(broadcast_home, pattern="^broadcast$"),
            CallbackQueryHandler(bcast_pick_target, pattern="^bcast_target_.+$"),
        ],
        states={
            BCAST_CUSTOM_TARGETS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bcast_custom_targets)],
            # Accept any message type: text, sticker, photo, video, emoji, etc.
            BCAST_MESSAGE: [MessageHandler(~filters.COMMAND, bcast_compose)],
        },
        fallbacks=[CallbackQueryHandler(bcast_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    import_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(import_accounts_start, pattern="^import_accounts_start$"),
            CallbackQueryHandler(import_campaigns_start, pattern="^import_campaigns_start$"),
        ],
        states={
            IMPORT_FILE: [MessageHandler(filters.Document.ALL, handle_import_file)],
        },
        fallbacks=[CallbackQueryHandler(import_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    grant_adv_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(grant_adv_start, pattern="^grant_adv_start$")],
        states={
            GRANT_ADV_ID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, grant_adv_receive_id)],
            GRANT_ADV_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, grant_adv_receive_limit)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    adv_set_limit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adv_set_limit_start, pattern=r"^adv_set_limit_\d+$")],
        states={
            SET_ADV_USER_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, adv_set_limit_receive)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    set_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_req_channel_start, pattern="^set_req_channel$")],
        states={
            SET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_req_channel_receive)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    set_limit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_limit_start, pattern="^set_account_limit$")],
        states={
            SET_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_limit_receive)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    set_owner_username_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_owner_username_start, pattern="^set_owner_username_start$")],
        states={
            SET_OWNER_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_owner_username_receive)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    add_owner_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_owner_start, pattern="^add_owner_start$")],
        states={
            ADD_OWNER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_owner_receive)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    owner_msg_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(owner_msg_users_start, pattern="^owner_msg_users$")],
        states={
            OWNER_MSG_STATE: [MessageHandler(~filters.COMMAND, owner_msg_users_send)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    set_log_channel_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_log_channel_start, pattern="^set_log_channel_start$")],
        states={
            SET_LOG_CHANNEL: [MessageHandler(filters.ALL & ~filters.COMMAND, set_log_channel_receive)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    db_restore_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(db_restore_start, pattern="^db_restore$")],
        states={
            RESTORE_FILE: [MessageHandler(filters.Document.ALL, db_restore_receive)],
        },
        fallbacks=[CallbackQueryHandler(admin_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    adv_campaign_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(adv_campaign_home, pattern="^adv_campaign$"),
            CommandHandler(["advcampaign", "adv_start"], adv_campaign_command),
            CommandHandler(
                [
                    "adv_react", "adv_vote", "adv_react_vote",
                    "adv_view", "adv_react_view", "adv_vote_view",
                    "adv_react_vote_view", "adv_join", "adv_leave",
                    "adv_leave_all", "adv_bulk_dm", "adv_bot_referral",
                ],
                adv_action_command,
            ),
        ],
        states={
            ADV_ACTION: [
                CallbackQueryHandler(adv_camp_get_action, pattern="^camp_action_.+$"),
                CommandHandler(
                    [
                        "adv_react", "adv_vote", "adv_react_vote",
                        "adv_view", "adv_react_view", "adv_vote_view",
                        "adv_react_vote_view", "adv_join", "adv_leave",
                        "adv_leave_all", "adv_bulk_dm", "adv_bot_referral",
                    ],
                    adv_action_command,
                ),
            ],
            ADV_REACT: [
                CallbackQueryHandler(adv_reaction_mode, pattern=r"^adv_reaction_(simple|premium)$"),
                CallbackQueryHandler(adv_toggle_react, pattern=r"^adv_react_\d+$"),
                CallbackQueryHandler(adv_react_done,   pattern="^adv_react_done$"),
                CommandHandler(["adv_simple", "adv_premium"], adv_reaction_mode_command),
                CommandHandler("adv_reaction", adv_reaction_command),
                CommandHandler("adv_done", adv_react_done_command),
            ],
            ADV_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, adv_camp_get_target)],
            ADV_DM_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, adv_camp_get_dm_msg)],
            ADV_JOIN_LINK: [
                CallbackQueryHandler(adv_camp_get_join_link, pattern="^adv_skip_join$"),
                CommandHandler("adv_skip_join", adv_camp_get_join_link),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adv_camp_get_join_link),
            ],
            ADV_BTN_NUM: [
                CallbackQueryHandler(adv_btn_choice, pattern=r"^adv_btn_(\d+|other)$"),
                CommandHandler("adv_button", adv_button_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adv_btn_num_text),
            ],
            ADV_ACCT_COUNT: [
                CallbackQueryHandler(adv_acct_choice, pattern="^adv_acct_all$"),
                CommandHandler("adv_accounts", adv_accounts_command),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adv_acct_text),
            ],
        },
        fallbacks=[CallbackQueryHandler(adv_campaign_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("cancel", cancel_command))
    # Command shortcuts
    app.add_handler(CommandHandler("stats",     my_stats))
    app.add_handler(CommandHandler("me",        my_profile))
    app.add_handler(CommandHandler("accounts",  my_accounts))
    app.add_handler(CommandHandler("campaigns", my_campaigns))
    app.add_handler(CommandHandler("help",      help_guide))
    app.add_handler(CommandHandler("admin",     owner_panel))

    async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Quick health/status overview for owners."""
        from storage import is_owner, get_global_stats, get_maintenance_mode, get_paid_mode
        import uptime as _uptime
        user_id = update.effective_user.id
        if not is_owner(user_id):
            await update.message.reply_text("⛔ This command is restricted to the bot owner.")
            return
        stats = get_global_stats()
        mode_parts = []
        if get_maintenance_mode():
            mode_parts.append("🔧 Maintenance")
        if get_paid_mode():
            mode_parts.append("💎 Paid mode")
        mode_str = "  |  ".join(mode_parts) if mode_parts else "✅ Normal"
        text = (
            "🤖 *Bot Status*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 *Status:* Online\n"
            f"🕐 *Uptime:* {_uptime.get_uptime_str()}\n"
            f"⚙️ *Mode:* {mode_str}\n\n"
            f"👥 *Users:* {stats['users']}\n"
            f"📦 *Accounts:* {stats['accounts']}  ·  Active: {stats['active']}\n"
            f"🚀 *Campaigns:* {stats['campaigns']}  ·  Running: {stats['running']}\n"
            f"⚡ *Total Actions:* {stats['actions']}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("adv_stop", adv_stop_command))
    app.add_handler(CommandHandler("adv_pause", adv_pause_command))
    add_label_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(account_label_add_start, pattern=r"^acc_lbl_add_\d+$")],
        states={
            ACC_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, account_label_receive)],
        },
        fallbacks=[_cancel_fallback],
        per_message=False,
    )

    campaign_rename_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(campaign_rename_start, pattern=r"^camp_rename_\d+$")],
        states={
            CAMP_RENAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, campaign_rename_receive)],
        },
        fallbacks=[CallbackQueryHandler(campaign_cancel, pattern="^main_menu$"), _cancel_fallback],
        per_message=False,
    )

    logout_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(user_logout_start, pattern=r"^user_logout_start_\d+$")
        ],
        states={
            LOGOUT_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_logout_count_receive),
                CallbackQueryHandler(
                    user_logout_cancel, pattern=r"^user_logout_cancel_\d+$"
                ),
            ],
            LOGOUT_CONFIRM: [
                CallbackQueryHandler(
                    user_logout_confirm, pattern=r"^user_logout_confirm_\d+$"
                ),
                CallbackQueryHandler(
                    user_logout_cancel, pattern=r"^user_logout_cancel_\d+$"
                ),
            ],
        },
        fallbacks=[_cancel_fallback],
        per_message=False,
    )

    app.add_handler(add_account_conv)
    app.add_handler(add_label_conv)
    app.add_handler(new_campaign_conv)
    app.add_handler(campaign_rename_conv)
    app.add_handler(logout_conv)
    app.add_handler(add_schedule_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(import_conv)
    app.add_handler(grant_adv_conv)
    app.add_handler(adv_set_limit_conv)
    app.add_handler(set_channel_conv)
    app.add_handler(set_limit_conv)
    app.add_handler(set_owner_username_conv)
    app.add_handler(add_owner_conv)
    app.add_handler(owner_msg_conv)
    app.add_handler(set_log_channel_conv)
    app.add_handler(db_restore_conv)
    app.add_handler(adv_campaign_conv)

    app.add_handler(CallbackQueryHandler(start_handler, pattern="^main_menu$"))
    async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Acknowledge informational buttons that do not change the current view."""
        await update.callback_query.answer("This is an owner account.")

    app.add_handler(CallbackQueryHandler(my_accounts, pattern="^my_accounts$"))
    app.add_handler(CallbackQueryHandler(noop_callback, pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(accounts_page, pattern="^acc_page_\\d+$"))
    app.add_handler(CallbackQueryHandler(account_view, pattern="^acc_view_\\d+$"))
    app.add_handler(CallbackQueryHandler(account_toggle, pattern="^acc_toggle_\\d+$"))
    app.add_handler(CallbackQueryHandler(account_delete, pattern="^acc_delete_\\d+$"))
    app.add_handler(CallbackQueryHandler(account_delete_confirm, pattern="^acc_delete_confirm_\\d+$"))
    app.add_handler(CallbackQueryHandler(account_health_single, pattern="^acc_health_\\d+$"))
    app.add_handler(CallbackQueryHandler(check_account_status, pattern="^check_account_status$"))
    app.add_handler(CallbackQueryHandler(account_labels_view,  pattern=r"^acc_labels_\d+$"))
    app.add_handler(CallbackQueryHandler(account_label_remove, pattern=r"^acc_lbl_rm_\d+_.+$"))
    # noop for label display button
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern=r"^acc_lbl_noop_\d+$"))
    app.add_handler(CallbackQueryHandler(my_campaigns, pattern="^my_campaigns$"))
    app.add_handler(CallbackQueryHandler(campaign_view, pattern="^camp_view_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_run, pattern="^camp_run_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_run_confirm, pattern="^camp_run_confirm_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_clone, pattern="^camp_clone_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_stop,   pattern="^camp_stop_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_pause,  pattern="^camp_pause_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_resume, pattern="^camp_resume_\\d+$"))
    app.add_handler(CallbackQueryHandler(adv_stop,  pattern="^adv_stop_\\d+$"))
    app.add_handler(CallbackQueryHandler(adv_pause, pattern="^adv_pause_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_delete, pattern="^camp_delete_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_delete_confirm, pattern="^camp_delete_confirm_\\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_retry_failed,  pattern=r"^camp_retry_\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_label_filter, pattern=r"^camp_lbl_\d+$"))
    app.add_handler(CallbackQueryHandler(campaign_label_set,    pattern=r"^camp_lbl_set_\d+_.+$"))
    app.add_handler(CallbackQueryHandler(campaign_label_clear,  pattern=r"^camp_lbl_clear_\d+$"))
    # Queue handlers
    app.add_handler(CallbackQueryHandler(queue_menu,   pattern="^queue_menu$"))
    app.add_handler(CallbackQueryHandler(queue_add,    pattern=r"^queue_add_\d+$"))
    app.add_handler(CallbackQueryHandler(queue_remove, pattern=r"^queue_remove_\d+$"))
    app.add_handler(CallbackQueryHandler(queue_clear,  pattern="^queue_clear$"))
    app.add_handler(CallbackQueryHandler(queue_start,  pattern="^queue_start$"))
    # Template handlers
    app.add_handler(CallbackQueryHandler(templates_menu,   pattern="^templates_menu$"))
    app.add_handler(CallbackQueryHandler(template_save,    pattern=r"^tpl_save_\d+$"))
    app.add_handler(CallbackQueryHandler(template_use,     pattern=r"^tpl_use_\d+$"))
    app.add_handler(CallbackQueryHandler(template_delete,  pattern=r"^tpl_delete_\d+$"))
    app.add_handler(CallbackQueryHandler(schedule_menu,          pattern="^schedule$"))
    app.add_handler(CallbackQueryHandler(schedule_view,          pattern="^sch_view_\\d+$"))
    app.add_handler(CallbackQueryHandler(schedule_toggle,        pattern="^sch_toggle_\\d+$"))
    app.add_handler(CallbackQueryHandler(schedule_delete,        pattern="^sch_delete_\\d+$"))
    app.add_handler(CallbackQueryHandler(schedule_delete_confirm, pattern="^sch_delete_confirm_\\d+$"))
    app.add_handler(CallbackQueryHandler(schedule_dryrun,        pattern=r"^sch_dryrun_\d+$"))
    app.add_handler(CallbackQueryHandler(schedule_toggle_oneshot, pattern=r"^sch_oneshot_\d+$"))
    app.add_handler(CallbackQueryHandler(my_stats, pattern="^my_stats$"))
    app.add_handler(CallbackQueryHandler(settings_handler, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(toggle_notifications, pattern="^setting_toggle_notifications$"))
    app.add_handler(CallbackQueryHandler(language_select, pattern="^setting_language$"))
    app.add_handler(CallbackQueryHandler(set_language, pattern="^lang_[a-z]+$"))
    app.add_handler(CallbackQueryHandler(timezone_select, pattern="^setting_timezone$"))
    app.add_handler(CallbackQueryHandler(set_timezone, pattern="^tz_.+$"))
    app.add_handler(CallbackQueryHandler(speed_select, pattern="^setting_speed$"))
    app.add_handler(CallbackQueryHandler(set_speed,        pattern="^speed_(slow|normal|fast|ultra|smart)$"))
    app.add_handler(CallbackQueryHandler(cooldown_select,  pattern="^setting_cooldown$"))
    app.add_handler(CallbackQueryHandler(set_cooldown,     pattern=r"^cooldown_\d+$"))
    app.add_handler(CallbackQueryHandler(my_profile, pattern="^my_profile$"))
    app.add_handler(CallbackQueryHandler(help_guide, pattern="^help_guide$"))
    app.add_handler(CallbackQueryHandler(support, pattern="^support$"))
    app.add_handler(CallbackQueryHandler(broadcast_history, pattern="^broadcast_history$"))
    app.add_handler(CallbackQueryHandler(bcast_view, pattern="^bcast_view_\\d+$"))
    app.add_handler(CallbackQueryHandler(bcast_delete, pattern="^bcast_delete_\\d+$"))
    app.add_handler(CallbackQueryHandler(bcast_confirm, pattern="^bcast_confirm$"))
    app.add_handler(CallbackQueryHandler(owner_panel,        pattern="^owner_panel$"))
    app.add_handler(CallbackQueryHandler(view_owners,         pattern="^owners_list$"))
    app.add_handler(CallbackQueryHandler(remove_owner_action, pattern=r"^owner_remove_\d+$"))
    app.add_handler(CallbackQueryHandler(view_adv_users,      pattern="^adv_access_list$"))
    app.add_handler(CallbackQueryHandler(revoke_adv_pick,     pattern=r"^adv_revoke_\d+$"))
    app.add_handler(CallbackQueryHandler(clear_req_channel_action, pattern="^clear_req_channel$"))
    app.add_handler(CallbackQueryHandler(bot_settings_panel,    pattern="^bot_settings$"))
    app.add_handler(CallbackQueryHandler(toggle_maintenance,    pattern="^toggle_maintenance$"))
    app.add_handler(CallbackQueryHandler(toggle_paid_mode,      pattern="^toggle_paid_mode$"))
    app.add_handler(CallbackQueryHandler(global_cooldown_select, pattern="^global_cooldown_select$"))
    app.add_handler(CallbackQueryHandler(set_global_cooldown,    pattern=r"^global_cooldown_\d+$"))
    app.add_handler(CallbackQueryHandler(db_backup,               pattern="^db_backup$"))
    app.add_handler(CallbackQueryHandler(clear_log_channel_action, pattern="^clear_log_channel$"))

    async def health_report_now(update: Update, context) -> None:
        query = update.callback_query
        from storage import is_owner
        if not is_owner(update.effective_user.id):
            await query.answer("⛔ Owner only.", show_alert=True)
            return
        await send_daily_health_report(context)
        await query.answer("✅ Health report sent!", show_alert=True)

    app.add_handler(CallbackQueryHandler(health_report_now, pattern="^health_report_now$"))
    app.add_handler(CallbackQueryHandler(session_health_check, pattern="^session_health_check$"))
    app.add_handler(CallbackQueryHandler(remove_all_expired, pattern="^remove_all_expired$"))
    app.add_handler(CallbackQueryHandler(import_home, pattern="^import_home$"))
    app.add_handler(CallbackQueryHandler(export_home, pattern="^export_home$"))
    app.add_handler(CallbackQueryHandler(export_accounts, pattern="^export_accounts$"))
    app.add_handler(CallbackQueryHandler(export_campaigns, pattern="^export_campaigns$"))
    app.add_handler(CallbackQueryHandler(export_schedules, pattern="^export_schedules$"))
    app.add_handler(CallbackQueryHandler(export_broadcasts, pattern="^export_broadcasts$"))
    app.add_handler(CallbackQueryHandler(export_run_logs, pattern="^export_run_logs$"))
    app.add_handler(CallbackQueryHandler(export_all, pattern="^export_all$"))
    app.add_handler(CallbackQueryHandler(user_management, pattern="^user_management$"))
    app.add_handler(CallbackQueryHandler(user_list_page, pattern="^user_page_\\d+$"))
    app.add_handler(CallbackQueryHandler(user_detail, pattern="^user_detail_\\d+$"))
    app.add_handler(CallbackQueryHandler(
        export_user_sessions, pattern=r"^user_export_sessions_\d+$"
    ))
    app.add_handler(CallbackQueryHandler(
        export_user_sessions_confirm, pattern=r"^user_export_confirm_\d+$"
    ))
    app.add_handler(CallbackQueryHandler(ban_user_action, pattern="^user_ban_\\d+$"))
    app.add_handler(CallbackQueryHandler(unban_user_action, pattern="^user_unban_\\d+$"))
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="^check_joined$"))

    async def unhandled_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Never leave a callback button spinning when its data is unknown."""
        query = update.callback_query
        if not query:
            return
        logger.warning(
            "Unhandled callback query: data=%r user_id=%s",
            query.data,
            update.effective_user.id if update.effective_user else None,
        )
        await query.answer(
            "This button is no longer active. Please send /start and try again.",
            show_alert=True,
        )

    # Keep this after the normal handlers in the same group. PTB stops after
    # the first matching handler in a group, so this runs only when no real
    # callback handler matched. A later group would run after every button.
    app.add_handler(CallbackQueryHandler(unhandled_callback), group=0)

    async def ban_check(update: Update, context) -> None:
        user = update.effective_user
        if not user:
            return
        from storage import is_banned, is_owner
        if is_banned(user.id) and not is_owner(user.id):
            if update.message:
                await update.message.reply_text(
                    "🚫 *You have been banned from using this bot.*\n\n"
                    "If you believe this is a mistake, please contact support.",
                    parse_mode="Markdown"
                )
            elif update.callback_query:
                await update.callback_query.answer(
                    "🚫 You are banned from using this bot.", show_alert=True
                )
            raise ApplicationHandlerStop

    async def maintenance_check(update: Update, context) -> None:
        user = update.effective_user
        if not user:
            return
        from storage import get_maintenance_mode, is_owner
        if not get_maintenance_mode() or is_owner(user.id):
            return
        text = (
            "🛠 *Under Maintenance*\n\n"
            "The bot is temporarily unavailable while we perform maintenance. "
            "Please try again shortly."
        )
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.answer("🛠 Bot is under maintenance. Try again shortly.", show_alert=True)
        raise ApplicationHandlerStop

    async def channel_check(update: Update, context) -> None:
        from storage import is_owner
        user = update.effective_user
        if not user:
            return
        if is_owner(user.id):
            return
        # The "I Joined" callback must reach its dedicated handler so it can
        # perform a fresh verification and then open the main menu.
        if update.callback_query and update.callback_query.data == "check_joined":
            return

        if await check_channel_membership(update, context):
            return
        raise ApplicationHandlerStop

    app.add_handler(TypeHandler(Update, ban_check), group=-1)
    app.add_handler(TypeHandler(Update, maintenance_check), group=-2)
    app.add_handler(TypeHandler(Update, channel_check), group=-3)

    async def error_handler(update: object, context) -> None:
        logger.error("Unhandled exception while handling update:", exc_info=context.error)
        if not isinstance(context.error, Exception):
            return
        from storage import get_owner_ids
        from handlers.log_gc import send_log, fmt_error
        import re as _re
        def _esc_err(s: str) -> str:
            return _re.sub(r'([_*\[\]`\\])', r'\\\1', str(s))
        error_preview = f"{type(context.error).__name__}: {str(context.error)[:200]}"
        msg = f"⚠️ *Bot Error*\n\n{_esc_err(error_preview)}"
        for owner_id in get_owner_ids():
            try:
                await context.bot.send_message(
                    chat_id=owner_id,
                    text=msg,
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        await send_log(context.bot, fmt_error(type(context.error).__name__, str(context.error)[:300]))

    app.add_error_handler(error_handler)

    async def trace_callback_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log callback delivery before any access/conversation checks run."""
        if update.callback_query:
            logger.info(
                "Received callback query: data=%r user_id=%s",
                update.callback_query.data,
                update.effective_user.id if update.effective_user else None,
            )

    # Keep this in an early group so Railway logs prove whether Telegram
    # delivered the button press, even when a later guard stops the update.
    app.add_handler(TypeHandler(Update, trace_callback_update), group=-4)

    import datetime
    app.job_queue.run_daily(
        send_daily_health_report,
        time=datetime.time(hour=7, minute=0, second=0),
        name="daily_health_check",
    )
    logger.info("Daily health check scheduled at 07:00 UTC")

    # Schedule runner — fires every minute, picks up HH:MM schedules
    app.job_queue.run_repeating(
        _run_due_schedules,
        interval=60,
        first=10,
        name="schedule_runner",
    )
    logger.info("Schedule runner started (checks every 60s)")

    logger.info("Bot is starting...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
