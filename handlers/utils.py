"""Shared utilities for handler modules."""


def escape_md(text: str) -> str:
    """Escape special characters for Telegram legacy Markdown mode.

    In legacy Markdown, ``_``, ``*``, `` ` ``, and ``[`` are formatting
    markers.  Any user-supplied string inserted *outside* a code-span must
    have these characters escaped so Telegram's parser doesn't mis-interpret
    them as entity boundaries.
    """
    if not isinstance(text, str):
        text = str(text)
    for ch in ('_', '*', '`', '['):
        text = text.replace(ch, f'\\{ch}')
    return text
