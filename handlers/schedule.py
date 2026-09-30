from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from storage import get_schedules, add_schedule, remove_schedule, toggle_schedule_enabled, get_campaigns
from keyboards import (
    schedules_menu, schedule_actions, schedule_delete_confirm_menu,
    schedule_campaign_picker, days_of_week_picker, back_button, cancel_button,
)

SCH_NAME, SCH_TIME, SCH_ACTION, SCH_CAMP_PICK, SCH_DAYS, SCH_JITTER = range(6)


async def schedule_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    schedules = get_schedules(user_id)
    query = update.callback_query
    await query.answer()

    if not schedules:
        text = (
            "⏰ *SCHEDULE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No schedules set up yet.\n"
            "Press ➕ New Schedule to create one."
        )
    else:
        text = (
            "⏰ *SCHEDULE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"You have {len(schedules)} scheduled task(s).\n\n"
            "✅ = enabled  ⏸ = paused\n\n"
            "Select to manage:"
        )

    await query.edit_message_text(text, reply_markup=schedules_menu(schedules), parse_mode="Markdown")


async def schedule_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    schedules = get_schedules(user_id)

    if index >= len(schedules):
        await query.edit_message_text("Schedule not found.", reply_markup=back_button("schedule"))
        return

    sch = schedules[index]
    enabled = sch.get("enabled", True)
    one_shot = sch.get("one_shot", False)
    state_label = "✅ Enabled" if enabled else "⏸ Disabled"

    # Compute next-run countdown in user's local timezone
    next_run_line = ""
    time_str = sch.get("time", "").strip()
    import re as _re
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from storage import get_settings as _get_settings
    user_tz_str = _get_settings(user_id).get("timezone", "UTC")
    tz_display = user_tz_str.split("/")[-1].replace("_", " ")
    if _re.fullmatch(r"\d{1,2}:\d{2}", time_str):
        try:
            from zoneinfo import ZoneInfo
            user_tz = ZoneInfo(user_tz_str)
            h, m = time_str.split(":")
            now = _dt.now(user_tz)
            target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            if target <= now:
                target += _td(days=1)
            diff = target - now
            hours, rem = divmod(int(diff.total_seconds()), 3600)
            mins = rem // 60
            if hours > 0:
                countdown = f"{hours}h {mins}m"
            else:
                countdown = f"{mins}m"
            next_run_line = f"\n⏭ *Next run in:* {countdown}" if enabled else "\n⏭ *Next run:* Paused"
        except Exception:
            pass

    # Days-of-week filter
    _DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = sch.get("days_of_week")
    if days and len(days) < 7:
        days_label = ", ".join(_DAY_NAMES[d] for d in sorted(days))
        days_line = f"\n📆 *Days:* {days_label}"
    else:
        days_line = "\n📆 *Days:* Every day"

    # Jitter
    jitter = sch.get("jitter_minutes", 0)
    jitter_line = f"\n🎲 *Jitter:* ±{jitter}m" if jitter else ""

    # One-shot
    oneshot_line = "\n🎯 *One-shot:* Yes (auto-disables after first run)" if one_shot else ""

    # Last run
    last_run = sch.get("last_run")
    last_result = sch.get("last_result", "")
    last_run_line = f"\n🕐 *Last run:* {last_run}  — {last_result}" if last_run else ""

    text = (
        "⏰ *Schedule Details*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 *Name:* {sch.get('name', 'N/A')}\n"
        f"🕐 *Time:* {sch.get('time', 'N/A')} ({tz_display})\n"
        f"⚡ *Campaign:* {sch.get('action', 'N/A')}\n"
        f"📅 *Created:* {sch.get('created', 'N/A')}\n"
        f"📌 *Status:* {state_label}"
        f"{next_run_line}"
        f"{days_line}"
        f"{jitter_line}"
        f"{oneshot_line}"
        f"{last_run_line}"
    )
    await query.edit_message_text(text, reply_markup=schedule_actions(index, enabled, one_shot), parse_mode="Markdown")


