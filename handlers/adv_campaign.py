import asyncio
import html as _html
import os
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from keyboards import (
    back_button, cancel_button, campaign_action_types_menu, reaction_mode_menu,
    reaction_picker_menu, REACTIONS, vote_button_picker_menu,
)
from storage import is_owner, has_adv_access, get_adv_access_limit

ADV_ACTION, ADV_TARGET, ADV_DM_MESSAGE, ADV_REACT, ADV_JOIN_LINK, ADV_BTN_NUM, ADV_ACCT_COUNT = range(7)

REACT_PICKER_ACTIONS = {"react", "react_vote", "react_view", "react_vote_view"}

REACT_ACTIONS = {"react", "react_vote", "react_view", "react_vote_view"}

# Actions that involve clicking a poll/vote button
VOTE_ACTIONS = {"vote", "react_vote", "vote_view", "react_vote_view"}

# A Telegram connection or peer lookup must not hold the whole campaign open
# forever. The worker reports a normal failure after this limit and continues
# with the remaining accounts.
ADV_ACCOUNT_TIMEOUT_SECONDS = 120

ACTION_LABELS = {
    "react": "⭐ React Only",
    "vote": "🗳 Vote Only",
    "react_vote": "⭐🗳 React + Vote",
    "view": "👁 View Only",
    "react_view": "⭐👁 React + View",
    "vote_view": "🗳👁 Vote + View",
    "react_vote_view": "⭐🗳👁 React + Vote + View",
    "join": "⚡ Join Channel",
    "leave": "🚫 Leave Channel",
    "leave_all": "🚫 Leave All Channels",
    "bulk_dm": "📩 Bulk DM",
    "bot_referral": "🔗 Bot Referral",
}

# Actions that run immediately with no target/reaction input required
NO_TARGET_ACTIONS = {"leave_all"}

TARGET_PROMPTS = {
    "react": "Post URL to react to:\n`https://t.me/channel/123`",
    "vote": "Post URL with poll/vote:\n`https://t.me/channel/123`",
    "react_vote": "Post URL to react + vote:\n`https://t.me/channel/123`",
    "view": "Post URL to view:\n`https://t.me/channel/123`",
    "react_view": "Post URL to react + view:\n`https://t.me/channel/123`",
    "vote_view": "Post URL to vote + view:\n`https://t.me/channel/123`",
    "react_vote_view": "Post URL to react + vote + view:\n`https://t.me/channel/123`",
    "join": (
        "Channel to join:\n"
        "Public: `@mychannel` or `https://t.me/mychannel`\n"
        "Private invite: `https://t.me/+AbCdEfGhIjKl` or `+AbCdEfGhIjKl`\n"
        "By ID: `-1001234567890`"
    ),
    "leave": (
        "Channel to leave:\n"
        "Public: `@mychannel` or `https://t.me/mychannel`\n"
        "Private invite: `https://t.me/+AbCdEfGhIjKl` or `+AbCdEfGhIjKl`\n"
        "By numeric ID: `-1001234567890`"
    ),
    "bulk_dm": "Username / user ID to DM:\n`@username` or `123456789`",
    "bot_referral": (
        "Paste your *bot referral link* below:\n\n"
        "• `https://t.me/YourBot?start=refXXX`\n"
        "• `https://t.me/YourBot/App?startapp=refXXX`\n"
        "• `https://t.me/YourBot`\n\n"
        "Each account will open your bot, join any channels it mentions, "
        "and complete verify steps automatically."
    ),
}


def _adv_join_link_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Skip (already joined)", callback_data="adv_skip_join", style="primary")],
        [InlineKeyboardButton("❌ Cancel", callback_data="main_menu", style="danger")],
    ])


def _usable_session_value(account: dict) -> str:
    """Read the same session aliases supported by the campaign runner."""
    for field in ("session_string", "session", "identifier"):
        value = account.get(field)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) >= 20 and not value.startswith("+") and not value.endswith("..."):
            return value
    return ""


def _has_usable_session(account: dict) -> bool:
    """Accept session strings and legacy on-disk Pyrogram sessions."""
    if _usable_session_value(account):
        return True
    session_file = account.get("session_file")
    return (
        isinstance(session_file, str)
        and bool(session_file.strip())
        and os.path.exists(session_file)
    )


