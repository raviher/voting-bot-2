"""
runner.py — Campaign execution engine.

Exports:
  progress_bar(done, total, width)  — ASCII progress bar string
  execute_campaign(...)             — Run a campaign against a list of accounts
  run_campaign(application, uid, idx) — Scheduler entry point
"""

import re
import os
import asyncio
import random
import time
import logging
import hashlib
from urllib.parse import parse_qs, urlparse
from typing import Any, Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WORKERS = int(os.environ.get('RUNNER_WORKERS', '15'))
MIN_DELAY = 0.5
MAX_DELAY = 1.0
ACTION_PAUSE = 1.0

# These are deliberately conservative. Telegram limits are applied per
# account and per action, so several accounts hitting the same post together
# can still look like coordinated automation.
ACTION_DELAY_MIN = float(os.environ.get('ACTION_DELAY_MIN', '0.5'))
ACTION_DELAY_MAX = float(os.environ.get('ACTION_DELAY_MAX', '1'))
ACCOUNT_MIN_GAP_SECONDS = float(os.environ.get('ACCOUNT_MIN_GAP_SECONDS', '10'))
MIN_ACCOUNT_COOLDOWN_SECONDS = int(
    os.environ.get('MIN_ACCOUNT_COOLDOWN_SECONDS', '300')
)
PEER_FLOOD_COOLDOWN_SECONDS = int(
    os.environ.get('PEER_FLOOD_COOLDOWN_SECONDS', '21600')
)
# Referral bots may reveal more channels after a callback. Keep walking the
# conversation, but retain a guard against a bot that endlessly paginates.
REFERRAL_MAX_ROUNDS = int(os.environ.get('REFERRAL_MAX_ROUNDS', '8'))
REFERRAL_HISTORY_LIMIT = int(os.environ.get('REFERRAL_HISTORY_LIMIT', '100'))
BOT_REFERRAL_TIMEOUT_SECONDS = int(
    os.environ.get('BOT_REFERRAL_TIMEOUT_SECONDS', '90')
)

_API_ID   = int(os.environ.get('PYROGRAM_API_ID')   or os.environ.get('API_ID')   or 0)
_API_HASH =     os.environ.get('PYROGRAM_API_HASH')  or os.environ.get('API_HASH')  or ''

SPEED_PRESETS = {
    'slow':   {'workers': 1, 'min_delay': 12.0, 'max_delay': 20.0},
    'normal': {'workers': 2, 'min_delay': 6.0,  'max_delay': 12.0},
    'fast':   {'workers': 3, 'min_delay': 4.0,  'max_delay': 8.0},
    'ultra':  {'workers': 4, 'min_delay': 2.0,  'max_delay': 5.0},
    'smart':  {'workers': 15, 'min_delay': 0.5,  'max_delay': 1.0},
}

_ACCOUNT_LOCKS = {}
_ACCOUNT_LAST_ACTION = {}
_ACCOUNT_LOCKS_GUARD = asyncio.Lock()


def _session_string_from_account(acc: dict) -> str | None:
    """Return a usable stored session string, ignoring phone-number fields."""
    for field in ("session_string", "session", "identifier"):
        value = acc.get(field)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) >= 20 and not value.startswith("+"):
            return value
    return None


def _account_key(acc: dict) -> str:
    """Create a stable, non-sensitive key for one Telegram session."""
    value = (
        _session_string_from_account(acc)
        or acc.get('phone')
        or acc.get('id')
        or acc.get('user_id')
        or 'unknown'
    )
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


async def _account_lock_for(key: str):
    async with _ACCOUNT_LOCKS_GUARD:
        return _ACCOUNT_LOCKS.setdefault(key, asyncio.Lock())

_FATAL_ERRORS = (
    'AUTH_KEY_INVALID',
    'USER_DEACTIVATED',
    'USER_DEACTIVATED_BAN',
    'SESSION_REVOKED',
    'SESSION_EXPIRED',
    'ACCOUNT_BANNED',
    'FROZEN_METHOD_INVALID',
)


def _is_fatal_error(exc: Exception) -> bool:
    msg = str(exc).upper()
    return any(fe in msg for fe in _FATAL_ERRORS)


def _needs_reauthentication(error: str | None) -> bool:
    message = (error or "").upper()
    return any(marker in message for marker in (
        "AUTH_KEY_INVALID",
        "SESSION_REVOKED",
        "SESSION_EXPIRED",
    ))


def _high_level_peer_id(peer):
    """Return a scalar peer value for Pyrogram's high-level methods.

    Pyrogram's raw ``InputPeer`` objects are valid for raw API functions, but
    they are not valid values for the SQLite-backed session storage used by
    high-level methods.  Keep raw peers at the raw API boundary only.
    """
    if isinstance(peer, (int, str)):
        return peer

    # A raw InputPeerChannel stores the bare channel ID in ``channel_id``.
    channel_id = getattr(peer, "channel_id", None)
    if channel_id is not None:
        return int(f"-100{int(channel_id)}")

    chat_id = getattr(peer, "id", None)
    if chat_id is not None:
        return _stable_chat_id(peer) or chat_id

    return peer


def _raw_channel_id(chat_id: int) -> int:
    """Convert a Pyrogram high-level channel ID to a raw channel ID."""
    raw_id = abs(int(chat_id))
    raw_text = str(raw_id)
    if raw_text.startswith("100"):
        raw_text = raw_text[3:]
    return int(raw_text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def progress_bar(done: int, total: int, width: int = 20) -> str:
    """Return an ASCII progress bar of given width."""
    filled = int(width * done / total) if total else 0
    return '█' * filled + '░' * (width - filled)


def parse_post_url(url: str) -> tuple:
    """Parse a Telegram post URL into (channel, message_id)."""
    raw = (url or '').strip().strip('`')
    parsed = urlparse(raw if re.match(r'https?://', raw, re.IGNORECASE)
                      else f'https://t.me/{raw.lstrip("/")}')
    if parsed.netloc.lower() not in {
        't.me', 'www.t.me', 'telegram.me', 'www.telegram.me'
    }:
        return None, None

    parts = [part for part in parsed.path.split('/') if part]
    if len(parts) >= 2 and parts[0].lower() == 'c' and parts[1].isdigit():
        if len(parts) >= 3 and parts[2].isdigit():
            return int(f'-100{parts[1]}'), int(parts[2])
        return None, None

    if len(parts) >= 2 and parts[1].isdigit():
        channel = parts[0]
        if channel.startswith('@'):
            channel = channel[1:]
        return f'@{channel}', int(parts[1])

    return None, None


def normalize_invite_link(link: str) -> str:
    """Normalize only private invite links; leave public channel links intact."""
    link = (link or '').strip().strip('`')
    if re.fullmatch(r'\+[A-Za-z0-9_-]+', link):
        return f'https://t.me/joinchat/{link[1:]}'

    match = re.fullmatch(
        r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)',
        link,
        re.IGNORECASE,
    )
    if match:
        return f'https://t.me/joinchat/{match.group(1)}'

    return link


