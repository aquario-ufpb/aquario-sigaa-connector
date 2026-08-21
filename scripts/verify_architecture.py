"""Verify the connector's durable architecture constraints."""

from __future__ import annotations

import ast
import inspect
import json
import re
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.routing import APIRoute  # noqa: E402

from api.index import app as asgi_app  # noqa: E402
from aquario_sigaa_connector.app import (  # noqa: E402
    MAX_REQUEST_BODY_BYTES,
    _SecureBoundaryMiddleware,
)
from aquario_sigaa_connector.app import (  # noqa: E402
    app as production_app,
)
from aquario_sigaa_connector.contracts import (  # noqa: E402
    UPSTREAM_REPOSITORY,
    ErrorResponse,
    HealthResponse,
    SyncRequest,
    SyncResponse,
)
from aquario_sigaa_connector.execution import (  # noqa: E402
    DEFAULT_MAX_WORKERS,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    BoundedSyncExecutor,
)
from aquario_sigaa_connector.provenance import read_upstream_provenance  # noqa: E402

_FULL_SHA = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
_PIN = re.compile(
    r"^sigaa-ai-agent\s*@\s*git\+(?P<repository>https://[^@]+)@(?P<commit>[0-9a-f]{40})$"
)
_IGNORED_PARTS = {".audit", ".git", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__"}


def _project_files(pattern: str):
    for path in ROOT.rglob(pattern):
        parts = path.relative_to(ROOT).parts
        generated = any(part.endswith(".egg-info") for part in parts)
        if not generated and not _IGNORED_PARTS.intersection(parts):
            yield path


def _verify_pin_and_provenance() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    matches = [
        match
        for dependency in project["dependencies"]
        if (match := _PIN.fullmatch(dependency)) is not None
    ]
    if len(matches) != 1:
        raise AssertionError("pyproject.toml must contain one full upstream Git pin")

    pin = matches[0].groupdict()
    provenance = read_upstream_provenance()
    if pin["repository"] != UPSTREAM_REPOSITORY or provenance.repository != UPSTREAM_REPOSITORY:
        raise AssertionError("upstream repository must equal the canonical HTTPS Git URL")
    if provenance.commit_id != pin["commit"]:
        raise AssertionError("installed upstream commit does not match pyproject.toml")

    occurrences = []
    for path in _project_files("*"):
        if not path.is_file() or path.suffix.lower() in {".pyc", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        occurrences.extend(
            (path.relative_to(ROOT), match.group()) for match in _FULL_SHA.finditer(text)
        )
    if occurrences != [(Path("pyproject.toml"), pin["commit"])]:
        raise AssertionError(
            f"the upstream SHA must appear manually only in pyproject.toml: {occurrences}"
        )


def _verify_no_parser_ownership() -> None:
    for path in _project_files("*"):
        relative = path.relative_to(ROOT)
        if path.is_dir() and path.name.lower() in {"parser", "parsers"}:
            raise AssertionError(f"vendored parser directory found: {relative}")
        if path.is_file() and path.suffix == ".py" and path.stem.lower() in {"parser", "parsers"}:
            raise AssertionError(f"vendored parser module found: {relative}")

    for path in _project_files("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sigaa.parsers"):
                raise AssertionError(f"direct parser import found: {path.relative_to(ROOT)}")
            if isinstance(node, ast.Import) and any(
                alias.name.startswith("sigaa.parsers") for alias in node.names
            ):
                raise AssertionError(f"direct parser import found: {path.relative_to(ROOT)}")


def _verify_sigaa_client_boundary() -> None:
    importers = []
    for path in _project_files("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "SigaaClient" for alias in node.names
            ):
                importers.append((path.relative_to(ROOT), node.module))
            if isinstance(node, ast.Import) and any(
                alias.name.endswith(".SigaaClient") for alias in node.names
            ):
                importers.append((path.relative_to(ROOT), None))
    expected = [(Path("src/aquario_sigaa_connector/service.py"), "sigaa.client")]
    if importers != expected:
        raise AssertionError(f"SigaaClient must be imported only by service.py: {importers}")


def _walk_schema(node: Any, path: str) -> None:
    if isinstance(node, list):
        for index, item in enumerate(node):
            _walk_schema(item, f"{path}[{index}]")
        return
    if not isinstance(node, dict):
        return

    if node.get("type") == "object" and node.get("additionalProperties") is not False:
        raise AssertionError(f"model allows extra fields at {path}")
    if node.get("type") == "array" and not {"minItems", "maxItems"}.issubset(node):
        raise AssertionError(f"list lacks explicit bounds at {path}")
    if (
        node.get("type") == "string"
        and node.get("format") != "date-time"
        and not {"minLength", "maxLength"}.issubset(node)
    ):
        raise AssertionError(f"string lacks explicit bounds at {path}")

    for key, value in node.items():
        _walk_schema(value, f"{path}.{key}")


def _verify_contract_schemas() -> None:
    for model in (SyncRequest, SyncResponse, HealthResponse, ErrorResponse):
        _walk_schema(model.model_json_schema(), model.__name__)


def _verify_http_and_execution() -> None:
    routes = {
        (route.path, frozenset(route.methods or set())): route
        for route in production_app.routes
        if isinstance(route, APIRoute)
    }
    expected = {
        ("/health", frozenset({"GET"})),
        ("/v1/sync", frozenset({"POST"})),
    }
    if set(routes) != expected:
        raise AssertionError(f"unexpected HTTP routes: {set(routes)}")
    if any(
        value is not None
        for value in (
            production_app.docs_url,
            production_app.redoc_url,
            production_app.openapi_url,
        )
    ):
        raise AssertionError("interactive docs and OpenAPI routes must be disabled")
    if MAX_REQUEST_BODY_BYTES != 16 * 1024:
        raise AssertionError("production request bodies must be capped at 16 KiB")
    if not any(
        middleware.cls is _SecureBoundaryMiddleware for middleware in production_app.user_middleware
    ):
        raise AssertionError("production must install the secure boundary middleware")
    sync_route = routes[("/v1/sync", frozenset({"POST"}))]
    if not inspect.iscoroutinefunction(sync_route.endpoint):
        raise AssertionError("POST /v1/sync must be async")

    executor = production_app.state.sync_executor
    if not isinstance(executor, BoundedSyncExecutor):
        raise AssertionError("production must use BoundedSyncExecutor")
    if DEFAULT_MAX_WORKERS != 1 or executor.max_workers != 1:
        raise AssertionError("production executor must default to one worker")
    if DEFAULT_WAIT_TIMEOUT_SECONDS != 145.0 or executor.wait_timeout_seconds != 145.0:
        raise AssertionError("production wait budget must be 145 seconds")
    if not isinstance(executor._pool, ThreadPoolExecutor):
        raise AssertionError("production must use a dedicated ThreadPoolExecutor")

    if asgi_app is not production_app or not callable(asgi_app):
        raise AssertionError("api.index must expose the production ASGI app")

    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    duration = vercel["functions"]["api/index.py"]["maxDuration"]
    if duration != 150:
        raise AssertionError("Vercel maxDuration must equal 150")
    include_files = vercel["functions"]["api/index.py"].get("includeFiles")
    if include_files != "pyproject.toml":
        raise AssertionError("Vercel must bundle pyproject.toml for provenance fallback")


def main() -> int:
    checks = (
        ("upstream pin and runtime provenance", _verify_pin_and_provenance),
        ("no vendored or direct parser access", _verify_no_parser_ownership),
        ("single SigaaClient adapter boundary", _verify_sigaa_client_boundary),
        ("recursively strict and bounded contracts", _verify_contract_schemas),
        ("exact async HTTP and dedicated execution boundary", _verify_http_and_execution),
    )
    try:
        for label, check in checks:
            check()
            print(f"PASS {label}")
    except (AssertionError, OSError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
