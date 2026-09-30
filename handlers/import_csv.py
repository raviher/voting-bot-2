import csv
import io
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from storage import add_account, add_campaign, get_accounts, get_campaigns, get_all_user_ids, get_user
from keyboards import import_menu, cancel_button, back_button

IMPORT_FILE = 0


async def import_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    text = (
        "📥 *IMPORT DATA*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Bulk-add records by uploading a CSV file.\n\n"
        "📋 *Supported imports:*\n"
        "• Accounts (Name, Username, Status)\n"
        "• Campaigns (Name, Target, Message)\n\n"
        "Choose what to import:"
    )
    await query.edit_message_text(text, reply_markup=import_menu(), parse_mode="Markdown")


async def import_accounts_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["import_type"] = "accounts"

    text = (
        "📥 *IMPORT ACCOUNTS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Upload a CSV file with the following columns:\n\n"
        "`Name, Username, Status`\n\n"
        "📌 *Rules:*\n"
        "• First row must be the header\n"
        "• `Name` and `Username` are required\n"
        "• `Status` is optional — defaults to `active`\n"
        "• Valid statuses: `active`, `dead`\n\n"
        "*Example:*\n"
        "```\n"
        "Name,Username,Status\n"
        "John Doe,johndoe,active\n"
        "Jane Smith,janesmith,dead\n"
        "```\n\n"
        "Upload your CSV file now:"
    )
    await query.edit_message_text(text, reply_markup=cancel_button(), parse_mode="Markdown")
    return IMPORT_FILE


async def import_campaigns_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["import_type"] = "campaigns"

    text = (
        "📥 *IMPORT CAMPAIGNS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Upload a CSV file with the following columns:\n\n"
        "`Name, Target, Message`\n\n"
        "📌 *Rules:*\n"
        "• First row must be the header\n"
        "• `Name`, `Target`, and `Message` are required\n"
        "• Any extra columns are safely ignored\n\n"
        "*Example:*\n"
        "```\n"
        "Name,Target,Message\n"
        "Spring Push,@groupname,Hello! Check this out.\n"
        "Outreach,@channel,Special offer just for you!\n"
        "```\n\n"
        "Upload your CSV file now:"
    )
    await query.edit_message_text(text, reply_markup=cancel_button(), parse_mode="Markdown")
    return IMPORT_FILE


async def handle_import_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    import_type = context.user_data.get("import_type", "accounts")
    doc = update.message.document

    if not doc:
        await update.message.reply_text(
            "⚠️ Please upload a CSV file (not a photo or other file type).",
            reply_markup=cancel_button()
        )
        return IMPORT_FILE

    if not doc.file_name.lower().endswith(".csv"):
        await update.message.reply_text(
            "⚠️ Only `.csv` files are supported. Please upload a valid CSV file.",
            reply_markup=cancel_button()
        )
        return IMPORT_FILE

    if doc.file_size > 500_000:
        await update.message.reply_text(
            "⚠️ File is too large (max 500 KB). Please reduce the file size and try again.",
            reply_markup=cancel_button()
        )
        return IMPORT_FILE

    processing_msg = await update.message.reply_text("⏳ Processing your file...")

    try:
        tg_file = await context.bot.get_file(doc.file_id)
        file_bytes = await tg_file.download_as_bytearray()
        text_content = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text_content))
        rows = list(reader)
    except Exception as e:
        await processing_msg.edit_text(
            f"❌ Could not read the file. Make sure it's a valid UTF-8 CSV.\n\nError: {e}",
            reply_markup=back_button("import_home")
        )
        return ConversationHandler.END

    if import_type == "accounts":
        result = await _import_accounts(user_id, rows)
    else:
        result = await _import_campaigns(user_id, rows)

    context.user_data.pop("import_type", None)
    await processing_msg.edit_text(result, reply_markup=back_button("main_menu"), parse_mode="Markdown")
    return ConversationHandler.END


async def _import_accounts(user_id: int, rows: list) -> str:
    imported = 0
    skipped = []

    # Build a global username set across ALL users to prevent cross-user duplicates
    global_usernames: set[str] = set()
    for uid_str in get_all_user_ids():
        try:
            for a in get_user(int(uid_str)).get("accounts", []):
                u = (a.get("username") or "").lstrip("@").lower()
                if u:
                    global_usernames.add(u)
        except Exception:
            pass

    for i, row in enumerate(rows, start=2):
        name = (row.get("Name") or row.get("name") or "").strip()
        username = (row.get("Username") or row.get("username") or "").strip().lstrip("@")
        status = (row.get("Status") or row.get("status") or "active").strip().lower()

        if not name:
            skipped.append(f"Row {i}: missing Name")
            continue
        if not username:
            skipped.append(f"Row {i}: missing Username")
            continue
        if status not in ("active", "dead"):
            status = "active"
        if username.lower() in global_usernames:
            skipped.append(f"Row {i}: @{username} already exists in bot")
            continue

        add_account(user_id, {
            "name": name,
            "username": username,
            "status": status,
            "added": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        global_usernames.add(username.lower())
        imported += 1

    return _format_result("Accounts", imported, skipped)


async def _import_campaigns(user_id: int, rows: list) -> str:
    imported = 0
    skipped = []
    existing_names = {c.get("name", "").lower() for c in get_campaigns(user_id)}

    for i, row in enumerate(rows, start=2):
        name = (row.get("Name") or row.get("name") or "").strip()
        target = (row.get("Target") or row.get("target") or "").strip()
        message = (row.get("Message") or row.get("message") or "").strip()

        if not name:
            skipped.append(f"Row {i}: missing Name")
            continue
        if not target:
            skipped.append(f"Row {i}: missing Target")
            continue
        if not message:
            skipped.append(f"Row {i}: missing Message")
            continue
        if name.lower() in existing_names:
            skipped.append(f"Row {i}: campaign '{name}' already exists")
            continue

        add_campaign(user_id, {
            "name": name,
            "target": target,
            "message": message,
            "active": True,
            "actions": 0,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        existing_names.add(name.lower())
        imported += 1

    return _format_result("Campaigns", imported, skipped)


def _format_result(label: str, imported: int, skipped: list) -> str:
    icon = "✅" if imported > 0 else "⚠️"
    lines = [
        f"{icon} *{label} Import Complete*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        f"✅ Imported: *{imported}* record(s)",
        f"⏭ Skipped: *{len(skipped)}* record(s)",
    ]
    if skipped:
        lines.append("\n*Skip reasons:*")
        for reason in skipped[:8]:
            lines.append(f"  • {reason}")
        if len(skipped) > 8:
            lines.append(f"  • ...and {len(skipped) - 8} more")
    if imported == 0 and not skipped:
        lines.append("\n⚠️ The file appears to be empty.")
    return "\n".join(lines)


async def import_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("import_type", None)
    from handlers.start import start_handler
    await start_handler(update, context)
    return ConversationHandler.END
