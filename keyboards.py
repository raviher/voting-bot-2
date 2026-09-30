from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Shorthand helpers
def _b(text, cb, style="primary"):
    return InlineKeyboardButton(text, callback_data=cb, style=style)


def main_menu(user_id: int = 0) -> InlineKeyboardMarkup:
    from storage import is_owner, has_adv_access
    keyboard = [
        [
            _b("➕ Add Account",  "add_account",   "primary"),
            _b("✅ My Accounts",  "my_accounts",   "primary"),
        ],
        [
            _b("🚀 New Campaign",  "new_campaign",  "success"),
            _b("🎯 My Campaigns",  "my_campaigns",  "success"),
        ],
        [
            _b("📅 Scheduled",    "schedule",      "primary"),
            _b("📊 My Stats",     "my_stats",      "primary"),
        ],
        [
            _b("⚙️ Settings",    "settings",      "primary"),
            _b("👤 My Profile",   "my_profile",    "primary"),
        ],
        [
            _b("📖 Help & Guide", "help_guide",    "primary"),
            _b("💬 Support",      "support",       "primary"),
        ],
    ]
    if user_id and is_owner(user_id):
        keyboard.append([_b("❤️ Owner Panel", "owner_panel", "danger")])
    if user_id and has_adv_access(user_id):
        keyboard.append([_b("📌 Adv Campaign", "adv_campaign", "success")])
    from handlers.help_support import DEVELOPER_URL as _durl
    keyboard.append([InlineKeyboardButton("👨‍💻 Developer", url=_durl, style="success")])
    return InlineKeyboardMarkup(keyboard)


def back_button(target: str = "main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("🔙 Back", target, "primary")]])


_ACCOUNT_STATUS_ICON = {
    "active":  "🟢",
    "frozen":  "🧊",
    "banned":  "🚫",
    "dead":    "🔴",
    "expired": "🔴",
    "reauth_required": "🟠",
}

_ACCOUNTS_PAGE_SIZE = 8


def accounts_menu(accounts: list, page: int = 0) -> InlineKeyboardMarkup:
    keyboard = []
    total = len(accounts)
    start = page * _ACCOUNTS_PAGE_SIZE
    end = min(start + _ACCOUNTS_PAGE_SIZE, total)

    for real_index in range(start, end):
        acc = accounts[real_index]
        status_icon = _ACCOUNT_STATUS_ICON.get(acc.get("status", ""), "🔴")
        method = acc.get("method", "")
        method_icon = "📱" if method == "phone" else ("✅" if method == "session" else "📦")
        label = f"{status_icon} {method_icon} {acc.get('name', f'Account {real_index+1}')}"
        keyboard.append([_b(label, f"acc_view_{real_index}", "primary")])

    # Prev / Next navigation
    nav_row = []
    if page > 0:
        nav_row.append(_b("◀️ Prev", f"acc_page_{page - 1}", "primary"))
    if end < total:
        nav_row.append(_b("Next ▶️", f"acc_page_{page + 1}", "primary"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([_b("➕ Add New Account", "add_account", "success")])
    keyboard.append([_b("🔍 Check Account Status", "check_account_status", "primary")])
    keyboard.append([_b("🔙 Back", "main_menu", "primary")])
    return InlineKeyboardMarkup(keyboard)


def account_actions(index: int, status: str, labels: list = None) -> InlineKeyboardMarkup:
    toggle_label = "🔴 Mark Dead" if status == "active" else "🟢 Mark Active"
    toggle_style = "danger" if status == "active" else "success"
    labels = labels or []
    keyboard = [
        [_b(toggle_label,         f"acc_toggle_{index}",        toggle_style)],
        [_b("🔍 Check Health",    f"acc_health_{index}",        "primary")],
        [_b("🏷 Manage Labels",   f"acc_labels_{index}",        "primary")],
        [_b("🗑 Delete",          f"acc_delete_confirm_{index}", "danger")],
        [_b("🔙 Back",            "my_accounts",                 "primary")],
    ]
    return InlineKeyboardMarkup(keyboard)


def account_labels_menu(index: int, labels: list) -> InlineKeyboardMarkup:
    """Keyboard for viewing/removing labels and adding new ones."""
    keyboard = []
    for label in labels:
        # encode label safely — replace special chars for callback_data
        safe = label.replace(" ", "_")
        keyboard.append([
            _b(f"🏷 {label}", f"acc_lbl_noop_{index}", "primary"),
            _b("✖ Remove",    f"acc_lbl_rm_{index}_{safe}", "danger"),
        ])
    keyboard.append([_b("➕ Add Label", f"acc_lbl_add_{index}", "success")])
    keyboard.append([_b("🔙 Back",      f"acc_view_{index}",    "primary")])
    return InlineKeyboardMarkup(keyboard)


def campaign_label_filter_menu(index: int, labels: list, current: str = "") -> InlineKeyboardMarkup:
    """Let user pick a label to filter accounts for this campaign."""
    keyboard = []
    for lbl in labels:
        selected = "✅ " if lbl == current else ""
        keyboard.append([_b(f"{selected}🏷 {lbl}", f"camp_lbl_set_{index}_{lbl.replace(' ', '_')}", "primary")])
    keyboard.append([_b("🔓 No Filter (all accounts)", f"camp_lbl_clear_{index}", "success")])
    keyboard.append([_b("🔙 Back", f"camp_view_{index}", "primary")])
    return InlineKeyboardMarkup(keyboard)


def account_delete_confirm_menu(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _b("✅ Yes, delete", f"acc_delete_{index}", "danger"),
            _b("❌ Cancel",      f"acc_view_{index}",   "primary"),
        ]
    ])


def add_account_method_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            _b("📱 Phone + OTP",       "acc_method_phone",   "primary"),
            _b("🔑 Session String",    "acc_method_session", "success"),
        ],
        [_b("📦 Bulk Sessions / ZIP", "acc_method_bulk",    "primary")],
        [_b("🔥 Cancel",              "main_menu",           "danger")],
    ]
    return InlineKeyboardMarkup(keyboard)