def _get_pool(user_id: int) -> list:
    """Collect the accounts that ADV is allowed to attempt."""
    from storage import get_all_user_ids, get_accounts as _get_accs

    all_accounts = []
    active_accounts = []
    now = time.time()
    for uid_str in get_all_user_ids():
        try:
            accs = _get_accs(int(uid_str))
        except Exception:
            continue
        for a in accs:
            try:
                throttled_until = float(a.get("throttled_until") or 0)
            except (TypeError, ValueError):
                throttled_until = 0
            if str(a.get("status") or "active").lower() == "active":
                # Embed owner uid so run_one can mark dead on fatal errors.
                record = {**a, "_uid": int(uid_str)}
                active_accounts.append(record)
                if throttled_until <= now and _has_usable_session(a):
                    all_accounts.append(record)

    if is_owner(user_id):
        # The owner panel is the source of truth for the owner's pool. Do not
        # hide active records merely because their legacy session field is
        # missing; the runner will report that account's failure explicitly.
        return active_accounts

    # ADV users get up to their personal limit
    limit = get_adv_access_limit(user_id)
    if limit < 0:
        return []                    # no access
    if limit == 0:
        return all_accounts          # unlimited
    return all_accounts[:limit]


# ─── Entry ────────────────────────────────────────────────────────────────────

async def _open_adv_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Open ADV Campaign from either its button or /advcampaign command."""
    query = update.callback_query
    user_id = update.effective_user.id

    if not has_adv_access(user_id):
        if query:
            await query.answer("⛔ Access denied.", show_alert=True)
        elif update.message:
            await update.message.reply_text("⛔ ADV Campaign access denied.")
        return ConversationHandler.END

    if query:
        await query.answer()

    pool = _get_pool(user_id)
    total = len(pool)

    back_target = "owner_panel" if is_owner(user_id) else "main_menu"

    if total == 0:
        text = (
            "⚠️ *ADV Campaign — No Accounts*\n\n"
            "There are no active accounts with valid session strings in the system."
        )
        markup = back_button(back_target)
        if query:
            await query.edit_message_text(
                text, reply_markup=markup, parse_mode="Markdown"
            )
        elif update.message:
            await update.message.reply_text(
                text, reply_markup=markup, parse_mode="Markdown"
            )
        return ConversationHandler.END

    role = "👑 Owner" if is_owner(user_id) else "📌 ADV User"
    text = (
        f"🌐 *ADV CAMPAIGN*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"🔑 *Access Level:* {role}\n"
        f"📦 *Available Accounts:* {total}\n\n"
        "This campaign runs on *all accounts* from all users.\n\n"
        "Select the action type:"
    )
    markup = campaign_action_types_menu(
        True,
        show_bot_referral=is_owner(user_id),
    )
    if query:
        await query.edit_message_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )

    context.user_data["adv_back"] = back_target
    return ADV_ACTION


async def adv_campaign_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Button entry point for ADV Campaign."""
    return await _open_adv_campaign(update, context)


