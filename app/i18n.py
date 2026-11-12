"""Per-user display language: locale resolution and catalog lookup.

Message keys are the English source strings themselves and there is no
``en.json``: ``translate`` falls back to the source, so English pages stay
byte-identical whether or not a key exists in a catalog.

Locale is resolved per request (``g.locale``, set by the ``before_request``
hook in :func:`app.create_app`) — never baked at import time. Anonymous
users always get ``en``; there is no browser detection.
"""

import json
from pathlib import Path

from flask import g

SUPPORTED: tuple[str, ...] = ("en", "es")

_CATALOG_DIR = Path(__file__).parent / "locales"
# locale -> flat {source string: translation}, read lazily once per process.
_catalog_cache: dict[str, dict[str, str]] = {}


def _load_catalog(locale: str) -> dict[str, str]:
    if locale not in _catalog_cache:
        try:
            data = json.loads((_CATALOG_DIR / f"{locale}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _catalog_cache[locale] = data
    return _catalog_cache[locale]


def get_locale() -> str:
    """Locale for the current request (``"en"`` when none was set)."""
    return getattr(g, "locale", "en")


def translate(message: str, **params) -> str:
    """Translate ``message`` in the current locale, falling back to the source.

    ``params`` are interpolated after lookup (translate-then-format).
    """
    text = _load_catalog(get_locale()).get(message, message)
    return text.format(**params) if params else text


# Python code marks strings as ``from app.i18n import _``.
_ = translate
