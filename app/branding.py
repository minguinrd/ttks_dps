"""Key/value site settings that back the deploy-wide branding."""

import re

from flask import url_for
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models.setting import Setting

DEFAULTS: dict[str, str] = {
    "site_name": "Tech Support",
    "accent_color": "#0d6efd",
}


def get_setting(key: str) -> str | None:
    try:
        row = db.session.get(Setting, key)
    except OperationalError:
        # Un-migrated database (app booted before ``db upgrade``): treat every
        # setting as unset so branding falls back to defaults instead of
        # breaking every page render. Writes stay strict (see ``set_setting``).
        db.session.rollback()
        return None
    return row.value if row else None


def set_setting(key: str, value: str) -> None:
    """Upsert ``key`` and commit."""
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key)
        db.session.add(row)
    row.value = value
    db.session.commit()


def get_branding() -> dict:
    site_name = get_setting("site_name") or DEFAULTS["site_name"]
    accent = get_setting("accent_color")
    if accent is None or re.fullmatch(r"#[0-9a-fA-F]{6}", accent) is None:
        # Sanitized on read so a corrupt/hostile row can never reach the
        # ``--brand-accent`` CSS variable (write-side validation is Task 2).
        accent = DEFAULTS["accent_color"]
    has_logo = bool(get_setting("logo_file"))
    return {
        "site_name": site_name,
        "accent_color": accent,
        "has_logo": has_logo,
        "logo_url": url_for("main.branding_logo") if has_logo else None,
    }
