"""
config/env.py — read settings from a `.env` file without extra dependencies.

Format: one `NAME=value` per line. Blank lines and lines starting with `#` are
ignored; a value may be wrapped in single or double quotes. Variables already
set in the real environment are not overwritten, so
`DJANGO_DEBUG=True python manage.py runserver` still works.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Union


def parse_env_text(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not name:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def load_env_file(path: Union[str, Path]) -> Dict[str, str]:
    """Put the file's variables into os.environ (existing ones win). Returns what the file held."""
    path = Path(path)
    try:
        if not path.is_file():
            return {}
        text = path.read_text(encoding="utf-8")
    except OSError:
        # Unreadable on purpose in the sandboxed sharing mode, where every
        # setting comes from the environment and the local .env stays private.
        return {}
    values = parse_env_text(text)
    for name, value in values.items():
        os.environ.setdefault(name, value)
    return values


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value and value.strip() else default


def env_list(name: str, default: list) -> list:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]
