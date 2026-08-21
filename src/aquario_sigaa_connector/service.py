"""One-shot SIGAA synchronization through PucaVaz's client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from threading import Lock
from typing import Any, Protocol

import httpx
from pydantic import SecretStr, ValidationError
from sigaa.client import SigaaClient
from sigaa.documents import AcademicDocumentError
from sigaa.http import AuthError

from .contracts import (
    ClassData,
    CraV1,
    CurriculumComponentV1,
    CurriculumCountsV1,
    CurriculumV1,
    GradeData,
    SemesterWorkloadV1,
    SourceInfo,
    StudentData,
    SyncResponse,
    WorkloadProgressV1,
)
from .errors import ConnectorError, FailureKind
from .provenance import ProvenanceError, UpstreamProvenance, read_upstream_provenance


@dataclass(frozen=True, slots=True)
class SyncCommand:
    username: str
    password: SecretStr
    expected_matricula: str | None


class _SyncProvider(Protocol):
    def synchronize(self, command: SyncCommand) -> SyncResponse: ...


class PucaVazSyncProvider:
    def __init__(
        self,
        *,
        client_factory: Callable[[str, str], Any] = SigaaClient,
        provenance: UpstreamProvenance | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._provenance = provenance
        self._provenance_lock = Lock()
        self._clock = clock or (lambda: datetime.now(UTC))

    def synchronize(self, command: SyncCommand) -> SyncResponse:
        try:
            provenance = self._installed_provenance()
            client = self._client_factory(command.username, command.password.get_secret_value())
            with client:
                student = client.get_student()
                student_data = _student_data(student)
                if (
                    command.expected_matricula is not None
                    and student_data.matricula != command.expected_matricula
                ):
                    raise ConnectorError(FailureKind.SIGAA_IDENTITY_MISMATCH)

                curriculum = client.get_curriculum_status(include_cra=True)
                grades = client.get_grades()
                classes = client.list_turmas()
                return self._build_response(
                    provenance=provenance,
                    student=student_data,
                    curriculum=curriculum,
                    grades=grades,
                    classes=classes,
                )
        except ConnectorError:
            raise
        except AuthError as exc:
            raise ConnectorError(FailureKind.SIGAA_AUTH_FAILED) from exc
        except httpx.TimeoutException as exc:
            raise ConnectorError(FailureKind.SIGAA_TIMEOUT) from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(FailureKind.SIGAA_UNAVAILABLE) from exc
        except AcademicDocumentError as exc:
            raise ConnectorError(FailureKind.SIGAA_RESPONSE_INVALID) from exc
        except ValueError as exc:
            kind = (
                FailureKind.SIGAA_AUTH_FAILED
                if str(exc).startswith("login failed")
                else FailureKind.SIGAA_RESPONSE_INVALID
            )
            raise ConnectorError(kind) from exc
        except (AttributeError, KeyError, TypeError, ValidationError) as exc:
            raise ConnectorError(FailureKind.SIGAA_RESPONSE_INVALID) from exc

    def _installed_provenance(self) -> UpstreamProvenance:
        if self._provenance is not None:
            return self._provenance

        with self._provenance_lock:
            if self._provenance is None:
                try:
                    self._provenance = read_upstream_provenance()
                except ProvenanceError as exc:
                    raise ConnectorError(FailureKind.CONNECTOR_MISCONFIGURED) from exc
            return self._provenance

    def _build_response(
        self,
        *,
        provenance: UpstreamProvenance,
        student: StudentData,
        curriculum: Any,
        grades: Any,
        classes: Any,
    ) -> SyncResponse:
        components = [
            CurriculumComponentV1(
                code=item.code,
                name=item.name,
                integration_type=item.integration_type,
                period=item.period,
                period_raw=item.period_raw,
                workload_hours=item.workload_hours,
                required=item.required,
                status=item.status,
                status_raw=item.status_raw,
                prerequisite=item.prerequisite,
                corequisite=item.corequisite,
            )
            for item in curriculum.components
        ]
        counts = _component_counts(components)

        return SyncResponse(
            observed_at=self._clock(),
            source=SourceInfo(
                upstream_repository=provenance.repository,
                upstream_commit=provenance.commit_id,
            ),
            student=student,
            curriculum=CurriculumV1(
                curriculum=curriculum.curriculum,
                maximum_completion_term=curriculum.maximum_completion_term,
                semester_workload_hours=SemesterWorkloadV1(
                    minimum=curriculum.min_semester_workload_hours,
                    maximum=curriculum.max_semester_workload_hours,
                ),
                cra=CraV1(
                    value=_decimal_string(curriculum.cra),
                    source=curriculum.cra_source,
                ),
                progress=[
                    WorkloadProgressV1(
                        description=item.description,
                        completed_hours=item.completed_hours,
                        total_hours=item.total_hours,
                        remaining_hours=max(item.total_hours - item.completed_hours, 0),
                        completed_percent=item.completed_percent,
                    )
                    for item in curriculum.progress
                ],
                counts=counts,
                components=components,
            ),
            grades=[
                GradeData(
                    semester=item.semester,
                    code=item.code,
                    discipline=item.discipline,
                    units=item.units,
                    exam=item.exam,
                    result=item.result,
                    absences=item.absences,
                    status=item.status,
                )
                for item in grades
            ],
            classes=[
                ClassData(
                    source_key=item.id_turma,
                    name=item.name,
                    code=item.code,
                    room=item.room,
                    schedule_raw=item.schedule_raw,
                    semester=item.semester,
                )
                for item in classes
            ],
        )


def _required_identity(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorError(FailureKind.SIGAA_IDENTITY_INVALID)
    return value.strip()


def _student_data(student: Any) -> StudentData:
    try:
        return StudentData(
            matricula=_required_identity(student.matricula),
            name=_required_identity(student.name),
            course=student.course,
            email=student.email,
            semester=student.semester,
        )
    except (AttributeError, ValidationError) as exc:
        raise ConnectorError(FailureKind.SIGAA_IDENTITY_INVALID) from exc


def _component_counts(components: list[CurriculumComponentV1]) -> CurriculumCountsV1:
    return CurriculumCountsV1(
        total=len(components),
        completed=sum(item.status == "completed" for item in components),
        enrolled=sum(item.status == "enrolled" for item in components),
        pending=sum(item.status == "pending" for item in components),
        unknown=sum(item.status == "unknown" for item in components),
        pending_required=sum(item.status == "pending" and item.required for item in components),
        pending_optional=sum(item.status == "pending" and not item.required for item in components),
    )


def _decimal_string(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
