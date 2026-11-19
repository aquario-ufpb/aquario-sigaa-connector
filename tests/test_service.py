from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sigaa.documents import AcademicDocumentError
from sigaa.errors import (
    CaptchaError,
    LoginRejectedError,
    MissingCredentialsError,
    UnrecognizedPageError,
    UnsafeUrlError,
)
from sigaa.http import AuthError

from aquario_sigaa_connector import service
from aquario_sigaa_connector.app import create_app
from aquario_sigaa_connector.errors import ConnectorError, FailureKind
from aquario_sigaa_connector.provenance import ProvenanceError
from aquario_sigaa_connector.service import PucaVazSyncProvider, SyncCommand

USERNAME = "20260000001"
PASSWORD = "private-password"


def test_default_provider_uses_a_longer_read_timeout(monkeypatch):
    captured: dict[str, object] = {}

    class CapturingClient:
        def __init__(self, username: str, password: str, **kwargs: object) -> None:
            captured.update(username=username, password=password, **kwargs)

    monkeypatch.setattr(service, "SigaaClient", CapturingClient)

    service._create_sigaa_client(USERNAME, PASSWORD)

    assert captured["username"] == USERNAME
    assert captured["password"] == PASSWORD
    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10.0
    assert timeout.read == 60.0


def _student(*, matricula: object = USERNAME, name: object = "Ralf") -> SimpleNamespace:
    return SimpleNamespace(
        matricula=matricula,
        name=name,
        course="COMPUTACAO - GRADUACAO",
        email=None,
        semester="2026.1",
    )


def _curriculum(*, component_status: str = "pending") -> SimpleNamespace:
    component = SimpleNamespace(
        code="DCC101",
        name="Programacao",
        integration_type="OB",
        period=1,
        period_raw=1,
        workload_hours=60,
        required=True,
        status=component_status,
        status_raw="A CURSAR",
        prerequisite=None,
        corequisite=None,
    )
    progress = SimpleNamespace(
        description="Obrigatoria",
        completed_hours=1200,
        total_hours=2400,
        completed_percent=50.0,
    )
    return SimpleNamespace(
        curriculum="2026",
        max_semester_workload_hours=480,
        min_semester_workload_hours=240,
        maximum_completion_term="2030.2",
        progress=[progress],
        components=[component],
        cra=Decimal("8.42"),
        cra_source="academic_transcript",
    )


def _grade() -> SimpleNamespace:
    return SimpleNamespace(
        semester="2026.1",
        code="DCC101",
        discipline="Programacao",
        units=["8.0"],
        exam=None,
        result="8.0",
        absences="0",
        status="MATRICULADO",
    )


def _class() -> SimpleNamespace:
    return SimpleNamespace(
        id_turma="123",
        name="Programacao",
        code="DCC101",
        room="CI 101",
        schedule_raw="246M12",
        semester="2026.1",
    )


class FakeClient:
    def __init__(
        self,
        events: list[str],
        *,
        student: object | None = None,
        failures: dict[str, Exception] | None = None,
        component_status: str = "pending",
    ) -> None:
        self.events = events
        self.student = student or _student()
        self.failures = failures or {}
        self.component_status = component_status

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, *_exc):
        self.events.append("close")

    def _result(self, operation: str, value):
        self.events.append(operation)
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure
        return value

    def get_student(self):
        return self._result("student", self.student)

    def get_curriculum_status(self, *, include_cra: bool):
        assert include_cra is True
        return self._result("curriculum", _curriculum(component_status=self.component_status))

    def get_grades(self):
        return self._result("grades", [_grade()])

    def list_turmas(self):
        return self._result("classes", [_class()])


def _provider(client: FakeClient) -> PucaVazSyncProvider:
    def factory(username: str, password: str) -> FakeClient:
        assert username == USERNAME
        assert password == PASSWORD
        client.events.append("create")
        return client

    return PucaVazSyncProvider(
        client_factory=factory,
        clock=lambda: datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
    )


def _command(*, expected_matricula: str | None = USERNAME) -> SyncCommand:
    return SyncCommand(
        username=USERNAME,
        password=SecretStr(PASSWORD),
        expected_matricula=expected_matricula,
    )


@pytest.mark.parametrize("expected_matricula", [USERNAME, None])
def test_provider_validates_identity_first_and_builds_complete_response(expected_matricula):
    events: list[str] = []
    response = _provider(FakeClient(events)).synchronize(
        _command(expected_matricula=expected_matricula)
    )

    assert events == ["create", "enter", "student", "curriculum", "grades", "classes", "close"]
    assert response.student.matricula == USERNAME
    assert response.curriculum.cra.value == "8.42"
    assert response.curriculum.progress[0].remaining_hours == 1200
    assert response.curriculum.counts.pending_required == 1
    assert PASSWORD not in response.model_dump_json()


