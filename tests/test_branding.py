"""Branding settings: site name, accent color, and logo state."""

import re

import pytest
from sqlalchemy.exc import OperationalError

from app.branding import get_branding, set_setting
from app.extensions import db


def test_settings_defaults_without_rows(app, db_schema):
    with app.app_context():
        branding = get_branding()
    assert branding["site_name"] == "Tech Support"
    assert branding["accent_color"] == "#0d6efd"
    assert branding["has_logo"] is False


def test_branding_context_reflects_settings(app, db_schema, client):
    with app.app_context():
        set_setting("site_name", "Acme IT")
    html = client.get("/auth/login").get_data(as_text=True)
    assert re.search(r"<title>[^<]*Acme IT[^<]*</title>", html)
    assert re.search(r'<a class="navbar-brand"[^>]*>\s*Acme IT\s*</a\s*>', html)


def test_accent_color_css_var_rendered(app, db_schema, client):
    with app.app_context():
        set_setting("accent_color", "#123456")
    html = client.get("/auth/login").get_data(as_text=True)
    assert "--brand-accent: #123456" in html


def test_accent_color_sanitized_on_render(app, db_schema, client):
    with app.app_context():
        set_setting("accent_color", "#fff;</style><script>alert(1)</script>")
    html = client.get("/auth/login").get_data(as_text=True)
    assert "#0d6efd" in html
    assert "<script>alert(1)</script>" not in html


def test_branding_db_error_not_silent(app, db_schema, monkeypatch):
    """Only the missing-``settings``-table case degrades to defaults.

    Any other OperationalError (lock, I/O) must propagate instead of being
    silently swallowed as "default branding".
    """

    def raise_operational(message):
        def _get(*args, **kwargs):
            raise OperationalError(message, None, Exception(message))

        return _get

    with app.app_context():
        monkeypatch.setattr(db.session, "get", raise_operational("no such table: settings"))
        assert get_branding() == {
            "site_name": "Tech Support",
            "accent_color": "#0d6efd",
            "has_logo": False,
            "logo_url": None,
        }

        monkeypatch.setattr(db.session, "get", raise_operational("database is locked"))
        with pytest.raises(OperationalError, match="database is locked"):
            get_branding()


def test_active_nav_link_rule_present(app, db_schema, client):
    """The active-nav-link accent rule must out-specific Bootstrap's own
    ``.navbar-nav .nav-link.active`` rule."""
    html = client.get("/auth/login").get_data(as_text=True)
    assert re.search(
        r"\.navbar\s+\.navbar-nav\s+\.nav-link\.active\s*\{[^}]*var\(--brand-accent\)", html
    )
