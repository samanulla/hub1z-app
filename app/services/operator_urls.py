from flask import current_app, request
from urllib.parse import urlsplit


def workspace_url(operator, path="/auth/login"):
    host = operator.primary_domain
    local = current_app.testing or current_app.debug
    port = urlsplit(request.host_url).port if local else None
    if port and ":" not in host:
        host = f"{host}:{port}"
    return f"{'http' if local else 'https'}://{host}{path}"