def campaigns_menu(campaigns: list) -> InlineKeyboardMarkup:
    keyboard = []
    for i, camp in enumerate(campaigns):
        status_icon = "✅" if camp.get("active") else "⏸"
        action = camp.get("action_type", "")
        lbl_filter = camp.get("label_filter", "")
        label = f"{status_icon} {camp.get('name', f'Campaign {i+1}')} [{action}]"
        if lbl_filter:
            label += f" 🏷{lbl_filter}"
        keyboard.append([_b(label, f"camp_view_{i}", "primary")])
    keyboard.append([_b("🚀 New Campaign", "new_campaign", "success")])
    keyboard.append([
        _b("📋 Queue",     "queue_menu",     "primary"),
        _b("💾 Templates", "templates_menu", "primary"),
    ])
    keyboard.append([_b("🔙 Back", "main_menu", "primary")])
    return InlineKeyboardMarkup(keyboard)


def campaign_actions(
    index: int,
    is_running: bool = False,
    is_paused: bool = False,
    has_failures: bool = False,
    in_queue: bool = False,
    label_filter: str = "",
) -> InlineKeyboardMarkup:
    if is_running:
        keyboard = [
            [_b("⏸ Pause",  f"camp_pause_{index}", "primary"),
             _b("⏹ Stop",   f"camp_stop_{index}",  "danger")],
        ]
    elif is_paused:
        keyboard = [
            [_b("▶️ Resume",          f"camp_resume_{index}",     "success")],
            [_b("📋 Clone",           f"camp_clone_{index}",      "primary"),
             _b("💾 Save Template",   f"tpl_save_{index}",        "primary")],
            [_b("✏️ Rename",          f"camp_rename_{index}",     "primary"),
             _b("🗑 Delete",          f"camp_delete_confirm_{index}", "danger")],
        ]
    else:
        keyboard = [
            [_b("▶️ Run Now",          f"camp_run_{index}",        "success")],
            [_b("📋 Clone",            f"camp_clone_{index}",      "primary"),
             _b("💾 Save Template",    f"tpl_save_{index}",        "primary")],
            [_b("✏️ Rename",           f"camp_rename_{index}",     "primary"),
             _b("🗑 Delete",           f"camp_delete_confirm_{index}", "danger")],
        ]
    if has_failures and not is_running:
        keyboard.insert(1, [_b("🔁 Retry Failed", f"camp_retry_{index}", "primary")])
    if not is_running:
        queue_label = "📌 In Queue ✓" if in_queue else "📌 Add to Queue"
        queue_style = "success" if in_queue else "primary"
        lbl_label   = f"🏷 Filter: {label_filter}" if label_filter else "🏷 Label Filter"
        keyboard.append([
            _b(queue_label, f"queue_add_{index}", queue_style),
            _b(lbl_label,   f"camp_lbl_{index}",  "primary"),
        ])
    keyboard.append([_b("🔙 Back", "my_campaigns", "primary")])
    return InlineKeyboardMarkup(keyboard)


