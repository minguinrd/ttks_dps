"""Per-user display language: locale resolution and catalog lookup.

Message keys are the English source strings themselves and there is no
``en.json``: ``translate`` falls back to the source, so English pages stay
byte-identical whether or not a key exists in a catalog.

Locale is resolved per request (``g.locale``, set by the ``before_request``
hook in :func:`app.create_app`) — never baked at import time. Anonymous
users get the default locale, ``es``; there is no browser detection.

On a lookup miss (and without params) catalog keys containing
``{placeholders}`` are matched as patterns against the concrete message and
re-formatted with the captured values — that is how parameterized validator
errors such as "Field must be between 8 and 128 characters long." translate
without any per-form bookkeeping.
"""

import json
import re
from pathlib import Path

from flask import g

SUPPORTED: tuple[str, ...] = ("en", "es")

_CATALOG_DIR = Path(__file__).parent / "locales"
# locale -> flat {source string: translation}, read lazily once per process.
_catalog_cache: dict[str, dict[str, str]] = {}
# {name} slots inside a catalog key, used for the pattern fallback below.
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load_catalog(locale: str) -> dict[str, str]:
    if locale not in _catalog_cache:
        try:
            data = json.loads((_CATALOG_DIR / f"{locale}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _catalog_cache[locale] = data
    return _catalog_cache[locale]


def get_locale() -> str:
    """Locale for the current request (``"es"`` when none was set).

    Also returns ``"en"`` outside an application context, so import-time key
    marking (e.g. form labels) stays plain English source.
    """
    try:
        return getattr(g, "locale", "es")
    except RuntimeError:  # pragma: no cover - only hit outside an app context
        return "en"


def _match_pattern(catalog: dict[str, str], message: str) -> str | None:
    """Match ``message`` against the placeholder keys of ``catalog``.

    A key like ``Field must be between {min} and {max} characters long.``
    becomes a regex whose placeholder slots capture the concrete values; the
    Spanish template is re-formatted with them. Exact keys never reach this
    path (``translate`` looks those up first).
    """
    for key, template in catalog.items():
        names = _PLACEHOLDER.findall(key)
        if not names:
            continue
        parts = _PLACEHOLDER.split(key)
        pattern = "".join(
            re.escape(part) if index % 2 == 0 else "(.+?)" for index, part in enumerate(parts)
        )
        match = re.fullmatch(pattern, message)
        if match:
            try:
                return template.format(**dict(zip(names, match.groups())))
            except (KeyError, IndexError):
                continue  # placeholder names in the translation drifted; try the next key
    return None


def translate(message: str, **params) -> str:
    """Translate ``message`` in the current locale, falling back to the source.

    ``params`` are interpolated after lookup (translate-then-format).
    """
    catalog = _load_catalog(get_locale())
    text = catalog.get(message)
    if text is None and not params:
        text = _match_pattern(catalog, message)
    if text is None:
        text = message
    return text.format(**params) if params else text


# Python code marks strings as ``from app.i18n import _``.
_ = translate