async def schedule_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable or disable a schedule."""
    query = update.callback_query
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    new_state = toggle_schedule_enabled(user_id, index)
    if new_state is None:
        await query.answer("Schedule not found.", show_alert=True)
        return
    label = "✅ Enabled" if new_state else "⏸ Disabled"
    await query.answer(f"Schedule {label}", show_alert=True)
    await schedule_view(update, context)


async def schedule_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show confirmation prompt before deleting schedule."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    schedules = get_schedules(update.effective_user.id)
    name = schedules[index].get("name", f"Schedule {index+1}") if index < len(schedules) else "?"
    await query.edit_message_text(
        f"⚠️ *Delete Schedule?*\n\n`{name}`\n\nThis cannot be undone.",
        reply_markup=schedule_delete_confirm_menu(index),
        parse_mode="Markdown",
    )


async def schedule_toggle_oneshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle one-shot flag on a schedule."""
    query = update.callback_query
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    schedules = get_schedules(user_id)
    if index >= len(schedules):
        await query.answer("Schedule not found.", show_alert=True)
        return
    from storage import get_user, save_user
    user = get_user(user_id)
    scheds = user.get("schedules", [])
    if index >= len(scheds):
        await query.answer("Schedule not found.", show_alert=True)
        return
    scheds[index]["one_shot"] = not scheds[index].get("one_shot", False)
    new_oneshot = scheds[index]["one_shot"]
    save_user(user_id, user)
    label = "enabled" if new_oneshot else "disabled"
    await query.answer(f"🎯 One-shot {label}", show_alert=True)
    await schedule_view(update, context)


