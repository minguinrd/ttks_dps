"""Branding settings: site name, accent color, and logo state."""

import re

from app.branding import get_branding, set_setting


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