def parse_channel(target: str) -> str:
    """Return a channel identifier usable by Pyrogram."""
    return parse_chat_target(target)


def parse_bot_referral(target: str) -> tuple[str | None, str | None]:
    """Return (bot_username, start_payload) from a Telegram bot link."""
    target = (target or '').strip()
    if not target:
        return None, None

    if not re.match(r'https?://', target, re.IGNORECASE):
        target = f'https://t.me/{target.lstrip("@")}'

    parsed = urlparse(target)
    if parsed.netloc.lower() not in {'t.me', 'www.t.me', 'telegram.me', 'www.telegram.me'}:
        return None, None

    parts = [part for part in parsed.path.split('/') if part]
    if not parts:
        return None, None

    bot_username = parts[0]
    if bot_username.startswith('@'):
        bot_username = bot_username[1:]
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', bot_username):
        return None, None

    query = parse_qs(parsed.query)
    payload = (query.get('start') or query.get('startapp') or [None])[0]
    return bot_username, payload


def _referral_join_target(url: str, bot_username: str) -> str | None:
    """Convert a Telegram URL from a referral reply into a join target."""
    raw = (url or '').strip().strip('`').rstrip('.,);]')
    if not raw:
        return None

    # Inline keyboards sometimes use tg://join?invite=HASH instead of t.me.
    tg_match = re.fullmatch(
        r'tg://join\?invite=([A-Za-z0-9_-]+)', raw, re.IGNORECASE
    )
    if tg_match:
        return normalize_invite_link(f"+{tg_match.group(1)}")

    # Some bots use tg://resolve?domain=<channel> for public channels.
    resolve_match = re.fullmatch(
        r'tg://resolve\?domain=([A-Za-z0-9_]{5,32})(?:[&#?].*)?',
        raw,
        re.IGNORECASE,
    )
    if resolve_match:
        username = resolve_match.group(1)
        if username.lower() == bot_username.lower():
            return None
        return f'@{username}'

    # Invite URLs may carry a query/fragment (for example ``?single``).
    # extract_invite_hash intentionally accepts only the canonical form, so
    # handle these referral-button variants here and strip the extra part.
    invite_match = re.fullmatch(
        r'(?:https?://)?(?:www\.)?t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)'
        r'(?:[?#].*)?',
        raw,
        re.IGNORECASE,
    )
    if invite_match:
        return normalize_invite_link(f"+{invite_match.group(1)}")
    invite_hash = extract_invite_hash(raw)
    if invite_hash:
        return normalize_invite_link(raw)

    if not re.match(r'https?://', raw, re.IGNORECASE):
        if re.match(r'(?:www\.)?(?:t\.me|telegram\.me)/', raw, re.IGNORECASE):
            raw = f'https://{raw}'
        else:
            raw = f'https://t.me/{raw.lstrip("@/")}'
    parsed = urlparse(raw)
    if parsed.netloc.lower() not in {
        't.me', 'www.t.me', 'telegram.me', 'www.telegram.me'
    }:
        return None

    parts = [part for part in parsed.path.split('/') if part]
    if not parts:
        return None
    username = parts[0].lstrip('@')
    if username.lower() in {
        bot_username.lower(), 'joinchat', 'c', 'addlist', 'share'
    }:
        return None
    # A bot deep link is not a channel invite and must not be passed to
    # join_chat(). The query check also covers links to other bots.
    if parsed.query and ('start' in parse_qs(parsed.query) or
                         'startapp' in parse_qs(parsed.query)):
        return None
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
        return None
    return f'@{username}'


def _referral_message_links(message: Any) -> list[str]:
    """Collect every channel/invite reference in a referral message.

    A link may be visible in text, hidden in a text-link entity, placed on an
    inline button, or encoded in callback data. Plain @channel mentions are
    accepted too, since not every referral bot makes them clickable.
    """
    values: list[str] = []
    for value, entities in (
        (getattr(message, 'text', None), getattr(message, 'entities', None)),
        (getattr(message, 'caption', None), getattr(message, 'caption_entities', None)),
    ):
        if value:
            values.extend(
                re.findall(
                    r'(?:(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/'
                    r'|tg://(?:join\?invite=|resolve\?domain=))'
                    r'[^\s<>"\']+',
                    str(value),
                    re.IGNORECASE,
                )
            )
            values.extend(
                re.findall(r'(?<![\w/])@[A-Za-z0-9_]{5,32}\b', str(value))
            )
        # Referral bots often hide invite links behind "Join" text.
        for entity in entities or []:
            if getattr(entity, 'type', '') == 'text_link':
                entity_url = getattr(entity, 'url', None)
                if entity_url:
                    values.append(str(entity_url))

    markup = getattr(message, 'reply_markup', None)
    for row in getattr(markup, 'inline_keyboard', None) or []:
        for button in row:
            button_url = getattr(button, 'url', None)
            if button_url:
                values.append(str(button_url))
            # Some referral bots encode the invite URL in callback data
            # instead of using a normal URL button.
            callback_data = getattr(button, 'callback_data', None)
            if isinstance(callback_data, bytes):
                callback_data = callback_data.decode('utf-8', errors='ignore')
            if callback_data:
                values.extend(
                    re.findall(
                        r'(?:(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/'
                        r'|tg://(?:join\?invite=|resolve\?domain=))'
                        r'[^\s<>"\']+',
                        str(callback_data),
                        re.IGNORECASE,
                    )
                )

    # Preserve order while removing duplicate links.
    return list(dict.fromkeys(values))


def _referral_verify_buttons(message: Any) -> list[tuple[str, str]]:
    """Return callback buttons that may advance a referral flow.

    Callback labels are controlled by the referral bot and do not have to
    contain words such as "verify" or "claim". URL buttons are handled by
    _referral_message_links(); every remaining callback is a possible
    verification or continue action.
    """
    markup = getattr(message, 'reply_markup', None)
    matches: list[tuple[str, str]] = []
    navigation_labels = {
        'back',
        'cancel',
        'close',
        'help',
        'leaderboard',
        'my referrals',
        'my referral',
        'settings',
    }
    for row in getattr(markup, 'inline_keyboard', None) or []:
        for button in row:
            callback_data = getattr(button, 'callback_data', None)
            if callback_data is not None:
                label = str(getattr(button, 'text', '') or '').strip().casefold()
                if label in navigation_labels:
                    continue
                if isinstance(callback_data, bytes):
                    callback_data = callback_data.decode(
                        'utf-8', errors='ignore'
                    )
                matches.append((str(getattr(button, 'text', '') or ''), str(callback_data)))
    return matches


