import html as _html

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from handlers.utils import escape_md as _escape_md


def _esc(s: str) -> str:
    """HTML-escape user-supplied strings for use in parse_mode='HTML' messages."""
    return _html.escape(str(s))
from storage import (
    get_accounts, get_campaigns, add_campaign, remove_campaign,
    get_paid_mode, get_owner_username, is_owner, has_adv_access,
    check_campaign_limit,
)
from keyboards import (
    campaigns_menu, campaign_actions, campaign_delete_confirm_menu,
    back_button, cancel_button,
    campaign_action_types_menu, reaction_mode_menu, reaction_picker_menu, REACTIONS,
    vote_button_picker_menu,
)
from handlers.start import start_handler

CAMP_ACTION, CAMP_TARGET, CAMP_DM_MESSAGE, CAMP_REACT, CAMP_JOIN_LINK, CAMP_BTN_NUM, CAMP_ACCT_COUNT = range(7)
CAMP_RENAME = 7  # separate conversation state for campaign rename

# Actions that include a react step
REACT_ACTIONS = {"react", "react_vote", "react_view", "react_vote_view"}

# Subset of REACT_ACTIONS that show the reaction picker during campaign creation.
# react_vote_view skips the picker and uses a sensible default reaction.
REACT_PICKER_ACTIONS = {"react", "react_vote", "react_view", "react_vote_view"}

# Actions that involve clicking a poll/vote button
VOTE_ACTIONS = {"vote", "react_vote", "vote_view", "react_vote_view"}

ACTION_LABELS = {
    "react": "⭐ React Only",
    "vote": "🎯 Vote Only",
    "react_vote": "⭐ React + Vote",
    "view": "👑 View Only",
    "react_view": "⭐ React + View",
    "vote_view": "🎯 Vote + View",
    "react_vote_view": "🔥 React + Vote + View",
    "join": "⚡ Join Channel",
    "leave": "🚫 Leave Channel",
    "leave_all": "🚫 Leave All Channels",
    "bulk_dm": "📩 Bulk DM",
    "bot_referral": "🔗 Bot Referral",
}

# Actions that run immediately with no target/reaction input required
NO_TARGET_ACTIONS = {"leave_all"}

TARGET_PROMPTS = {
    "react": "Send the *post URL* to react to:\n\nExample:\n`https://t.me/channel/123`",
    "vote": "Send the *post URL* containing the poll/vote to click:\n\nExample:\n`https://t.me/channel/123`",
    "react_vote": "Send the *post URL* to react and vote on:\n\nExample:\n`https://t.me/channel/123`",
    "view": "Send the *post URL* to view:\n\nExample:\n`https://t.me/channel/123`",
    "react_view": "Send the *post URL* to react and view:\n\nExample:\n`https://t.me/channel/123`",
    "vote_view": "Send the *post URL* to vote and view:\n\nExample:\n`https://t.me/channel/123`",
    "react_vote_view": "Send the *post URL* to react, vote and view:\n\nExample:\n`https://t.me/channel/123`",
    "join": (
        "Send the *channel link or username* to join:\n\n"
        "Public channel:\n`@mychannel` or `https://t.me/mychannel`\n\n"
        "Private channel (invite link):\n`https://t.me/+AbCdEfGhIjKl` or `+AbCdEfGhIjKl`\n\n"
        "By numeric ID:\n`-1001234567890`"
    ),
    "leave": (
        "Send the *channel link, username, or ID* to leave:\n\n"
        "Public channel:\n`@mychannel` or `https://t.me/mychannel`\n\n"
        "Private channel (invite link):\n`https://t.me/+AbCdEfGhIjKl` or `+AbCdEfGhIjKl`\n\n"
        "By numeric ID:\n`-1001234567890`"
    ),
    "bulk_dm": "Send the *username or user ID* to DM:\n\nExample:\n`@username` or `123456789`",
    "bot_referral": (
        "Paste your *bot referral link* below:\n\n"
        "• `https://t\\.me/YourBot?start=refXXX`\n"
        "• `https://t\\.me/YourBot/App?startapp=refXXX`\n"
        "• `https://t\\.me/YourBot`\n\n"
        "Each account will open your bot, read the response, "
        "join any channels it mentions, and AI\\-verify automatically\\."
    ),
}


