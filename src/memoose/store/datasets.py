"""Datasets are scopes. Each maps to one SQLite file under the data directory.

The default Dataset is the project the Host is working in, derived from the
server's working directory (the Host launches the MCP server inside the project).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_SAFE = re.compile(r"[^a-z0-9._-]+")


def env(name: str) -> str | None:
    return os.environ.get(f"MEMOOSE_{name}")


def data_dir() -> Path:
    """`~/.memoose`, unless MEMOOSE_DATA_DIR points elsewhere."""
    override = env("DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / ".memoose"


def project_dataset_name(cwd: str | os.PathLike | None = None) -> str:
    path = Path(cwd or env("PROJECT_DIR") or os.getcwd()).resolve()
    digest = hashlib.sha1(str(path).encode()).hexdigest()[:8]
    base = _SAFE.sub("-", path.name.casefold()).strip("-") or "project"
    return f"{base}-{digest}"


def normalize_dataset_name(name: str) -> str:
    clean = _SAFE.sub("-", name.strip().casefold()).strip("-.")
    if not clean:
        raise ValueError("Dataset name must contain letters or digits.")
    return clean


def dataset_path(name: str) -> Path:
    return data_dir() / f"{normalize_dataset_name(name)}.sqlite"
