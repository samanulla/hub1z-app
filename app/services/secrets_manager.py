"""Optional: load mail SMTP credentials from AWS Secrets Manager instead of
plain env vars, using the EC2 instance's IAM role (no static AWS keys on
disk). No-ops when MAIL_CREDENTIALS_SECRET_NAME isn't set, so local/dev/test
configs that use plain MAIL_USERNAME/MAIL_PASSWORD env vars are unaffected.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def _fetch_secret_json(secret_name: str, region: str) -> dict:
    import boto3
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


def load_mail_credentials(app) -> None:
    """Override MAIL_USERNAME/MAIL_PASSWORD from Secrets Manager, if configured.

    Expects the secret to be a JSON object: {"username": "...", "password": "..."}.
    Never raises — a Secrets Manager hiccup should not block app startup.
    """
    secret_name = app.config.get("MAIL_CREDENTIALS_SECRET_NAME")
    if not secret_name:
        return
    try:
        secret = _fetch_secret_json(secret_name, app.config.get("AWS_REGION", "us-east-1"))
        app.config["MAIL_USERNAME"] = secret.get("username") or app.config.get("MAIL_USERNAME")
        app.config["MAIL_PASSWORD"] = secret.get("password") or app.config.get("MAIL_PASSWORD")
    except Exception:  # noqa: BLE001 - never block app startup on a secrets hiccup
        logger.exception("Could not load mail credentials from Secrets Manager secret %s", secret_name)
