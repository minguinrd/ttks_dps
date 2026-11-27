"""Navbar light/dark switch."""

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_navbar_has_theme_toggle_next_to_notifications(client, user_factory, login):
    login(client, user_factory(username="theme-user"))

    html = client.get("/tickets/mine").get_data(as_text=True)

    toggle = html.index("data-theme-toggle")
    assert toggle < html.index('href="/notifications"')
    assert 'aria-pressed="false"' in html
    # The early theme script honours a saved choice before the system one.
    assert 'localStorage.getItem("theme")' in html


def test_theme_toggle_script_persists_choice():
    js = (_STATIC / "js" / "app.js").read_text(encoding="utf-8")

    assert "[data-theme-toggle]" in js
    assert 'localStorage.setItem("theme", next)' in js


def test_view_transition_opt_in_is_inline(client, user_factory, login):
    # In main.css the opt-in can be missing when the browser checks the
    # incoming page, which aborts the transition with an uncaught
    # "ViewTransition opt-in disabled" error.
    login(client, user_factory(username="vt-user"))

    html = client.get("/tickets/mine").get_data(as_text=True)
    css = (_STATIC / "css" / "main.css").read_text(encoding="utf-8")

    assert html.index("@view-transition") < html.index("css/main.css")
    assert "@view-transition" not in css