async def adv_campaign_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Slash-command entry point for the complete ADV Campaign flow."""
    return await _open_adv_campaign(update, context)


async def adv_camp_get_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.replace("camp_action_", "")
    user_id = update.effective_user.id
    if action == "bot_referral" and not is_owner(user_id):
        await query.answer(
            "⛔ Bot Referral is restricted to owners and co-owners.",
            show_alert=True,
        )
        return ADV_ACTION
    context.user_data["adv_action"] = action
    context.user_data["adv_reactions"] = []
    context.user_data["adv_reaction_mode"] = "simple"
    label = ACTION_LABELS.get(action, action)

    if action in NO_TARGET_ACTIONS:
        context.user_data["adv_target"] = "All Chats"
        return await _show_adv_acct_prompt(update, context)

    if action in REACT_ACTIONS:
        await query.edit_message_text(
            f"🌐 *ADV Campaign — {label}*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "Step 2 — Choose the reaction type.",
            reply_markup=reaction_mode_menu(prefix="adv"),
            parse_mode="Markdown",
        )
        return ADV_REACT

    prompt = TARGET_PROMPTS.get(action, "Enter the target:")
    await query.edit_message_text(
        f"🌐 *ADV Campaign — {label}*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"📍 {prompt}",
        reply_markup=cancel_button(), parse_mode="Markdown",
    )
    return ADV_TARGET


async def adv_action_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Select an ADV action without using the action buttons."""
    command = (update.message.text or "").split()[0].split("@", 1)[0].lstrip("/")
    action = command.removeprefix("adv_")
    if action not in ACTION_LABELS:
        await update.message.reply_text("⚠️ Unknown ADV action. Use /advcampaign.")
        return ADV_ACTION

    user_id = update.effective_user.id
    if action == "bot_referral" and not is_owner(user_id):
        await update.message.reply_text(
            "⛔ Bot Referral is restricted to owners and co-owners."
        )
        return ADV_ACTION

    context.user_data["adv_action"] = action
    context.user_data["adv_reactions"] = []
    context.user_data["adv_reaction_mode"] = "simple"
    label = ACTION_LABELS[action]

    if action in NO_TARGET_ACTIONS:
        context.user_data["adv_target"] = "All Chats"
        return await _show_adv_acct_prompt(update, context)

    if action in REACT_ACTIONS:
        await update.message.reply_text(
            f"🌐 *ADV Campaign — {label}*\n\n"
            "Step 2 — Choose reaction mode:\n"
            "Use `/adv_simple` or `/adv_premium`.",
            reply_markup=reaction_mode_menu(prefix="adv"),
            parse_mode="Markdown",
        )
        return ADV_REACT

    await update.message.reply_text(
        f"🌐 *ADV Campaign — {label}*\n\n"
        f"📍 {TARGET_PROMPTS.get(action, 'Enter the target:')}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return ADV_TARGET


async def adv_reaction_mode_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Choose simple/premium reactions without using the mode buttons."""
    command = (update.message.text or "").split()[0].split("@", 1)[0].lstrip("/")
    mode = "premium" if command == "adv_premium" else "simple"
    action = context.user_data.get("adv_action", "react")
    label = ACTION_LABELS.get(action, action)
    context.user_data["adv_reaction_mode"] = mode
    context.user_data["adv_reactions"] = []

    if mode == "simple":
        await update.message.reply_text(
            f"🌐 *ADV Campaign — {label}*\n\n"
            "Choose reactions with `/adv_reaction NUMBER`.\n"
            "Example: `/adv_reaction 1`\n"
            "When finished, send `/adv_done`.",
            reply_markup=reaction_picker_menu([], prefix="adv"),
            parse_mode="Markdown",
        )
        return ADV_REACT

    await update.message.reply_text(
        f"🌐 *ADV Campaign — {label}*\n\n"
        "💎 Premium mode selected.\n\n"
        f"Step 3 — {TARGET_PROMPTS.get(action, 'Enter the target:')}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return ADV_TARGET


async def adv_reaction_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Toggle a reaction by its 1-based number, without the reaction picker."""
    try:
        number = int(context.args[0])
        if not 1 <= number <= len(REACTIONS):
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text(
            f"⚠️ Use `/adv_reaction NUMBER`, where NUMBER is 1–{len(REACTIONS)}."
        )
        return ADV_REACT

    emoji = REACTIONS[number - 1]
    selected = context.user_data.setdefault("adv_reactions", [])
    if emoji in selected:
        selected.remove(emoji)
    else:
        selected.append(emoji)
    await update.message.reply_text(
        f"✅ Selected reactions: {' '.join(selected) or 'none'}\n"
        "Add/remove another with `/adv_reaction NUMBER` or continue with `/adv_done`.",
        reply_markup=reaction_picker_menu(selected, prefix="adv"),
    )
    return ADV_REACT


async def adv_react_done_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Finish manual reaction selection without pressing Done."""
    selected = context.user_data.get("adv_reactions", [])
    if not selected:
        await update.message.reply_text(
            "⚠️ Select at least one reaction using `/adv_reaction NUMBER`."
        )
        return ADV_REACT

    context.user_data["adv_reaction_mode"] = "simple"
    action = context.user_data.get("adv_action", "react")
    label = ACTION_LABELS.get(action, action)
    await update.message.reply_text(
        f"🌐 *ADV Campaign — {label}*\n\n"
        f"✅ Reactions: {' '.join(selected)}\n\n"
        f"📍 {TARGET_PROMPTS.get(action, 'Enter the target:')}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return ADV_TARGET


async def adv_reaction_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Choose the existing manual picker or premium auto-reactions."""
    query = update.callback_query
    await query.answer()
    mode = query.data.rsplit("_", 1)[-1]
    action = context.user_data.get("adv_action", "react")
    label = ACTION_LABELS.get(action, action)
    context.user_data["adv_reaction_mode"] = mode
    context.user_data["adv_reactions"] = []

    if mode == "simple":
        await query.edit_message_text(
            f"🌐 *ADV Campaign — {label}*\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            "Step 2 — Choose the *reaction(s)* to send.\n"
            "Tap to select/deselect. You can pick multiple.\n"
            "Then press ✅ Done.",
            reply_markup=reaction_picker_menu([], prefix="adv"),
            parse_mode="Markdown",
        )
        return ADV_REACT

    prompt = TARGET_PROMPTS.get(action, "Enter the target:")
    await query.edit_message_text(
        f"🌐 *ADV Campaign — {label}*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "💎 Premium mode will use the first two reactions available on the post.\n\n"
        f"Step 3 — {prompt}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return ADV_TARGET


async def adv_toggle_react(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    idx = int(query.data.replace("adv_react_", ""))
    emoji = REACTIONS[idx]
    selected: list = context.user_data.setdefault("adv_reactions", [])
    if emoji in selected:
        selected.remove(emoji)
    else:
        selected.append(emoji)
    action = context.user_data.get("adv_action", "react")
    label = ACTION_LABELS.get(action, action)
    await query.edit_message_text(
        f"🌐 *ADV Campaign — {label}*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "Step 2 — Choose the *reaction(s)* to send.\n"
        "Tap to select/deselect. You can pick multiple.\n"
        "Then press ✅ Done.",
        reply_markup=reaction_picker_menu(selected, prefix="adv"),
        parse_mode="Markdown",
    )
    return ADV_REACT


async def adv_react_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    selected: list = context.user_data.get("adv_reactions", [])
    if not selected:
        await query.answer("⚠️ Please pick at least one reaction first!", show_alert=True)
        return ADV_REACT
    await query.answer()
    context.user_data["adv_reaction_mode"] = "simple"
    action = context.user_data.get("adv_action", "react")
    label = ACTION_LABELS.get(action, action)
    prompt = TARGET_PROMPTS.get(action, "Enter the target:")
    await query.edit_message_text(
        f"🌐 *ADV Campaign — {label}*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"✅ Reactions: {' '.join(selected)}\n\n"
        f"📍 {prompt}",
        reply_markup=cancel_button(),
        parse_mode="Markdown",
    )
    return ADV_TARGET


async def adv_camp_get_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target = update.message.text.strip()
    context.user_data["adv_target"] = target
    action = context.user_data.get("adv_action", "")

    if action == "bulk_dm":
        await update.message.reply_text(
            "📩 *Enter the DM message to send:*",
            reply_markup=cancel_button(), parse_mode="Markdown"
        )
        return ADV_DM_MESSAGE

    # join/leave/bot_referral: no separate join link needed
    if action in ("join", "leave", "leave_all", "bot_referral"):
        return await _show_adv_acct_prompt(update, context)

    # All other actions: ask for optional auto-join link
    label = ACTION_LABELS.get(action, action)
    reactions = context.user_data.get("adv_reactions") or []
    react_line = f"✅ Reactions: {' '.join(reactions)}\n\n" if action in REACT_ACTIONS else ""
    join_step = "Step 4" if action in REACT_PICKER_ACTIONS else "Step 3"
    await update.message.reply_text(
        f"🌐 *ADV Campaign — {label}*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"{react_line}"
        "✅ Post URL saved!\n\n"
        f"🔗 *{join_step} — Paste the channel join link.*\n\n"
        "📣 This is used to auto-join accounts that are not yet members before acting.\n\n"
        "• Public channel: `https://t.me/channelname`\n"
        "• Private invite: `https://t.me/+InviteCode`\n\n"
        "Tap ⏭ *Skip* if all accounts are already joined:",
        reply_markup=_adv_join_link_kb(),
        parse_mode="Markdown",
    )
    return ADV_JOIN_LINK


async def adv_camp_get_dm_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["adv_dm_msg"] = update.message.text.strip()
    action = context.user_data.get("adv_action", "")
    # bulk_dm has no channel to join — skip straight to account count
    if action == "bulk_dm":
        context.user_data["adv_join_link"] = ""
        return await _show_adv_acct_prompt(update, context)
    label = ACTION_LABELS.get(action, action)
    await update.message.reply_text(
        f"🌐 *ADV Campaign — {label}*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        "✅ Message saved!\n\n"
        "🔗 *Step 4 — Paste the channel join link.*\n\n"
        "📣 This is used to auto-join accounts that are not yet members before acting.\n\n"
        "• Public channel: `https://t.me/channelname`\n"
        "• Private invite: `https://t.me/+InviteCode`\n\n"
        "Tap ⏭ *Skip* if all accounts are already joined:",
        reply_markup=_adv_join_link_kb(),
        parse_mode="Markdown",
    )
    return ADV_JOIN_LINK


async def adv_camp_get_join_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles both the join-link text input and the Skip callback."""
    if update.callback_query:
        await update.callback_query.answer()
        join_link = ""
    else:
        raw = update.message.text.strip()
        command = raw.split()[0].split("@", 1)[0].lstrip("/")
        join_link = "" if command == "adv_skip_join" else raw
    context.user_data["adv_join_link"] = join_link

    action = context.user_data.get("adv_action", "")
    if action in VOTE_ACTIONS:
        label = ACTION_LABELS.get(action, action)
        join_status = "✅ Channel join skipped!" if not join_link else f"✅ Channel link saved!\n🔗 <code>{_html.escape(join_link[:50])}</code>"
        btn_step = "Step 5" if action in REACT_PICKER_ACTIONS else "Step 4"
        text = (
            f"🌐 <b>ADV Campaign — {label}</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"{join_status}\n\n"
            f"🖱 <b>{btn_step} — Which button should your accounts click?</b>\n"
            "Send <code>/adv_button 3</code> for the third button."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text, reply_markup=vote_button_picker_menu("adv"), parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                text, reply_markup=vote_button_picker_menu("adv"), parse_mode="HTML"
            )
        return ADV_BTN_NUM

    return await _show_adv_acct_prompt(update, context)


async def adv_btn_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles 1st–5th button click or 'Other #' in the ADV vote button picker."""
    query = update.callback_query
    await query.answer()
    data = query.data  # adv_btn_1 … adv_btn_5 or adv_btn_other

    if data == "adv_btn_other":
        await query.edit_message_text(
            "🔢 *Enter the button number* (e.g. 6, 7, 8...):",
            reply_markup=cancel_button(),
            parse_mode="Markdown",
        )
        return ADV_BTN_NUM

    btn_num = int(data.replace("adv_btn_", ""))
    context.user_data["adv_btn_index"] = btn_num - 1
    return await _show_adv_acct_prompt(update, context)


async def adv_btn_num_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles a custom button number typed by the user for ADV campaigns."""
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
        return ADV_BTN_NUM
    context.user_data["adv_btn_index"] = btn_num - 1
    return await _show_adv_acct_prompt(update, context)


async def adv_button_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Select a vote button by command, e.g. /adv_button 3."""
    try:
        btn_num = int(context.args[0])
        if btn_num < 1:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text(
            "⚠️ Use `/adv_button NUMBER`, for example `/adv_button 3`."
        )
        return ADV_BTN_NUM
    context.user_data["adv_btn_index"] = btn_num - 1
    return await _show_adv_acct_prompt(update, context)


async def _show_adv_acct_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ask how many accounts to use for this ADV campaign."""
    user_id = update.effective_user.id
    pool = _get_pool(user_id)
    total = len(pool)
    context.user_data["adv_acct_total"] = total
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ All ({total})", callback_data="adv_acct_all", style="success"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu", style="danger"),
        ]
    ])
    text = (
        "📊 *How many accounts?*\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"📱 You have *{total}* active account(s) available.\n"
        f"Max you can use: *{total}*\n\n"
        f"Send a number (1–{total}), use `/adv_accounts NUMBER`, "
        "or send `/adv_accounts all`:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return ADV_ACCT_COUNT


async def adv_acct_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User tapped 'All (N)' — use all available accounts."""
    query = update.callback_query
    await query.answer()
    context.user_data["adv_acct_count"] = 0  # 0 = all
    return await _run_adv(update, context)


async def adv_acct_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User typed a specific account count for the ADV campaign."""
    raw = update.message.text.strip()
    total = context.user_data.get("adv_acct_total", 0)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ All ({total})", callback_data="adv_acct_all", style="success"),
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
        return ADV_ACCT_COUNT
    context.user_data["adv_acct_count"] = n
    return await _run_adv(update, context)


async def adv_accounts_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Choose ADV account count by command, e.g. /adv_accounts 5."""
    total = int(context.user_data.get("adv_acct_total") or len(_get_pool(update.effective_user.id)))
    raw = (context.args[0].lower() if context.args else "")
    if raw == "all":
        context.user_data["adv_acct_count"] = 0
        return await _run_adv(update, context)
    try:
        count = int(raw)
        if count < 1 or count > total:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            f"⚠️ Use `/adv_accounts all` or `/adv_accounts NUMBER` (1–{total})."
        )
        return ADV_ACCT_COUNT
    context.user_data["adv_acct_count"] = count
    return await _run_adv(update, context)
# ─── Core run ─────────────────────────────────────────────────────────────────

async def _run_adv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from runner import (
        run_campaign_on_account,
        progress_bar,
        SPEED_PRESETS,
        _API_ID,
        _API_HASH,
    )
    from storage import (
        is_adv_stop_requested, clear_adv_stop,
        is_adv_pause_requested, clear_adv_pause,
        get_settings, get_accounts as _get_owner_accounts,
        set_account_throttle, get_cooldown_minutes,
        get_global_cooldown_minutes,
    )
    import random

    user_id      = update.effective_user.id
    action       = context.user_data.get("adv_action", "")
    if action == "bot_referral" and not is_owner(user_id):
        if update.callback_query:
            await update.callback_query.answer(
                "⛔ Bot Referral is restricted to owners and co-owners.",
                show_alert=True,
            )
        else:
            await update.message.reply_text(
                "⛔ Bot Referral is restricted to owners and co-owners."
            )
        return ConversationHandler.END
    target       = context.user_data.get("adv_target", "")
    dm_msg       = context.user_data.get("adv_dm_msg", "")
    join_link    = context.user_data.get("adv_join_link", "")
    reaction_mode = context.user_data.get("adv_reaction_mode", "simple")
    reactions    = context.user_data.get("adv_reactions") or (
        [] if reaction_mode == "premium" else ["👍"]
    )
    button_index = context.user_data.get("adv_btn_index", 0)
    label        = ACTION_LABELS.get(action, action)

    # Use the user's speed preset (same as regular campaigns)
    speed_key = get_settings(user_id).get("speed", "slow")
    preset    = SPEED_PRESETS.get(speed_key, SPEED_PRESETS["slow"])
    # Advanced campaigns share the same target across accounts, so keep even
    # the fastest selected preset at three concurrent sessions.
    WORKERS   = min(preset["workers"], 3)
    MIN_DELAY = preset["min_delay"]

    pool = _get_pool(user_id)
    adv_acct_count = context.user_data.get("adv_acct_count", 0)
    if adv_acct_count > 0:
        pool = pool[:adv_acct_count]
    total = len(pool)

    chat_id = update.effective_chat.id

    if total == 0:
        if update.message:
            await update.message.reply_text("⚠️ No runnable accounts available.", reply_markup=cancel_button())
        else:
            await context.bot.send_message(chat_id, "⚠️ No runnable accounts available.", reply_markup=cancel_button())
        return ConversationHandler.END

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

    start_time = time.monotonic()
    last_edit   = [0.0]

    # Stop / Pause inline keyboards shown while running
    running_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏸ Pause",  callback_data=f"adv_pause_{user_id}", style="primary"),
        InlineKeyboardButton("⏹ Stop",   callback_data=f"adv_stop_{user_id}",  style="danger"),
    ]])
    pausing_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏸ Pausing…", callback_data=f"adv_pause_{user_id}", style="primary"),
        InlineKeyboardButton("⏹ Stop",     callback_data=f"adv_stop_{user_id}",  style="danger"),
    ]])

    starting_text = (
        f"🌐 <b>ADV Campaign Starting...</b>\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
        f"⚡ Action: {label}\n"
        f"🎯 Target: <code>{_html.escape(target)}</code>\n"
        f"📦 Accounts: {total}\n\n"
        f"📊 [{'░' * 12}] 0%\n"
        f"🔢 0/{total}\n"
        f"⏱ Estimating...\n\n"
        f"✅ 0   ❌ 0   ⏳ {total}"
    )
    if update.message:
        prog_msg = await update.message.reply_text(starting_text, reply_markup=running_kb, parse_mode="HTML")
    else:
        prog_msg = await context.bot.send_message(chat_id, starting_text, reply_markup=running_kb, parse_mode="HTML")

    # Pre-assign reactions evenly across accounts.
    if reaction_mode == "premium":
        _assigned = [None] * total
    elif reactions and len(reactions) > 1:
        _assigned: list = []
        per, rem = divmod(total, len(reactions))
        for i, r in enumerate(reactions):
            _assigned.extend([r] * (per + (1 if i < rem else 0)))
        import random as _rnd; _rnd.shuffle(_assigned)
    else:
        _assigned = [(reactions[0] if reactions else "👍")] * total

    counters = {"done": 0, "failed": 0, "errors": [], "stopped": False, "paused": False, "flood_waits": []}
    lock      = asyncio.Lock()
    semaphore = asyncio.Semaphore(WORKERS)

    def _throttle_adv_account(acc: dict, until: float) -> None:
        """Persist a rest period for an ADV account in its owner's record."""
        owner_uid = acc.get("_uid")
        identifier = acc.get("identifier")
        if not owner_uid or not identifier:
            return
        try:
            owner_accounts = _get_owner_accounts(owner_uid)
            stored_idx = next(
                (
                    i for i, stored in enumerate(owner_accounts)
                    if stored.get("identifier") == identifier
                ),
                None,
            )
            if stored_idx is not None:
                set_account_throttle(owner_uid, stored_idx, int(until))
        except Exception:
            pass

    def _adv_rest_seconds(acc: dict) -> int:
        owner_uid = acc.get("_uid")
        try:
            configured = max(
                get_cooldown_minutes(owner_uid),
                get_global_cooldown_minutes(),
            )
        except Exception:
            configured = 0
        return max(5 * 60, int(configured) * 60)

    async def refresh_progress():
        now      = time.monotonic()
        finished = counters["done"] + counters["failed"]
        if finished > 0:
            if now - last_edit[0] >= 1.5 or finished == total:
                bar = progress_bar(finished, total)
                eta = _eta(start_time, counters["done"], counters["failed"], total)

                # Flood wait summary
                flood_line = ""
                flood_waits = counters.get("flood_waits", [])
                if flood_waits:
                    _now_ts = time.time()
                    active = [(n, max(0, int(u - _now_ts))) for n, u in flood_waits if u - _now_ts > 0]
                    if active:
                        max_secs = max(s for _, s in active)
                        flood_line = (
                            f"\n🌊 <b>Flood wait:</b> {len(active)} acc throttled"
                            f" — up to <b>{max_secs}s</b> left"
                        )

                err_lines = ""
                if counters["errors"]:
                    err_lines = "\n\n⚠️ <b>Errors:</b>\n" + "\n".join(
                        f"• {_html.escape(e)}" for e in counters["errors"][-2:]
                    )
                try:
                    await prog_msg.edit_text(
                        f"🌐 <b>ADV Campaign Running...</b>\n"
                        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
                        f"⚡ Action: {label}\n"
                        f"🎯 Target: <code>{_html.escape(target)}</code>\n\n"
                        f"📊 {bar}\n"
                        f"🔢 {finished}/{total}\n"
                        f"{eta}"
                        f"{flood_line}\n\n"
                        f"✅ {counters['done']}   ❌ {counters['failed']}   "
                        f"⏳ {total - finished}"
                        f"{err_lines}",
                        reply_markup=running_kb,
                        parse_mode="HTML"
                    )
                    last_edit[0] = time.monotonic()
                except Exception:
                    pass

    async def run_one(acc: dict, idx: int):
        async with semaphore:
            await asyncio.sleep(random.uniform(0, MIN_DELAY))

            # Honour stop / pause flags after stagger delay
            if is_adv_stop_requested(user_id):
                async with lock:
                    counters["stopped"] = True
                return
            if is_adv_pause_requested(user_id):
                async with lock:
                    counters["paused"] = True
                return

            identifier = acc.get("identifier", "")
            # The shared runner accepts an account record and campaign
            # record. ADV campaigns used to call an older positional
            # interface, which caused ``unexpected keyword argument
            # 'reactions'`` before the leave action could run.
            camp = {
                "action": action,
                "target": target,
                "message": dm_msg,
                "join_link": join_link,
                "reactions": [] if reaction_mode == "premium" else [_assigned[idx]],
                "reaction_mode": reaction_mode,
                "button_index": button_index,
            }
            try:
                result = await asyncio.wait_for(
                    run_campaign_on_account(
                        acc,
                        camp,
                        api_id=_API_ID,
                        api_hash=_API_HASH,
                        reactions=[] if reaction_mode == "premium" else [_assigned[idx]],
                    ),
                    timeout=ADV_ACCOUNT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                result = {
                    "ok": False,
                    "error": (
                        f"Timed out after {ADV_ACCOUNT_TIMEOUT_SECONDS}s "
                        "while connecting or performing the action"
                    ),
                }
            except Exception as exc:
                result = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            cooldown_until = result.get("cooldown_until") or result.get("flood_until")
            if result.get("ok"):
                cooldown_until = time.time() + _adv_rest_seconds(acc)
            if cooldown_until:
                _throttle_adv_account(
                    acc,
                    max(
                        float(cooldown_until),
                        time.time() + _adv_rest_seconds(acc),
                    ),
                )
            # Campaigns are non-destructive. A single campaign error must not
            # hide an account or overwrite its stored status. Use the
            # explicit Session Health check to confirm re-login is required.
            # Track flood wait
            flood_until = result.get("flood_until")
            if flood_until:
                async with lock:
                    counters["flood_waits"].append((acc.get("name", "?"), flood_until))

            async with lock:
                if result.get("ok"):
                    counters["done"] += 1
                else:
                    counters["failed"] += 1
                    phone = acc.get("phone") or acc.get("username", "?")
                    error = result.get("error") or result.get("detail") or "Unknown error"
                    counters["errors"].append(f"{acc.get('name','?')} ({phone}): {error}")
            await refresh_progress()

    # Snapshot conversation data before clearing (needed inside background task)
    back_target = context.user_data.get("adv_back", "owner_panel")
    for k in ["adv_action", "adv_target", "adv_dm_msg", "adv_back", "adv_reactions",
              "adv_reaction_mode",
              "adv_join_link", "adv_btn_index", "adv_acct_count", "adv_acct_total"]:
        context.user_data.pop(k, None)

    # Capture user info for log channel (before _bg closes over these)
    import hashlib as _hl
    _log_tg_user   = update.effective_user
    _log_full_name = _log_tg_user.full_name or str(user_id)
    _log_username  = _log_tg_user.username
    _log_camp_id   = _hl.md5(f"{user_id}{target}{start_time}".encode()).hexdigest()[:24]

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
        reactions=reactions,
        join_link=join_link,
    ))

    # ── Background task ────────────────────────────────────────────────────────
    # Handler returns immediately so the Stop/Pause buttons stay visible.
    async def _bg() -> None:
        try:
            await asyncio.gather(*[run_one(acc, i) for i, acc in enumerate(pool)])
        finally:
            clear_adv_stop(user_id)
            clear_adv_pause(user_id)

        elapsed     = int(time.monotonic() - start_time)
        elapsed_str = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"
        done_total  = counters["done"] + counters["failed"]
        bar         = progress_bar(done_total, total)

        was_stopped = counters["stopped"]
        was_paused  = counters["paused"]

        if was_paused:
            title = "⏸ <b>ADV Campaign Paused</b>"
            status_note = "\n⏸ <b>Paused by user.</b>"
        elif was_stopped:
            title = "⏹ <b>ADV Campaign Stopped</b>"
            status_note = "\n⏹ <b>Stopped by user.</b>"
        else:
            title = "✅ <b>ADV Campaign Complete!</b>"
            status_note = ""

        all_errors = counters["errors"]
        if len(all_errors) > 4:
            err_lines = "\n\n📎 <b>Full error report sent as document below.</b>"
        elif all_errors:
            err_lines = "\n\n⚠️ <b>Errors:</b>\n" + "\n".join(f"• {_html.escape(e)}" for e in all_errors)
        else:
            err_lines = ""

        await prog_msg.edit_text(
            f"{title}\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n\n"
            f"⚡ Action: {label}\n"
            f"🎯 Target: <code>{_html.escape(target)}</code>\n\n"
            f"📊 {bar}\n"
            f"🔢 {done_total}/{total} accounts\n"
            f"⏱ Elapsed: {elapsed_str}\n\n"
            f"✅ Done: {counters['done']}   ❌ Failed: {counters['failed']}"
            f"{status_note}"
            f"{err_lines}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Panel", callback_data=back_target, style="primary")
            ]]),
            parse_mode="HTML"
        )

        if len(all_errors) > 4:
            import io
            file_content = "\n".join(all_errors)
            err_filename = target.replace("/", "_")[:32]
            filename = f"adv_campaign_{err_filename}_errors.txt"
            await prog_msg.reply_document(
                document=io.BytesIO(file_content.encode("utf-8")),
                filename=filename,
                caption=f"⚠️ {len(all_errors)} errors from ADV campaign run",
            )

        from handlers.log_gc import send_log, fmt_campaign_done
        await send_log(context.bot, fmt_campaign_done(
            user_id=user_id,
            full_name=_log_full_name,
            camp_id=_log_camp_id,
            action_label=label,
            done=counters["done"],
            failed=counters["failed"],
            total=total,
            elapsed=elapsed_str,
            was_stopped=was_stopped,
            was_paused=was_paused,
        ))

    context.application.create_task(_bg())
    return ConversationHandler.END


