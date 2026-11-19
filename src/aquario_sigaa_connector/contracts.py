"""Versioned, privacy-safe HTTP contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

UPSTREAM_REPOSITORY = "https://github.com/PucaVaz/sigaa-tools.git"

Username = Annotated[str, Field(min_length=1, max_length=64)]
Password = Annotated[SecretStr, Field(min_length=1, max_length=256)]
Matricula = Annotated[str, Field(min_length=11, max_length=11, pattern=r"^\d{11}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=64)]
MediumText = Annotated[str, Field(min_length=1, max_length=256)]
NullableShortText = ShortText | None
NullableMediumText = MediumText | None
CommitId = Annotated[str, Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")]
CraValue = Annotated[
    str,
    Field(min_length=1, max_length=16, pattern=r"^(?:10(?:\.0+)?|[0-9](?:\.\d+)?)$"),
]
HourCount = Annotated[int, Field(ge=0, le=100_000)]
ComponentCount = Annotated[int, Field(ge=0, le=2_048)]
Percent = Annotated[float, Field(ge=0, le=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncRequest(StrictModel):
    username: Username
    password: Password
    expected_matricula: Matricula | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class SourceInfo(StrictModel):
    system: Annotated[Literal["SIGAA_UFPB"], Field(min_length=10, max_length=10)] = "SIGAA_UFPB"
    adapter: Annotated[Literal["sigaa-tools"], Field(min_length=11, max_length=11)] = "sigaa-tools"
    upstream_repository: Annotated[
        Literal["https://github.com/PucaVaz/sigaa-tools.git"],
        Field(min_length=42, max_length=42),
    ] = UPSTREAM_REPOSITORY
    upstream_commit: CommitId


class StudentData(StrictModel):
    matricula: Matricula
    name: MediumText
    course: NullableMediumText
    email: Annotated[str, Field(min_length=3, max_length=320)] | None
    semester: NullableShortText


class CraV1(StrictModel):
    value: CraValue | None
    source: Annotated[
        Literal["academic_transcript", "unavailable"], Field(min_length=11, max_length=19)
    ]


class SemesterWorkloadV1(StrictModel):
    minimum: HourCount | None
    maximum: HourCount | None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum semester workload exceeds maximum")
        return self


class WorkloadProgressV1(StrictModel):
    description: MediumText
    completed_hours: HourCount
    total_hours: HourCount
    remaining_hours: HourCount
    completed_percent: Percent

    @model_validator(mode="after")
    def validate_hours(self) -> Self:
        if self.completed_hours > self.total_hours:
            raise ValueError("completed hours exceed total hours")
        if self.remaining_hours != self.total_hours - self.completed_hours:
            raise ValueError("remaining hours do not match total and completed hours")
        return self


class CurriculumComponentV1(StrictModel):
    code: ShortText
    name: MediumText
    integration_type: ShortText
    period: Annotated[int, Field(ge=0, le=100)] | None
    period_raw: Annotated[str, Field(min_length=1, max_length=32)] | int | float | None
    workload_hours: HourCount
    required: bool
    status: Annotated[
        Literal["completed", "enrolled", "pending", "unknown"],
        Field(min_length=7, max_length=9),
    ]
    status_raw: NullableShortText
    prerequisite: NullableMediumText
    corequisite: NullableMediumText


class CurriculumCountsV1(StrictModel):
    total: ComponentCount
    completed: ComponentCount
    enrolled: ComponentCount
    pending: ComponentCount
    unknown: ComponentCount
    pending_required: ComponentCount
    pending_optional: ComponentCount


class CurriculumV1(StrictModel):
    curriculum: ShortText
    maximum_completion_term: NullableShortText
    semester_workload_hours: SemesterWorkloadV1
    cra: CraV1
    progress: Annotated[list[WorkloadProgressV1], Field(min_length=0, max_length=64)]
    counts: CurriculumCountsV1
    components: Annotated[list[CurriculumComponentV1], Field(min_length=0, max_length=2_048)]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        expected = {
            "total": len(self.components),
            "completed": sum(item.status == "completed" for item in self.components),
            "enrolled": sum(item.status == "enrolled" for item in self.components),
            "pending": sum(item.status == "pending" for item in self.components),
            "unknown": sum(item.status == "unknown" for item in self.components),
            "pending_required": sum(
                item.status == "pending" and item.required for item in self.components
            ),
            "pending_optional": sum(
                item.status == "pending" and not item.required for item in self.components
            ),
        }
        if self.counts.model_dump() != expected:
            raise ValueError("curriculum counts do not match components")
        return self


class GradeData(StrictModel):
    semester: ShortText
    code: ShortText
    discipline: MediumText
    units: Annotated[list[ShortText], Field(min_length=0, max_length=16)]
    exam: NullableShortText
    result: NullableShortText
    absences: NullableShortText
    status: NullableShortText


class ClassData(StrictModel):
    source_key: ShortText
    name: MediumText
    code: NullableShortText
    room: NullableMediumText
    schedule_raw: NullableMediumText
    semester: NullableShortText


class DeadlineData(StrictModel):
    id: ShortText
    kind: ShortText
    title: MediumText
    date: Annotated[str, Field(min_length=0, max_length=256)]


class ClassWithDeadlines(ClassData):
    deadlines: Annotated[list[DeadlineData], Field(min_length=0, max_length=256)]


class SyncResponse(StrictModel):
    schema_version: Annotated[Literal["1.0"], Field(min_length=3, max_length=3)] = "1.0"
    observed_at: datetime
    source: SourceInfo
    student: StudentData
    curriculum: CurriculumV1
    grades: Annotated[list[GradeData], Field(min_length=0, max_length=256)]
    classes: Annotated[list[ClassWithDeadlines | ClassData], Field(min_length=0, max_length=64)]


class HealthResponse(StrictModel):
    status: Annotated[Literal["ok"], Field(min_length=2, max_length=2)] = "ok"
    service: Annotated[Literal["aquario-sigaa-connector"], Field(min_length=23, max_length=23)] = (
        "aquario-sigaa-connector"
    )
    schema_version: Annotated[Literal["1.0"], Field(min_length=3, max_length=3)] = "1.0"


class ErrorBody(StrictModel):
    code: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")]
    message: MediumText


class ErrorResponse(StrictModel):
    error: ErrorBody
