"""The platform owner's password can be changed from the command line."""
import os

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app
from app.cli import set_platform_owner_password_cmd
from app.extensions import db
from app.models import User, UserRole


def _app_with_owner():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "WTF_CSRF_ENABLED": False,
                      "MAIL_SUPPRESS_SEND": True, "STORAGE_BACKEND": "local", "LOCAL_STORAGE_DIR": "./var/test-uploads"})
    with app.app_context():
        db.create_all()
        owner = User(email="admin@hub1z.com", full_name="Platform Owner", role=UserRole.PLATFORM_OWNER,
                     is_active=True, email_verified=True)
        owner.set_password("ChangeMe123!")
        db.session.add(owner)
        db.session.commit()
    return app


def test_password_is_changed_and_short_ones_are_refused():
    app = _app_with_owner()
    runner = app.test_cli_runner()
    short = runner.invoke(set_platform_owner_password_cmd, ["--password", "short"])
    assert short.exit_code != 0 and "at least 12" in short.output
    ok = runner.invoke(set_platform_owner_password_cmd, ["--password", "A-Much-Longer-Passphrase-1"])
    assert ok.exit_code == 0, ok.output
    with app.app_context():
        owner = User.query.filter_by(email="admin@hub1z.com").one()
        assert owner.check_password("A-Much-Longer-Passphrase-1") and not owner.check_password("ChangeMe123!")


def test_unknown_owner_email_is_an_error():
    app = _app_with_owner()
    result = app.test_cli_runner().invoke(set_platform_owner_password_cmd,
                                          ["--email", "nobody@hub1z.com", "--password", "A-Much-Longer-Passphrase-1"])
    assert result.exit_code != 0 and "No Platform Owner" in result.output