async def _wait_for_referral_replies(
    client, bot_username: str, sent_message_id: int, timeout: float = 12.0
) -> list[Any]:
    """Poll for the complete burst of messages sent after the /start command."""
    deadline = time.monotonic() + timeout
    replies: dict[int, Any] = {}
    first_reply_at = None
    while time.monotonic() < deadline:
        try:
            async for message in client.get_chat_history(
                bot_username, limit=REFERRAL_HISTORY_LIMIT
            ):
                if (
                    getattr(message, 'id', 0) > sent_message_id
                    and not getattr(message, 'outgoing', False)
                ):
                    replies[message.id] = message
        except Exception:
            # The original /start may still have succeeded even if history
            # briefly fails while Telegram updates the bot chat.
            pass
        if replies and first_reply_at is None:
            first_reply_at = time.monotonic()
        # A referral bot can send an introductory message and the Join
        # keyboard as separate updates. Keep polling briefly after the first
        # reply so we do not process only the first message in that burst.
        if replies and time.monotonic() - first_reply_at >= 2.0:
            return [replies[key] for key in sorted(replies)]
        await asyncio.sleep(0.6)
    return [replies[key] for key in sorted(replies)]


async def _run_bot_referral(client, bot_username: str, payload: str | None) -> dict:
    """Open a referral bot, join its advertised channels, and verify."""
    command = f'/start {payload}' if payload else '/start'
    sent = await client.send_message(bot_username, command)
    replies = await _wait_for_referral_replies(client, bot_username, sent.id)
    if not replies:
        return {
            'ok': False,
            'error': (
                f'@{bot_username} did not reply within 12 seconds after '
                'the referral command.'
            ),
            'fatal': False,
        }

    joined = 0
    join_errors: list[str] = []
    verified = 0
    verify_errors: list[str] = []
    join_targets: list[str] = []
    joined_targets: set[str] = set()
    clicked_callbacks: set[tuple[int, str]] = set()
    processed_messages: set[int] = set()

    async def collect_messages(messages: list[Any]) -> None:
        """Extract links from each newly received referral message."""
        for message in messages:
            message_id = int(getattr(message, 'id', 0) or 0)
            if message_id in processed_messages:
                continue
            processed_messages.add(message_id)
            for url in _referral_message_links(message):
                target = _referral_join_target(url, bot_username)
                if target and target not in join_targets:
                    join_targets.append(target)

    async def join_all_discovered() -> None:
        """Join every target, including channels revealed by later callbacks."""
        nonlocal joined
        for target in join_targets:
            if target in joined_targets:
                continue
            joined_targets.add(target)
            try:
                # Plain @mentions can be users, bots, or channels. Only call
                # join_chat for a real group/channel; referral messages often
                # mention the referrer with @username and that is not joinable.
                if target.startswith('@'):
                    chat = await client.get_chat(target)
                    chat_type = getattr(chat, 'type', '')
                    chat_type = getattr(chat_type, 'value', chat_type)
                    chat_type = str(chat_type).casefold().rsplit('.', 1)[-1]
                    if chat_type not in {'channel', 'group', 'supergroup'}:
                        continue
                await client.join_chat(target)
                joined += 1
            except Exception as exc:
                error_text = str(exc)
                if 'USER_ALREADY_PARTICIPANT' in error_text.upper():
                    joined += 1
                else:
                    join_errors.append(f'{target}: {error_text}')

    await collect_messages(replies)
    max_message_id = max(getattr(message, 'id', 0) for message in replies)

    # Referral bots can be multi-stage: the first page may expose only a few
    # channels, then a callback reveals another page or the real verification
    # button. Repeat extraction -> join -> callback until the flow is done.
    for _ in range(max(1, REFERRAL_MAX_ROUNDS)):
        await join_all_discovered()

        callbacks: list[tuple[Any, str, str]] = []
        for message in replies:
            for label, callback_data in _referral_verify_buttons(message):
                callback_key = (
                    int(getattr(message, 'id', 0) or 0),
                    callback_data,
                )
                if callback_key not in clicked_callbacks:
                    callbacks.append((message, label, callback_data))

        if not callbacks:
            break

        clicked_this_round = 0
        for message, label, callback_data in callbacks:
            callback_key = (
                int(getattr(message, 'id', 0) or 0),
                callback_data,
            )
            clicked_callbacks.add(callback_key)
            try:
                await client.request_callback_answer(
                    bot_username,
                    message.id,
                    callback_data=callback_data,
                )
                verified += 1
                clicked_this_round += 1
            except Exception as exc:
                verify_errors.append(f'{label or "callback"}: {exc}')

        if not clicked_this_round:
            break

        follow_up = await _wait_for_referral_replies(
            client,
            bot_username,
            max_message_id,
            timeout=5.0,
        )
        if not follow_up:
            break
        replies.extend(follow_up)
        await collect_messages(follow_up)
        max_message_id = max(
            max_message_id,
            max(getattr(message, 'id', 0) for message in follow_up),
        )

    if join_errors and joined == 0:
        return {
            'ok': False,
            'error': 'Referral channels could not be joined: ' + '; '.join(join_errors[:3]),
            'fatal': False,
        }
    if verify_errors and verified == 0 and clicked_callbacks:
        return {
            'ok': False,
            'error': 'Referral verification failed: ' + '; '.join(verify_errors[:3]),
            'fatal': False,
        }
    if not join_targets and not clicked_callbacks:
        return {
            'ok': False,
            'error': (
                f'@{bot_username} replied, but no channel invite links or '
                'verification button were found in its messages.'
            ),
            'fatal': False,
        }

    details = [f'@{bot_username} replied']
    if join_targets:
        details.append(f'joined {joined}/{len(join_targets)} channel(s)')
    if clicked_callbacks:
        details.append(f'verified {verified} callback(s)')
    if join_errors:
        details.append(f'{len(join_errors)} join warning(s)')
    return {'ok': True, 'error': '; '.join(details), 'fatal': False}


def parse_chat_target(target):
    """Return a Pyrogram chat identifier from a public channel target.

    Telegram's ``/c/<id>`` links contain the internal channel id rather than
    a username.  Treat numeric ids as integers too; passing them through
    ``parse_channel`` would incorrectly turn them into ``@-100...``.
    """
    # ``parse_post_url`` returns an integer for private ``/c/<id>/<msg>``
    # links.  Keep that ID intact instead of treating it like a string.
    if isinstance(target, int):
        return target

    target = (target or '').strip().strip('`')
    if not target:
        return None

    parsed = urlparse(target if re.match(r'https?://', target, re.IGNORECASE)
                      else f'https://t.me/{target.lstrip("@")}')
    path_parts = [part for part in parsed.path.split('/') if part]

    if (
        parsed.netloc.lower() in {'t.me', 'www.t.me', 'telegram.me', 'www.telegram.me'}
        and path_parts
        and path_parts[0].lower() == 'c'
        and len(path_parts) >= 2
        and path_parts[1].isdigit()
    ):
        return int(f'-100{path_parts[1]}')

    if extract_invite_hash(target):
        # An invite hash identifies an invitation, not the already-joined
        # chat.  It cannot be passed to leave_chat().
        return None

    if parsed.netloc.lower() in {'t.me', 'www.t.me', 'telegram.me', 'www.telegram.me'}:
        target = path_parts[0] if path_parts else ''

    numeric = target.lstrip('@')
    if re.fullmatch(r'-?\d+', numeric):
        return int(numeric)

    target = target.lstrip('@').strip()
    return f'@{target}' if target else None


