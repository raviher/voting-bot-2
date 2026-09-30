"""Tracks the bot's start time for uptime display."""
from datetime import datetime, timezone

_start_time: datetime = datetime.now(timezone.utc)


def get_uptime_str() -> str:
    """Return a human-readable uptime string like '2d 3h 14m'."""
    delta = datetime.now(timezone.utc) - _start_time
    total_seconds = int(delta.total_seconds())
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