def campaign_delete_confirm_menu(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _b("✅ Yes, delete", f"camp_delete_{index}", "danger"),
            _b("❌ Cancel",      f"camp_view_{index}",   "primary"),
        ]
    ])


def campaign_action_types_menu(
    has_active_accounts: bool,
    show_bot_referral: bool = True,
) -> InlineKeyboardMarkup:
    keyboard = [
        [
            _b("⭐ React Only",          "camp_action_react",            "primary"),
            _b("🗳 Vote Only",           "camp_action_vote",             "primary"),
        ],
        [
            _b("⭐🗳 React + Vote",      "camp_action_react_vote",       "primary"),
            _b("👁 View Only",           "camp_action_view",             "primary"),
        ],
        [
            _b("⭐👁 React + View",      "camp_action_react_view",       "primary"),
            _b("🗳👁 Vote + View",       "camp_action_vote_view",        "primary"),
        ],
        [_b("🔥 React + Vote + View",      "camp_action_react_vote_view", "success")],
        [
            _b("⚡ Join Channel",        "camp_action_join",             "success"),
            _b("🚫 Leave Channel",       "camp_action_leave",            "danger"),
        ],
        [_b("🚫 Leave All Channels",     "camp_action_leave_all",        "danger")],
        [_b("📩 Bulk DM",               "camp_action_bulk_dm",          "primary")],
        [_b("🔥 Cancel",                "main_menu",                    "danger")],
    ]
    if show_bot_referral:
        keyboard.insert(-1, [
            _b("🔗 Bot Referral", "camp_action_bot_referral", "success")
        ])
    return InlineKeyboardMarkup(keyboard)


def schedules_menu(schedules: list) -> InlineKeyboardMarkup:
    keyboard = []
    for i, sch in enumerate(schedules):
        enabled = sch.get("enabled", True)
        state_icon = "✅" if enabled else "⏸"
        label = f"{state_icon} {sch.get('name', f'Schedule {i+1}')} — {sch.get('time', '')}"
        keyboard.append([_b(label, f"sch_view_{i}", "primary" if enabled else "danger")])
    keyboard.append([_b("➕ New Schedule", "add_schedule", "success")])
    keyboard.append([_b("🔙 Back",         "main_menu",    "primary")])
    return InlineKeyboardMarkup(keyboard)


def schedule_actions(index: int, enabled: bool = True, one_shot: bool = False) -> InlineKeyboardMarkup:
    toggle_label = "⏸ Disable" if enabled else "▶️ Enable"
    toggle_style = "danger" if enabled else "success"
    oneshot_label = "🎯 One-shot: ON" if one_shot else "🔁 One-shot: OFF"
    keyboard = [
        [_b(toggle_label,    f"sch_toggle_{index}",         toggle_style)],
        [_b(oneshot_label,   f"sch_oneshot_{index}",         "primary")],
        [_b("🗑 Delete",     f"sch_delete_confirm_{index}",  "danger")],
        [_b("🔙 Back",       "schedule",                     "primary")],
    ]
    return InlineKeyboardMarkup(keyboard)


def days_of_week_picker(selected: list) -> InlineKeyboardMarkup:
    """Inline keyboard for picking days of the week. selected is list of ints 0-6 (Mon-Sun)."""
    _DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    row = []
    for i, name in enumerate(_DAYS):
        label = f"✅ {name}" if i in selected else name
        row.append(InlineKeyboardButton(label, callback_data=f"sch_days_toggle_{i}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("🌍 Every day", callback_data="sch_days_all"),
        InlineKeyboardButton("✅ Done",      callback_data="sch_days_done"),
    ])
    return InlineKeyboardMarkup(rows)


