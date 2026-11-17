"""
Tell the front-door page (deploy/pages/) where the demo is.

The page is served by GitHub Pages from the `gh-pages` branch of this
repository. Next to it lies `status.json`; the sharing launcher (share.py
--publish) rewrites that file when a session starts and when it stops:

    {"online": true, "url": "https://<name>.trycloudflare.com",
     "until": "2026-11-17T21:30:00Z", "updated": "2026-11-17T18:30:00Z"}

How it is published, and what keeps that safe:

  * Only four things can be written: online or not, the sharing link, the stop
    time and the time of writing. `build_status` has no other input, so the
    access code cannot end up in the file.
  * The work happens in a small repository of its own (share_data/pages/),
    made from scratch every time. Git is told exactly where that repository
    is, so the project's own checkout, index and `main` branch are never
    touched.
  * The branch always holds ONE commit: page files plus the status. Each
    publish replaces it. GitHub therefore keeps no list of when the demo was
    online or of old links.
  * Replacing means a forced push, so two guards come first: the branch name
    is fixed (`gh-pages`), and a branch that holds any file this module did
    not put there is left alone.
  * Git may not ask questions and has a time limit. A missing login or a
    network problem ends in `PublishError` with a short message.

Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

PROJECT = Path(__file__).resolve().parents[2]
PAGES_SRC = PROJECT / "deploy" / "pages"

BRANCH = "gh-pages"
PAGE_FILES = ("index.html", "door.css", "door.js")
STATUS_FILE = "status.json"
NO_JEKYLL = ".nojekyll"                      # tells GitHub Pages to serve the files as they are
OUR_FILES = frozenset(PAGE_FILES + (STATUS_FILE, NO_JEKYLL))
STATUS_KEYS = frozenset(("online", "url", "until", "updated"))

# A sharing link, and nothing else. door.js uses the same pattern, anchored.
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
# The page reads times in exactly this form (TIME_RE in door.js) ...
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# ... and does not believe a stop time further away than this (MAX_SESSION_HOURS in door.js).
MAX_AHEAD = timedelta(hours=13)
GIT_TIMEOUT = 60                             # seconds for each git command

_GITHUB_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


class PublishError(Exception):
    """Publishing did not work. `str(exc)` is a short message for the owner."""


# --------------------------------------------------------------------------- #
# The status
# --------------------------------------------------------------------------- #
def utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(TIME_FORMAT)


def build_status(online: bool, url: str = "", until: Optional[datetime] = None,
                 now: Optional[datetime] = None) -> Dict[str, object]:
    """
    The content of status.json. "Online" needs a sharing link and a stop time
    in the near future (with a time zone); anything else raises ValueError.
    """
    now = now or datetime.now(timezone.utc)
    if not online:
        return {"online": False, "url": "", "until": "", "updated": utc_text(now)}
    if not isinstance(url, str) or not TUNNEL_URL_RE.fullmatch(url):
        raise ValueError("the address is not a sharing link")
    if until is None or until.tzinfo is None:
        raise ValueError("the stop time needs a time zone")
    if not now < until <= now + MAX_AHEAD:
        raise ValueError("the stop time must be in the future and at most 13 hours away")
    return {"online": True, "url": url, "until": utc_text(until), "updated": utc_text(now)}


def check_status(status: Dict[str, object]) -> None:
    """Refuse to publish anything that `build_status` could not have made."""
    if not isinstance(status, dict) or set(status) != STATUS_KEYS:
        raise PublishError("the status has unexpected fields")
    if status["online"] is True:
        if not isinstance(status["url"], str) or not TUNNEL_URL_RE.fullmatch(status["url"]):
            raise PublishError("the status holds an address that is not a sharing link")
    elif status["online"] is not False or status["url"] != "" or status["until"] != "":
        raise PublishError("the status is neither a proper 'online' nor a proper 'offline'")


# --------------------------------------------------------------------------- #
# Where to publish
# --------------------------------------------------------------------------- #
def origin_url(project: Path = PROJECT) -> Optional[str]:
    """The address of this project's `origin` on GitHub, or None."""
    try:
        run = subprocess.run(["git", "-C", str(project), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if run.returncode != 0:
        return None
    return run.stdout.strip() or None


def pages_address(remote: str) -> Optional[str]:
    """`https://<owner>.github.io/<repository>/` for a GitHub remote, else None."""
    match = _GITHUB_RE.match(remote or "")
    if not match:
        return None
    return f"https://{match.group(1).lower()}.github.io/{match.group(2)}/"


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #
def _git(args: List[str], repo: Path) -> str:
    """Run git on the small repository in `repo`, and only on that one."""
    env = dict(os.environ)
    env.update({
        "GIT_DIR": str(repo / ".git"),           # never fall back to the project's own repository
        "GIT_WORK_TREE": str(repo),
        "GIT_TERMINAL_PROMPT": "0",              # fail instead of waiting for an answer
    })
    for name in ("GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE"):
        env.pop(name, None)
    command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"] + args
    try:
        # Its own session: Ctrl+C in the launcher's terminal does not cut a push in half.
        run = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True,
                             timeout=GIT_TIMEOUT, start_new_session=True)
    except FileNotFoundError as exc:
        raise PublishError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise PublishError(f"git {args[0]} did not finish within {GIT_TIMEOUT} seconds") from exc
    if run.returncode != 0:
        lines = [line.strip() for line in (run.stderr or run.stdout).splitlines() if line.strip()]
        telling = [line for line in lines if line.startswith(("fatal:", "error:", "remote:", "!"))]
        detail = (telling or lines or ["no message"])[0]
        detail = re.sub(r"://[^@/\s]+@", "://", detail)                                 # no login in messages
        raise PublishError(f"git {args[0]} failed: {detail[:300]}")
    return run.stdout


def publish(status: Dict[str, object], remote: str, work_dir: Path,
            pages_src: Path = PAGES_SRC) -> str:
    """
    Put the page files and `status` on the remote's `gh-pages` branch as its
    one and only commit. Returns the id of that commit. Raises PublishError.
    """
    check_status(status)
    work_dir = Path(work_dir)
    ref = f"refs/heads/{BRANCH}"

    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True)
    _git(["init", "-q"], work_dir)
    _git(["symbolic-ref", "HEAD", ref], work_dir)

    # What is on the branch now? Leave it alone unless it is ours.
    listed = _git(["ls-remote", remote, ref], work_dir).split()
    old = listed[0] if listed else ""
    if old:
        _git(["fetch", "-q", "--depth", "1", remote, ref], work_dir)
        names = {n for n in _git(["ls-tree", "-r", "--name-only", "FETCH_HEAD"], work_dir).splitlines() if n}
        foreign = sorted(names - OUR_FILES)
        if foreign:
            raise PublishError(
                f"the {BRANCH} branch holds files this launcher did not put there "
                f"({', '.join(foreign[:3])}); it is left as it is"
            )

    for name in PAGE_FILES:
        shutil.copyfile(Path(pages_src) / name, work_dir / name)
    (work_dir / NO_JEKYLL).write_text("")
    (work_dir / STATUS_FILE).write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

    _git(["add", "-A"], work_dir)
    _git(["-c", "user.name=Demo sharing launcher", "-c", "user.email=launcher@localhost",
          "commit", "-q", "-m", "Demo online" if status["online"] else "Demo offline"], work_dir)
    # Replace the branch, but only if it still is what we just looked at
    # (or still does not exist).
    _git(["push", "-q", f"--force-with-lease={ref}:{old}", remote, f"HEAD:{ref}"], work_dir)
    return _git(["rev-parse", "HEAD"], work_dir).strip()
