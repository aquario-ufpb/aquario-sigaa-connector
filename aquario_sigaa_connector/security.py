"""Authentication boundary for calls from the Aquario backend."""

from __future__ import annotations

import hmac
import os

from fastapi import Header

from .errors import ConnectorError, FailureKind

_MINIMUM_SECRET_LENGTH = 32


def require_connector_auth(authorization: str | None = Header(default=None)) -> None:
    configured = os.environ.get("CONNECTOR_API_SECRET")
    if not configured or len(configured) < _MINIMUM_SECRET_LENGTH:
        raise ConnectorError(FailureKind.CONNECTOR_MISCONFIGURED)

    scheme, _, token = (authorization or "").partition(" ")
    valid = scheme.lower() == "bearer" and hmac.compare_digest(
        token.encode("utf-8"),
        configured.encode("utf-8"),
    )
    if not valid:
        raise ConnectorError(FailureKind.UNAUTHORIZED)
