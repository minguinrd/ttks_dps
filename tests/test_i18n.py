"""Per-user display language: locale resolution, translate() fallback, selector."""

import re

from flask import g

from app import i18n
from app.extensions import db
from app.i18n import translate
from app.models import User


def test_language_selector_requires_login(app, client, user_factory):
    user = user_factory(username="anonling")

    resp = client.post("/profile/language", data={"language": "es"})

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/auth/login")
    with app.app_context():
        assert db.session.get(User, user.id).language == "en"


def test_language_save_switches_locale(app, client, user_factory, login):
    user = user_factory(username="polyglot")
    login(client, user)

    resp = client.post("/profile/language", data={"language": "es"})

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/profile"
    with app.app_context():
        assert db.session.get(User, user.id).language == "es"

    # The profile heading switches to the pinned Spanish string ("Perfil",
    # the es.json translation of "Profile") and drops the English heading.
    html = client.get("/profile").get_data(as_text=True)
    assert re.search(r"<h1[^>]*>Perfil</h1>", html)
    assert not re.search(r"<h1[^>]*>Profile</h1>", html)


def test_anonymous_pages_stay_english(client, monkeypatch):
    # Even with a Spanish catalog entry for "Sign in", anonymous requests stay
    # English: locale comes from the user row, never from the browser.
    monkeypatch.setitem(i18n._catalog_cache, "es", {"Sign in": "Iniciar sesión"})

    resp = client.get("/auth/login")

    html = resp.get_data(as_text=True)
    assert "Sign in" in html
    assert "Iniciar sesión" not in html


def test_invalid_language_value_rejected(app, client, user_factory, login):
    user = user_factory(username="francois")
    login(client, user)

    resp = client.post("/profile/language", data={"language": "fr"})

    assert resp.status_code == 200
    assert "Not a valid choice." in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(User, user.id).language == "en"


def test_missing_catalog_falls_back_to_source(app):
    with app.app_context():
        g.locale = "es"
        assert translate("Untranslated sentinél") == "Untranslated sentinél"