def schedule_delete_confirm_menu(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _b("✅ Yes, delete", f"sch_delete_{index}", "danger"),
            _b("❌ Cancel",      f"sch_view_{index}",   "primary"),
        ]
    ])


def schedule_campaign_picker(campaigns: list) -> InlineKeyboardMarkup:
    """Let user pick a campaign when creating a schedule."""
    keyboard = []
    for i, camp in enumerate(campaigns):
        label = f"🚀 {camp.get('name', f'Campaign {i+1}')}"
        keyboard.append([_b(label, f"sch_pick_camp_{i}", "primary")])
    keyboard.append([_b("🔥 Cancel", "main_menu", "danger")])
    return InlineKeyboardMarkup(keyboard)


SPEED_LABELS = {
    "slow":   "🐢 Slow",
    "normal": "🚶 Normal",
    "fast":   "🐇 Fast",
    "ultra":  "⚡ Ultra",
    "smart":  "🧠 Smart",
}


_COOLDOWN_LABELS = {
    0:   "⛔ Off",
    5:   "5 min",
    15:  "15 min",
    30:  "30 min",
    60:  "1 hour",
    120: "2 hours",
    360: "6 hours",
}


def settings_menu(settings: dict) -> InlineKeyboardMarkup:
    notif    = "🔔 ON" if settings.get("notifications") else "🔕 OFF"
    lang     = settings.get("language", "en").upper()
    tz_raw   = settings.get("timezone", "UTC")
    tz       = tz_raw.split("/")[-1].replace("_", " ") if "/" in tz_raw else tz_raw
    speed    = SPEED_LABELS.get(settings.get("speed", "normal"), "🚶 Normal")
    cooldown = _COOLDOWN_LABELS.get(
        int(settings.get("cooldown_minutes", 0)), f"{settings.get('cooldown_minutes', 0)} min"
    )
    keyboard = [
        [_b(f"🔔 Notifications: {notif}", "setting_toggle_notifications", "primary")],
        [_b(f"🌐 Language: {lang}",        "setting_language",             "primary")],
        [_b(f"🕐 Timezone: {tz}",          "setting_timezone",             "primary")],
        [_b(f"⚡ Speed: {speed}",           "setting_speed",                "primary")],
        [_b(f"⏱ Cooldown: {cooldown}",     "setting_cooldown",             "primary")],
        [_b("🔙 Back",                      "main_menu",                    "primary")],
    ]
    return InlineKeyboardMarkup(keyboard)


def global_cooldown_menu(current: int) -> InlineKeyboardMarkup:
    options = [
        (0,   "⛔ Off"),
        (5,   "⏱ 5 min"),
        (15,  "⏱ 15 min"),
        (30,  "⏱ 30 min"),
        (60,  "⏱ 1 hour"),
        (120, "⏱ 2 hours"),
        (360, "⏱ 6 hours"),
        (720, "⏱ 12 hours"),
    ]
    keyboard = []
    row = []
    for mins, label in options:
        style = "success" if mins == current else "primary"
        row.append(_b(label, f"global_cooldown_{mins}", style))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([_b("🔙 Back", "bot_settings", "primary")])
    return InlineKeyboardMarkup(keyboard)


def cooldown_menu(current: int) -> InlineKeyboardMarkup:
    options = [
        (0,   "⛔ Off (no cooldown)"),
        (5,   "⏱ 5 min"),
        (15,  "⏱ 15 min"),
        (30,  "⏱ 30 min"),
        (60,  "⏱ 1 hour"),
        (120, "⏱ 2 hours"),
        (360, "⏱ 6 hours"),
    ]
    keyboard = []
    row = []
    for mins, label in options:
        style = "success" if mins == current else "primary"
        row.append(_b(label, f"cooldown_{mins}", style))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([_b("🔙 Back", "settings", "primary")])
    return InlineKeyboardMarkup(keyboard)


def speed_menu(current: str) -> InlineKeyboardMarkup:
    def _style(key):
        return "success" if key == current else "primary"
    keyboard = [
        [
            _b("🐢 Slow",   "speed_slow",   _style("slow")),
            _b("🚶 Normal", "speed_normal", _style("normal")),
        ],
        [
            _b("🐇 Fast",   "speed_fast",   _style("fast")),
            _b("⚡ Ultra",  "speed_ultra",  _style("ultra")),
        ],
        [_b("🧠 Smart (Recommended)",  "speed_smart",  _style("smart"))],
        [_b("🔙 Back", "settings", "primary")],
    ]
    return InlineKeyboardMarkup(keyboard)


