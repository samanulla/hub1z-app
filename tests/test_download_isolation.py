"""Local-mode file downloads never cross operators or companies."""
import os
from pathlib import Path

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.cli import PERSONA_PASSWORD, seed_personas_cmd
from app.extensions import db
from tests.test_role_paths import APEX, DEMO, OTHER, OWNER_PASSWORD, _login


def _app(tmp_path):
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local", "LOCAL_STORAGE_DIR": str(tmp_path),
                      "PLATFORM_BASE_DOMAIN": "localhost", "RATELIMIT_ENABLED": False})
    with app.app_context():
        db.create_all()
    assert app.test_cli_runner().invoke(seed_personas_cmd).exit_code == 0
    return app


def _keys(app, tmp_path):
    from app.models import Company, Operator
    with app.app_context():
        companies = {c.name: c.id for c in Company.query.execution_options(skip_operator_filter=True).all()}
        demo, other = (Operator.query.filter_by(slug=slug).one().id for slug in ("demo", "other"))
    keys = {
        "demo_doc": f"operators/{demo}/documents/own.pdf",
        "acme": f"operators/{demo}/companies/{companies['Acme Co']}/kyc.pdf",
        "zenith": f"operators/{demo}/companies/{companies['Zenith Traders']}/kyc.pdf",
        "other_doc": f"operators/{other}/documents/theirs.pdf",
        "platform": "platform/documents/internal.pdf",
    }
    for key in keys.values():
        path = Path(tmp_path) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"file")
    return keys


def _status(client, host, key):
    return client.get(f"/downloads/{key}", headers={"Host": host}).status_code


def _client(app, host, email, password=PERSONA_PASSWORD):
    client = app.test_client()
    assert _login(client, host, email, password).status_code == 302
    return client


def test_each_user_reads_only_their_own_operator_and_company_files(tmp_path):
    app = _app(tmp_path)
    keys = _keys(app, tmp_path)

    owner = _client(app, DEMO, "owner@demospace.com")
    assert [_status(owner, DEMO, keys[name]) for name in ("demo_doc", "acme", "zenith")] == [200, 200, 200]
    assert [_status(owner, DEMO, keys[name]) for name in ("other_doc", "platform")] == [404, 404]
    assert _status(owner, DEMO, keys["demo_doc"].replace("/documents/", "/../documents/")) == 404

    other = _client(app, OTHER, "owner@otherspace.com")
    assert _status(other, OTHER, keys["other_doc"]) == 200
    assert [_status(other, OTHER, keys[name]) for name in ("demo_doc", "acme", "platform")] == [404, 404, 404]

    company_admin = _client(app, DEMO, "admin@acmeco.com")
    assert _status(company_admin, DEMO, keys["acme"]) == 200
    assert [_status(company_admin, DEMO, keys[name]) for name in ("zenith", "demo_doc", "other_doc")] == [404, 404, 404]

    for email in ("employee@acmeco.com", "individual@demospace.com"):
        member = _client(app, DEMO, email)
        assert _status(member, DEMO, keys["acme"]) == 404, email

    platform = _client(app, APEX, "admin@hub1z.com", OWNER_PASSWORD)
    assert _status(platform, APEX, keys["platform"]) == 200
    assert [_status(platform, APEX, keys[name]) for name in ("demo_doc", "other_doc")] == [404, 404]

    assert _status(app.test_client(), DEMO, keys["demo_doc"]) == 401
