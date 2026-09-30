from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from handlers.utils import escape_md

from storage import (
    get_queue, add_to_queue, remove_from_queue, clear_queue,
    get_campaigns,
)


async def queue_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    _refresh_queue(user_id)
    queue = get_queue(user_id)
    campaigns = get_campaigns(user_id)

    if not queue:
        text = (
            "📋 *CAMPAIGN QUEUE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Your queue is empty.\n\n"
            "_Open any campaign → 📌 Add to Queue to enqueue it._"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="my_campaigns")]
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    lines = []
    keyboard = []
    for pos, idx in enumerate(queue):
        if idx < len(campaigns):
            c = campaigns[idx]
            name = c.get("name", f"Campaign {idx+1}")
            action = c.get("action_type", "?")
            status = "🟢" if c.get("active") else "⏸"
            lines.append(f"`{pos+1}.` {status} *{escape_md(name)}* `[{action}]`")
            keyboard.append([
                InlineKeyboardButton(f"🗑 Remove #{pos+1}: {name[:20]}", callback_data=f"queue_remove_{idx}")
            ])

    text = (
        "📋 *CAMPAIGN QUEUE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Campaigns run in order when you tap ▶️ Start Queue.\n\n"
        + "\n".join(lines)
    )
    keyboard.append([
        InlineKeyboardButton("▶️ Start Queue", callback_data="queue_start"),
        InlineKeyboardButton("🔴 Clear All",   callback_data="queue_clear"),
    ])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="my_campaigns")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def queue_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: queue_add_<camp_index>"""
    query = update.callback_query
    user_id = update.effective_user.id
    idx = int(query.data.split("_")[-1])
    campaigns = get_campaigns(user_id)
    if idx >= len(campaigns):
        await query.answer("Campaign not found.", show_alert=True)
        return
    added = add_to_queue(user_id, idx)
    name = campaigns[idx].get("name", f"Campaign {idx+1}")
    if added:
        await query.answer(f"📋 Added to queue: {name}", show_alert=True)
    else:
        await query.answer(f"Already in queue: {name}", show_alert=True)
    # Refresh campaign view
    from handlers.campaigns import campaign_view
    await campaign_view(update, context)


async def queue_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pattern: queue_remove_<camp_index>"""
    query = update.callback_query
    user_id = update.effective_user.id
    idx = int(query.data.split("_")[-1])
    remove_from_queue(user_id, idx)
    await query.answer("Removed from queue.")
    await queue_menu(update, context)


async def queue_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    clear_queue(user_id)
    await query.answer("Queue cleared.", show_alert=True)
    await queue_menu(update, context)


async def queue_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = update.effective_user.id
    _refresh_queue(user_id)
    queue = get_queue(user_id)
    campaigns = get_campaigns(user_id)

    if not queue:
        await query.answer("Queue is empty.", show_alert=True)
        return

    await query.answer("▶️ Queue started!")

    prog_msg = await query.message.reply_text(
        f"📋 *Queue Started* — {len(queue)} campaign(s)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Starting in a moment...",
        parse_mode="Markdown",
    )

    from runner import execute_campaign
    results_summary = []

    for pos, camp_idx in enumerate(list(queue)):
        if camp_idx >= len(campaigns):
            results_summary.append(f"⚠️ Campaign #{camp_idx+1}: no longer exists")
            continue
        camp = campaigns[camp_idx]
        name = camp.get("name", f"Campaign {camp_idx+1}")

        try:
            await prog_msg.edit_text(
                f"📋 *Queue Running* ({pos+1}/{len(queue)})\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚡ Now running: *{escape_md(name)}*\n\n"
                "_Please wait..._",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        try:
            result = await execute_campaign(
                camp,
                get_accounts(user_id),
                user_id,
                camp_idx,
            )
            done    = result.get("done", 0)
            failed  = result.get("failed", 0)
            skipped = result.get("skipped", 0)
            results_summary.append(
                f"✅ *{escape_md(name)}*: {done} done · {failed} failed · {skipped} skipped"
            )
        except Exception as e:
            results_summary.append(f"❌ *{escape_md(name)}*: {str(e)[:60]}")

    summary = "\n".join(results_summary)
    try:
        from keyboards import back_button
        await prog_msg.edit_text(
            f"📋 *Queue Complete!*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{summary}",
            reply_markup=back_button("my_campaigns"),
            parse_mode="Markdown",
        )
    except Exception:
        pass


def _refresh_queue(user_id: int) -> None:
    """Remove indices that no longer correspond to existing campaigns."""
    from storage import get_queue as _gq, clear_queue as _cq, add_to_queue as _aq
    campaigns = get_campaigns(user_id)
    valid = [i for i in _gq(user_id) if i < len(campaigns)]
    _cq(user_id)
    for i in valid:
        _aq(user_id, i)