async def my_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)
    query = update.callback_query
    if query:
        await query.answer()

    if not campaigns:
        text = (
            "🎯 *My Campaigns*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "No campaigns yet.\n"
            "Press ⭐ New Campaign to create one."
        )
    else:
        total_actions = sum(c.get("actions", 0) for c in campaigns)
        # Build per-campaign last-activity summary
        import re as _re
        def _safe(s: str) -> str:
            """Escape Markdown special chars in user-supplied strings."""
            return _re.sub(r'([_*\[\]`\\])', r'\\\1', str(s))
        lines = []
        for i, c in enumerate(campaigns):
            status_icon = "✅" if c.get("active") else "⏸"
            run_log = c.get("run_log", [])
            last_ts = run_log[0].get("ts", "Never") if run_log else "Never"
            lines.append(f"  {i+1}. {status_icon} {_safe(c.get('name','?'))}  ·  last run: {last_ts}")
        activity_block = "\n".join(lines)
        text = (
            "🎯 *My Campaigns*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"📊 Total: {len(campaigns)} campaigns | {total_actions} actions\n\n"
            f"{activity_block}\n\n"
            "Select a campaign to manage it:"
        )

    markup = campaigns_menu(campaigns)
    if query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def campaign_view(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campaign_index: int | None = None,
) -> None:
    query = update.callback_query
    await query.answer()
    index = (
        campaign_index
        if campaign_index is not None
        else int(query.data.split("_")[-1])
    )
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)

    if index >= len(campaigns):
        await query.edit_message_text("Campaign not found.", reply_markup=back_button("my_campaigns"))
        return

    camp = campaigns[index]
    status = "✅ Active" if camp.get("active") else "⏸ Paused"
    action_label = ACTION_LABELS.get(camp.get("action_type", ""), camp.get("action_type", "N/A"))

    # Build run history block + success rate + trend chart
    run_log = camp.get("run_log", [])
    if run_log:
        total_done   = sum(r.get("done", 0) for r in run_log)
        total_failed = sum(r.get("failed", 0) for r in run_log)
        total_runs   = total_done + total_failed
        rate_str = f"{int(100 * total_done / total_runs)}%" if total_runs > 0 else "N/A"
        history_lines = "\n".join(
            f"  • {r.get('ts','?')}  ✅{r.get('done',0)} ❌{r.get('failed',0)}  ⏱{r.get('elapsed','?')}"
            for r in run_log[:5]
        )
        # Text bar chart — each bar represents success% of a run (oldest→newest, up to 7)
        chart_runs = list(reversed(run_log[:7]))
        bars = []
        for r in chart_runs:
            t = r.get("done", 0) + r.get("failed", 0)
            pct = r["done"] / t if t > 0 else 0
            filled = round(pct * 5)
            bars.append("█" * filled + "░" * (5 - filled))
        trend_line = f"\n📊 <b>Trend (oldest→latest):</b>  <code>{'  '.join(bars)}</code>"
        history_block = (
            f"\n\n📈 <b>Success rate:</b> {rate_str}  <i>(last {len(run_log)} run(s))</i>"
            f"{trend_line}"
            f"\n\n📜 <b>Last runs:</b>\n{history_lines}"
        )
    else:
        history_block = ""

    has_failures = bool(camp.get("last_failed_ids"))
    label_filter = camp.get("label_filter", "")
    lbl_line = f"\n🏷 <b>Label Filter:</b> <code>{_esc(label_filter)}</code>" if label_filter else ""

    # Extra detail lines (matching ADV campaign style)
    _reactions = camp.get("reactions") or []
    _reaction_mode = camp.get("reaction_mode", "simple")
    _join_link = camp.get("join_link", "")
    _btn_index = camp.get("button_index")
    _max_acc   = camp.get("max_accounts", 0)
    if camp.get("action_type", "") in REACT_ACTIONS:
        react_line = (
            "💎 <b>Reactions:</b> Premium — first two reactions available on the post\n"
            if _reaction_mode == "premium"
            else f"⭐ <b>Reactions:</b> {' '.join(_reactions)}\n"
        )
    else:
        react_line = ""
    btn_line   = f"🖱 <b>Button:</b> #{_btn_index + 1}\n" if _btn_index is not None and camp.get("action_type","") in VOTE_ACTIONS else ""
    join_line  = f"🔗 <b>Auto-join:</b> <code>{_esc(_join_link[:50])}</code>\n" if _join_link else ""
    acct_line  = f"👥 <b>Accounts:</b> {_max_acc if _max_acc else 'All'}\n"

    text = (
        "🚀 <b>Campaign Details</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"📌 <b>Name:</b> {_esc(camp.get('name', 'N/A'))}\n"
        f"⚡ <b>Action:</b> {action_label}\n"
        f"🎯 <b>Target:</b> <code>{_esc(camp.get('target', 'N/A'))}</code>\n"
        f"{react_line}{btn_line}{join_line}{acct_line}"
        f"📊 <b>Total Actions:</b> {camp.get('actions', 0)}\n"
        f"📅 <b>Created:</b> {camp.get('created', 'N/A')}\n"
        f"🚀 <b>Status:</b> {status}"
        f"{lbl_line}"
        f"{history_block}"
    )
    if has_failures:
        n_failed = len(camp["last_failed_ids"])
        text += f"\n\n🔁 <b>{n_failed} account(s) failed last run — tap Retry Failed to re-run them.</b>"
    from storage import is_campaign_running, get_queue
    currently_running = is_campaign_running(user_id, index)
    in_queue = index in get_queue(user_id)
    await query.edit_message_text(
        text,
        reply_markup=campaign_actions(
            index,
            is_running=currently_running,
            has_failures=has_failures,
            in_queue=in_queue,
            label_filter=label_filter,
        ),
        parse_mode="HTML",
    )


async def campaign_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show confirmation keyboard before deleting."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    campaigns = get_campaigns(update.effective_user.id)
    name = campaigns[index].get("name", f"Campaign {index+1}") if index < len(campaigns) else "?"
    await query.edit_message_text(
        f"⚠️ *Delete Campaign?*\n\n`{name}`\n\nThis cannot be undone.",  # name in code-span: safe
        reply_markup=campaign_delete_confirm_menu(index),
        parse_mode="Markdown",
    )


async def campaign_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    remove_campaign(user_id, index)
    await query.answer("🗑 Campaign deleted", show_alert=True)
    await my_campaigns(update, context)