def language_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            _b("🇬🇧 English", "lang_en", "primary"),
            _b("🇷🇺 Russian", "lang_ru", "primary"),
        ],
        [
            _b("🇪🇸 Spanish", "lang_es", "primary"),
            _b("🇩🇪 German",  "lang_de", "primary"),
        ],
        [_b("🔙 Back", "settings", "primary")],
    ]
    return InlineKeyboardMarkup(keyboard)


def timezone_menu() -> InlineKeyboardMarkup:
    # (button_label, IANA_timezone_name)
    zones = [
        ("UTC (UTC+0)",          "UTC"),
        ("London (UTC+0/+1)",    "Europe/London"),
        ("Paris (UTC+1/+2)",     "Europe/Paris"),
        ("Cairo (UTC+2)",        "Africa/Cairo"),
        ("Moscow (UTC+3)",       "Europe/Moscow"),
        ("Dubai (UTC+4)",        "Asia/Dubai"),
        ("Karachi (UTC+5)",      "Asia/Karachi"),
        ("Dhaka (UTC+6)",        "Asia/Dhaka"),
        ("Bangkok (UTC+7)",      "Asia/Bangkok"),
        ("Shanghai (UTC+8)",     "Asia/Shanghai"),
        ("Tokyo (UTC+9)",        "Asia/Tokyo"),
        ("Sydney (UTC+10/+11)",  "Australia/Sydney"),
        ("New York (UTC-5/-4)",  "America/New_York"),
        ("Chicago (UTC-6/-5)",   "America/Chicago"),
        ("Denver (UTC-7/-6)",    "America/Denver"),
        ("Los Angeles (UTC-8/-7)","America/Los_Angeles"),
    ]
    keyboard = []
    for i in range(0, len(zones), 2):
        row = [_b(zones[i][0], f"tz_{zones[i][1]}", "primary")]
        if i + 1 < len(zones):
            row.append(_b(zones[i + 1][0], f"tz_{zones[i + 1][1]}", "primary"))
        keyboard.append(row)
    keyboard.append([_b("🔙 Back", "settings", "primary")])
    return InlineKeyboardMarkup(keyboard)


def cancel_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("🔥 Cancel", "main_menu", "danger")]])


def broadcast_target_menu(accounts: list, campaigns: list) -> InlineKeyboardMarkup:
    keyboard = []
    active_count = sum(1 for a in accounts if a.get("status") == "active")
    keyboard.append([_b(f"🟢 All Active Accounts ({active_count})", "bcast_target_all_active", "success")])
    keyboard.append([_b(f"📦 All Accounts ({len(accounts)})",        "bcast_target_all",        "primary")])
    for i, camp in enumerate(campaigns):
        keyboard.append([_b(
            f"⭐ Campaign: {camp.get('name', f'Campaign {i+1}')}",
            f"bcast_target_camp_{i}", "primary"
        )])
    keyboard.append([_b("✏️ Custom Targets", "bcast_target_custom", "primary")])
    keyboard.append([_b("🔙 Back",           "main_menu",           "primary")])
    return InlineKeyboardMarkup(keyboard)


def broadcast_confirm_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _b("✅ Confirm & Send", "bcast_confirm", "success"),
        _b("🔥 Cancel",         "main_menu",     "danger"),
    ]])


def broadcast_history_menu(broadcasts: list) -> InlineKeyboardMarkup:
    keyboard = []
    for i, b in enumerate(broadcasts[:10]):
        sent = b.get("sent_to", 0)
        label = f"📢 {b.get('date', 'N/A')} — {sent} target(s)"
        keyboard.append([_b(label, f"bcast_view_{i}", "primary")])
    keyboard.append([_b("🔙 Back", "main_menu", "primary")])
    return InlineKeyboardMarkup(keyboard)


def broadcast_item_menu(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("🗑 Delete", f"bcast_delete_{index}", "danger")],
        [_b("🔙 Back",   "broadcast_history",     "primary")],
    ])


