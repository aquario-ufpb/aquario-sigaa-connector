"""Installed identity for the pinned upstream dependency."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

from .contracts import UPSTREAM_REPOSITORY

UPSTREAM_DISTRIBUTION = "sigaa-tools"
PROJECT_DISTRIBUTION = "aquario-sigaa-connector"
PROJECT_CONFIG = Path(__file__).resolve().parents[2] / "pyproject.toml"
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PINNED_DEPENDENCY = re.compile(
    r"^sigaa-tools\s*@\s*git\+(?P<repository>https://[^@]+)@(?P<commit>[0-9a-f]{40})$"
)


class ProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UpstreamProvenance:
    repository: str
    commit_id: str


def read_upstream_provenance() -> UpstreamProvenance:
    try:
        direct_url_text = distribution(UPSTREAM_DISTRIBUTION).read_text("direct_url.json")
    except PackageNotFoundError:
        direct_url_text = None

    if not direct_url_text:
        return _read_build_provenance()

    try:
        direct_url: Any = json.loads(direct_url_text)
        repository = direct_url["url"]
        vcs_info = direct_url["vcs_info"]
        vcs = vcs_info["vcs"]
        commit_id = vcs_info["commit_id"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ProvenanceError("upstream PEP 610 metadata is invalid") from exc

    if repository != UPSTREAM_REPOSITORY or vcs != "git":
        raise ProvenanceError("installed upstream repository is not canonical")
    if not isinstance(commit_id, str) or _FULL_COMMIT.fullmatch(commit_id) is None:
        raise ProvenanceError("installed upstream commit is not a full Git SHA")

    return UpstreamProvenance(repository=repository, commit_id=commit_id)


def _read_build_provenance() -> UpstreamProvenance:
    dependencies: list[str] = []
    try:
        dependencies = list(distribution(PROJECT_DISTRIBUTION).requires or [])
    except PackageNotFoundError:
        pass

    if not dependencies:
        try:
            project = tomllib.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))["project"]
            dependencies = project["dependencies"]
        except (KeyError, OSError, TypeError, tomllib.TOMLDecodeError) as exc:
            raise ProvenanceError("connector build provenance is unavailable") from exc

    matches = [
        match
        for dependency in dependencies
        if (match := _PINNED_DEPENDENCY.fullmatch(dependency)) is not None
    ]
    if len(matches) != 1:
        raise ProvenanceError("connector build provenance is invalid")

    pin = matches[0].groupdict()
    if pin["repository"] != UPSTREAM_REPOSITORY:
        raise ProvenanceError("connector build repository is not canonical")
    return UpstreamProvenance(repository=pin["repository"], commit_id=pin["commit"])