async def schedule_dryrun(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger a dry run for the campaign linked to this schedule."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    schedules = get_schedules(user_id)
    if index >= len(schedules):
        await query.answer("Schedule not found.", show_alert=True)
        return
    sch = schedules[index]
    campaign_id = sch.get("campaign_id")
    campaigns = get_campaigns(user_id)
    camp_index = None
    if campaign_id:
        for i, c in enumerate(campaigns):
            if c.get("id") == campaign_id:
                camp_index = i
                break
    if camp_index is None:
        # Fall back: match by name
        action = sch.get("action", "")
        for i, c in enumerate(campaigns):
            if c.get("name") == action:
                camp_index = i
                break
    if camp_index is None:
        await query.answer("Linked campaign not found.", show_alert=True)
        return
    # Pass the linked campaign index directly. CallbackQuery.data is
    # immutable in python-telegram-bot.
    from handlers.campaigns import campaign_dryrun
    await campaign_dryrun(update, context, campaign_index=camp_index)


async def schedule_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    index = int(query.data.split("_")[-1])
    user_id = update.effective_user.id
    remove_schedule(user_id, index)
    await query.answer("🗑 Schedule deleted", show_alert=True)
    await schedule_menu(update, context)


async def add_schedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    text = (
        "⏰ *NEW SCHEDULE*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Step 1/3: Enter a *schedule name*:"
    )
    await query.edit_message_text(text, reply_markup=cancel_button(), parse_mode="Markdown")
    return SCH_NAME


async def sch_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sch_name"] = update.message.text.strip()
    from storage import get_settings as _gs
    user_tz = _gs(update.effective_user.id).get("timezone", "UTC")
    tz_display = user_tz.split("/")[-1].replace("_", " ") if "/" in user_tz else user_tz
    await update.message.reply_text(
        f"Step 2/3: Enter the *time* for this schedule.\n\n"
        f"Format: `HH:MM`  e.g. `09:00`, `18:30`\n\n"
        f"⏰ Your current timezone: *{tz_display}*\n"
        f"_(Change in ⚙️ Settings → Timezone)_",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return SCH_TIME


async def sch_get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    import re
    time_val = update.message.text.strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", time_val):
        await update.message.reply_text(
            "⚠️ Please use HH:MM format (e.g. `09:00`).",
            reply_markup=cancel_button(),
            parse_mode="Markdown"
        )
        return SCH_TIME

    context.user_data["sch_time"] = time_val
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)

    if campaigns:
        await update.message.reply_text(
            "Step 3/3: *Pick a campaign* to run at this time:",
            reply_markup=schedule_campaign_picker(campaigns),
            parse_mode="Markdown"
        )
        return SCH_CAMP_PICK

    # No campaigns yet — fall back to free text
    await update.message.reply_text(
        "Step 3/3: Enter the *action* this schedule should trigger:\n\n"
        "_(No campaigns yet — you can also type a campaign name once you create one)_",
        reply_markup=cancel_button(),
        parse_mode="Markdown"
    )
    return SCH_ACTION


async def sch_pick_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User tapped a campaign from the picker."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.replace("sch_pick_camp_", ""))
    user_id = update.effective_user.id
    campaigns = get_campaigns(user_id)
    if index >= len(campaigns):
        await query.answer("Campaign not found.", show_alert=True)
        return SCH_CAMP_PICK

    camp = campaigns[index]
    campaign_name = camp.get("name", f"Campaign {index+1}")
    context.user_data["sch_action"] = campaign_name
    # Store stable ID so the schedule resolves correctly even after reordering/deleting
    context.user_data["sch_campaign_id"] = camp.get("id")
    return await _ask_days(update, context, via_query=True)


async def sch_get_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sch_action"] = update.message.text.strip()
    return await _ask_days(update, context, via_query=False)


async def _ask_days(update: Update, context: ContextTypes.DEFAULT_TYPE, via_query: bool) -> int:
    """Ask user to pick days of week for the schedule."""
    context.user_data.setdefault("sch_days_selected", list(range(7)))  # all days by default
    kb = days_of_week_picker(context.user_data["sch_days_selected"])
    text = (
        "📆 *Days of Week*\n\n"
        "Choose which days this schedule runs.\n"
        "By default it runs every day.\n"
        "Tap days to toggle them, then press ✅ Done."
    )
    if via_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    return SCH_DAYS


async def sch_days_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Toggle a single day in the selection."""
    query = update.callback_query
    await query.answer()
    day = int(query.data.replace("sch_days_toggle_", ""))
    selected = context.user_data.setdefault("sch_days_selected", list(range(7)))
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    context.user_data["sch_days_selected"] = selected
    await query.edit_message_reply_markup(reply_markup=days_of_week_picker(selected))
    return SCH_DAYS


async def sch_days_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Select all days."""
    query = update.callback_query
    await query.answer()
    context.user_data["sch_days_selected"] = list(range(7))
    await query.edit_message_reply_markup(reply_markup=days_of_week_picker(list(range(7))))
    return SCH_DAYS


async def sch_days_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Proceed to jitter step."""
    query = update.callback_query
    await query.answer()
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("0 min (exact)",  callback_data="sch_jitter_0")],
        [InlineKeyboardButton("±5 min",          callback_data="sch_jitter_5"),
         InlineKeyboardButton("±10 min",          callback_data="sch_jitter_10")],
        [InlineKeyboardButton("±15 min",          callback_data="sch_jitter_15"),
         InlineKeyboardButton("±30 min",          callback_data="sch_jitter_30")],
    ])
    await query.edit_message_text(
        "🎲 *Random Jitter*\n\n"
        "Add a random delay so all accounts don't fire at the exact same second.\n\n"
        "Choose the jitter window:",
        reply_markup=kb,
        parse_mode="Markdown",
    )
    return SCH_JITTER


async def sch_jitter_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive jitter selection and finish schedule creation."""
    query = update.callback_query
    await query.answer()
    jitter = int(query.data.replace("sch_jitter_", ""))
    context.user_data["sch_jitter"] = jitter
    return await _finish_schedule(update, context, via_query=True)


async def _finish_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, via_query: bool) -> int:
    from datetime import datetime
    from storage import get_settings
    action = context.user_data.get("sch_action", "")
    name = context.user_data.get("sch_name", "Unnamed")
    time_val = context.user_data.get("sch_time", "N/A")
    campaign_id = context.user_data.get("sch_campaign_id")
    days = context.user_data.get("sch_days_selected", list(range(7)))
    jitter = context.user_data.get("sch_jitter", 0)
    user_id = update.effective_user.id

    tz_str = get_settings(user_id).get("timezone", "UTC")
    tz_display = tz_str.split("/")[-1].replace("_", " ")

    _DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days_str = "Every day" if len(days) == 7 else ", ".join(_DAY_NAMES[d] for d in sorted(days))

    schedule = {
        "name": name,
        "time": time_val,
        "action": action,
        "campaign_id": campaign_id,
        "days_of_week": sorted(days),
        "jitter_minutes": jitter,
        "one_shot": False,
        "enabled": True,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    add_schedule(user_id, schedule)

    text = (
        "✅ *Schedule Created!*\n\n"
        f"📌 Name: {name}\n"
        f"🕐 Time: {time_val} ({tz_display})\n"
        f"📆 Days: {days_str}\n"
        f"🎲 Jitter: {'±' + str(jitter) + 'm' if jitter else 'None'}\n"
        f"⚡ Campaign: {action}"
    )

    for key in ["sch_name", "sch_time", "sch_action", "sch_campaign_id",
                "sch_days_selected", "sch_jitter"]:
        context.user_data.pop(key, None)

    from handlers.start import start_handler

    if via_query:
        query = update.callback_query
        await query.edit_message_text(text, parse_mode="Markdown")
        # Show main menu
        class _FakeUpdate:
            callback_query = query
            effective_user = update.effective_user
            message = None
        await start_handler(_FakeUpdate(), context)
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

        class FakeQuery:
            async def answer(self): pass
            async def edit_message_text(self, *a, **kw):
                await update.message.reply_text(*a, **kw)

        update.callback_query = FakeQuery()
        await start_handler(update, context)

    return ConversationHandler.END


async def schedule_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    for key in ["sch_name", "sch_time", "sch_action"]:
        context.user_data.pop(key, None)
    from handlers.start import start_handler
    await start_handler(update, context)
    return ConversationHandler.END