def extract_invite_hash(target: str) -> str | None:
    """Extract a Telegram invite hash from a public invite-link format."""
    target = (target or '').strip()
    match = re.fullmatch(
        r'(?:https?://)?(?:www\.)?t\.me/(?:joinchat/|\+)([A-Za-z0-9_-]+)',
        target,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    if re.fullmatch(r'\+[A-Za-z0-9_-]+', target):
        return target[1:]
    return None


def _leave_chat_peer(chat):
    """Convert a raw Telegram chat into a peer Pyrogram can leave."""
    chat_id = getattr(chat, 'id', None)
    if chat_id is None:
        return None

    chat_type = (
        f"{type(chat).__name__} "
        f"{getattr(chat, 'type', '')}"
    ).lower()
    if 'channel' in chat_type:
        raw_channel_id = int(chat_id)
        if raw_channel_id < 0:
            raw_channel_id = int(str(abs(raw_channel_id)).removeprefix('100'))
        access_hash = getattr(chat, 'access_hash', None)
        if access_hash is not None:
            from pyrogram.raw.types import InputPeerChannel
            return InputPeerChannel(
                channel_id=raw_channel_id,
                access_hash=int(access_hash),
            )
        return int(chat_id) if chat_id < 0 else int(f'-100{chat_id}')
    if chat_type.startswith('chat') and chat_id > 0:
        return -int(chat_id)
    return int(chat_id)


def _stable_chat_id(chat) -> int | None:
    """Return a high-level Pyrogram-compatible ID from any Telegram chat."""
    chat_id = getattr(chat, "id", None)
    if chat_id is None:
        return None

    chat_type = (
        f"{type(chat).__name__} "
        f"{getattr(chat, 'type', '')}"
    ).lower()
    if "channel" in chat_type and int(chat_id) > 0:
        return int(f"-100{int(chat_id)}")
    return int(chat_id)


async def _leave_resolved_chat(client, peer):
    """Leave a peer returned by Telegram's private-invite lookup."""
    if type(peer).__name__ == 'InputPeerChannel':
        await _leave_channel_peer(client, peer)
        return

    if isinstance(peer, int):
        try:
            resolved = await client.resolve_peer(peer)
        except Exception:
            resolved = None
        if type(resolved).__name__ == 'InputPeerChannel':
            await _leave_channel_peer(client, resolved)
            return

    await client.leave_chat(peer)


async def _leave_channel_peer(client, peer):
    """Leave a resolved channel without relying on Pyrogram's peer cache."""
    from pyrogram.raw.functions.channels import LeaveChannel
    from pyrogram.raw.types import InputChannel

    try:
        await client.invoke(LeaveChannel(
            channel=InputChannel(
                channel_id=int(peer.channel_id),
                access_hash=int(peer.access_hash),
            )
        ))
    except AttributeError as exc:
        if 'NoneType' in str(exc) and '.id' in str(exc):
            raise ValueError(
                'Telegram did not return a usable channel peer for this account. '
                'Make sure the account is currently a member of the channel.'
            ) from exc
        raise


async def resolve_leave_target(client, target: str):
    """Resolve a leave target to a peer known by this account.

    Private invite links do not contain the channel ID.  CheckChatInvite
    returns the joined chat for accounts that are already members.  Numeric
    IDs are checked against the account's dialogs first so Telegram does not
    receive an unknown peer and return ``PEER_ID_INVALID``.
    """
    target = (target or '').strip()
    invite_hash = extract_invite_hash(target)
    if invite_hash:
        from pyrogram.raw.functions.messages import CheckChatInvite

        try:
            invite = await client.invoke(CheckChatInvite(hash=invite_hash))
        except Exception as exc:
            return None, f'Could not resolve invite link: {exc}'

        chat = getattr(invite, 'chat', None)
        peer = _leave_chat_peer(chat)
        if peer is not None:
            return peer, None
        return None, (
            'This account is not a member of the channel from that invite link, '
            'so there is nothing for it to leave.'
        )

    peer = parse_chat_target(target)
    if peer is None:
        return None, 'No valid channel target was provided.'

    if isinstance(peer, int):
        # Telegram channel IDs are commonly copied without the ``-100``
        # prefix. Normalize that form only for the leave action so the other
        # campaign actions keep their existing target behavior.
        if peer > 0:
            peer = int(f'-100{peer}')

        async for dialog in client.get_dialogs():
            chat = getattr(dialog, 'chat', None)
            if getattr(chat, 'id', None) == peer:
                return _leave_chat_peer(chat) or peer, None

        # A valid channel may not be present in the local dialog cache yet.
        # Let Telegram resolve it before reporting that the ID is invalid.
        try:
            chat = await client.get_chat(peer)
            return _leave_chat_peer(chat) or getattr(chat, 'id', peer), None
        except Exception as exc:
            return None, _friendly_peer_error(exc, peer)

    try:
        chat = await client.get_chat(peer)
        return _leave_chat_peer(chat) or getattr(chat, 'id', peer), None
    except Exception as exc:
        return None, _friendly_peer_error(exc, peer)


def _friendly_peer_error(exc: Exception, target=None) -> str:
    """Turn Telegram's opaque peer errors into an actionable campaign error."""
    message = str(exc)
    upper = message.upper()
    if 'FROZEN_METHOD_INVALID' in upper:
        return (
            'This Telegram account is frozen. Telegram rejected the invite/join '
            'method for this session, so the account has been disabled.'
        )
    if 'AUTH_KEY_UNREGISTERED' in upper:
        return (
            'This Telegram user session is no longer registered. '
            'Please log in again with Phone + OTP + 2FA. '
            'The account record was kept unchanged.'
        )
    if 'INPUTPEERCHANNEL' in upper and 'BINDING PARAMETER' in upper:
        return (
            'Could not prepare the channel peer for the view action. '
            'The account may still react or vote, but Telegram rejected the '
            'view request for this session.'
        )
    if 'PEER_ID_INVALID' in upper or 'USERNAME_NOT_OCCUPIED' in upper:
        suffix = f' for {target}' if target is not None else ''
        return (
            f'Telegram could not resolve the chat{suffix}. '
            'Use the channel username or numeric ID, and make sure this account '
            'has opened or joined the channel first.'
        )
    return message


async def resolve_chat_target(client, target: str):
    """Resolve a target to a peer ID known to the current account."""
    peer = parse_chat_target(target)
    if peer is None:
        return None, 'Invite links cannot identify a chat until the account joins it.'

    if isinstance(peer, int):
        async for dialog in client.get_dialogs():
            chat = getattr(dialog, 'chat', None)
            if getattr(chat, 'id', None) == peer:
                return peer, None
        try:
            chat = await client.get_chat(peer)
            return getattr(chat, 'id', peer), None
        except Exception as exc:
            return None, _friendly_peer_error(exc, peer)

    try:
        chat = await client.get_chat(peer)
        return getattr(chat, 'id', peer), None
    except Exception as exc:
        return None, _friendly_peer_error(exc, peer)


async def resolve_post_target(client, target: str):
    """Resolve a t.me post URL and return (peer_id, message_id, error)."""
    channel, message_id = parse_post_url(target)
    if channel is None or message_id is None:
        return None, None, 'Use a Telegram post URL such as https://t.me/channel/123.'
    peer, error = await resolve_chat_target(client, channel)
    return peer, message_id, error


async def _lookup_invite_chat(client, link: str):
    """Return the joined chat carried by a private invite, when available."""
    invite_hash = extract_invite_hash(link)
    if not invite_hash:
        return None

    from pyrogram.raw.functions.messages import CheckChatInvite
    try:
        invite = await client.invoke(CheckChatInvite(hash=invite_hash))
    except Exception:
        return None
    return getattr(invite, 'chat', None)


async def click_vote_button(client, peer, message_id: int, button_index: int) -> None:
    """Click an inline vote button or submit a native poll vote."""
    message = await client.get_messages(peer, message_id)
    poll = getattr(message, 'poll', None)
    if poll is not None and hasattr(client, 'vote_poll'):
        await client.vote_poll(peer, message_id, [button_index])
        return

    markup = getattr(message, 'reply_markup', None)
    keyboard = getattr(markup, 'inline_keyboard', None) if markup else None
    buttons = [button for row in (keyboard or []) for button in row]
    if button_index < 0 or button_index >= len(buttons):
        raise ValueError(
            f'Button #{button_index + 1} was not found on the Telegram post.'
        )

    callback_data = getattr(buttons[button_index], 'callback_data', None)
    if callback_data is None:
        raise ValueError(f'Button #{button_index + 1} is not a callback button.')
    if isinstance(callback_data, bytes):
        callback_data = callback_data.decode('utf-8', errors='ignore')
    await client.request_callback_answer(
        peer, message_id, callback_data=callback_data
    )


async def _resolve_views_peer(client, peer, message_id: int):
    """Return a concrete raw peer for GetMessagesViews.

    Some sessions can react successfully while their local Pyrogram peer
    cache is incomplete.  In that case resolve_peer() may fail internally
    with a ``NoneType.id`` error.  Fetching the message and rebuilding the
    channel peer from Telegram's access hash repairs that cache path.
    """
    # Never pass a raw InputPeer into get_messages/get_chat/resolve_peer.
    # Those methods may bind the value into Pyrogram's SQLite session store.
    high_level_peer = _high_level_peer_id(peer)

    try:
        message = await client.get_messages(high_level_peer, message_id)
    except Exception as exc:
        raise ValueError(f'Could not load Telegram post for view: {exc}') from exc

    if message is None:
        raise ValueError('Telegram returned no message for this account.')

    try:
        resolved = await client.resolve_peer(high_level_peer)
        if resolved is not None:
            return resolved
    except Exception:
        # Try the hydrated Chat object below.
        pass

    chat = None
    try:
        chat = await client.get_chat(high_level_peer)
    except Exception:
        pass

    chat_id = getattr(chat, 'id', None)
    access_hash = getattr(chat, 'access_hash', None)
    if chat_id is not None and access_hash is not None:
        from pyrogram.raw.types import InputPeerChannel
        return InputPeerChannel(
            channel_id=_raw_channel_id(int(chat_id)),
            access_hash=int(access_hash),
        )

    raise ValueError(
        'Telegram could not resolve this channel for the view action. '
        'Make sure this account joined the channel and can open the post.'
    )


# ---------------------------------------------------------------------------
# Per-account action
# ---------------------------------------------------------------------------

_PREMIUM_REACTION_FALLBACKS = (
    "👍", "👎", "❤️", "🔥", "🎉", "😍", "😂", "🤩",
    "👏", "🙏", "💯", "😎", "🤝", "❤️‍🔥", "🥰", "😘",
    "💋", "🌚", "🌭", "💩", "🤡", "🥱", "🥴", "😭",
    "🤓", "👻", "🙈", "😇", "🦄", "💥", "🏆", "🤗",
)


def _reaction_value(value) -> tuple[str, str | int] | None:
    """Normalize a Pyrogram/TL reaction into a sendable reaction value."""
    if isinstance(value, str):
        return "emoji", value

    emoji = (
        getattr(value, "emoji", None)
        or getattr(value, "emoticon", None)
        or getattr(value, "reaction", None)
    )
    if emoji:
        return "emoji", str(emoji)

    custom_emoji_id = getattr(value, "custom_emoji_id", None)
    if custom_emoji_id is not None:
        return "custom", int(custom_emoji_id)

    document_id = getattr(value, "document_id", None)
    if document_id is not None:
        return "custom", int(document_id)

    return None


async def _premium_reaction_choices(
    client, peer, message=None
) -> list[tuple[str, str | int]]:
    """Resolve the first two reactions enabled for a post's chat.

    Telegram exposes chat-specific reaction settings through ``Chat``.  Some
    accounts/older Pyrogram builds only hydrate the reactions already present on
    the message, so that is used as a secondary source. When all reactions are
    enabled, the raw Telegram catalog supplies the correct ordered list,
    including reactions marked as premium.
    """
    choices: list[tuple[str, str | int]] = []
    seen: set[tuple[str, str | int]] = set()

    def add(value) -> None:
        normalized = _reaction_value(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            choices.append(normalized)

    available = None
    try:
        chat = await client.get_chat(peer)
        available = getattr(chat, "available_reactions", None)
        for reaction in getattr(available, "reactions", None) or []:
            add(reaction)
    except Exception:
        pass

    if len(choices) < 2 and message is not None:
        current = getattr(getattr(message, "reactions", None), "reactions", None) or []
        for reaction in current:
            add(reaction)

    # ChatReactionsAll does not include the catalog itself. Fetch it directly
    # so premium reactions are not replaced by the old hard-coded emoji list.
    if len(choices) < 2 and (
        available is None or getattr(available, "all_are_enabled", False)
    ):
        try:
            from pyrogram.raw.functions.messages import GetAvailableReactions

            catalog = await client.invoke(GetAvailableReactions(hash=0))
            for reaction in getattr(catalog, "reactions", None) or []:
                if not getattr(reaction, "inactive", False):
                    add(reaction)
        except Exception:
            pass

    if not choices:
        choices.extend(("emoji", emoji) for emoji in _PREMIUM_REACTION_FALLBACKS)

    return choices[:2]


async def _send_reaction(client, peer, message_id: int, reaction) -> None:
    """Send either a normal or custom Telegram reaction."""
    kind, value = reaction
    if kind == "custom":
        from pyrogram.raw.functions.messages import SendReaction
        from pyrogram.raw.types import ReactionCustomEmoji

        await client.invoke(
            SendReaction(
                peer=await client.resolve_peer(peer),
                msg_id=message_id,
                reaction=[ReactionCustomEmoji(document_id=int(value))],
            )
        )
        return

    await client.send_reaction(peer, message_id, emoji=str(value))


async def run_campaign_on_account(
    acc: dict,
    camp: dict,
    *,
    api_id: int,
    api_hash: str,
    reactions: Optional[list] = None,
    workdir: str = '/tmp/sessions',
) -> dict:
    """Run one account with a process-wide per-session safety gate."""
    key = _account_key(acc)
    lock = await _account_lock_for(key)
    async with lock:
        last_action = _ACCOUNT_LAST_ACTION.get(key)
        if last_action is not None:
            remaining = ACCOUNT_MIN_GAP_SECONDS - (
                time.monotonic() - last_action
            )
            if remaining > 0:
                await asyncio.sleep(remaining + random.uniform(0, 5))
        try:
            return await _run_campaign_on_account_unlocked(
                acc,
                camp,
                api_id=api_id,
                api_hash=api_hash,
                reactions=reactions,
                workdir=workdir,
            )
        finally:
            _ACCOUNT_LAST_ACTION[key] = time.monotonic()


async def _run_campaign_on_account_unlocked(
    acc: dict,
    camp: dict,
    *,
    api_id: int,
    api_hash: str,
    reactions: Optional[list] = None,
    workdir: str = '/tmp/sessions',
) -> dict:
    """
    Run the campaign action for a single account.
    Returns {'ok': bool, 'error': str|None, 'fatal': bool}.
    """
    import os, tempfile
    from pyrogram import Client
    from pyrogram.errors import (
        FloodWait, UserPrivacyRestricted, PeerFlood, ChatWriteForbidden,
        InputUserDeactivated, UserBannedInChannel, UserNotParticipant,
        UserAlreadyParticipant,
    )

    # Account records created by the bot store the Pyrogram session string
    # under ``identifier``. Keep the explicit names for compatibility with
    # imported/legacy records, but use the stored identifier as the fallback.
    session_str = _session_string_from_account(acc)
    session_file = acc.get('session_file')
    identifier   = acc.get('phone') or acc.get('id') or acc.get('user_id', 'unknown')

    os.makedirs(workdir, exist_ok=True)

    try:
        if not api_id or not api_hash:
            return {
                'ok': False,
                'error': 'Pyrogram API ID/API hash is not configured.',
                'fatal': False,
            }
        if session_file and os.path.exists(session_file):
            session_name = os.path.splitext(session_file)[0]
            client = Client(session_name, api_id=api_id, api_hash=api_hash,
                            no_updates=True)
        elif session_str:
            session_name = 'campaign_' + hashlib.sha256(
                str(session_str).encode('utf-8')
            ).hexdigest()[:16]
            client = Client(
                session_name,
                session_string=session_str,
                api_id=api_id,
                api_hash=api_hash,
                no_updates=True,
                in_memory=True,
            )
        else:
            return {'ok': False, 'error': 'No session available', 'fatal': False}
    except Exception as e:
        return {'ok': False, 'error': f'Client init: {e}', 'fatal': False}

    # Campaigns created by the regular campaign flow are stored with the
    # ``action_type`` key, while older/advanced campaigns use ``action`` or
    # ``camp_action``.  Accept all three formats.
    action = (
        camp.get('action')
        or camp.get('action_type')
        or camp.get('camp_action', '')
    )
    action = str(action).removeprefix('camp_action_')
    target = camp.get('target', camp.get('camp_target', ''))

    try:
        async with client:
            if action in {'dm', 'bulk_dm'}:
                message = camp.get('message') or camp.get('camp_dm_message', '')
                if not message:
                    return {'ok': False, 'error': 'No DM message configured', 'fatal': False}
                peer, error = await resolve_chat_target(client, target)
                if error:
                    return {'ok': False, 'error': error, 'fatal': False}
                await client.send_message(peer, message)

            elif action in {
                'react', 'vote', 'react_vote', 'view', 'react_view',
                'vote_view', 'react_vote_view',
            }:
                # ADV campaigns can include an optional auto-join link for
                # actions that operate on a post. Join before resolving the
                # private /c/<id>/<message> target; otherwise Telegram does
                # not know the channel for accounts that are not members yet.
                join_link = camp.get('join_link') or camp.get('camp_join_link', '')
                joined_chat = None
                if join_link:
                    link = normalize_invite_link(str(join_link))
                    try:
                        joined_chat = await client.join_chat(link)
                    except UserAlreadyParticipant:
                        # Already joined is the desired state; continue with
                        # resolving and acting on the post.
                        joined_chat = await _lookup_invite_chat(client, link)

                peer, msg_id, error = await resolve_post_target(client, target)
                if error:
                    return {'ok': False, 'error': error, 'fatal': False}

                # Private /c/<channel_id>/<message_id> links only expose an
                # internal numeric ID. Prefer the concrete channel peer from
                # the auto-join/invite lookup so all post actions retain its
                # access hash.
                post_channel, _ = parse_post_url(target)
                if isinstance(post_channel, int) and joined_chat is not None:
                    # ``_leave_chat_peer`` intentionally returns a raw
                    # InputPeerChannel for the low-level LeaveChannel call.
                    # High-level Pyrogram methods such as get_messages() and
                    # send_reaction() require a numeric/string chat ID instead.
                    peer = _stable_chat_id(joined_chat) or peer

                if action in {'react', 'react_vote', 'react_view', 'react_vote_view'}:
                    reaction_mode = camp.get("reaction_mode", "simple")
                    if reaction_mode == "premium":
                        message = await client.get_messages(peer, msg_id)
                        reaction_choices = await _premium_reaction_choices(
                            client, peer, message
                        )
                    else:
                        configured_reactions = (
                            reactions
                            or camp.get('reactions')
                            or camp.get('camp_reactions')
                        )
                        reaction_choices = [
                            normalized
                            for value in (configured_reactions or ["👍"])
                            if (normalized := _reaction_value(value)) is not None
                        ] or [("emoji", "👍")]
                    await _send_reaction(
                        client, peer, msg_id, random.choice(reaction_choices)
                    )
                    if action in {'react_vote', 'react_view', 'react_vote_view'}:
                        await asyncio.sleep(
                            random.uniform(ACTION_DELAY_MIN, ACTION_DELAY_MAX)
                        )

                if action in {'vote', 'react_vote', 'vote_view', 'react_vote_view'}:
                    button_index = int(
                        camp.get('button_index', camp.get('camp_button_index', 0)) or 0
                    )
                    await click_vote_button(client, peer, msg_id, button_index)
                    if action in {'vote_view', 'react_vote_view'}:
                        await asyncio.sleep(
                            random.uniform(ACTION_DELAY_MIN, ACTION_DELAY_MAX)
                        )

                if action in {'view', 'react_view', 'vote_view', 'react_vote_view'}:
                    from pyrogram.raw.functions.messages import GetMessagesViews
                    views_peer = await _resolve_views_peer(client, peer, msg_id)
                    await client.invoke(
                        GetMessagesViews(
                            peer=views_peer,
                            id=[msg_id],
                            increment=True,
                        )
                    )

            elif action == 'join':
                join_link = camp.get('join_link') or camp.get('camp_join_link', '')
                # A Join campaign may store the invite directly in ``target``
                # (for example, https://t.me/+InviteHash). Do not send that
                # URL through parse_channel(), which turns it into an invalid
                # username and causes Telegram USERNAME_NOT_OCCUPIED.
                if not join_link and extract_invite_hash(target):
                    join_link = target
                if join_link:
                    link = normalize_invite_link(join_link)
                    await client.join_chat(link)
                else:
                    peer, error = await resolve_chat_target(client, target)
                    if error:
                        return {'ok': False, 'error': error, 'fatal': False}
                    await client.join_chat(peer)

            elif action == 'bot_referral':
                bot_username, payload = parse_bot_referral(target)
                if not bot_username:
                    return {
                        'ok': False,
                        'error': (
                            'Invalid bot referral link. Use '
                            'https://t.me/BotName?start=payload.'
                        ),
                        'fatal': False,
                    }

                try:
                    return await asyncio.wait_for(
                        _run_bot_referral(client, bot_username, payload),
                        timeout=BOT_REFERRAL_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    return {
                        'ok': False,
                        'error': (
                            f'Bot referral timed out after '
                            f'{BOT_REFERRAL_TIMEOUT_SECONDS}s '
                            'while waiting for the referral flow.'
                        ),
                        'fatal': False,
                    }

            elif action == 'leave':
                if not target:
                    return {'ok': False, 'error': 'No channel configured', 'fatal': False}

                peer, resolve_error = await resolve_leave_target(client, target)
                if peer is None:
                    return {
                        'ok': False,
                        'error': resolve_error or 'Could not resolve channel target.',
                        'fatal': False,
                    }
                await _leave_resolved_chat(client, peer)

            elif action == 'leave_all':
                from pyrogram.enums import ChatType

                failures = []
                left_count = 0
                async for dialog in client.get_dialogs():
                    chat = dialog.chat
                    # Private and public channels both use CHANNEL. Include
                    # regular groups and supergroups as well. Direct-message
                    # chats are not leaveable Telegram group/channel chats.
                    if getattr(chat, 'type', None) not in (
                        ChatType.CHANNEL,
                        ChatType.GROUP,
                        ChatType.SUPERGROUP,
                    ):
                        continue
                    try:
                        await client.leave_chat(chat.id)
                        left_count += 1
                    except Exception as exc:
                        failures.append(f'{chat.id}: {exc}')

                if failures and left_count == 0:
                    return {
                        'ok': False,
                        'error': '; '.join(failures[:3]),
                        'fatal': False,
                    }

            else:
                return {'ok': False, 'error': f'Unknown action: {action}', 'fatal': False}

        return {'ok': True, 'error': None, 'fatal': False}

    except FloodWait as e:
        return {
            'ok': False,
            'error': f'FloodWait {e.value}s',
            'fatal': False,
            'flood_until': time.time() + int(e.value),
            'cooldown_until': time.time() + int(e.value),
        }
    except (UserPrivacyRestricted, PeerFlood, ChatWriteForbidden,
            InputUserDeactivated, UserBannedInChannel) as e:
        fatal = _is_fatal_error(e) or isinstance(e, InputUserDeactivated)
        result = {
            'ok': False,
            'error': str(e),
            'fatal': fatal,
            'expired': fatal,
        }
        if isinstance(e, PeerFlood):
            result['cooldown_until'] = time.time() + PEER_FLOOD_COOLDOWN_SECONDS
        elif isinstance(e, ChatWriteForbidden):
            result['cooldown_until'] = time.time() + 3600
        return result
    except Exception as e:
        fatal = _is_fatal_error(e)
        error = _friendly_peer_error(e)
        result = {
            'ok': False,
            'error': error,
            'fatal': fatal,
            'expired': fatal,
        }
        if 'FROZEN_METHOD_INVALID' in str(e).upper():
            result['frozen'] = True
        if _needs_reauthentication(str(e)):
            result['reauth_required'] = True
        return result


# ---------------------------------------------------------------------------
# Main execute_campaign
# ---------------------------------------------------------------------------

async def execute_campaign(
    camp: dict,
    accounts: list,
    user_id: int,
    camp_index: int,
    on_progress: Optional[Callable] = None,
    resume_ids: Optional[list] = None,
    retry_ids: Optional[list] = None,
    dry_run: bool = False,
) -> dict:
    """
    Execute a campaign against a list of accounts.

    Returns a result dict:
      {'done': int, 'failed': int, 'skipped': int, 'errors': list,
       'stopped': bool, 'paused': bool, 'paused_remaining': list,
       'dead_alerts': list}
    """
    import storage

    speed  = storage.get_settings(user_id).get('speed', 'slow')
    preset = SPEED_PRESETS.get(speed, SPEED_PRESETS['slow'])
    workers     = preset['workers']
    min_delay   = preset['min_delay']
    max_delay   = preset['max_delay']

    # Per-user or global cooldown override
    user_cd   = storage.get_cooldown_minutes(user_id) * 60
    global_cd = storage.get_global_cooldown_minutes() * 60
    # "Off" must not mean "reuse the same account immediately". A short
    # mandatory rest is the minimum protection against repeated actions on the
    # same Telegram identity.
    effective_cd = max(
        user_cd,
        global_cd,
        MIN_ACCOUNT_COOLDOWN_SECONDS,
    )

    # Determine working set
    label_filter = camp.get('label') or camp.get('label_filter')
    if label_filter:
        working = [a for a in accounts if label_filter in a.get('labels', [])]
    else:
        working = list(accounts)

    # Limit the selected pool before checking cooldowns, so progress totals
    # remain accurate when a campaign has a max_accounts setting.
    max_accts = camp.get('max_accounts') or camp.get('camp_max_accounts')
    if max_accts and str(max_accts).isdigit():
        working = working[:int(max_accts)]

    # Filter to only active accounts and skip accounts that are still cooling
    # down from a previous run or FloodWait.
    working = [a for a in working if a.get('status', 'active') == 'active']
    now = time.time()
    throttled = []
    ready = []
    for account in working:
        try:
            until = float(account.get('throttled_until') or 0)
        except (TypeError, ValueError):
            until = 0
        if until > now:
            throttled.append(account)
        else:
            ready.append(account)
    working = ready

    # Resume from a subset if requested
    if resume_ids:
        id_set = set(str(r) for r in resume_ids)
        working = [a for a in working
                   if str(a.get('identifier') or a.get('phone') or
                          a.get('user_id') or a.get('id', '')) in id_set]
    elif retry_ids:
        id_set = set(str(r) for r in retry_ids)
        working = [a for a in working
                   if str(a.get('identifier') or a.get('phone') or
                          a.get('user_id') or a.get('id', '')) in id_set]

    total = len(working) + len(throttled)
    result = {
        'done': 0, 'failed': 0, 'skipped': len(throttled),
        'errors': [], 'stopped': False, 'paused': False,
        'paused_remaining': [], 'dead_alerts': [],
    }

    if dry_run or not working:
        return result

    api_id   = _API_ID
    api_hash = _API_HASH

    semaphore = asyncio.Semaphore(workers)

    async def process_one(idx: int, acc: dict):
        async with semaphore:
            identifier = (
                acc.get('identifier')
                or acc.get('phone')
                or str(acc.get('user_id') or acc.get('id', idx))
            )

            if storage.is_campaign_stop_requested(user_id, camp_index):
                result['stopped'] = True
                result['paused_remaining'].append(identifier)
                return

            if storage.is_campaign_pause_requested(user_id, camp_index):
                result['paused'] = True
                result['paused_remaining'].append(identifier)
                return

            res = await run_campaign_on_account(acc, camp, api_id=api_id, api_hash=api_hash)

            stored_accounts = storage.get_accounts(user_id)
            stored_idx = next(
                (
                    i for i, stored in enumerate(stored_accounts)
                    if str(
                        stored.get('identifier')
                        or stored.get('phone')
                        or stored.get('user_id')
                        or stored.get('id', '')
                    ) == str(identifier)
                ),
                None,
            )

            if res['ok']:
                result['done'] += 1
                storage.update_account_last_used(user_id, identifier, int(time.time()))
                storage.increment_campaign_actions(user_id, camp_index, 1)
                if stored_idx is not None:
                    storage.set_account_throttle(
                        user_id,
                        stored_idx,
                        int(time.time()) + effective_cd,
                    )
            else:
                result['failed'] += 1
                result['errors'].append(f'{identifier}: {res["error"]}')
                storage.increment_account_fail_count(user_id, identifier)
                cooldown_until = res.get('cooldown_until') or res.get('flood_until')
                if cooldown_until and stored_idx is not None:
                    storage.set_account_throttle(
                        user_id,
                        stored_idx,
                        max(
                            int(float(cooldown_until)),
                            int(time.time()) + MIN_ACCOUNT_COOLDOWN_SECONDS,
                        ),
                    )
                # Campaigns are non-destructive. Do not change an account's
                # stored status from a single campaign error; run the
                # explicit Session Health check before requiring re-login.
                if res['fatal']:
                    result['dead_alerts'].append(identifier)

            if on_progress:
                done_so_far = result['done'] + result['failed'] + result['skipped']
                try:
                    await on_progress(done_so_far, total, result)
                except Exception:
                    pass

            # Inter-account delay
            await asyncio.sleep(random.uniform(min_delay, max_delay))

    tasks = [process_one(i, acc) for i, acc in enumerate(working)]
    await asyncio.gather(*tasks)

    # Clean up stop/pause flags
    if result['stopped']:
        try:
            storage.clear_campaign_stop(user_id, camp_index)
        except Exception:
            pass
    if result['paused']:
        try:
            storage.set_campaign_paused_remaining(user_id, camp_index, result['paused_remaining'])
            storage.set_campaign_pause(user_id, camp_index)
        except Exception:
            pass
    else:
        try:
            storage.clear_campaign_pause(user_id, camp_index)
            storage.clear_campaign_paused_remaining(user_id, camp_index)
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------

async def run_campaign(application, user_id: int, camp_index: int):
    """
    High-level entry point called by the scheduler and schedule runner.
    Runs the campaign and updates storage state; does not send any Telegram messages.
    """
    import storage

    if storage.is_campaign_running(user_id, camp_index):
        logger.info('Campaign %s/%s already running, skipping duplicate start', user_id, camp_index)
        return

    campaigns = storage.get_campaigns(user_id)
    if camp_index >= len(campaigns):
        logger.warning('Campaign index %s out of range for user %s', camp_index, user_id)
        return

    camp     = campaigns[camp_index]
    accounts = storage.get_accounts(user_id)

    storage.set_campaign_running(user_id, camp_index, True)
    start_ts = int(time.time())

    try:
        result = await execute_campaign(camp, accounts, user_id, camp_index)
    except Exception as exc:
        logger.exception('execute_campaign failed for user %s camp %s: %s', user_id, camp_index, exc)
        result = {'done': 0, 'failed': 0, 'skipped': 0, 'errors': [str(exc)],
                  'stopped': False, 'paused': False, 'paused_remaining': [], 'dead_alerts': []}
    finally:
        if not result.get('paused'):
            storage.set_campaign_running(user_id, camp_index, False)

    elapsed = int(time.time()) - start_ts
    record  = {
        'ts':      __import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
        'done':    result.get('done',    0),
        'failed':  result.get('failed',  0),
        'skipped': result.get('skipped', 0),
        'elapsed': elapsed,
        'stopped': result.get('stopped', False),
        'paused':  result.get('paused',  False),
    }
    try:
        storage.append_campaign_run_log(user_id, camp_index, record)
    except Exception as exc:
        logger.warning('append_campaign_run_log failed: %s', exc)

    if result.get('dead_alerts'):
        try:
            storage.set_campaign_last_failed(user_id, camp_index, result['dead_alerts'])
        except Exception:
            pass

    logger.info(
        'Campaign %s/%s finished: done=%s failed=%s stopped=%s paused=%s elapsed=%ss',
        user_id, camp_index,
        result['done'], result['failed'],
        result['stopped'], result['paused'], elapsed,
    )