async def campaign_clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Duplicate a campaign with 'Copy of' prefix."""
    query = update.callback_query
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)
    if index >= len(campaigns):
        await query.answer("Campaign not found.", show_alert=True)
        return
    import copy
    clone = copy.deepcopy(campaigns[index])
    clone["name"] = "Copy of " + clone.get("name", f"Campaign {index+1}")
    clone["actions"] = 0
    clone.pop("run_log", None)
    from datetime import datetime
    clone["created"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    add_campaign(user_id, clone)
    await query.answer("📋 Campaign cloned!", show_alert=True)
    await my_campaigns(update, context)


from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def _large_confirm_kb(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, run it", callback_data=f"camp_run_confirm_{index}"),
            InlineKeyboardButton("❌ Cancel",      callback_data=f"camp_view_{index}"),
        ]
    ])


async def campaign_run_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User confirmed running a large campaign."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    context.user_data["_run_confirmed"] = True
    # Pass the parsed index directly. CallbackQuery.data is read-only in
    # python-telegram-bot and must not be replaced to reuse a handler.
    await campaign_run(update, context, campaign_index=index)


async def campaign_retry_failed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-run only the accounts that failed in the last campaign run."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    index = int(query.data.split("_")[-1])
    campaigns = get_campaigns(user_id)
    if index >= len(campaigns):
        await query.answer("Campaign not found.", show_alert=True)
        return
    failed_ids = campaigns[index].get("last_failed_ids", [])
    if not failed_ids:
        await query.answer("No failed accounts from last run.", show_alert=True)
        return
    context.user_data["_retry_ids"] = failed_ids
    await campaign_run(update, context, campaign_index=index)


async def campaign_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Request stop for a running campaign."""
    query = update.callback_query
    index = int(query.data.split("_")[-1])
    from storage import set_campaign_stop
    set_campaign_stop(update.effective_user.id, index)
    await query.answer("⏹ Stop requested — finishing current accounts…", show_alert=True)


