"""Translation completeness gate: marked literals ↔ ``app/locales/es.json``.

Key collection scans ``app/templates/**/*.html`` and ``app/**/*.py`` for
literal catalog keys in two call shapes: ``_()`` marks (the template/Python
marking convention) and ``notify(key=...)`` notification sentences (keyed but
never passed through the translate call). ``app/i18n.py`` is skipped: its
docstrings illustrate the machinery and are not UI strings.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
CATALOG_PATH = APP_DIR / "locales" / "es.json"

# Literal catalog keys: _("...") marks and notify(key="...") sentences.
_MARKED = re.compile(r"_\(\s*[\"']([^\"']+)[\"']")
_NOTIFY_KEY = re.compile(r"notify\(.*?key\s*=\s*[\"']([^\"']+)[\"']", re.DOTALL)
# Computed keys (f-strings / concatenation) can never match the catalog.
_DYNAMIC_KEY = re.compile(r"_\(\s*(?:f[\"']|[\"']\s*\+)")


def _source_files() -> list[Path]:
    """Templates plus app Python, skipping the i18n module's internals."""
    templates = sorted((APP_DIR / "templates").rglob("*.html"))
    python = sorted(path for path in APP_DIR.rglob("*.py") if path.name != "i18n.py")
    return templates + python


def _collect_keys() -> set[str]:
    keys: set[str] = set()
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        keys.update(_MARKED.findall(text))
        keys.update(_NOTIFY_KEY.findall(text))
    return keys


def test_all_marked_strings_translated():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    missing = sorted(key for key in _collect_keys() if key not in catalog)
    assert not missing, f"marked strings missing from es.json: {missing}"


def test_no_stale_catalog_keys():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    marked = _collect_keys()
    stale = sorted(key for key in catalog if key not in marked)
    assert not stale, f"stale es.json keys (unmarked in app source): {stale}"


def test_no_dynamic_translation_keys():
    offenders = []
    for path in sorted((APP_DIR / "templates").rglob("*.html")) + sorted(APP_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _DYNAMIC_KEY.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)!r}")
    assert not offenders, f"computed translation keys (use literal keys): {offenders}"


def test_spanish_user_sees_spanish_queue(app, client, user_factory, login):
    user = user_factory(username="es-queue-agent", role="agent", language="es")
    login(client, user)

    html = client.get("/tickets/queue").get_data(as_text=True)

    assert re.search(r"<h1[^>]*>Cola de tickets</h1>", html)
    assert not re.search(r"<h1[^>]*>Ticket Queue</h1>", html)


def test_confirm_dialog_chrome_translates(app, client, user_factory, login):
    # SweetAlert2's modal chrome (title, confirm/cancel buttons) must follow
    # the reader's language too: the shared data-confirm handler reads these
    # data attributes off <body> (app/static/js/app.js), with English fallbacks.
    user = user_factory(username="es-confirm", language="es")
    login(client, user)

    html = client.get("/notifications").get_data(as_text=True)

    assert '<html lang="es">' in html
    assert 'data-confirm-title="¿Estás seguro?"' in html
    assert 'data-confirm-yes="Sí"' in html
    assert 'data-confirm-cancel="Cancelar"' in html

    # English pages stay byte-identical: plain lang="en", English chrome.
    anon_html = app.test_client().get("/auth/login").get_data(as_text=True)
    assert '<html lang="en">' in anon_html
    assert 'data-confirm-title="Are you sure?"' in anon_html
    assert 'data-confirm-yes="Yes"' in anon_html
    assert 'data-confirm-cancel="Cancel"' in anon_html


def test_role_labels_translate_correctly():
    # Role words name the *person*, not the administrative function: a user
    # with role="admin" is an "Administrador", never "Administración".
    # Keys asserted: the AdminUserForm role option labels ("User"/"Agent"/
    # "Admin", app/admin/forms.py role_labels) and the role badge labels
    # ("user"/"agent"/"admin", macros/badges.html role_label).
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    expected = {
        "User": "Usuario",
        "Agent": "Agente",
        "Admin": "Administrador",
        "user": "usuario",
        "agent": "agente",
        "admin": "administrador",
    }
    wrong = {key: catalog.get(key) for key, value in expected.items() if catalog.get(key) != value}
    assert not wrong, f"role keys must name the person: {wrong}"