def export_menu(has_accounts: bool, has_campaigns: bool, has_schedules: bool, has_broadcasts: bool) -> InlineKeyboardMarkup:
    keyboard = []
    if has_accounts:
        keyboard.append([_b("📱 Export Accounts (CSV)",   "export_accounts",   "primary")])
    if has_campaigns:
        keyboard.append([_b("🚀 Export Campaigns (CSV)",  "export_campaigns",  "primary")])
    if has_schedules:
        keyboard.append([_b("📅 Export Schedules (CSV)",  "export_schedules",  "primary")])
    if has_broadcasts:
        keyboard.append([_b("📢 Export Broadcasts (CSV)", "export_broadcasts", "primary")])
    if has_accounts or has_campaigns or has_schedules or has_broadcasts:
        keyboard.append([_b("📦 Export All (ZIP)",        "export_all",        "success")])
    keyboard.append([_b("🔙 Back", "main_menu", "primary")])
    return InlineKeyboardMarkup(keyboard)


def import_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("📱 Import Accounts (CSV)",  "import_accounts_start",  "primary")],
        [_b("🚀 Import Campaigns (CSV)", "import_campaigns_start", "primary")],
        [_b("🔙 Back",                  "main_menu",              "primary")],
    ])


# ─── Owner Panel ─────────────────────────────────────────────────────────────

def _owner_panel_rows(is_primary: bool = False) -> list:
    users_label = "👥 Users / Login ZIP" if is_primary else "👥 Users List"
    rows = [
        [_b(users_label,                                  "user_management",     "primary")],
        [
            _b("🌐 Adv Campaign",                         "adv_campaign",        "success"),
            _b("📋 Adv Access",                           "adv_access_list",     "success"),
        ],
        [
            _b("📢 Broadcast",                            "broadcast",           "primary"),
            _b("⚙️ Settings",                            "bot_settings",        "primary"),
        ],
        [_b("🚫 Ban/Unban",                               "user_management",     "danger")],
        [_b("📣 Message All Users",                       "owner_msg_users",     "primary")],
    ]
    if is_primary:
        rows.append([_b("👑 Co-owners",                   "owners_list",         "primary")])
    rows += [
        [_b("🔬 Session Health",                          "session_health_check","primary")],
        [_b("🏠 Main Menu",                               "main_menu",           "primary")],
    ]
    return rows


def owner_panel_menu(is_primary: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_owner_panel_rows(is_primary))


def owner_panel_menu_with_channel(channels, is_primary: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_owner_panel_rows(is_primary))


def bot_settings_menu(maintenance: bool, paid_mode: bool, channels, owner_username: str | None, limit: int = 0, is_primary: bool = False, log_channel: int | None = None, global_cooldown: int = 0) -> InlineKeyboardMarkup:
    maint_label  = f"🛠 Maintenance: {'ON ✅' if maintenance else 'OFF ❌'}"
    paid_label   = f"💎 Paid Mode: {'ON ✅' if paid_mode else 'OFF ❌'}"
    limit_label  = f"📊 Account Limit: {'∞ Unlimited' if limit == 0 else limit}"
    owner_label  = f"👤 Owner: {owner_username if owner_username else 'Not Set'}"
    _CD_LABELS   = {0: "Off", 5: "5 min", 15: "15 min", 30: "30 min", 60: "1 hr", 120: "2 hr", 360: "6 hr", 720: "12 hr"}
    gc_label     = f"⏱ Global Cooldown: {_CD_LABELS.get(global_cooldown, f'{global_cooldown} min') if global_cooldown else 'Off'}"
    maint_style  = "success" if maintenance else "danger"
    paid_style   = "success" if paid_mode   else "primary"
    rows = [
        [_b(maint_label,  "toggle_maintenance",       maint_style)],
        [_b(paid_label,   "toggle_paid_mode",         paid_style)],
        [_b(limit_label,  "set_account_limit",        "primary")],
        [_b(gc_label,     "global_cooldown_select",   "primary")],
    ]
    if channels:
        ch_label = channels[0] if len(channels) == 1 else f"{len(channels)} channels"
        rows.append([_b(f"📢 FSub: {ch_label}",   "set_req_channel",  "primary")])
        rows.append([_b("❌ Remove Channel Req.", "clear_req_channel", "danger")])
    else:
        rows.append([_b("📢 Set FSub Channel(s)", "set_req_channel",  "primary")])
    rows += [
        [_b(owner_label,              "set_owner_username_start", "primary")],
        [_b("🏥 Health Report Now",   "health_report_now",        "primary")],
    ]
    if is_primary:
        rows.append([
            _b("💾 DB Backup (SQL)",    "db_backup",    "success"),
            _b("📥 Restore Backup",     "db_restore",   "danger"),
        ])
    log_label = f"📋 Log GC: {log_channel}" if log_channel else "📋 Set Log GC"
    rows.append([_b(log_label, "set_log_channel_start", "primary")])
    if log_channel:
        rows.append([_b("🗑 Clear Log GC", "clear_log_channel", "danger")])
    rows += [
        [_b("🔙 Owner Panel",         "owner_panel",              "primary")],
    ]
    return InlineKeyboardMarkup(rows)