@pytest.mark.parametrize("header", [None, "0", "1"])
def test_http_class_deadlines_require_opt_in_and_match_the_class(header, monkeypatch):
    class CalendarClient(FakeClient):
        def list_turmas(self):
            other = _class()
            other.id_turma = "456"
            return [_class(), other]

        def list_deadlines(self):
            assert header == "1"
            return [
                SimpleNamespace(id_turma="123", id="a", kind="avaliacao", title="Prova", date=""),
                SimpleNamespace(
                    id_turma="other", id="b", kind="tarefa", title="Outro trabalho", date="19/05"
                ),
            ]

    secret = "x" * 32
    monkeypatch.setenv("CONNECTOR_API_SECRET", secret)
    headers = {"Authorization": f"Bearer {secret}"}
    if header is not None:
        headers["X-Aquario-Sigaa-Deadlines"] = header
    application = create_app(provider=_provider(CalendarClient([])))

    async def request():
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/sync", headers=headers, json={"username": USERNAME, "password": PASSWORD}
            )

    response = asyncio.run(request())
    application.state.sync_executor.shutdown()
    assert response.status_code == 200
    first, second = response.json()["classes"]
    if header == "1":
        assert first["deadlines"] == [
            {"id": "a", "kind": "avaliacao", "title": "Prova", "date": ""}
        ]
        assert second["deadlines"] == []
    else:
        assert "deadlines" not in first
        assert "deadlines" not in second


@pytest.mark.parametrize(
    "student",
    [
        _student(matricula=""),
        _student(matricula=" "),
        _student(matricula="123"),
        _student(name=""),
        _student(name=" "),
        _student(name="x" * 257),
    ],
)
def test_invalid_identity_stops_collection_and_closes_client(student):
    events: list[str] = []

    with pytest.raises(ConnectorError) as error:
        _provider(FakeClient(events, student=student)).synchronize(_command())

    assert error.value.kind is FailureKind.SIGAA_IDENTITY_INVALID
    assert events == ["create", "enter", "student", "close"]


def test_identity_mismatch_stops_collection_and_closes_client():
    events: list[str] = []

    with pytest.raises(ConnectorError) as error:
        _provider(FakeClient(events, student=_student(matricula="20260000002"))).synchronize(
            _command()
        )

    assert error.value.kind is FailureKind.SIGAA_IDENTITY_MISMATCH
    assert events == ["create", "enter", "student", "close"]


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (AuthError("expired"), FailureKind.SIGAA_AUTH_FAILED),
        (LoginRejectedError("rejected"), FailureKind.SIGAA_AUTH_FAILED),
        (MissingCredentialsError("unsupported credentials"), FailureKind.SIGAA_AUTH_FAILED),
        (CaptchaError("unsupported challenge"), FailureKind.SIGAA_UNAVAILABLE),
        (UnsafeUrlError("http", "test.invalid", None, "blocked"), FailureKind.SIGAA_UNAVAILABLE),
        (UnrecognizedPageError("login", {}), FailureKind.SIGAA_RESPONSE_INVALID),
        (httpx.ReadTimeout("slow"), FailureKind.SIGAA_TIMEOUT),
        (httpx.ConnectError("down"), FailureKind.SIGAA_UNAVAILABLE),
        (ValueError("unexpected HTML"), FailureKind.SIGAA_RESPONSE_INVALID),
        (AcademicDocumentError("unexpected PDF"), FailureKind.SIGAA_RESPONSE_INVALID),
        (AttributeError("missing field"), FailureKind.SIGAA_RESPONSE_INVALID),
    ],
)
def test_provider_classifies_failures_safely_and_closes_client(failure, kind):
    events: list[str] = []

    with pytest.raises(ConnectorError) as error:
        _provider(FakeClient(events, failures={"student": failure})).synchronize(_command())

    assert error.value.kind is kind
    assert str(error.value) == kind.code
    assert PASSWORD not in str(error.value)
    assert events == ["create", "enter", "student", "close"]


@pytest.mark.parametrize("operation", ["curriculum", "grades", "classes"])
def test_later_collection_failures_always_close_client(operation):
    events: list[str] = []

    with pytest.raises(ConnectorError) as error:
        _provider(FakeClient(events, failures={operation: httpx.ConnectError("down")})).synchronize(
            _command()
        )

    assert error.value.kind is FailureKind.SIGAA_UNAVAILABLE
    assert events[-1] == "close"


def test_incompatible_response_is_mapped_before_leaving_context_manager():
    events: list[str] = []

    with pytest.raises(ConnectorError) as error:
        _provider(FakeClient(events, component_status="new-upstream-status")).synchronize(
            _command()
        )

    assert error.value.kind is FailureKind.SIGAA_RESPONSE_INVALID
    assert events == ["create", "enter", "student", "curriculum", "grades", "classes", "close"]


def test_sync_command_repr_redacts_password():
    command = _command()

    assert PASSWORD not in repr(command)
    assert "**********" in repr(command)


def test_missing_runtime_provenance_fails_safe_before_creating_client(monkeypatch):
    events: list[str] = []

    def unavailable_provenance():
        raise ProvenanceError("private build detail")

    monkeypatch.setattr(service, "read_upstream_provenance", unavailable_provenance)

    with pytest.raises(ConnectorError) as error:
        _provider(FakeClient(events)).synchronize(_command())

    assert error.value.kind is FailureKind.CONNECTOR_MISCONFIGURED
    assert "private build detail" not in str(error.value)
    assert events == []