async def campaign_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Request pause for a running campaign."""
    query = update.callback_query
    index = int(query.data.split("_")[-1])
    from storage import set_campaign_pause
    set_campaign_pause(update.effective_user.id, index)
    paused_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("▶️ Resume", callback_data=f"camp_resume_{index}", style="success"),
        InlineKeyboardButton("⏹ Stop",   callback_data=f"camp_stop_{index}",   style="danger"),
    ]])
    try:
        await query.edit_message_reply_markup(reply_markup=paused_kb)
    except Exception:
        pass
    await query.answer("⏸ Paused — tap ▶️ Resume to continue.", show_alert=True)


async def campaign_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume a paused campaign from the accounts that were skipped."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id

    from storage import (
        is_campaign_running, get_campaign_paused_remaining,
        clear_campaign_paused_remaining, clear_campaign_pause,
    )

    if is_campaign_running(user_id, index):
        # Pause was clicked but campaign hasn't finished yet — cancel the pause
        clear_campaign_pause(user_id, index)
        running_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏸ Pause", callback_data=f"camp_pause_{index}", style="primary"),
            InlineKeyboardButton("⏹ Stop",  callback_data=f"camp_stop_{index}",  style="danger"),
        ]])
        try:
            await query.edit_message_reply_markup(reply_markup=running_kb)
        except Exception:
            pass
        return

    # Campaign has fully paused — resume with the skipped accounts
    remaining = get_campaign_paused_remaining(user_id, index)
    clear_campaign_paused_remaining(user_id, index)

    if remaining:
        context.user_data["_resume_ids"] = remaining
    context.user_data["_run_confirmed"] = True
    await campaign_run(update, context)


async def new_campaign_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)
    has_active = any(a.get("status") == "active" for a in accounts)

    warning = ""
    if not has_active:
        warning = "⚠️ No active accounts yet. You can still choose an action.\n\n"

    text = (
        "🚀 Campaign\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"{warning}"
        "Step 1 — Choose what your accounts should do:"
    )
    await query.edit_message_text(
        text,
        reply_markup=campaign_action_types_menu(has_active),
    )
    return CAMP_ACTION


def _save_campaign(
    user_id: int,
    action: str,
    target: str,
    reactions: list = None,
    message: str = "",
    join_link: str = "",
    button_index: int = 0,
    max_accounts: int = 0,
    reaction_mode: str = "simple",
) -> dict:
    import uuid
    from datetime import datetime
    label = ACTION_LABELS.get(action, action)
    campaign = {
        "id": str(uuid.uuid4()),
        "name": f"{label} — {target[:30]}" if target else label,
        "action_type": action,
        "target": target,
        "reactions": reactions or [],
        "reaction_mode": reaction_mode if reaction_mode in {"simple", "premium"} else "simple",
        "active": True,
        "actions": 0,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    if message:
        campaign["message"] = message
    if join_link:
        campaign["join_link"] = join_link
    if action in VOTE_ACTIONS:
        campaign["button_index"] = button_index
    if max_accounts > 0:
        campaign["max_accounts"] = max_accounts
    add_campaign(user_id, campaign)
    return campaign


def _join_link_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Skip (already joined)", callback_data="camp_skip_join", style="primary")],
        [InlineKeyboardButton("🔥 ❌ Cancel", callback_data="main_menu", style="danger")],
    ])


async def camp_get_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.replace("camp_action_", "")
    user_id = update.effective_user.id
    context.user_data["camp_action"] = action
    context.user_data["camp_reactions"] = []
    context.user_data["camp_reaction_mode"] = "simple"
    label = ACTION_LABELS.get(action, action)

    if action in NO_TARGET_ACTIONS:
        context.user_data["camp_target"] = "All Chats"
        return await _show_camp_acct_prompt(update, context)

    if action in REACT_ACTIONS:
        await query.edit_message_text(
            f"🚀 Campaign — {label}\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "Step 2 — Choose the reaction type:",
            reply_markup=reaction_mode_menu(prefix="camp"),
            parse_mode="Markdown",
        )
        return CAMP_REACT

    prompt = TARGET_PROMPTS.get(action, "Send the target URL or username:")
    await query.edit_message_text(
        f"🚀 Campaign — {label}\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"Step 2 — {prompt}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return CAMP_TARGET


async def camp_reaction_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Choose the existing manual picker or premium auto-reactions."""
    query = update.callback_query
    await query.answer()
    mode = query.data.rsplit("_", 1)[-1]
    action = context.user_data.get("camp_action", "react")
    label = ACTION_LABELS.get(action, action)
    context.user_data["camp_reaction_mode"] = mode
    context.user_data["camp_reactions"] = []

    if mode == "simple":
        await query.edit_message_text(
            f"🚀 Campaign — {label}\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "Step 2 — Choose the *reaction(s)* to send.\n"
            "Tap to select/deselect. You can pick multiple.\n"
            "Then press ✅ Done.",
            reply_markup=reaction_picker_menu([], prefix="camp"),
            parse_mode="Markdown",
        )
        return CAMP_REACT

    prompt = TARGET_PROMPTS.get(action, "Send the target URL or username:")
    await query.edit_message_text(
        f"🚀 Campaign — {label}\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "💎 Premium mode will use the first two reactions available on the post.\n\n"
        f"Step 3 — {prompt}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return CAMP_TARGET


async def camp_toggle_react(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.replace("camp_react_", ""))
    emoji = REACTIONS[idx]
    selected: list = context.user_data.setdefault("camp_reactions", [])
    if emoji in selected:
        selected.remove(emoji)
    else:
        selected.append(emoji)
    action = context.user_data.get("camp_action", "react")
    label = ACTION_LABELS.get(action, action)
    await query.edit_message_text(
        f"🚀 Campaign — {label}\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "Step 2 — Choose the *reaction(s)* to send.\n"
        "Tap to select/deselect. You can pick multiple.\n"
        "Then press ✅ Done.",
        reply_markup=reaction_picker_menu(selected, prefix="camp"),
        parse_mode="Markdown",
    )
    return CAMP_REACT


async def camp_react_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    selected: list = context.user_data.get("camp_reactions", [])
    if not selected:
        await query.answer("⚠️ Please pick at least one reaction first!", show_alert=True)
        return CAMP_REACT
    await query.answer()
    context.user_data["camp_reaction_mode"] = "simple"
    action = context.user_data.get("camp_action", "react")
    label = ACTION_LABELS.get(action, action)
    prompt = TARGET_PROMPTS.get(action, "Send the target URL or username:")
    await query.edit_message_text(
        f"🚀 Campaign — {label}\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"✅ Reactions: {' '.join(selected)}\n\n"
        f"Step 3 — {prompt}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return CAMP_TARGET


async def camp_get_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target = update.message.text.strip()
    action = context.user_data.get("camp_action", "vote")
    user_id = update.effective_user.id

    if action == "bulk_dm":
        context.user_data["camp_target"] = target
        await update.message.reply_text(
            "Step 3 — Enter the *message* to send as DM:",
            reply_markup=cancel_button(),
            parse_mode="Markdown"
        )
        return CAMP_DM_MESSAGE

    # For join/leave the target IS the channel — no separate join link needed
    if action in ("join", "leave", "bot_referral"):
        context.user_data["camp_target"] = target
        return await _show_camp_acct_prompt(update, context)

    # Ask for optional auto-join link before acting
    context.user_data["camp_target"] = target
    reactions = context.user_data.get("camp_reactions") or []
    reaction_mode = context.user_data.get("camp_reaction_mode", "simple")
    react_line = (
        "💎 Premium reactions: first two available on the post\n\n"
        if action in REACT_ACTIONS and reaction_mode == "premium"
        else (f"✅ Reactions: {' '.join(reactions)}\n\n" if action in REACT_ACTIONS else "")
    )
    label = ACTION_LABELS.get(action, action)
    join_step = (
        "Step 4"
        if action in REACT_PICKER_ACTIONS and reaction_mode != "premium"
        else "Step 3"
    )
    await update.message.reply_text(
        f"🚀 Campaign — {label}\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"{react_line}"
        "✅ Post URL saved!\n\n"
        f"🔗 *{join_step} — Paste the channel join link.*\n\n"
        "This is used to auto-join accounts that are not yet members before acting.\n\n"
        "• Public channel: `https://t.me/channelname`\n"
        "• Private invite: `https://t.me/+InviteCode`\n\n"
        "Tap ⏭ *Skip* if all accounts are already joined:",
        reply_markup=_join_link_kb(),
        parse_mode="Markdown",
    )
    return CAMP_JOIN_LINK


async def camp_get_dm_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dm_message = update.message.text.strip()
    context.user_data["camp_dm_message"] = dm_message
    return await _show_camp_acct_prompt(update, context)


async def camp_get_join_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles both the join-link text input and the Skip callback."""
    user_id = update.effective_user.id
    action = context.user_data.get("camp_action", "vote")
    target = context.user_data.get("camp_target", "")
    reactions = context.user_data.get("camp_reactions") or ["👍"]
    reaction_mode = context.user_data.get("camp_reaction_mode", "simple")
    dm_message = context.user_data.get("camp_dm_message", "")
    label = ACTION_LABELS.get(action, action)

    # Determine join link
    if update.callback_query:
        await update.callback_query.answer()
        join_link = ""
    else:
        join_link = update.message.text.strip()

    # For vote actions: store join link and ask which button to click
    if action in VOTE_ACTIONS:
        context.user_data["camp_join_link"] = join_link
        join_status = "✅ Channel join skipped!" if not join_link else f"✅ Channel link saved!\n🔗 `{join_link[:50]}`"
        btn_step = (
            "Step 5"
            if action in REACT_PICKER_ACTIONS and reaction_mode != "premium"
            else "Step 4"
        )
        text = (
            f"🚀 Campaign — {label}\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"{join_status}\n\n"
            f"🖱 *{btn_step} — Which button should your accounts click?*"
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text, reply_markup=vote_button_picker_menu("camp"), parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text, reply_markup=vote_button_picker_menu("camp"), parse_mode="Markdown"
            )
        return CAMP_BTN_NUM

    # Non-vote actions: ask account count, then save
    context.user_data["camp_join_link"] = join_link
    return await _show_camp_acct_prompt(update, context)


async def camp_btn_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles 1st–5th button click or 'Other #' in the vote button picker."""
    query = update.callback_query
    await query.answer()
    data = query.data  # camp_btn_1 … camp_btn_5 or camp_btn_other

    if data == "camp_btn_other":
        await query.edit_message_text(
            "🔢 *Enter the button number* (e.g. 6, 7, 8...):",
            reply_markup=cancel_button(),
            parse_mode="Markdown",
        )
        return CAMP_BTN_NUM

    btn_num = int(data.replace("camp_btn_", ""))
    return await _finish_camp_with_btn(update, context, btn_num - 1)


async def camp_btn_num_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles a custom button number typed by the user."""
    raw = update.message.text.strip()
    try:
        btn_num = int(raw)
        if btn_num < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "⚠️ Enter a valid button number (e.g. 1, 2, 6...):",
            reply_markup=cancel_button(),
        )
        return CAMP_BTN_NUM
    return await _finish_camp_with_btn(update, context, btn_num - 1)


async def _finish_camp_with_btn(update: Update, context: ContextTypes.DEFAULT_TYPE, button_index: int) -> int:
    """Store button index then ask how many accounts to use."""
    context.user_data["camp_btn_index"] = button_index
    return await _show_camp_acct_prompt(update, context)


async def _show_camp_acct_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask the user how many accounts to use for the campaign."""
    user_id = update.effective_user.id
    accounts = get_accounts(user_id)
    active = [a for a in accounts if a.get("status") == "active"]
    total = len(active)
    context.user_data["camp_acct_total"] = total
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ All ({total})", callback_data="camp_acct_all", style="success"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu", style="danger"),
        ]
    ])
    text = (
        "📊 *How many accounts?*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"📱 You have *{total}* active account(s) available.\n"
        f"Max you can use: *{total}*\n\n"
        f"Send a number (1–{total}) or tap *All* to use all:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return CAMP_ACCT_COUNT


async def camp_acct_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User tapped 'All (N)' — use all available accounts."""
    query = update.callback_query
    await query.answer()
    context.user_data["camp_max_accounts"] = 0  # 0 = all
    return await _do_save_camp(update, context)


async def camp_acct_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed a specific account count."""
    raw = update.message.text.strip()
    total = context.user_data.get("camp_acct_total", 0)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ All ({total})", callback_data="camp_acct_all", style="success"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu", style="danger"),
        ]
    ])
    try:
        n = int(raw)
        if n < 1 or (total > 0 and n > total):
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            f"⚠️ Enter a number between 1 and {total}:",
            reply_markup=kb,
        )
        return CAMP_ACCT_COUNT
    context.user_data["camp_max_accounts"] = n
    return await _do_save_camp(update, context)