# ─── Stop / Pause handlers ────────────────────────────────────────────────────

async def adv_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Request stop for a running ADV campaign."""
    query = update.callback_query
    from storage import set_adv_stop
    set_adv_stop(update.effective_user.id)
    await query.answer("⏹ Stop requested — finishing current accounts…", show_alert=True)


async def adv_stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command alternative to the ADV Stop button."""
    from storage import set_adv_stop
    set_adv_stop(update.effective_user.id)
    await update.message.reply_text(
        "⏹ Stop requested — finishing current accounts…"
    )


async def adv_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Request pause for a running ADV campaign."""
    query = update.callback_query
    user_id = update.effective_user.id
    from storage import set_adv_pause
    set_adv_pause(user_id)
    pausing_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏸ Pausing…", callback_data=f"adv_pause_{user_id}", style="primary"),
        InlineKeyboardButton("⏹ Stop",     callback_data=f"adv_stop_{user_id}",  style="danger"),
    ]])
    try:
        await query.edit_message_reply_markup(reply_markup=pausing_kb)
    except Exception:
        pass
    await query.answer("⏸ Pause requested — finishing current accounts…", show_alert=True)


async def adv_pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command alternative to the ADV Pause button."""
    from storage import set_adv_pause
    set_adv_pause(update.effective_user.id)
    await update.message.reply_text(
        "⏸ Pause requested — finishing current accounts…"
    )



async def adv_campaign_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    for k in ["adv_action", "adv_target", "adv_dm_msg", "adv_back", "adv_reactions", "adv_join_link"]:
        context.user_data.pop(k, None)
    from handlers.start import start_handler
    await start_handler(update, context)
    return ConversationHandler.END
