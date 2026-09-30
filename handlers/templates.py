import copy
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from storage import get_templates, add_template, delete_template, get_campaigns, add_campaign
from keyboards import back_button


async def templates_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    templates = get_templates(user_id)

    if not templates:
        text = (
            "💾 *CAMPAIGN TEMPLATES*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No templates saved yet.\n\n"
            "_Open any campaign → 💾 Save as Template to save it._\n\n"
            "Templates let you re-create a campaign with the same settings "
            "instantly — useful for recurring jobs."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="my_campaigns")]
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    text = (
        "💾 *CAMPAIGN TEMPLATES*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Tap a template to create a new campaign from it.\n"
        "Tap 🗑 to delete.\n"
    )
    keyboard = []
    for i, tpl in enumerate(templates):
        action = tpl.get("action_type", "?")
        name   = tpl.get("name", f"Template {i+1}")
        saved  = tpl.get("saved_at", "")
        row_label = f"🚀 {name} [{action}]"
        if saved:
            row_label += f" · {saved[:10]}"
        keyboard.append([
            InlineKeyboardButton(row_label,  callback_data=f"tpl_use_{i}"),
            InlineKeyboardButton("🗑",       callback_data=f"tpl_delete_{i}"),
        ])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="my_campaigns")])
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )


async def template_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: tpl_save_<camp_index> — saves a campaign as a template."""
    query = update.callback_query
    user_id = update.effective_user.id
    idx = int(query.data.split("_")[-1])
    campaigns = get_campaigns(user_id)
    if idx >= len(campaigns):
        await query.answer("Campaign not found.", show_alert=True)
        return

    camp = campaigns[idx]
    # Strip runtime / history fields
    strip_keys = {"run_log", "last_failed_ids", "running_since", "actions"}
    template = {k: v for k, v in camp.items() if k not in strip_keys}
    template["active"] = True
    template["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Avoid exact duplicates (same name + same action_type)
    existing = get_templates(user_id)
    for t in existing:
        if (t.get("name") == template.get("name") and
                t.get("action_type") == template.get("action_type")):
            await query.answer("⚠️ Template already saved (same name + action).", show_alert=True)
            return

    add_template(user_id, template)
    await query.answer(f"💾 Saved as template: {camp.get('name', '?')}", show_alert=True)


async def template_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: tpl_use_<tpl_index> — creates a new campaign from a template."""
    query = update.callback_query
    user_id = update.effective_user.id
    idx = int(query.data.split("_")[-1])
    templates = get_templates(user_id)
    if idx >= len(templates):
        await query.answer("Template not found.", show_alert=True)
        return

    tpl = templates[idx]
    new_camp = copy.deepcopy(tpl)
    new_camp["name"] = "📄 " + tpl.get("name", f"Template {idx+1}")
    new_camp["created"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_camp["active"] = True
    new_camp["actions"] = 0
    new_camp.pop("run_log", None)
    new_camp.pop("saved_at", None)
    new_camp.pop("last_failed_ids", None)

    add_campaign(user_id, new_camp)
    await query.answer("✅ Campaign created from template!", show_alert=True)
    await templates_menu(update, context)


async def template_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: tpl_delete_<tpl_index>"""
    query = update.callback_query
    user_id = update.effective_user.id
    idx = int(query.data.split("_")[-1])
    templates = get_templates(user_id)
    name = templates[idx].get("name", f"Template {idx+1}") if idx < len(templates) else "?"
    delete_template(user_id, idx)
    await query.answer(f"🗑 Deleted: {name}", show_alert=True)
    await templates_menu(update, context)