async def _do_save_camp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Final step: save campaign after all inputs are collected."""
    user_id      = update.effective_user.id
    action       = context.user_data.get("camp_action", "vote")
    target       = context.user_data.get("camp_target", "All Chats")
    reaction_mode = context.user_data.get("camp_reaction_mode", "simple")
    reactions    = context.user_data.get("camp_reactions") or (
        [] if reaction_mode == "premium" else ["👍"]
    )
    dm_message   = context.user_data.get("camp_dm_message", "")
    join_link    = context.user_data.get("camp_join_link", "")
    btn_index    = context.user_data.get("camp_btn_index", 0)
    max_accounts = context.user_data.get("camp_max_accounts", 0)
    label        = ACTION_LABELS.get(action, action)

    _save_campaign(user_id, action, target, reactions=reactions,
                   message=dm_message, join_link=join_link,
                   button_index=btn_index, max_accounts=max_accounts,
                   reaction_mode=reaction_mode)

    # Index of the campaign we just saved
    new_index = len(get_campaigns(user_id)) - 1

    react_line = (
        "💎 Reactions: Premium — first two available on the post\n"
        if action in REACT_ACTIONS and reaction_mode == "premium"
        else (f"⭐ Reactions: {' '.join(reactions)}\n" if action in REACT_ACTIONS else "")
    )
    join_line  = f"🔗 Auto-join: <code>{_esc(join_link[:50])}</code>\n" if join_link else ""
    btn_line   = f"🖱 Button: #{btn_index + 1}\n" if action in VOTE_ACTIONS else ""
    acct_line  = f"👥 Accounts: {max_accounts if max_accounts else 'All'}\n"
    text = (
        "✅ <b>Campaign Created!</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"⚡ Action: {label}\n"
        f"🎯 Target: <code>{_esc(target)}</code>\n"
        f"{react_line}{btn_line}{join_line}{acct_line}"
        "🚀 Status: ✅ Active"
    )
    for key in ["camp_action", "camp_target", "camp_reactions", "camp_reaction_mode", "camp_dm_message",
                "camp_join_link", "camp_btn_index", "camp_acct_total", "camp_max_accounts"]:
        context.user_data.pop(key, None)

    # Show run/navigate buttons so the user is never left stuck
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Run Now",      callback_data=f"camp_run_{new_index}",  style="success"),
        ],
        [
            InlineKeyboardButton("🎯 My Campaigns", callback_data="my_campaigns", style="primary"),
            InlineKeyboardButton("🔙 Main Menu",    callback_data="main_menu",    style="primary"),
        ],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    return ConversationHandler.END


async def campaign_dryrun(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campaign_index: int | None = None,
) -> None:
    """Show what a scheduled campaign would use without contacting Telegram."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    index = (
        campaign_index
        if campaign_index is not None
        else int(query.data.split("_")[-1])
    )
    campaigns = get_campaigns(user_id)

    if index < 0 or index >= len(campaigns):
        await query.edit_message_text(
            "Campaign not found.",
            reply_markup=back_button("schedule"),
        )
        return

    camp = campaigns[index]
    action = camp.get("action_type", "")
    accounts = get_accounts(user_id)
    active_count = sum(1 for account in accounts if account.get("status") == "active")
    max_accounts = camp.get("max_accounts") or camp.get("camp_max_accounts")
    try:
        selected_count = min(active_count, int(max_accounts)) if max_accounts else active_count
    except (TypeError, ValueError):
        selected_count = active_count

    text = (
        "🧪 <b>Campaign Dry Run</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"⚡ <b>Action:</b> {_esc(ACTION_LABELS.get(action, action))}\n"
        f"🎯 <b>Target:</b> <code>{_esc(camp.get('target', 'N/A'))}</code>\n"
        f"👥 <b>Active accounts available:</b> {active_count}\n"
        f"✅ <b>Accounts selected:</b> {selected_count}\n\n"
        "No Telegram actions were performed."
    )
    await query.edit_message_text(
        text,
        reply_markup=back_button("schedule"),
        parse_mode="HTML",
    )


