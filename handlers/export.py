import csv
import io
import re
import zipfile
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import ContextTypes
from storage import (
    OWNER_ID,
    append_audit_log,
    get_accounts,
    get_broadcasts,
    get_campaigns,
    get_schedules,
)
from keyboards import export_menu, back_button


def _session_file_stem(account: dict, index: int) -> str:
    """Return a safe filename without exposing the session itself."""
    label = account.get("username") or account.get("name") or f"account_{index + 1}"
    label = str(label).lstrip("@")
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("._-") or f"account_{index + 1}"
    tg_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(account.get("tg_id") or "unknown"))
    return f"{index + 1:03d}_{label[:40]}_{tg_id}.txt"


async def export_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    accounts = get_accounts(user_id)
    campaigns = get_campaigns(user_id)
    schedules = get_schedules(user_id)
    broadcasts = get_broadcasts(user_id)

    text = (
        "📤 *EXPORT DATA*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Download your data as a CSV file.\n\n"
        f"📦 Accounts: *{len(accounts)}* records\n"
        f"🚀 Campaigns: *{len(campaigns)}* records\n"
        f"⏰ Schedules: *{len(schedules)}* records\n"
        f"📢 Broadcasts: *{len(broadcasts)}* records\n\n"
        "Choose what to export:"
    )
    await query.edit_message_text(
        text,
        reply_markup=export_menu(
            bool(accounts),
            bool(campaigns),
            bool(schedules),
            bool(broadcasts),
        ),
        parse_mode="Markdown",
    )


