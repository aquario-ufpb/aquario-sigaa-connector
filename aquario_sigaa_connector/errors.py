"""Closed registry of sanitized public failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class FailureDefinition:
    status_code: int
    code: str
    message: str


class FailureKind(Enum):
    UNAUTHORIZED = FailureDefinition(401, "UNAUTHORIZED", "Authentication is required.")
    CONNECTOR_MISCONFIGURED = FailureDefinition(
        503, "CONNECTOR_MISCONFIGURED", "Connector is unavailable."
    )
    INVALID_REQUEST = FailureDefinition(422, "INVALID_REQUEST", "Request validation failed.")
    REQUEST_TOO_LARGE = FailureDefinition(413, "REQUEST_TOO_LARGE", "Request body is too large.")
    CONNECTOR_BUSY = FailureDefinition(503, "CONNECTOR_BUSY", "Connector is busy.")
    SIGAA_AUTH_FAILED = FailureDefinition(401, "SIGAA_AUTH_FAILED", "SIGAA authentication failed.")
    SIGAA_IDENTITY_INVALID = FailureDefinition(
        502, "SIGAA_IDENTITY_INVALID", "SIGAA returned an invalid account identity."
    )
    SIGAA_IDENTITY_MISMATCH = FailureDefinition(
        409,
        "SIGAA_IDENTITY_MISMATCH",
        "The SIGAA account does not match the Aquario profile.",
    )
    SIGAA_TIMEOUT = FailureDefinition(504, "SIGAA_TIMEOUT", "SIGAA took too long to respond.")
    CONNECTOR_DEADLINE = FailureDefinition(
        504,
        "CONNECTOR_DEADLINE",
        "The connector stopped waiting for SIGAA.",
    )
    SIGAA_UNAVAILABLE = FailureDefinition(
        503, "SIGAA_UNAVAILABLE", "SIGAA is temporarily unavailable."
    )
    SIGAA_RESPONSE_INVALID = FailureDefinition(
        502, "SIGAA_RESPONSE_INVALID", "SIGAA returned an unsupported response."
    )
    INTERNAL_ERROR = FailureDefinition(500, "INTERNAL_ERROR", "Connector request failed.")

    @property
    def status_code(self) -> int:
        return self.value.status_code

    @property
    def code(self) -> str:
        return self.value.code

    @property
    def public_message(self) -> str:
        return self.value.message


class ConnectorError(Exception):
    def __init__(self, kind: FailureKind):
        super().__init__(kind.code)
        self.kind = kind

    @property
    def status_code(self) -> int:
        return self.kind.status_code

    @property
    def code(self) -> str:
        return self.kind.code

    @property
    def public_message(self) -> str:
        return self.kind.public_message
