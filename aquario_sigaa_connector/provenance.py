"""Installed identity for the pinned upstream dependency."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from typing import Any

from .contracts import UPSTREAM_REPOSITORY

UPSTREAM_DISTRIBUTION = "sigaa-ai-agent"
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class UpstreamProvenance:
    repository: str
    commit_id: str


def read_upstream_provenance() -> UpstreamProvenance:
    try:
        direct_url_text = distribution(UPSTREAM_DISTRIBUTION).read_text("direct_url.json")
    except PackageNotFoundError as exc:
        raise ProvenanceError("upstream distribution is not installed") from exc

    if not direct_url_text:
        raise ProvenanceError("upstream PEP 610 metadata is unavailable")

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
