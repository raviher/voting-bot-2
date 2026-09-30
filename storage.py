"""
storage.py — PostgreSQL-backed data store.

All public function signatures are identical to the old JSON-file version.
Handlers need zero changes.
"""

import os
import json
import base64 as _b64
import logging
import time as _time
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

# ── Connection pool ────────────────────────────────────────────────────────────
_DATABASE_URL = os.environ["DATABASE_URL"]
_pool = ThreadedConnectionPool(1, 20, _DATABASE_URL)


class _DB:
    """Context manager: borrow a connection, auto-commit or rollback."""
    def __enter__(self):
        self.conn = _pool.getconn()
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.cur.close()
        _pool.putconn(self.conn)
        return False


# ── Schema bootstrap (runs once at import) ─────────────────────────────────────
def _init_schema() -> None:
    with _DB() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id BIGINT PRIMARY KEY,
                data    JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            CREATE TABLE IF NOT EXISTS bot_settings (
                key   TEXT PRIMARY KEY,
                value JSONB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id      SERIAL PRIMARY KEY,
                ts      TEXT NOT NULL,
                user_id BIGINT,
                action  TEXT NOT NULL,
                details TEXT DEFAULT ''
            );
        """)

_init_schema()

# ── OWNER_ID ──────────────────────────────────────────────────────────────────
_env_owner = os.environ.get("OWNER_ID", "").strip()
if _env_owner and _env_owner.isdigit():
    OWNER_ID = int(_env_owner)
else:
    OWNER_ID = int.from_bytes(_b64.b64decode(b"AWA0Lx8="), "big")

# ── Default user structure ────────────────────────────────────────────────────
_USER_DEFAULT: dict[str, Any] = {
    "accounts":   [],
    "campaigns":  [],
    "schedules":  [],
    "profile":    {},
    "settings": {
        "notifications": True,
        "language":      "en",
        "timezone":      "UTC",
        "speed":         "smart",
    },
    "broadcasts": [],
    "queue":      [],
    "templates":  [],
}


# ── Low-level user helpers ─────────────────────────────────────────────────────

def _get_user_row(user_id: int) -> dict[str, Any]:
    """Return the user's data dict, creating a default row if missing."""
    with _DB() as cur:
        cur.execute("SELECT data FROM user_data WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            return dict(row["data"])
        default = json.loads(json.dumps(_USER_DEFAULT))
        cur.execute(
            "INSERT INTO user_data (user_id, data) VALUES (%s, %s::jsonb) "
            "ON CONFLICT DO NOTHING",
            (user_id, json.dumps(default)),
        )
        return default


def _set_user_row(user_id: int, data: dict[str, Any]) -> None:
    with _DB() as cur:
        cur.execute(
            "INSERT INTO user_data (user_id, data) VALUES (%s, %s::jsonb) "
            "ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data",
            (user_id, json.dumps(data)),
        )


# ── Shim kept for the two handlers that call _user_data()/_save() directly ────
def _user_data(user_id: int) -> dict[str, Any]:
    """Return a slim container: {'users': {str(user_id): <user_dict>}}."""
    user = _get_user_row(user_id)
    return {"users": {str(user_id): user}}


def _save(data: dict[str, Any]) -> None:
    """Persist data returned by _user_data()."""
    for uid_str, user_dict in data.get("users", {}).items():
        _set_user_row(int(uid_str), user_dict)


# ── Low-level global-settings helpers ─────────────────────────────────────────

def _get_global() -> dict[str, Any]:
    with _DB() as cur:
        cur.execute("SELECT value FROM bot_settings WHERE key = 'global'")
        row = cur.fetchone()
        return dict(row["value"]) if row else {}


def _set_global(settings: dict[str, Any]) -> None:
    with _DB() as cur:
        cur.execute(
            "INSERT INTO bot_settings (key, value) VALUES ('global', %s::jsonb) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (json.dumps(settings),),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Public API — identical signatures to the old JSON version
# ═══════════════════════════════════════════════════════════════════════════════

def get_user(user_id: int) -> dict[str, Any]:
    return _get_user_row(user_id)


def save_user(user_id: int, user: dict[str, Any]) -> None:
    _set_user_row(user_id, user)


# ── Accounts ──────────────────────────────────────────────────────────────────

def get_accounts(user_id: int) -> list:
    return _get_user_row(user_id).get("accounts", [])


def is_account_duplicate(
    tg_id: int | None = None,
    phone: str | None = None,
    identifier: str | None = None,
) -> bool:
    norm_phone: str | None = None
    if phone:
        p = phone.strip()
        norm_phone = p if p.startswith("+") else "+" + p

    with _DB() as cur:
        cur.execute("SELECT data->'accounts' AS accounts FROM user_data")
        for row in cur.fetchall():
            for acc in (row["accounts"] or []):
                stored_tg = acc.get("tg_id")
                if tg_id and stored_tg:
                    try:
                        if int(stored_tg) == int(tg_id):
                            return True
                    except (TypeError, ValueError):
                        pass
                if norm_phone:
                    stored_phone = (acc.get("phone") or "").strip()
                    if stored_phone and stored_phone == norm_phone:
                        return True
                if identifier and acc.get("identifier") == identifier:
                    return True
    return False


def add_account(user_id: int, account: dict) -> None:
    user = _get_user_row(user_id)
    user.setdefault("accounts", []).append(account)
    _set_user_row(user_id, user)


def update_account_session(
    user_id: int,
    account: dict,
    session_string: str,
) -> bool:
    """Persist the current Pyrogram session for an existing account.

    Pyrogram can update the session after a reconnect or DC migration.  The
    campaign runner uses in-memory clients, so the refreshed string must be
    written back to PostgreSQL before the client is discarded.
    """
    if not isinstance(session_string, str) or len(session_string.strip()) < 20:
        return False

    new_session = session_string.strip()
    old_identifier = account.get("identifier")
    old_phone = account.get("phone")
    old_tg_id = account.get("tg_id")
    user = _get_user_row(user_id)

    for stored in user.get("accounts", []):
        same_tg_id = (
            old_tg_id is not None
            and stored.get("tg_id") is not None
            and str(stored.get("tg_id")) == str(old_tg_id)
        )
        same_identifier = (
            bool(old_identifier)
            and stored.get("identifier") == old_identifier
        )
        same_phone = (
            bool(old_phone)
            and stored.get("phone")
            and str(stored.get("phone")).strip() == str(old_phone).strip()
        )
        if not (same_tg_id or same_identifier or same_phone):
            continue

        # Keep all legacy aliases in sync.  Otherwise the runner could select
        # an older value from ``session`` before reaching ``identifier``.
        keys = {
            key for key in ("identifier", "session", "session_string")
            if key in stored
        }
        keys.add("identifier")
        for key in keys:
            stored[key] = new_session
        _set_user_row(user_id, user)
        return True

    return False


def remove_account(user_id: int, index: int) -> bool:
    user = _get_user_row(user_id)
    accounts = user.get("accounts", [])
    if 0 <= index < len(accounts):
        accounts.pop(index)
        _set_user_row(user_id, user)
        return True
    return False


def toggle_account_status(user_id: int, index: int) -> str | None:
    user = _get_user_row(user_id)
    accounts = user.get("accounts", [])
    if 0 <= index < len(accounts):
        current = accounts[index].get("status", "active")
        accounts[index]["status"] = "dead" if current == "active" else "active"
        _set_user_row(user_id, user)
        return accounts[index]["status"]
    return None


def set_account_status(user_id: int, index: int, status: str) -> bool:
    user = _get_user_row(user_id)
    accounts = user.get("accounts", [])
    if 0 <= index < len(accounts):
        accounts[index]["status"] = status
        _set_user_row(user_id, user)
        return True
    return False


def set_account_throttle(user_id: int, index: int, until_ts: float) -> None:
    user = _get_user_row(user_id)
    accounts = user.get("accounts", [])
    if 0 <= index < len(accounts):
        accounts[index]["throttled_until"] = until_ts
        _set_user_row(user_id, user)


def clear_account_throttle(user_id: int, index: int) -> None:
    user = _get_user_row(user_id)
    accounts = user.get("accounts", [])
    if 0 <= index < len(accounts):
        accounts[index].pop("throttled_until", None)
        _set_user_row(user_id, user)


def add_account_label(user_id: int, acc_index: int, label: str) -> bool:
    label = label.strip().lower()
    if not label or len(label) > 32:
        return False
    user = _get_user_row(user_id)
    accounts = user.get("accounts", [])
    if 0 <= acc_index < len(accounts):
        existing = accounts[acc_index].setdefault("labels", [])
        if label not in existing:
            existing.append(label)
        _set_user_row(user_id, user)
        return True
    return False


def remove_account_label(user_id: int, acc_index: int, label: str) -> bool:
    user = _get_user_row(user_id)
    accounts = user.get("accounts", [])
    if 0 <= acc_index < len(accounts):
        labels = accounts[acc_index].get("labels", [])
        if label in labels:
            labels.remove(label)
        _set_user_row(user_id, user)
        return True
    return False


def get_all_user_labels(user_id: int) -> list[str]:
    labels: set[str] = set()
    for acc in get_accounts(user_id):
        labels.update(acc.get("labels", []))
    return sorted(labels)


# ── Campaigns ─────────────────────────────────────────────────────────────────

def get_campaigns(user_id: int) -> list:
    return _get_user_row(user_id).get("campaigns", [])


def add_campaign(user_id: int, campaign: dict) -> None:
    user = _get_user_row(user_id)
    user.setdefault("campaigns", []).append(campaign)
    _set_user_row(user_id, user)


def remove_campaign(user_id: int, index: int) -> bool:
    user = _get_user_row(user_id)
    campaigns = user.get("campaigns", [])
    if 0 <= index < len(campaigns):
        campaigns.pop(index)
        _set_user_row(user_id, user)
        return True
    return False


def rename_campaign(user_id: int, camp_index: int, new_name: str) -> bool:
    """Rename a campaign by index. Returns True on success."""
    user = _get_user_row(user_id)
    camps = user.get("campaigns", [])
    if 0 <= camp_index < len(camps):
        camps[camp_index]["name"] = new_name.strip()
        _set_user_row(user_id, user)
        return True
    return False


def append_campaign_run_log(user_id: int, camp_index: int, record: dict) -> None:
    user = _get_user_row(user_id)
    camps = user.get("campaigns", [])
    if 0 <= camp_index < len(camps):
        log = camps[camp_index].setdefault("run_log", [])
        log.insert(0, record)
        camps[camp_index]["run_log"] = log[:10]
        _set_user_row(user_id, user)


def set_campaign_last_failed(user_id: int, camp_index: int, failed_ids: list) -> None:
    user = _get_user_row(user_id)
    camps = user.get("campaigns", [])
    if camp_index < len(camps):
        camps[camp_index]["last_failed_ids"] = failed_ids
        _set_user_row(user_id, user)


def set_campaign_running(user_id: int, camp_index: int, running: bool) -> None:
    import time as _t
    user = _get_user_row(user_id)
    camps = user.get("campaigns", [])
    if 0 <= camp_index < len(camps):
        if running:
            camps[camp_index]["running_since"] = _t.time()
        else:
            camps[camp_index].pop("running_since", None)
        _set_user_row(user_id, user)


def is_campaign_running(user_id: int, camp_index: int) -> bool:
    import time as _t
    camps = get_campaigns(user_id)
    if camp_index >= len(camps):
        return False
    ts = camps[camp_index].get("running_since")
    return bool(ts and _t.time() - ts < 3600)


# ── In-memory stop/pause flags (intentionally not persisted) ──────────────────
_campaign_stop_flags:  dict[str, bool] = {}
_campaign_pause_flags: dict[str, bool] = {}


def set_campaign_stop(user_id: int, camp_index: int) -> None:
    _campaign_stop_flags[f"{user_id}:{camp_index}"] = True


def clear_campaign_stop(user_id: int, camp_index: int) -> None:
    _campaign_stop_flags.pop(f"{user_id}:{camp_index}", None)


def is_campaign_stop_requested(user_id: int, camp_index: int) -> bool:
    return _campaign_stop_flags.get(f"{user_id}:{camp_index}", False)


def set_campaign_pause(user_id: int, camp_index: int) -> None:
    _campaign_pause_flags[f"{user_id}:{camp_index}"] = True


def clear_campaign_pause(user_id: int, camp_index: int) -> None:
    _campaign_pause_flags.pop(f"{user_id}:{camp_index}", None)


def is_campaign_pause_requested(user_id: int, camp_index: int) -> bool:
    return _campaign_pause_flags.get(f"{user_id}:{camp_index}", False)


# ── Campaign paused-remaining identifiers (for resume-from-pause) ──────────────
_campaign_paused_remaining: dict[str, list] = {}


def set_campaign_paused_remaining(user_id: int, camp_index: int, identifiers: list) -> None:
    _campaign_paused_remaining[f"{user_id}:{camp_index}"] = identifiers[:]


def get_campaign_paused_remaining(user_id: int, camp_index: int) -> list:
    return _campaign_paused_remaining.get(f"{user_id}:{camp_index}", [])


def clear_campaign_paused_remaining(user_id: int, camp_index: int) -> None:
    _campaign_paused_remaining.pop(f"{user_id}:{camp_index}", None)


# ── ADV campaign stop/pause flags ─────────────────────────────────────────────
_adv_stop_flags:  dict[int, bool] = {}
_adv_pause_flags: dict[int, bool] = {}


def set_adv_stop(user_id: int) -> None:
    _adv_stop_flags[user_id] = True


def clear_adv_stop(user_id: int) -> None:
    _adv_stop_flags.pop(user_id, None)


def is_adv_stop_requested(user_id: int) -> bool:
    return _adv_stop_flags.get(user_id, False)


def set_adv_pause(user_id: int) -> None:
    _adv_pause_flags[user_id] = True


def clear_adv_pause(user_id: int) -> None:
    _adv_pause_flags.pop(user_id, None)


def is_adv_pause_requested(user_id: int) -> bool:
    return _adv_pause_flags.get(user_id, False)


# ── Schedules ─────────────────────────────────────────────────────────────────

def get_schedules(user_id: int) -> list:
    return _get_user_row(user_id).get("schedules", [])


def add_schedule(user_id: int, schedule: dict) -> None:
    user = _get_user_row(user_id)
    user.setdefault("schedules", []).append(schedule)
    _set_user_row(user_id, user)


def remove_schedule(user_id: int, index: int) -> bool:
    user = _get_user_row(user_id)
    schedules = user.get("schedules", [])
    if 0 <= index < len(schedules):
        schedules.pop(index)
        _set_user_row(user_id, user)
        return True
    return False


def toggle_schedule_enabled(user_id: int, index: int) -> bool | None:
    user = _get_user_row(user_id)
    schedules = user.get("schedules", [])
    if 0 <= index < len(schedules):
        current = schedules[index].get("enabled", True)
        schedules[index]["enabled"] = not current
        _set_user_row(user_id, user)
        return schedules[index]["enabled"]
    return None


def set_schedule_last_run(user_id: int, sch_index: int, ts: str, result: str) -> None:
    user = _get_user_row(user_id)
    scheds = user.get("schedules", [])
    if sch_index < len(scheds):
        scheds[sch_index]["last_run"] = ts
        scheds[sch_index]["last_result"] = result
        _set_user_row(user_id, user)


def disable_schedule(user_id: int, sch_index: int) -> None:
    user = _get_user_row(user_id)
    scheds = user.get("schedules", [])
    if sch_index < len(scheds):
        scheds[sch_index]["enabled"] = False
        _set_user_row(user_id, user)


# ── Settings ──────────────────────────────────────────────────────────────────

def get_settings(user_id: int) -> dict:
    return _get_user_row(user_id).get("settings", {})


def update_settings(user_id: int, key: str, value: Any) -> None:
    user = _get_user_row(user_id)
    user.setdefault("settings", {})[key] = value
    _set_user_row(user_id, user)


def get_cooldown_minutes(user_id: int) -> int:
    """Return effective cooldown: global overrides per-user if set.
    Minimum default is 3 minutes so each account rests between uses."""
    global_cd = get_global_cooldown_minutes()
    if global_cd > 0:
        return global_cd
    return int(get_settings(user_id).get("cooldown_minutes", 3))


def set_cooldown_minutes(user_id: int, minutes: int) -> None:
    update_settings(user_id, "cooldown_minutes", int(minutes))


# ── Profile ───────────────────────────────────────────────────────────────────

def get_profile(user_id: int) -> dict:
    return _get_user_row(user_id).get("profile", {})


def update_profile(user_id: int, updates: dict) -> None:
    user = _get_user_row(user_id)
    user.setdefault("profile", {}).update(updates)
    _set_user_row(user_id, user)


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats(user_id: int) -> dict:
    user = _get_user_row(user_id)
    accounts  = user.get("accounts",  [])
    campaigns = user.get("campaigns", [])
    active  = sum(1 for a in accounts if a.get("status") == "active")
    dead    = len(accounts) - active
    actions = sum(c.get("actions", 0) for c in campaigns)
    return {
        "active":    active,
        "dead":      dead,
        "total":     len(accounts),
        "campaigns": len(campaigns),
        "actions":   actions,
    }


def get_global_stats() -> dict:
    total_accounts = active_accounts = total_campaigns = running_campaigns = total_actions = n_users = 0
    with _DB() as cur:
        cur.execute("SELECT data FROM user_data")
        for row in cur.fetchall():
            user = row["data"]
            n_users += 1
            accs  = user.get("accounts",  [])
            camps = user.get("campaigns", [])
            total_accounts   += len(accs)
            active_accounts  += sum(1 for a in accs if a.get("status") == "active")
            total_campaigns  += len(camps)
            running_campaigns += sum(1 for c in camps if c.get("active"))
            total_actions    += sum(c.get("actions", 0) for c in camps)
    return {
        "users":    n_users,
        "accounts": total_accounts,
        "active":   active_accounts,
        "campaigns":total_campaigns,
        "running":  running_campaigns,
        "actions":  total_actions,
    }


# ── Broadcasts ────────────────────────────────────────────────────────────────

def get_broadcasts(user_id: int) -> list:
    return _get_user_row(user_id).get("broadcasts", [])


def add_broadcast(user_id: int, broadcast: dict) -> None:
    user = _get_user_row(user_id)
    bcs = user.setdefault("broadcasts", [])
    bcs.insert(0, broadcast)
    user["broadcasts"] = bcs[:20]
    _set_user_row(user_id, user)


def delete_broadcast(user_id: int, index: int) -> bool:
    user = _get_user_row(user_id)
    broadcasts = user.get("broadcasts", [])
    if 0 <= index < len(broadcasts):
        broadcasts.pop(index)
        _set_user_row(user_id, user)
        return True
    return False


# ── Campaign Queue ────────────────────────────────────────────────────────────

def get_queue(user_id: int) -> list:
    return list(_get_user_row(user_id).get("queue", []))


def add_to_queue(user_id: int, camp_index: int) -> bool:
    user = _get_user_row(user_id)
    queue = user.setdefault("queue", [])
    if camp_index in queue:
        return False
    queue.append(camp_index)
    _set_user_row(user_id, user)
    return True


def remove_from_queue(user_id: int, camp_index: int) -> None:
    user = _get_user_row(user_id)
    queue = user.get("queue", [])
    if camp_index in queue:
        queue.remove(camp_index)
    _set_user_row(user_id, user)


def clear_queue(user_id: int) -> None:
    user = _get_user_row(user_id)
    user["queue"] = []
    _set_user_row(user_id, user)


def save_queue(user_id: int, queue: list) -> None:
    user = _get_user_row(user_id)
    user["queue"] = list(queue)
    _set_user_row(user_id, user)


# ── Campaign Templates ────────────────────────────────────────────────────────

def get_templates(user_id: int) -> list:
    return list(_get_user_row(user_id).get("templates", []))


def add_template(user_id: int, template: dict) -> None:
    user = _get_user_row(user_id)
    user.setdefault("templates", []).append(template)
    _set_user_row(user_id, user)


def delete_template(user_id: int, index: int) -> bool:
    user = _get_user_row(user_id)
    templates = user.get("templates", [])
    if 0 <= index < len(templates):
        templates.pop(index)
        _set_user_row(user_id, user)
        return True
    return False


# ── Account / campaign limits ─────────────────────────────────────────────────

def get_account_limit() -> int:
    return int(_get_global().get("account_limit", 0))


def set_account_limit(limit: int) -> None:
    settings = _get_global()
    settings["account_limit"] = limit
    _set_global(settings)


def get_user_account_limit(user_id: int) -> int | None:
    try:
        return _get_user_row(user_id).get("account_limit")
    except Exception:
        return None


def set_user_account_limit(user_id: int, limit: int | None) -> None:
    user = _get_user_row(user_id)
    if limit is None:
        user.pop("account_limit", None)
    else:
        user["account_limit"] = limit
    _set_user_row(user_id, user)


def check_account_limit(user_id: int) -> tuple:
    current   = len(get_accounts(user_id))
    per_user  = get_user_account_limit(user_id)
    limit     = per_user if per_user is not None else get_account_limit()
    if limit == 0:
        return True, current, 0
    return current < limit, current, limit


def get_per_user_camp_limit() -> int:
    return int(_get_global().get("per_user_camp_limit", 0))


def set_per_user_camp_limit(n: int) -> None:
    settings = _get_global()
    settings["per_user_camp_limit"] = n
    _set_global(settings)


def check_campaign_limit(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    limit = get_per_user_camp_limit()
    if limit == 0:
        return True
    return len(get_campaigns(user_id)) < limit


def get_log_channel() -> int | None:
    val = _get_global().get("log_channel")
    return int(val) if val else None


def set_log_channel(channel_id: int) -> None:
    settings = _get_global()
    settings["log_channel"] = channel_id
    _set_global(settings)


def clear_log_channel() -> None:
    settings = _get_global()
    settings.pop("log_channel", None)
    _set_global(settings)


def user_exists(user_id: int) -> bool:
    with _DB() as cur:
        cur.execute("SELECT 1 FROM user_data WHERE user_id = %s", (user_id,))
        return cur.fetchone() is not None


def get_auto_remove_threshold() -> int:
    return int(_get_global().get("auto_remove_threshold", 0))


def set_auto_remove_threshold(n: int) -> None:
    settings = _get_global()
    settings["auto_remove_threshold"] = n
    _set_global(settings)


# ── Banned users ──────────────────────────────────────────────────────────────

def is_banned(user_id: int) -> bool:
    with _DB() as cur:
        cur.execute("SELECT 1 FROM banned_users WHERE user_id = %s", (user_id,))
        return cur.fetchone() is not None


def get_banned_users() -> list:
    with _DB() as cur:
        cur.execute("SELECT user_id FROM banned_users")
        return [row["user_id"] for row in cur.fetchall()]


def ban_user(user_id: int) -> None:
    with _DB() as cur:
        cur.execute(
            "INSERT INTO banned_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (user_id,),
        )


def unban_user(user_id: int) -> None:
    with _DB() as cur:
        cur.execute("DELETE FROM banned_users WHERE user_id = %s", (user_id,))


# ── Owner management ──────────────────────────────────────────────────────────

def get_owner_ids() -> list[int]:
    stored = _get_global().get("owner_ids", [])
    ids = [int(i) for i in stored]
    if OWNER_ID not in ids:
        ids.insert(0, OWNER_ID)
    return ids


def add_owner_id(user_id: int) -> None:
    settings = _get_global()
    ids = settings.setdefault("owner_ids", [OWNER_ID])
    if OWNER_ID not in ids:
        ids.insert(0, OWNER_ID)
    if user_id not in ids:
        ids.append(user_id)
    settings["owner_ids"] = ids
    _set_global(settings)


def remove_owner_id(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return False
    settings = _get_global()
    ids = settings.get("owner_ids", [OWNER_ID])
    if user_id in ids:
        ids.remove(user_id)
        settings["owner_ids"] = ids
        _set_global(settings)
        return True
    return False


def is_owner(user_id: int) -> bool:
    return user_id in get_owner_ids()


# ── ADV access ────────────────────────────────────────────────────────────────

def get_adv_access_users() -> dict:
    return dict(_get_global().get("adv_access", {}))


def grant_adv_access(user_id: int, limit: int) -> None:
    settings = _get_global()
    settings.setdefault("adv_access", {})[str(user_id)] = limit
    _set_global(settings)


def revoke_adv_access(user_id: int) -> None:
    settings = _get_global()
    settings.setdefault("adv_access", {}).pop(str(user_id), None)
    _set_global(settings)


def has_adv_access(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    return str(user_id) in get_adv_access_users()


def get_adv_access_limit(user_id: int) -> int:
    if is_owner(user_id):
        return 0
    val = get_adv_access_users().get(str(user_id))
    return int(val) if val is not None else -1


def get_adv_admin_limit() -> int:
    return int(_get_global().get("adv_admin_limit", 0))


def set_adv_admin_limit(limit: int) -> None:
    settings = _get_global()
    settings["adv_admin_limit"] = limit
    _set_global(settings)


# ── Legacy shims ──────────────────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return has_adv_access(user_id)

def get_admins() -> list:
    return []

def add_admin(user_id: int) -> None:
    pass

def remove_admin(user_id: int) -> None:
    pass


# ── All user IDs ──────────────────────────────────────────────────────────────

def get_all_user_ids() -> list:
    with _DB() as cur:
        cur.execute("SELECT user_id FROM user_data")
        return [str(row["user_id"]) for row in cur.fetchall()]


# ── Required channels ─────────────────────────────────────────────────────────

def _normalize_channel(channel: str) -> str:
    channel = channel.strip()
    if not channel:
        return ""

    # Telegram's getChatMember accepts @public_username or a numeric chat ID,
    # not a public t.me URL.  Admins are allowed to paste the URL in the UI,
    # so convert public links to the form required by the Bot API.
    lowered = channel.lower()
    for prefix in ("https://t.me/", "http://t.me/", "https://telegram.me/", "http://telegram.me/"):
        if lowered.startswith(prefix):
            path = channel[len(prefix):].split("?", 1)[0].split("#", 1)[0].strip("/")
            if path and not path.startswith(("+", "joinchat/")):
                username = path.split("/", 1)[0]
                if username:
                    return username if username.startswith("@") else "@" + username
            return channel

    if channel.lstrip("-").isdigit():
        return channel
    if not channel.startswith("@"):
        channel = "@" + channel
    return channel


def get_required_channels() -> list:
    settings = _get_global()
    channels = settings.get("required_channels")
    if channels is None:
        legacy = settings.get("required_channel")
        channels = [legacy] if legacy else []
        settings["required_channels"] = channels
        settings.pop("required_channel", None)
        _set_global(settings)

    normalized = []
    for channel in channels:
        channel = _normalize_channel(str(channel))
        if channel and channel not in normalized:
            normalized.append(channel)
    if normalized != list(channels):
        settings["required_channels"] = normalized
        _set_global(settings)
    return normalized


def set_required_channels(channels: list) -> None:
    settings = _get_global()
    normalized = []
    for c in channels:
        c = _normalize_channel(c)
        if c and c not in normalized:
            normalized.append(c)
    settings["required_channels"] = normalized
    settings.pop("required_channel", None)
    _set_global(settings)


def add_required_channel(channel: str) -> None:
    channels = get_required_channels()
    channel = _normalize_channel(channel)
    if channel and channel not in channels:
        channels.append(channel)
        set_required_channels(channels)


def remove_required_channel(channel: str) -> None:
    channels = get_required_channels()
    channel = _normalize_channel(channel)
    if channel in channels:
        channels.remove(channel)
        set_required_channels(channels)


def clear_required_channels() -> None:
    set_required_channels([])


# Legacy single-channel shims
def get_required_channel() -> str | None:
    channels = get_required_channels()
    return channels[0] if channels else None

def set_required_channel(channel: str) -> None:
    add_required_channel(channel)

def clear_required_channel() -> None:
    clear_required_channels()


# ── Maintenance / paid mode / owner username ──────────────────────────────────

def get_maintenance_mode() -> bool:
    return bool(_get_global().get("maintenance_mode", False))

def set_maintenance_mode(enabled: bool) -> None:
    settings = _get_global()
    settings["maintenance_mode"] = bool(enabled)
    _set_global(settings)

def get_global_cooldown_minutes() -> int:
    return int(_get_global().get("global_cooldown_minutes", 0))


def set_global_cooldown_minutes(minutes: int) -> None:
    settings = _get_global()
    settings["global_cooldown_minutes"] = int(minutes)
    _set_global(settings)


def get_paid_mode() -> bool:
    return bool(_get_global().get("paid_mode", False))

def set_paid_mode(enabled: bool) -> None:
    settings = _get_global()
    settings["paid_mode"] = bool(enabled)
    _set_global(settings)

def get_owner_username() -> str | None:
    return _get_global().get("owner_username")

def set_owner_username(username: str) -> None:
    settings = _get_global()
    username = username.strip()
    if username and not username.startswith("@"):
        username = "@" + username
    settings["owner_username"] = username
    _set_global(settings)


# ── Audit log ─────────────────────────────────────────────────────────────────

def update_account_last_used(user_id: int, identifier: str, last_used: float) -> None:
    """Find account by identifier and update last_used + increment success_count."""
    user = _get_user_row(user_id)
    for acc in user.get("accounts", []):
        if acc.get("identifier") == identifier:
            acc["last_used"] = last_used
            acc["success_count"] = acc.get("success_count", 0) + 1
            break
    _set_user_row(user_id, user)


def increment_account_fail_count(user_id: int, identifier: str) -> None:
    """Find account by identifier and increment fail_count."""
    user = _get_user_row(user_id)
    for acc in user.get("accounts", []):
        if acc.get("identifier") == identifier:
            acc["fail_count"] = acc.get("fail_count", 0) + 1
            break
    _set_user_row(user_id, user)


def increment_campaign_actions(user_id: int, camp_index: int, count: int) -> None:
    """Add count to campaigns[camp_index]['actions']."""
    if count <= 0:
        return
    user = _get_user_row(user_id)
    camps = user.get("campaigns", [])
    if camp_index < len(camps):
        camps[camp_index]["actions"] = camps[camp_index].get("actions", 0) + count
        _set_user_row(user_id, user)


def append_audit_log(user_id: int, action: str, details: str = "") -> None:
    from datetime import datetime as _dt, timezone as _tz
    ts = _dt.now(_tz.utc).strftime("%Y-%m-%d %H:%M")
    with _DB() as cur:
        cur.execute(
            "INSERT INTO audit_log (ts, user_id, action, details) VALUES (%s, %s, %s, %s)",
            (ts, user_id, action, details),
        )
        # Keep only the last 500 entries
        cur.execute(
            "DELETE FROM audit_log WHERE id NOT IN "
            "(SELECT id FROM audit_log ORDER BY id DESC LIMIT 500)"
        )


def get_audit_log(limit: int = 50) -> list:
    with _DB() as cur:
        cur.execute(
            "SELECT ts, user_id, action, details FROM audit_log "
            "ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
