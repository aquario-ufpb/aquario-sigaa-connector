from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError

import pytest

from aquario_sigaa_connector.contracts import UPSTREAM_REPOSITORY
from aquario_sigaa_connector.provenance import ProvenanceError, read_upstream_provenance


class FakeDistribution:
    def __init__(self, payload: dict | None, *, requirements: list[str] | None = None):
        self.payload = payload
        self.requires = requirements

    def read_text(self, filename: str) -> str | None:
        assert filename == "direct_url.json"
        return json.dumps(self.payload) if self.payload is not None else None


def test_installed_provenance_uses_canonical_git_repository_and_full_commit():
    provenance = read_upstream_provenance()

    assert provenance.repository == UPSTREAM_REPOSITORY
    assert len(provenance.commit_id) == 40


def test_provenance_falls_back_to_installed_project_dependency(monkeypatch):
    commit = "a" * 40
    dependency = f"sigaa-tools @ git+{UPSTREAM_REPOSITORY}@{commit}"

    def fake_distribution(name: str):
        if name == "sigaa-tools":
            return FakeDistribution(None)
        return FakeDistribution(None, requirements=[dependency])

    monkeypatch.setattr("aquario_sigaa_connector.provenance.distribution", fake_distribution)

    provenance = read_upstream_provenance()

    assert provenance.repository == UPSTREAM_REPOSITORY
    assert provenance.commit_id == commit


def test_provenance_falls_back_to_bundled_project_config(monkeypatch):
    def missing_distribution(_name: str):
        raise PackageNotFoundError

    monkeypatch.setattr("aquario_sigaa_connector.provenance.distribution", missing_distribution)

    provenance = read_upstream_provenance()

    assert provenance.repository == UPSTREAM_REPOSITORY
    assert len(provenance.commit_id) == 40


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": "file:///tmp/upstream", "dir_info": {"editable": True}},
        {
            "url": "https://example.test/fork.git",
            "vcs_info": {"vcs": "git", "commit_id": "a" * 40},
        },
        {
            "url": UPSTREAM_REPOSITORY,
            "vcs_info": {"vcs": "git", "commit_id": "abc123"},
        },
    ],
)
def test_provenance_rejects_missing_or_untrusted_metadata(monkeypatch, payload):
    monkeypatch.setattr(
        "aquario_sigaa_connector.provenance.distribution", lambda _name: FakeDistribution(payload)
    )

    with pytest.raises(ProvenanceError):
        read_upstream_provenance()


def test_provenance_rejects_missing_pep610_and_build_metadata(monkeypatch, tmp_path):
    def missing_distribution(_name: str):
        raise PackageNotFoundError

    monkeypatch.setattr("aquario_sigaa_connector.provenance.distribution", missing_distribution)
    monkeypatch.setattr(
        "aquario_sigaa_connector.provenance.PROJECT_CONFIG", tmp_path / "missing.toml"
    )

    with pytest.raises(ProvenanceError):
        read_upstream_provenance()