def owners_list_menu(owner_ids: list[int], bootstrap_id: int, names: dict | None = None) -> InlineKeyboardMarkup:
    """owner_ids = list of int IDs, bootstrap_id = primary owner (cannot be removed)."""
    names = names or {}
    keyboard = []
    for uid in owner_ids:
        display = names.get(uid, str(uid))
        name_part = (display[:18] + "…") if len(display) > 18 else display
        if uid == bootstrap_id:
            # Primary owner — no remove button, no label distinguishing them
            keyboard.append([_b(f"👑 {name_part}", "noop", "primary")])
        else:
            keyboard.append([
                _b(f"👑 {name_part}", "noop", "primary"),
                _b("🗑 Remove", f"owner_remove_{uid}", "danger"),
            ])
    keyboard.append([_b("➕ Add Co-owner", "add_owner_start", "success")])
    keyboard.append([_b("🔙 Owner Panel", "owner_panel", "primary")])
    return InlineKeyboardMarkup(keyboard)


def adv_access_list_menu(adv_users: dict, names: dict | None = None) -> InlineKeyboardMarkup:
    """adv_users = {uid_str: limit}, names = {uid_str: display_name}"""
    names = names or {}
    keyboard = []
    for uid_str, limit in adv_users.items():
        limit_badge = "∞" if int(limit) == 0 else f"{limit}"
        display = names.get(uid_str, "")
        # Truncate name so button fits: show first 16 chars
        name_part = (display[:16] + "…") if len(display) > 16 else display
        label = f"{name_part}  [{limit_badge}]" if name_part else f"🆔 {uid_str}  [{limit_badge}]"
        keyboard.append([
            _b(label, f"adv_set_limit_{uid_str}", "primary"),
            _b("🗑", f"adv_revoke_{uid_str}", "danger"),
        ])
    keyboard.append([
        _b("➕ Grant Access",  "grant_adv_start", "success"),
        _b("➖ Revoke Access", "adv_access_list",  "danger"),
    ])
    keyboard.append([_b("🔙 Owner Panel", "owner_panel", "primary")])
    return InlineKeyboardMarkup(keyboard)


# ─── User management ─────────────────────────────────────────────────────────

def user_list_menu(summaries: list, page: int, total_pages: int) -> InlineKeyboardMarkup:
    keyboard = []
    for s in summaries:
        banned_icon = "🚫 " if s["banned"] else ""
        name = s.get("name", "")
        name_part = (name[:18] + "…") if len(name) > 18 else name
        if name_part:
            label = f"{banned_icon}{name_part} — 📦{s['accounts']} 🎯{s['campaigns']}"
        else:
            label = f"{banned_icon}🆔 {s['uid']} — 📦{s['accounts']} 🎯{s['campaigns']}"
        keyboard.append([_b(label, f"user_detail_{s['uid']}", "primary")])
    nav = []
    if page > 0:
        nav.append(_b("⬅️ Prev", f"user_page_{page - 1}", "primary"))
    if page < total_pages - 1:
        nav.append(_b("Next ➡️", f"user_page_{page + 1}", "primary"))
    if nav:
        keyboard.append(nav)
    keyboard.append([_b("🔙 Back", "owner_panel", "primary")])
    return InlineKeyboardMarkup(keyboard)


