from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from threading import Event, Lock

import httpx
from fastapi.routing import APIRoute

from aquario_sigaa_connector import service
from aquario_sigaa_connector.app import MAX_REQUEST_BODY_BYTES, create_app
from aquario_sigaa_connector.contracts import SyncResponse
from aquario_sigaa_connector.execution import BoundedSyncExecutor
from aquario_sigaa_connector.provenance import read_upstream_provenance
from aquario_sigaa_connector.service import SyncCommand

SECRET = "a" * 32
PASSWORD = "private-password"
FIXTURE = Path(__file__).parent / "fixtures" / "sync-response-v1.json"


def _snapshot() -> SyncResponse:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    provenance = read_upstream_provenance()
    payload["source"]["upstream_repository"] = provenance.repository
    payload["source"]["upstream_commit"] = provenance.commit_id
    return SyncResponse.model_validate(payload)


def _request_payload() -> dict[str, str]:
    return {
        "username": "20260000001",
        "password": PASSWORD,
        "expected_matricula": "20260000001",
    }


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


def _assert_security_headers(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def _asgi_request(application, method: str, path: str, **kwargs):
    async def scenario():
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(scenario())


class ImmediateExecutor:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.commands: list[SyncCommand] = []
        self.error = error

    async def execute(self, command: SyncCommand) -> SyncResponse:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return _snapshot()


class BlockingProvider:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.completed = Event()
        self._lock = Lock()
        self.calls = 0

    def synchronize(self, _command: SyncCommand) -> SyncResponse:
        with self._lock:
            self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test did not release provider")
        self.completed.set()
        return _snapshot()


def test_app_exposes_only_health_and_sync_without_docs():
    application = create_app(executor=ImmediateExecutor())
    routes = {
        (route.path, frozenset(route.methods or set()))
        for route in application.routes
        if isinstance(route, APIRoute)
    }

    assert routes == {
        ("/health", frozenset({"GET"})),
        ("/v1/sync", frozenset({"POST"})),
    }
    assert application.docs_url is None
    assert application.redoc_url is None
    assert application.openapi_url is None


def test_health_does_not_require_upstream_provenance_at_startup(monkeypatch):
    def unavailable_provenance():
        raise AssertionError("health loaded upstream provenance")

    monkeypatch.setattr(service, "read_upstream_provenance", unavailable_provenance)
    application = create_app()
    executor = application.state.sync_executor

    response = _asgi_request(application, "GET", "/health")

    assert response.status_code == 200
    _assert_security_headers(response)
    executor.shutdown()


def test_every_response_gets_fresh_server_headers(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)
    application = create_app(executor=ImmediateExecutor())

    first = _asgi_request(
        application, "GET", "/health", headers={"X-Request-ID": "caller-controlled"}
    )
    second = _asgi_request(application, "GET", "/missing")

    assert first.status_code == 200
    assert second.status_code == 404
    _assert_security_headers(first)
    _assert_security_headers(second)
    assert first.headers["x-request-id"] != "caller-controlled"
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_sync_requires_service_auth_and_never_echoes_password(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)
    response = _asgi_request(
        create_app(executor=ImmediateExecutor()),
        "POST",
        "/v1/sync",
        json=_request_payload(),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert PASSWORD not in response.text


def test_sync_rejects_non_ascii_bearer_as_unauthorized(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)
    application = create_app(executor=ImmediateExecutor())

    response = _asgi_request(
        application,
        "POST",
        "/v1/sync",
        headers=[(b"authorization", b"Bearer \xff")],
        json=_request_payload(),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    _assert_security_headers(response)


def test_invalid_request_never_echoes_password(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)
    response = _asgi_request(
        create_app(executor=ImmediateExecutor()),
        "POST",
        "/v1/sync",
        headers=_auth_headers(),
        json={
            "username": "20260000001",
            "password": {"secret": "must-not-leak"},
            "expected_matricula": "invalid",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "must-not-leak" not in response.text
    _assert_security_headers(response)


def test_sync_uses_injected_executor_with_redacted_command(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)
    executor = ImmediateExecutor()
    response = _asgi_request(
        create_app(executor=executor),
        "POST",
        "/v1/sync",
        headers=_auth_headers(),
        json=_request_payload(),
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.0"
    assert len(executor.commands) == 1
    assert PASSWORD not in repr(executor.commands[0])
    assert PASSWORD not in response.text
    _assert_security_headers(response)


def test_body_limit_uses_actual_bytes_not_content_length(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)
    application = create_app(executor=ImmediateExecutor())

    too_large = _asgi_request(
        application,
        "POST",
        "/v1/sync",
        headers={**_auth_headers(), "Content-Length": "1"},
        content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
    )
    at_limit = _asgi_request(
        application,
        "POST",
        "/v1/sync",
        headers=_auth_headers(),
        content=b"x" * MAX_REQUEST_BODY_BYTES,
    )

    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert at_limit.status_code == 422
    _assert_security_headers(too_large)
    _assert_security_headers(at_limit)


def test_body_limit_rejects_stream_as_soon_as_cumulative_bytes_exceed_limit(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)

    async def scenario():
        async def oversized_stream():
            yield b"x" * MAX_REQUEST_BODY_BYTES
            yield b"x"
            raise AssertionError("the application read beyond its body limit")

        transport = httpx.ASGITransport(app=create_app(executor=ImmediateExecutor()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/sync",
                headers=_auth_headers(),
                content=oversized_stream(),
            )

    response = asyncio.run(scenario())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    _assert_security_headers(response)


def test_unexpected_error_is_sanitized(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)
    executor = ImmediateExecutor(error=RuntimeError(f"failure contained {PASSWORD}"))
    response = _asgi_request(
        create_app(executor=executor),
        "POST",
        "/v1/sync",
        headers=_auth_headers(),
        json=_request_payload(),
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert PASSWORD not in response.text
    _assert_security_headers(response)


def test_sync_provider_runs_off_the_event_loop(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)

    async def scenario() -> None:
        provider = BlockingProvider()
        application = create_app(provider=provider)
        executor = application.state.sync_executor
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            request = asyncio.create_task(
                client.post("/v1/sync", headers=_auth_headers(), json=_request_payload())
            )
            assert await asyncio.to_thread(provider.started.wait, 1)
            assert not request.done()
            provider.release.set()
            response = await request

        assert response.status_code == 200
        _assert_security_headers(response)
        executor.shutdown()

    asyncio.run(scenario())


def test_timeout_keeps_capacity_busy_until_real_worker_finishes(monkeypatch):
    monkeypatch.setenv("CONNECTOR_API_SECRET", SECRET)

    async def scenario() -> None:
        provider = BlockingProvider()
        executor = BoundedSyncExecutor(provider, wait_timeout_seconds=0.02)
        application = create_app(executor=executor)
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            timed_out = await client.post(
                "/v1/sync", headers=_auth_headers(), json=_request_payload()
            )
            busy = await client.post("/v1/sync", headers=_auth_headers(), json=_request_payload())
            assert provider.calls == 1
            provider.release.set()
            assert await asyncio.to_thread(provider.completed.wait, 1)
            await asyncio.sleep(0.01)
            executor.wait_timeout_seconds = 1.0
            accepted = await client.post(
                "/v1/sync", headers=_auth_headers(), json=_request_payload()
            )

        assert timed_out.status_code == 504
        assert timed_out.json()["error"]["code"] == "CONNECTOR_DEADLINE"
        assert busy.status_code == 503
        assert busy.json()["error"]["code"] == "CONNECTOR_BUSY"
        assert accepted.status_code == 200
        assert provider.calls == 2
        _assert_security_headers(timed_out)
        _assert_security_headers(busy)
        _assert_security_headers(accepted)
        executor.shutdown()

    asyncio.run(scenario())
