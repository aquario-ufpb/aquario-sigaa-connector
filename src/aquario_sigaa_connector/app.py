"""Private FastAPI application exposed as a Vercel Python Function."""

from __future__ import annotations

from typing import Annotated, Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .contracts import ErrorBody, ErrorResponse, HealthResponse, SyncRequest, SyncResponse
from .errors import ConnectorError, FailureKind
from .execution import BoundedSyncExecutor
from .security import require_connector_auth
from .service import PucaVazSyncProvider, SyncCommand, _SyncProvider

MAX_REQUEST_BODY_BYTES = 16 * 1024


class _SyncExecutor(Protocol):
    async def execute(self, command: SyncCommand) -> SyncResponse: ...


class _SecureBoundaryMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        received = 0
        body_too_large = False
        replacement_sent = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal body_too_large, received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    body_too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def send_with_security_headers(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"pragma", b"no-cache"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-request-id", request_id.encode("ascii")),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        async def secure_send(message: Message) -> None:
            nonlocal replacement_sent
            if body_too_large:
                if not replacement_sent:
                    replacement_sent = True
                    response = _error_response(FailureKind.REQUEST_TOO_LARGE)
                    await response(scope, receive, send_with_security_headers)
                return
            await send_with_security_headers(message)

        try:
            await self.app(scope, limited_receive, secure_send)
        except Exception:
            if response_started:
                raise
            kind = FailureKind.REQUEST_TOO_LARGE if body_too_large else FailureKind.INTERNAL_ERROR
            response = _error_response(kind)
            await response(scope, receive, send_with_security_headers)


def _error_response(kind: FailureKind) -> JSONResponse:
    payload = ErrorResponse(error=ErrorBody(code=kind.code, message=kind.public_message))
    return JSONResponse(status_code=kind.status_code, content=payload.model_dump())


def create_app(
    *,
    provider: _SyncProvider | None = None,
    executor: _SyncExecutor | None = None,
) -> FastAPI:
    if provider is not None and executor is not None:
        raise ValueError("provide either provider or executor")

    active_executor: _SyncExecutor = executor or BoundedSyncExecutor(
        provider or PucaVazSyncProvider()
    )
    application = FastAPI(
        title="Aquario SIGAA Connector",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.sync_executor = active_executor
    application.add_middleware(
        _SecureBoundaryMiddleware,
        max_body_bytes=MAX_REQUEST_BODY_BYTES,
    )

    @application.exception_handler(ConnectorError)
    async def connector_error_handler(_request: Request, exc: ConnectorError) -> JSONResponse:
        return _error_response(exc.kind)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(FailureKind.INVALID_REQUEST)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @application.post(
        "/v1/sync",
        response_model=SyncResponse,
        dependencies=[Depends(require_connector_auth)],
    )
    async def sync(
        request: SyncRequest,
        x_aquario_sigaa_deadlines: Annotated[str | None, Header()] = None,
    ) -> SyncResponse:
        return await active_executor.execute(
            SyncCommand(
                username=request.username,
                password=request.password,
                expected_matricula=request.expected_matricula,
                include_deadlines=x_aquario_sigaa_deadlines == "1",
            )
        )

    return application


app = create_app()
