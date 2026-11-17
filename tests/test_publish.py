"""
deploy/tunnel/publish.py and the launcher's --publish option.

Everything is published into a bare repository in a temporary folder, which
stands in for GitHub. Nothing here goes onto the network.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TUNNEL_DIR = REPO_ROOT / "deploy" / "tunnel"
PAGES = REPO_ROOT / "deploy" / "pages"
DOOR_JS = (PAGES / "door.js").read_text(encoding="utf-8")

GOOD = "https://some-random-words.trycloudflare.com"
ACCESS_CODE = "k7m2-xq9d"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TUNNEL_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def share():
    return _load("share")


@pytest.fixture(scope="module")
def publish(share):
    return share.publish            # the very module the launcher uses


def _git(repo: Path, *args: str) -> str:
    run = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
                         cwd=repo, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return run.stdout.strip()


@pytest.fixture
def remote(tmp_path):
    """A bare repository with a `main` branch, like the project on GitHub."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q")
    _git(seed, "symbolic-ref", "HEAD", "refs/heads/main")
    (seed / "README.md").write_text("the project\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "project")
    _git(seed, "push", "-q", str(bare), "main")
    return bare


def _soon(hours: float = 3):
    return datetime.now(timezone.utc) + timedelta(hours=hours)


# --------------------------------------------------------------------------- #
# The status
# --------------------------------------------------------------------------- #
def test_status_online_and_offline(publish):
    now = datetime(2026, 11, 17, 18, 0, 0, tzinfo=timezone.utc)
    online = publish.build_status(True, GOOD, now + timedelta(hours=3), now=now)
    assert online == {"online": True, "url": GOOD, "until": "2026-11-17T21:00:00Z",
                      "updated": "2026-11-17T18:00:00Z"}
    assert publish.build_status(False, now=now) == {
        "online": False, "url": "", "until": "", "updated": "2026-11-17T18:00:00Z"}
    # A stop time given in another time zone is written in UTC.
    berlin = timezone(timedelta(hours=1))
    local = datetime(2026, 11, 17, 22, 0, 0, tzinfo=berlin)
    assert publish.build_status(True, GOOD, local, now=now)["until"] == "2026-11-17T21:00:00Z"


@pytest.mark.parametrize("url", [
    "http://some-random-words.trycloudflare.com", "https://example.com",
    "https://a.trycloudflare.com/path", "https://a.trycloudflare.com.evil.example",
    "https://a.trycloudflare.com\n", f"https://a.trycloudflare.com/?code={ACCESS_CODE}", "", None,
])
def test_status_refuses_other_addresses(publish, url):
    with pytest.raises(ValueError):
        publish.build_status(True, url, _soon())


def test_status_refuses_bad_stop_times(publish):
    now = datetime(2026, 11, 17, 18, 0, 0, tzinfo=timezone.utc)
    for until in (None, datetime(2026, 11, 17, 21, 0, 0), now, now - timedelta(minutes=1),
                  now + timedelta(hours=13, seconds=1)):
        with pytest.raises(ValueError):
            publish.build_status(True, GOOD, until, now=now)
    publish.build_status(True, GOOD, now + timedelta(hours=13), now=now)       # the limit itself is fine


def test_status_agrees_with_the_front_door_page(publish, share):
    # One pattern for the link, shared by the launcher, publish.py and door.js.
    assert share.TUNNEL_URL_RE is publish.TUNNEL_URL_RE
    time_re = re.search(r"var TIME_RE = /(.+?)/;", DOOR_JS).group(1)
    status = publish.build_status(True, GOOD, _soon())
    assert re.fullmatch(time_re, status["until"]) and re.fullmatch(time_re, status["updated"])
    believed_hours = int(re.search(r"var MAX_SESSION_HOURS = (\d+);", DOOR_JS).group(1))
    assert publish.MAX_AHEAD == timedelta(hours=believed_hours)
    assert timedelta(hours=share.MAX_HOURS) < publish.MAX_AHEAD
    assert set(status) == set(json.loads((PAGES / "status.example.json").read_text()))


def test_the_access_code_has_no_way_into_the_status(publish, share):
    assert list(inspect.signature(publish.build_status).parameters) == ["online", "url", "until", "now"]
    assert list(inspect.signature(share.publish_state).parameters) == [
        "remote", "work_dir", "online", "url", "until"]
    for extra in ({"code": ACCESS_CODE}, {"note": "x"}):
        status = dict(publish.build_status(False), **extra)
        with pytest.raises(publish.PublishError):
            publish.check_status(status)
    with pytest.raises(publish.PublishError):
        publish.check_status(dict(publish.build_status(True, GOOD, _soon()), url="https://example.com"))
    with pytest.raises(publish.PublishError):
        publish.check_status(dict(publish.build_status(False), url=GOOD))
    # In the launcher, the code is used for the server and the printed box only.
    source = (TUNNEL_DIR / "share.py").read_text()
    for line in source.splitlines():
        if "publish_state(" in line or "build_status(" in line:
            assert "access_code" not in line, line


def test_pages_address(publish):
    assert publish.pages_address("https://github.com/Some-One/some_repo.git") == "https://some-one.github.io/some_repo/"
    assert publish.pages_address("https://github.com/someone/some_repo") == "https://someone.github.io/some_repo/"
    assert publish.pages_address("git@github.com:someone/some_repo.git") == "https://someone.github.io/some_repo/"
    for other in ("/tmp/remote.git", "https://example.com/a/b.git", "https://github.com/onlyowner", "", None):
        assert publish.pages_address(other) is None


# --------------------------------------------------------------------------- #
# Publishing into the stand-in repository
# --------------------------------------------------------------------------- #
def test_first_publish_creates_the_branch_with_page_and_status(publish, remote, tmp_path):
    main_before = _git(remote, "rev-parse", "main")
    status = publish.build_status(True, GOOD, _soon())
    commit = publish.publish(status, str(remote), tmp_path / "work")

    assert _git(remote, "rev-parse", "gh-pages") == commit
    assert sorted(_git(remote, "ls-tree", "-r", "--name-only", "gh-pages").split()) == sorted(publish.OUR_FILES)
    assert json.loads(_git(remote, "show", "gh-pages:status.json")) == status
    for name in publish.PAGE_FILES:
        assert _git(remote, "show", f"gh-pages:{name}") == (PAGES / name).read_text().strip(), name
    # The project's own branch is exactly as it was, and no other branch appeared.
    assert _git(remote, "rev-parse", "main") == main_before
    assert sorted(_git(remote, "for-each-ref", "--format=%(refname)").split()) == [
        "refs/heads/gh-pages", "refs/heads/main"]
    author = _git(remote, "log", "-1", "--format=%an <%ae>|%s", "gh-pages")
    assert author == "Demo sharing launcher <launcher@localhost>|Demo online"


def test_second_publish_changes_only_the_status_and_keeps_one_commit(publish, remote, tmp_path):
    first = publish.publish(publish.build_status(True, GOOD, _soon()), str(remote), tmp_path / "work")
    offline = publish.build_status(False)
    second = publish.publish(offline, str(remote), tmp_path / "work")

    assert second != first and _git(remote, "rev-parse", "gh-pages") == second
    assert _git(remote, "diff", "--name-only", first, second).split() == ["status.json"]
    assert json.loads(_git(remote, "show", "gh-pages:status.json")) == offline
    # No history: nobody can read from GitHub when the demo was online before.
    assert _git(remote, "rev-list", "--count", "gh-pages") == "1"
    assert _git(remote, "log", "-1", "--format=%s", "gh-pages") == "Demo offline"
    assert GOOD not in _git(remote, "log", "-p", "gh-pages")


def test_a_branch_with_other_content_is_left_alone(publish, remote, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    _git(other, "symbolic-ref", "HEAD", "refs/heads/gh-pages")
    (other / "index.html").write_text("someone's own site\n")
    (other / "thesis.pdf").write_text("important\n")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "my site")
    _git(other, "push", "-q", str(remote), "gh-pages")
    before = _git(remote, "rev-parse", "gh-pages")

    with pytest.raises(publish.PublishError, match="thesis.pdf"):
        publish.publish(publish.build_status(False), str(remote), tmp_path / "work")
    assert _git(remote, "rev-parse", "gh-pages") == before


def test_publishing_never_touches_a_repository_around_the_work_folder(publish, remote, tmp_path):
    """share_data/pages/ lies inside the project's checkout; git must not act on that one."""
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "symbolic-ref", "HEAD", "refs/heads/main")
    (project / "code.py").write_text("x = 1\n")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "work")
    head = _git(project, "rev-parse", "HEAD")

    publish.publish(publish.build_status(True, GOOD, _soon()), str(remote), project / "share_data" / "pages")

    assert _git(project, "rev-parse", "HEAD") == head
    assert _git(project, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert _git(project, "branch", "--format=%(refname:short)").split() == ["main"]
    assert _git(project, "status", "--porcelain").split() == ["??", "share_data/"]
    assert _git(project, "remote") == ""


def test_an_unreachable_remote_is_a_publish_error(publish, tmp_path):
    with pytest.raises(publish.PublishError, match="git ls-remote failed"):
        publish.publish(publish.build_status(False), str(tmp_path / "nowhere.git"), tmp_path / "work")


def test_login_details_never_appear_in_error_messages(publish, tmp_path):
    with pytest.raises(publish.PublishError) as caught:
        publish.publish(publish.build_status(False),
                        "https://someuser:sometoken@127.0.0.1:9/owner/repo.git", tmp_path / "work")
    assert "sometoken" not in str(caught.value)


# --------------------------------------------------------------------------- #
# The launcher
# --------------------------------------------------------------------------- #
def test_publish_state_reports_success_and_failure_without_raising(share, remote, tmp_path, capsys):
    work = tmp_path / "work"
    assert share.publish_state(str(remote), work, True, GOOD, _soon()) is True
    assert json.loads(_git(remote, "show", "gh-pages:status.json"))["url"] == GOOD
    assert share.publish_state(str(remote), work, False) is True
    assert json.loads(_git(remote, "show", "gh-pages:status.json"))["online"] is False
    assert capsys.readouterr().out == ""

    # A push that cannot work, and a status that cannot be built: a warning, no exception.
    assert share.publish_state(str(tmp_path / "nowhere.git"), work, False) is False
    assert share.publish_state(str(remote), work, True, "https://example.com", _soon()) is False
    warnings = capsys.readouterr().out
    assert warnings.count("warning: the front door could not be updated") == 2
    assert json.loads(_git(remote, "show", "gh-pages:status.json"))["online"] is False


def test_publish_and_open_cannot_be_combined(share, capsys):
    for arguments in (["--open", "--publish"], ["--publish-remote", "/tmp/x.git"]):
        with pytest.raises(SystemExit) as stopped:
            share.main(arguments)
        assert stopped.value.code == 2
    errors = capsys.readouterr().err
    assert "--publish cannot be combined with --open" in errors and "--publish-remote needs --publish" in errors


def test_launcher_publishes_in_the_right_places():
    source = (TUNNEL_DIR / "share.py").read_text()
    online = source.index("publish_state(remote, pages_work, True, url, until_utc)")
    offline = source.index("publish_state(remote, pages_work, False)")
    # "Online" only after Cloudflare confirmed the link; "offline" only after the tunnel is closed.
    assert source.index("registered = True") < online
    assert "if remote and registered" in source
    assert source.index('_stop(tunnel, "the tunnel') < offline
    assert "if published:" in source[source.index('_stop(server, "the server")'):offline]
    # The pattern for the link exists once.
    assert source.count("trycloudflare\\.com") == 0 and "from publish import TUNNEL_URL_RE" in source