async def campaign_run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campaign_index: int | None = None,
) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if get_paid_mode() and not is_owner(user_id) and not has_adv_access(user_id):
        owner_username = get_owner_username()
        contact = f" Contact {owner_username} to get access." if owner_username else " Contact the bot owner to get access."
        await query.answer(
            f"💎 This bot is currently in Paid Mode.{contact}",
            show_alert=True
        )
        return

    retry_ids  = context.user_data.pop("_retry_ids",  None)  # set by campaign_retry_failed
    resume_ids = context.user_data.pop("_resume_ids", None)  # set by campaign_resume
    confirmed  = context.user_data.pop("_run_confirmed", False)
    index = (
        campaign_index
        if campaign_index is not None
        else int(query.data.split("_")[-1])
    )
    campaigns = get_campaigns(user_id)

    if index >= len(campaigns):
        await query.edit_message_text("Campaign not found.", reply_markup=back_button("my_campaigns"))
        return

    camp = campaigns[index]
    action = camp.get("action_type", "")
    label = ACTION_LABELS.get(action, action)
    target = camp.get("target", "N/A")

    import time

    accounts = get_accounts(user_id)

    if resume_ids is not None:
        # Resume mode: only accounts that were skipped due to pause
        active_sessions = [a for a in accounts if a.get("identifier") in set(resume_ids) and a.get("status") == "active"]
    elif retry_ids is not None:
        # Retry mode: only accounts that failed in the last run
        active_sessions = [a for a in accounts if a.get("identifier") in retry_ids and a.get("status") == "active"]
    else:
        active_sessions = [a for a in accounts if a.get("status") == "active"]

    if not active_sessions:
        await query.answer()
        await query.edit_message_text(
            "⚠️ *No Active Accounts Found*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "This campaign needs at least one active account to run.\n\n"
            "Add accounts via:\n"
            "• 📱 Phone + OTP\n"
            "• 🔑 Session String\n"
            "• 📦 Bulk Sessions / ZIP",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Account",    callback_data="add_account",   style="success")],
                [InlineKeyboardButton("🔙 Back",           callback_data=f"camp_view_{index}", style="primary")],
            ]),
            parse_mode="Markdown",
        )
        return

    total = len(active_sessions)

    # Large campaign confirmation (>50 accounts, not already confirmed)
    if total > 50 and not confirmed and retry_ids is None:
        context.user_data["_pending_run_index"] = index
        await query.edit_message_text(
            f"⚠️ *Large Campaign Confirmation*\n\n"
            f"This campaign will run on *{total} accounts*.\n"
            f"Are you sure you want to proceed?",
            reply_markup=_large_confirm_kb(index),
            parse_mode="Markdown",
        )
        return

    from runner import execute_campaign, progress_bar
    from storage import clear_campaign_stop, clear_campaign_pause, append_campaign_run_log, set_campaign_running
    from datetime import datetime

    set_campaign_running(user_id, index, True)
    _log_tg_user   = update.effective_user
    _log_full_name = _log_tg_user.full_name or str(user_id)
    _log_username  = _log_tg_user.username
    _log_camp_id   = camp.get("id", str(index))
    from handlers.log_gc import send_log, fmt_campaign_start
    await send_log(context.bot, fmt_campaign_start(
        user_id=user_id,
        full_name=_log_full_name,
        username=_log_username,
        camp_id=_log_camp_id,
        action_label=label,
        action_type=action,
        target=target,
        total=total,
        reactions=camp.get("reactions"),
        join_link=camp.get("join_link", ""),
    ))

    def _eta(start: float, done: int, failed: int, tot: int) -> str:
        finished = done + failed
        if finished == 0:
            return "⏱ Estimating..."
        elapsed = time.monotonic() - start
        avg = elapsed / finished
        remaining = tot - finished
        if remaining == 0:
            return f"⏱ Done in {int(elapsed)}s"
        secs = int(avg * remaining)
        if secs < 60:
            return f"⏱ ~{secs}s left"
        m, s = divmod(secs, 60)
        return f"⏱ ~{m}m {s}s left"

    def make_progress_text(done: int, failed: int, skipped: int, tot: int,
                           errors: list, start: float,
                           flood_waits: list = None) -> str:
        finished = done + failed
        bar = progress_bar(finished, tot)
        eta = _eta(start, done, failed, tot)

        # Flood wait summary — show throttled account count + max seconds left
        flood_line = ""
        if flood_waits:
            _now = time.time()
            active = [(name, max(0, int(until - _now))) for name, until in flood_waits if until - _now > 0]
            if active:
                max_secs = max(s for _, s in active)
                flood_line = (
                    f"\n🌊 <b>Flood wait:</b> {len(active)} acc throttled"
                    f" — up to <b>{max_secs}s</b> left"
                )

        error_lines = ""
        if errors:
            error_lines = "\n\n⚠️ <b>Latest errors:</b>\n" + "\n".join(f"• {_esc(e)}" for e in errors[-3:])
        return (
            f"⚡ <b>Running Campaign...</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"⚡ Action: {label}\n"
            f"🎯 Target: <code>{_esc(target)}</code>\n\n"
            f"📊 {bar}\n"
            f"🔢 {finished}/{tot} accounts\n"
            f"{eta}"
            f"{flood_line}\n\n"
            f"✅ {done}   ❌ {failed}   ⏭ {skipped}"
            f"{error_lines}"
        )

    start_time = time.monotonic()
    last_edit = [0.0]

    running_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏸ Pause",  callback_data=f"camp_pause_{index}", style="primary"),
        InlineKeyboardButton("⏹ Stop",   callback_data=f"camp_stop_{index}",  style="danger"),
    ]])
    pausing_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏸ Pausing…", callback_data=f"camp_pause_{index}", style="primary"),
        InlineKeyboardButton("⏹ Stop",     callback_data=f"camp_stop_{index}",  style="danger"),
    ]])
    context.user_data[f"camp_pausing_kb_{index}"] = pausing_kb

    await query.edit_message_text(
        make_progress_text(0, 0, 0, total, [], start_time),
        reply_markup=running_kb,
        parse_mode="HTML"
    )

    async def on_progress(done_so_far: int, tot: int, run_result: dict) -> None:
        done = run_result.get("done", 0)
        failed = run_result.get("failed", 0)
        skipped = run_result.get("skipped", 0)
        errors = run_result.get("errors", [])
        flood_waits = run_result.get("flood_waits")
        now = time.monotonic()
        finished = done + failed
        if finished % 2 == 0 or finished == tot:
            if now - last_edit[0] >= 1.5 or finished == tot:
                try:
                    await query.edit_message_text(
                        make_progress_text(done, failed, skipped, tot, errors, start_time,
                                           flood_waits=flood_waits),
                        reply_markup=running_kb,
                        parse_mode="HTML"
                    )
                    last_edit[0] = time.monotonic()
                except Exception:
                    pass

    dry_tag = ""  # reserved for future dry-run mode prefix

    # ── Background task ────────────────────────────────────────────────────────
    # The handler returns immediately after showing the running state so the
    # Stop/Pause buttons stay visible regardless of how fast the campaign runs.
    async def _bg() -> None:
        try:
            result = await execute_campaign(
                camp, active_sessions, user_id, index,
                on_progress=on_progress,
                resume_ids=resume_ids,
                retry_ids=retry_ids,
            )
        finally:
            set_campaign_running(user_id, index, False)
            clear_campaign_stop(user_id, index)
            clear_campaign_pause(user_id, index)

        done    = result["done"]
        failed  = result["failed"]
        skipped = result["skipped"]
        errors  = result.get("errors", [])
        was_stopped = result.get("stopped", False)
        was_paused  = result.get("paused", False)

        # Save remaining accounts so Resume can pick up from here
        from storage import set_campaign_paused_remaining, clear_campaign_paused_remaining
        paused_remaining = result.get("paused_remaining", [])
        if was_paused and paused_remaining:
            set_campaign_paused_remaining(user_id, index, paused_remaining)
        else:
            clear_campaign_paused_remaining(user_id, index)
        elapsed = int(time.monotonic() - start_time)
        elapsed_str = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"

        append_campaign_run_log(user_id, index, {
            "ts": datetime.now().strftime("%m-%d %H:%M"),
            "done": done,
            "failed": failed,
            "elapsed": elapsed_str,
        })
        from handlers.log_gc import send_log, fmt_campaign_done
        await send_log(context.bot, fmt_campaign_done(
            user_id=user_id,
            full_name=_log_full_name,
            camp_id=_log_camp_id,
            action_label=label,
            done=done,
            failed=failed,
            total=total,
            elapsed=elapsed_str,
            was_stopped=was_stopped,
            was_paused=was_paused,
        ))

        # Persist failed account identifiers for the Retry Failed button
        from storage import set_campaign_last_failed
        failed_ids = result.get("failed_ids", [])
        set_campaign_last_failed(user_id, index, failed_ids)

        # Alert for accounts that went dead during this run
        dead_alerts = result.get("dead_alerts", [])
        if dead_alerts:
            dead_lines = "\n".join(f"• {name}: {reason}" for name, reason in dead_alerts[:5])
            try:
                await context.bot.send_message(
                    user_id,
                    f"🔴 *Account(s) went dead during campaign:*\n\n{dead_lines}",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        bar = progress_bar(total, total)

        if was_paused:
            status_note = "\n⏸ <b>Paused — press ▶️ Resume to continue.</b>"
            title = f"⏸ <b>{dry_tag}Campaign Paused</b>"
        elif was_stopped:
            status_note = "\n⏹ <b>Stopped early by user.</b>"
            title = f"⏹ <b>{dry_tag}Campaign Stopped</b>"
        else:
            status_note = ""
            title = f"✅ <b>{dry_tag}Campaign Complete!</b>"

        if len(errors) > 4:
            error_lines = "\n\n📎 <b>Full error report sent as document below.</b>"
        elif errors:
            error_lines = "\n\n⚠️ <b>Errors:</b>\n" + "\n".join(f"• {_esc(e)}" for e in errors)
        else:
            error_lines = ""

        final_text = (
            f"{title}\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"⚡ Action: {label}\n"
            f"🎯 Target: <code>{_esc(target)}</code>\n\n"
            f"📊 {bar}\n"
            f"🔢 {done + failed + skipped}/{total} accounts\n"
            f"⏱ Elapsed: {elapsed_str}\n\n"
            f"✅ Done: {done}   ❌ Failed: {failed}   ⏭ Skipped: {skipped}"
            f"{status_note}"
            f"{error_lines}"
        )

        if was_paused:
            from telegram import InlineKeyboardMarkup as _IKM, InlineKeyboardButton as _IKB
            _final_kb = _IKM([[
                _IKB("▶️ Resume", callback_data=f"camp_resume_{index}", style="success"),
                _IKB("⏹ Stop",   callback_data=f"camp_stop_{index}",   style="danger"),
            ]])
        else:
            _final_kb = campaign_actions(index, is_paused=False)

        await query.edit_message_text(
            final_text,
            reply_markup=_final_kb,
            parse_mode="HTML"
        )

        from storage import get_settings
        if get_settings(user_id).get("notifications", True):
            try:
                notif = (
                    f"🔔 <b>Campaign finished:</b> {_esc(camp.get('name', 'N/A'))}\n"
                    f"✅ Done: {done}  ❌ Failed: {failed}  ⏭ Skipped: {skipped}\n"
                    f"⏱ Elapsed: {elapsed_str}"
                )
                await context.bot.send_message(user_id, notif, parse_mode="HTML")
            except Exception:
                pass

        if len(errors) > 4:
            import io
            camp_id = camp.get("id", str(index))
            file_content = "\n".join(errors)
            filename = f"campaign_{camp_id}_errors.txt"
            await query.message.reply_document(
                document=io.BytesIO(file_content.encode("utf-8")),
                filename=filename,
                caption=f"⚠️ {len(errors)} errors from campaign run",
            )

    # Schedule background execution; handler returns so running state stays visible
    context.application.create_task(_bg())


async def campaign_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    for key in ["camp_action", "camp_target"]:
        context.user_data.pop(key, None)
    from handlers.start import start_handler
    await start_handler(update, context)
    return ConversationHandler.END


# ─── Campaign Rename ───────────────────────────────────────────────────────────

async def campaign_rename_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show a prompt to enter a new campaign name."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)
    if index >= len(campaigns):
        await query.answer("Campaign not found.", show_alert=True)
        return ConversationHandler.END
    context.user_data["rename_camp_index"] = index
    current_name = campaigns[index].get("name", f"Campaign {index + 1}")
    await query.edit_message_text(
        "✏️ *Rename Campaign*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"Current name: `{current_name}`\n\n"
        "Send the new name (max 60 characters):",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return CAMP_RENAME


async def campaign_rename_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save the new campaign name."""
    new_name = update.message.text.strip()
    if not new_name:
        await update.message.reply_text(
            "⚠️ Name cannot be empty. Try again:",
            reply_markup=cancel_button(),
        )
        return CAMP_RENAME
    if len(new_name) > 60:
        await update.message.reply_text(
            "⚠️ Name must be 60 characters or fewer. Try again:",
            reply_markup=cancel_button(),
        )
        return CAMP_RENAME

    user_id = update.effective_user.id
    index = context.user_data.pop("rename_camp_index", None)
    if index is None:
        return ConversationHandler.END

    from storage import rename_campaign
    success = rename_campaign(user_id, index, new_name)
    if success:
        await update.message.reply_text(
            f"✅ *Campaign renamed!*\n\nNew name: *{_escape_md(new_name)}*",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("⚠️ Campaign not found.")

    await start_handler(update, context)
    return ConversationHandler.END


# ─── Label Filter ──────────────────────────────────────────────────────────────

async def campaign_label_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show label-filter picker for a campaign. Pattern: camp_lbl_<camp_index>"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    index = int(query.data.split("_")[-1])
    from storage import get_all_user_labels
    from keyboards import campaign_label_filter_menu
    campaigns = get_campaigns(user_id)
    if index >= len(campaigns):
        await query.answer("Campaign not found.", show_alert=True)
        return
    labels = get_all_user_labels(user_id)
    current = campaigns[index].get("label_filter", "")
    if not labels:
        await query.answer("⚠️ No labels found. Add labels to accounts first.", show_alert=True)
        return
    await query.edit_message_text(
        "🏷 *Campaign Label Filter*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose a label — only accounts with that label will run.\n"
        "Tap *No Filter* to use all active accounts.",
        reply_markup=campaign_label_filter_menu(index, labels, current),
        parse_mode="Markdown",
    )


async def campaign_label_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set label filter on campaign. Pattern: camp_lbl_set_<index>_<label>"""
    query = update.callback_query
    user_id = update.effective_user.id
    # camp_lbl_set_<index>_<label_safe>
    parts = query.data.split("_", 4)   # ['camp', 'lbl', 'set', '<index>', '<label>']
    if len(parts) < 5:
        await query.answer("Invalid action.", show_alert=True)
        return
    index = int(parts[3])
    label = parts[4].replace("_", " ")
    # Save to campaign
    from storage import get_user, save_user
    user = get_user(user_id)
    camps = user.get("campaigns", [])
    if 0 <= index < len(camps):
        camps[index]["label_filter"] = label
        save_user(user_id, user)
    await query.answer(f"🏷 Filter set to: {label}", show_alert=True)
    await campaign_view(update, context, campaign_index=index)


async def campaign_label_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear label filter. Pattern: camp_lbl_clear_<index>"""
    query = update.callback_query
    user_id = update.effective_user.id
    index = int(query.data.split("_")[-1])
    from storage import get_user, save_user
    user = get_user(user_id)
    camps = user.get("campaigns", [])
    if 0 <= index < len(camps):
        camps[index].pop("label_filter", None)
        save_user(user_id, user)
    await query.answer("🔓 Label filter cleared.", show_alert=True)
    await campaign_view(update, context, campaign_index=index)
