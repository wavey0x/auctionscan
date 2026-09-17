from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def env_path() -> Path:
    return project_root() / ".env"


def load_project_env(*, override: bool = False) -> None:
    path = env_path()
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _parse_env_value(value.strip())
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def _parse_env_value(raw: str) -> str:
    if not raw:
        return ""
    if raw[0] == raw[-1] and raw[0] in {"'", '"'} and len(raw) >= 2:
        return raw[1:-1]
    return raw
