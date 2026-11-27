"""Shared helpers for free-text search boxes."""

# Escape character passed to ``ilike(..., escape=LIKE_ESCAPE)``.
LIKE_ESCAPE = "\\"


def like_pattern(text: str) -> str:
    """``%text%`` for a LIKE match, with ``%``/``_`` in ``text`` matched literally."""
    escaped = (
        text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"
