"""Vercel ASGI entry point."""

import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from aquario_sigaa_connector.app import app  # noqa: E402

__all__ = ["app"]
