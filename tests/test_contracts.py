from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from aquario_sigaa_connector.contracts import SyncRequest, SyncResponse
from aquario_sigaa_connector.provenance import read_upstream_provenance

FIXTURE = Path(__file__).parent / "fixtures" / "sync-response-v1.json"


def _response_payload() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    provenance = read_upstream_provenance()
    payload["source"]["upstream_repository"] = provenance.repository
    payload["source"]["upstream_commit"] = provenance.commit_id
    return payload


@pytest.mark.parametrize("expected_matricula", ["20260000001", None])
def test_sync_request_accepts_present_or_absent_expected_matricula(expected_matricula):
    payload = {"username": " 20260000001 ", "password": "private-password"}
    if expected_matricula is not None:
        payload["expected_matricula"] = expected_matricula

    request = SyncRequest.model_validate(payload)

    assert request.username == "20260000001"
    assert request.expected_matricula == expected_matricula
    assert "private-password" not in repr(request)


@pytest.mark.parametrize("matricula", ["", "2026", "2026000000x", "202600000012"])
def test_sync_request_rejects_invalid_expected_matricula(matricula):
    with pytest.raises(ValidationError):
        SyncRequest.model_validate(
            {
                "username": "20260000001",
                "password": "private-password",
                "expected_matricula": matricula,
            }
        )


def test_golden_response_is_complete_and_strict():
    response = SyncResponse.model_validate(_response_payload())

    assert response.schema_version == "1.0"
    assert response.curriculum.cra.value == "8.42"
    assert response.curriculum.progress[0].remaining_hours == 1200
    assert response.curriculum.counts.pending_required == 1
    assert "cra" not in response.model_dump(exclude={"curriculum"})


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), True),
        (("curriculum", "cra", "unexpected"), True),
        (("curriculum", "progress", 0, "description"), "x" * 257),
        (("grades", 0, "units"), ["1"] * 17),
    ],
)
def test_response_rejects_extra_fields_and_bound_violations(path, value):
    payload = deepcopy(_response_payload())
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        SyncResponse.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("counts", "total"), 3),
        (("progress", 0, "remaining_hours"), 1199),
    ],
)
def test_response_rejects_inconsistent_derived_values(path, value):
    payload = _response_payload()
    target = payload["curriculum"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        SyncResponse.model_validate(payload)
