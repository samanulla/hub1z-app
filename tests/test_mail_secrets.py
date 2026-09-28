"""Secrets Manager mail-credential loading is opt-in and never blocks startup."""
import os
os.environ.setdefault("FLASK_ENV", "testing")

from unittest.mock import patch

from app import create_app
from app.services import secrets_manager


def test_no_secret_name_leaves_mail_config_untouched():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "MAIL_USERNAME": "plain-user", "MAIL_PASSWORD": "plain-pass",
                      "MAIL_CREDENTIALS_SECRET_NAME": ""})
    assert app.config["MAIL_USERNAME"] == "plain-user"
    assert app.config["MAIL_PASSWORD"] == "plain-pass"


def test_secret_fetch_overrides_mail_credentials():
    with patch.object(secrets_manager, "_fetch_secret_json",
                      return_value={"username": "secret-user", "password": "secret-pass"}) as mocked:
        app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                          "MAIL_USERNAME": "plain-user", "MAIL_PASSWORD": "plain-pass",
                          "MAIL_CREDENTIALS_SECRET_NAME": "hub1z/prod/ses-smtp"})
        mocked.assert_called_once()
    assert app.config["MAIL_USERNAME"] == "secret-user"
    assert app.config["MAIL_PASSWORD"] == "secret-pass"


def test_secret_fetch_failure_does_not_crash_app_startup():
    with patch.object(secrets_manager, "_fetch_secret_json", side_effect=RuntimeError("boom")):
        app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                          "MAIL_USERNAME": "plain-user", "MAIL_PASSWORD": "plain-pass",
                          "MAIL_CREDENTIALS_SECRET_NAME": "hub1z/prod/ses-smtp"})
    assert app.config["MAIL_USERNAME"] == "plain-user"
    assert app.config["MAIL_PASSWORD"] == "plain-pass"