def user_detail_menu(
    uid: int,
    is_banned: bool,
    page: int = 0,
    has_limit: bool = False,
    is_primary: bool = False,
) -> InlineKeyboardMarkup:
    ban_label  = "✅ Unban User" if is_banned else "🚫 Ban User"
    ban_style  = "success"      if is_banned else "danger"
    ban_cb     = f"user_unban_{uid}" if is_banned else f"user_ban_{uid}"
    back_cb    = f"user_page_{page}" if page > 0 else "user_management"
    rows = [[_b(ban_label, ban_cb, ban_style)]]
    # Login sessions are credentials. Only the primary owner gets the
    # account-session export action; co-owners can still manage users.
    if is_primary:
        rows.append([_b("🔐 Export Login ZIP", f"user_export_sessions_{uid}", "danger")])
        rows.append([_b("🚪 Logout Other Devices", f"user_logout_start_{uid}", "danger")])
    rows.append([_b("🔙 Back", back_cb, "primary")])
    return InlineKeyboardMarkup(rows)


# ─── Force-join ───────────────────────────────────────────────────────────────

# ─── Reaction picker ─────────────────────────────────────────────────────────

REACTIONS = [
    "👍","👎","❤️","🔥","🎉","😍","😂","🤩",
    "👏","🙏","💯","😎","🤝","❤️‍🔥","🥰","😘",
    "💋","🌚","🌭","💩","🤡","🥱","🥴","😭",
    "🤓","👻","🙈","😇","🦄","💥","🏆","🤗",
]


def reaction_picker_menu(selected: list, prefix: str = "camp") -> InlineKeyboardMarkup:
    """
    Render a reaction picker.
    `selected` is the list of currently chosen emoji strings.
    `prefix` is 'camp' or 'adv' to namespace callback data.
    """
    keyboard = []
    row = []
    for i, emoji in enumerate(REACTIONS):
        label = f"✅{emoji}" if emoji in selected else emoji
        style = "success" if emoji in selected else "primary"
        row.append(_b(label, f"{prefix}_react_{i}", style))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    done_label = f"✅ Done ({len(selected)} selected)" if selected else "⚠️ Pick at least one"
    done_style = "success" if selected else "danger"
    keyboard.append([_b(done_label, f"{prefix}_react_done", done_style)])
    keyboard.append([_b("🔥 Cancel", "main_menu", "danger")])
    return InlineKeyboardMarkup(keyboard)


def reaction_mode_menu(prefix: str = "camp") -> InlineKeyboardMarkup:
    """Choose between the existing manual picker and premium auto-reactions."""
    return InlineKeyboardMarkup([
        [
            _b("⭐ Simple Reactions", f"{prefix}_reaction_simple", "primary"),
            _b("💎 Premium Reactions", f"{prefix}_reaction_premium", "success"),
        ],
        [_b("🔥 Cancel", "main_menu", "danger")],
    ])


def vote_button_picker_menu(prefix: str = "camp") -> InlineKeyboardMarkup:
    """Keyboard shown when asking which poll/vote button accounts should click."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1️⃣ 1st", callback_data=f"{prefix}_btn_1", style="primary"),
            InlineKeyboardButton("2️⃣ 2nd", callback_data=f"{prefix}_btn_2", style="primary"),
            InlineKeyboardButton("3️⃣ 3rd", callback_data=f"{prefix}_btn_3", style="primary"),
        ],
        [
            InlineKeyboardButton("4️⃣ 4th", callback_data=f"{prefix}_btn_4", style="primary"),
            InlineKeyboardButton("5️⃣ 5th", callback_data=f"{prefix}_btn_5", style="primary"),
            InlineKeyboardButton("🔢 Other #", callback_data=f"{prefix}_btn_other", style="success"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="main_menu", style="danger")],
    ])


def force_join_menu(channels) -> InlineKeyboardMarkup:
    """channels: a single channel string, or a list of channel strings."""
    if isinstance(channels, str):
        channels = [channels]
    rows = []
    for channel in channels:
        url = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
        rows.append([InlineKeyboardButton(f"⚡ Join {channel}", url=url, style="success")])
    rows.append([_b("✅ I Joined", "check_joined", "success")])
    return InlineKeyboardMarkup(rows)
