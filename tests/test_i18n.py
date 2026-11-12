"""Per-user display language: locale resolution, translate() fallback, selector."""

import re

from flask import g

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


def test_anonymous_pages_default_to_spanish(client):
    # Spanish is the default locale: anonymous requests carry no stored
    # preference yet, so they render the catalog translation. Locale still
    # never comes from the browser.
    resp = client.get("/auth/login")

    html = resp.get_data(as_text=True)
    assert '<html lang="es">' in html
    assert "Iniciar sesión" in html
    assert "Sign in" not in html


def test_outside_app_context_stays_english():
    # Import-time key marking (module-level constants such as
    # FORCED_PASSWORD_CHANGE_MESSAGE) runs with no request locale: it must
    # stay English source so translation happens per request, not at import.
    assert translate("Sign in") == "Sign in"


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


def test_placeholder_pattern_translation(app):
    # Validator errors arrive as concrete messages; catalog keys keep {min}/
    # {max} slots and app.i18n matches the concrete text against them (the
    # macros/forms.html error rendering path).
    with app.app_context():
        g.locale = "es"
        # The catalog key keeps its placeholders so callers can format them.
        template = translate("Field must be between {min} and {max} characters long.")
        assert template == "El campo debe tener entre {min} y {max} caracteres."
        assert template.format(min=8, max=128) == "El campo debe tener entre 8 y 128 caracteres."
        # The concrete message matches the pattern and is re-formatted with
        # the captured values.
        concrete = translate("Field must be between 8 and 128 characters long.")
        assert concrete == "El campo debe tener entre 8 y 128 caracteres."
