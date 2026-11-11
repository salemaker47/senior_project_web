"""
Create `.env` from `.env.example` with a fresh secret key.

    python -m config.make_env

Does nothing if `.env` already exists. Uses only the standard library, so it
runs before Django is configured.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KEY_LINE = "DJANGO_SECRET_KEY="


def build_env_text(example_text: str, secret_key: str) -> str:
    lines = []
    replaced = False
    for line in example_text.splitlines():
        if line.strip() == KEY_LINE and not replaced:
            lines.append(f"{KEY_LINE}{secret_key}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append(f"{KEY_LINE}{secret_key}")
    return "\n".join(lines) + "\n"


def main(base_dir: Path = BASE_DIR) -> int:
    env_file = base_dir / ".env"
    example = base_dir / ".env.example"
    if env_file.exists():
        print(f"{env_file} already exists; left unchanged.")
        return 0
    if not example.is_file():
        print(f"error: {example} is missing", file=sys.stderr)
        return 1
    text = build_env_text(example.read_text(encoding="utf-8"), secrets.token_urlsafe(50))
    env_file.write_text(text, encoding="utf-8")
    try:
        env_file.chmod(0o600)
    except OSError:
        pass
    print(f"Wrote {env_file} with a new secret key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