async def export_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Generating CSV...", show_alert=False)
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Username", "Status", "Added"])
    if not accounts:
        writer.writerow(["No accounts yet", "", "", ""])
    else:
        for acc in accounts:
            writer.writerow([
                acc.get("name", ""),
                acc.get("username", ""),
                acc.get("status", "active"),
                acc.get("added", ""),
            ])

    filename = f"accounts_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    buf.seek(0)
    file_bytes = buf.getvalue().encode("utf-8")

    await query.edit_message_text(
        f"✅ *Accounts Export Ready*\n\n{len(accounts)} record(s) exported.",
        reply_markup=back_button("export_home"),
        parse_mode="Markdown"
    )
    await context.bot.send_document(
        chat_id=user_id,
        document=InputFile(io.BytesIO(file_bytes), filename=filename),
        caption=f"📦 Accounts — {len(accounts)} record(s)\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


async def export_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Generating CSV...", show_alert=False)
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Target", "Message", "Status", "Actions", "Created"])
    if not campaigns:
        writer.writerow(["No campaigns yet", "", "", "", "", ""])
    else:
        for camp in campaigns:
            writer.writerow([
                camp.get("name", ""),
                camp.get("target", ""),
                camp.get("message", ""),
                "Active" if camp.get("active") else "Paused",
                camp.get("actions", 0),
                camp.get("created", ""),
            ])

    filename = f"campaigns_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    buf.seek(0)
    file_bytes = buf.getvalue().encode("utf-8")

    await query.edit_message_text(
        f"✅ *Campaigns Export Ready*\n\n{len(campaigns)} record(s) exported.",
        reply_markup=back_button("export_home"),
        parse_mode="Markdown"
    )
    await context.bot.send_document(
        chat_id=user_id,
        document=InputFile(io.BytesIO(file_bytes), filename=filename),
        caption=f"🚀 Campaigns — {len(campaigns)} record(s)\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


async def export_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Generating CSV...", show_alert=False)
    user_id = update.effective_user.id
    schedules = get_schedules(user_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Time", "Action", "Created"])
    if not schedules:
        writer.writerow(["No schedules yet", "", "", ""])
    else:
        for sch in schedules:
            writer.writerow([
                sch.get("name", ""),
                sch.get("time", ""),
                sch.get("action", ""),
                sch.get("created", ""),
            ])

    filename = f"schedules_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    buf.seek(0)
    file_bytes = buf.getvalue().encode("utf-8")

    await query.edit_message_text(
        f"✅ *Schedules Export Ready*\n\n{len(schedules)} record(s) exported.",
        reply_markup=back_button("export_home"),
        parse_mode="Markdown"
    )
    await context.bot.send_document(
        chat_id=user_id,
        document=InputFile(io.BytesIO(file_bytes), filename=filename),
        caption=f"⏰ Schedules — {len(schedules)} record(s)\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


async def export_broadcasts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Generating CSV...", show_alert=False)
    user_id = update.effective_user.id
    broadcasts = get_broadcasts(user_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Target Label", "Sent To", "Recipients", "Message"])
    if not broadcasts:
        writer.writerow(["No broadcasts yet", "", "", "", ""])
    else:
        for b in broadcasts:
            writer.writerow([
                b.get("date", ""),
                b.get("target_label", ""),
                b.get("sent_to", 0),
                ", ".join(b.get("targets", [])),
                b.get("message", ""),
            ])

    filename = f"broadcasts_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    buf.seek(0)
    file_bytes = buf.getvalue().encode("utf-8")

    await query.edit_message_text(
        f"✅ *Broadcast History Export Ready*\n\n{len(broadcasts)} record(s) exported.",
        reply_markup=back_button("export_home"),
        parse_mode="Markdown"
    )
    await context.bot.send_document(
        chat_id=user_id,
        document=InputFile(io.BytesIO(file_bytes), filename=filename),
        caption=f"📢 Broadcast History — {len(broadcasts)} record(s)\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


async def export_run_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export all campaign run logs as a CSV."""
    query = update.callback_query
    await query.answer("Generating CSV...", show_alert=False)
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Campaign", "Timestamp", "Done", "Failed", "Elapsed"])
    total_rows = 0
    for camp in campaigns:
        camp_name = camp.get("name", "")
        for r in camp.get("run_log", []):
            writer.writerow([
                camp_name,
                r.get("ts", ""),
                r.get("done", 0),
                r.get("failed", 0),
                r.get("elapsed", ""),
            ])
            total_rows += 1
    if total_rows == 0:
        writer.writerow(["No run logs yet", "", "", "", ""])

    filename = f"run_logs_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    buf.seek(0)
    file_bytes = buf.getvalue().encode("utf-8")

    await query.edit_message_text(
        f"✅ *Run Logs Export Ready*\n\n{total_rows} run record(s) across {len(campaigns)} campaign(s).",
        reply_markup=back_button("export_home"),
        parse_mode="Markdown",
    )
    await context.bot.send_document(
        chat_id=user_id,
        document=InputFile(io.BytesIO(file_bytes), filename=filename),
        caption=f"📈 Campaign Run Logs — {total_rows} record(s)\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )


async def export_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Generating full export...", show_alert=False)
    user_id = update.effective_user.id

    accounts = get_accounts(user_id)
    campaigns = get_campaigns(user_id)
    schedules = get_schedules(user_id)
    broadcasts = get_broadcasts(user_id)

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["=== ACCOUNTS ==="])
    writer.writerow(["Name", "Username", "Status", "Added"])
    for acc in accounts:
        writer.writerow([acc.get("name", ""), acc.get("username", ""), acc.get("status", ""), acc.get("added", "")])
    if not accounts:
        writer.writerow(["No accounts"])

    writer.writerow([])
    writer.writerow(["=== CAMPAIGNS ==="])
    writer.writerow(["Name", "Target", "Message", "Status", "Actions", "Created"])
    for camp in campaigns:
        writer.writerow([
            camp.get("name", ""), camp.get("target", ""), camp.get("message", ""),
            "Active" if camp.get("active") else "Paused", camp.get("actions", 0), camp.get("created", "")
        ])
    if not campaigns:
        writer.writerow(["No campaigns"])

    writer.writerow([])
    writer.writerow(["=== SCHEDULES ==="])
    writer.writerow(["Name", "Time", "Action", "Created"])
    for sch in schedules:
        writer.writerow([sch.get("name", ""), sch.get("time", ""), sch.get("action", ""), sch.get("created", "")])
    if not schedules:
        writer.writerow(["No schedules"])

    writer.writerow([])
    writer.writerow(["=== BROADCAST HISTORY ==="])
    writer.writerow(["Date", "Target Label", "Sent To", "Recipients", "Message"])
    for b in broadcasts:
        writer.writerow([
            b.get("date", ""), b.get("target_label", ""), b.get("sent_to", 0),
            ", ".join(b.get("targets", [])), b.get("message", "")
        ])
    if not broadcasts:
        writer.writerow(["No broadcasts"])

    filename = f"full_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    buf.seek(0)
    file_bytes = buf.getvalue().encode("utf-8")

    total = len(accounts) + len(campaigns) + len(schedules) + len(broadcasts)
    await query.edit_message_text(
        f"✅ *Full Export Ready*\n\n{total} total records across all sections.",
        reply_markup=back_button("export_home"),
        parse_mode="Markdown"
    )
    await context.bot.send_document(
        chat_id=user_id,
        document=InputFile(io.BytesIO(file_bytes), filename=filename),
        caption=(
            f"📤 Full Export\n"
            f"📦 Accounts: {len(accounts)}  🚀 Campaigns: {len(campaigns)}\n"
            f"⏰ Schedules: {len(schedules)}  📢 Broadcasts: {len(broadcasts)}\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
    )


def _login_zip_keyboard(target_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "⚠️ Confirm & Send ZIP",
            callback_data=f"user_export_confirm_{target_uid}",
            style="danger",
        ),
        InlineKeyboardButton(
            "Cancel",
            callback_data=f"user_detail_{target_uid}",
            style="primary",
        ),
    ]])


async def export_user_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a confirmation screen before exporting another user's sessions."""
    query = update.callback_query
    await query.answer()

    owner_id = update.effective_user.id
    if owner_id != OWNER_ID:
        await query.answer("⛔ Primary owner only.", show_alert=True)
        return

    try:
        target_uid = int(query.data.replace("user_export_sessions_", "", 1))
    except (TypeError, ValueError):
        await query.answer("⚠️ Invalid user.", show_alert=True)
        return

    accounts = get_accounts(target_uid)
    exportable = [
        account for account in accounts
        if isinstance(account.get("identifier"), str)
        and len(account["identifier"].strip()) >= 20
    ]
    if not exportable:
        await query.edit_message_text(
            "⚠️ *No login sessions found*\n\n"
            f"User `{target_uid}` has no exportable login sessions.",
            reply_markup=back_button(f"user_detail_{target_uid}"),
            parse_mode="Markdown",
        )
        return

    await query.edit_message_text(
        "⚠️ *EXPORT LOGIN SESSIONS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"User: `{target_uid}`\n"
        f"Accounts with sessions: *{len(exportable)}*\n\n"
        "The ZIP will contain login credentials for these Telegram accounts. "
        "Anyone who gets this file may be able to access them. "
        "Store it securely and delete it after use.\n\n"
        "Send the ZIP to the primary owner now?",
        reply_markup=_login_zip_keyboard(target_uid),
        parse_mode="Markdown",
    )


async def export_user_sessions_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Create and send a selected user's login-session ZIP to the primary owner."""
    query = update.callback_query
    await query.answer("Generating secure ZIP...", show_alert=False)

    owner_id = update.effective_user.id
    if owner_id != OWNER_ID:
        await query.answer("⛔ Primary owner only.", show_alert=True)
        return

    try:
        target_uid = int(query.data.replace("user_export_confirm_", "", 1))
    except (TypeError, ValueError):
        await query.answer("⚠️ Invalid user.", show_alert=True)
        return

    accounts = get_accounts(target_uid)
    exported = []
    session_strings = []
    session_filename = "sessions/session_ids.txt"
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow([
        "Account Number", "Telegram ID", "Name", "Username", "Phone",
        "Status", "Method", "Session File",
    ])

    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(
        zip_bytes, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for index, account in enumerate(accounts):
            session = account.get("identifier")
            if not isinstance(session, str) or len(session.strip()) < 20:
                continue

            session_strings.append(session.strip())
            # Keep correctly labelled text copies for tools that accept one
            # Pyrogram string per uploaded file. These are not SQLite
            # session databases and must not use a .session extension.
            archive.writestr(
                f"sessions/{_session_file_stem(account, index)}",
                session.strip() + "\n",
            )
            writer.writerow([
                index + 1,
                account.get("tg_id", ""),
                account.get("name", ""),
                account.get("username", ""),
                account.get("phone", ""),
                account.get("status", ""),
                account.get("method", ""),
                session_filename,
            ])
            exported.append(account)

        if session_strings:
            archive.writestr(session_filename, "\n".join(session_strings) + "\n")
        archive.writestr("accounts.csv", manifest.getvalue())
        archive.writestr(
            "README.txt",
            "This ZIP contains Telegram login session credentials.\n"
            "Keep it private, do not forward it, and delete it after use.\n"
            "To import it into RAVI: Add Account > Bulk Import and upload this ZIP.\n"
            "The file sessions/session_ids.txt contains all Pyrogram session strings,\n"
            "one per line, in the same order as Account Number in accounts.csv.\n"
            "Individual .txt copies are included for tools that require one\n"
            "Pyrogram string per uploaded file. Do not rename them to .session:\n"
            ".session files are SQLite databases, while these files contain text.\n",
        )

    if not exported:
        await query.edit_message_text(
            "⚠️ No exportable login sessions remain for this user.",
            reply_markup=back_button(f"user_detail_{target_uid}"),
            parse_mode="Markdown",
        )
        return

    zip_bytes.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"user_{target_uid}_login_sessions_{timestamp}.zip"
    append_audit_log(
        owner_id,
        "export_login_zip",
        f"target_user_id={target_uid}; accounts={len(exported)}",
    )

    await query.edit_message_text(
        "✅ *Login ZIP Ready*\n\n"
        f"User `{target_uid}` — {len(exported)} account(s) exported.\n\n"
        "Keep this file private and delete it after importing or using it.",
        reply_markup=back_button(f"user_detail_{target_uid}"),
        parse_mode="Markdown",
    )
    await context.bot.send_document(
        chat_id=owner_id,
        document=InputFile(zip_bytes, filename=filename),
        caption=(
            f"🔐 Login sessions for user {target_uid}\n"
            f"📦 {len(exported)} account(s)\n"
            "⚠️ Contains credentials — keep private."
        ),
    )
