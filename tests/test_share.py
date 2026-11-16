"""deploy/tunnel/share.py: the pieces that can be checked without opening a tunnel."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARE_PY = REPO_ROOT / "deploy" / "tunnel" / "share.py"


@pytest.fixture(scope="module")
def share():
    spec = importlib.util.spec_from_file_location("share", SHARE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_access_codes_are_random_and_typeable(share):
    codes = {share.make_access_code() for _ in range(200)}
    assert len(codes) == 200
    for code in codes:
        assert re.fullmatch(r"[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}", code), code
        assert not set(code) & set("01ilo")


def test_tunnel_url_is_found_in_the_log(share):
    log = "INF |  https://deputy-pie-latest-blessed.trycloudflare.com   |\nINF other"
    assert share.parse_tunnel_url(log) == "https://deputy-pie-latest-blessed.trycloudflare.com"
    assert share.parse_tunnel_url("no link here https://example.com") is None
    assert share.TUNNEL_READY_RE.search("INF Registered tunnel connection connIndex=0")


def test_free_port_is_on_loopback(share):
    port = share.find_free_port()
    assert 1024 < port < 65536


def test_server_environment(share, tmp_path):
    env = share.server_env(tmp_path, "abcd-efgh", all_formats=False)
    assert env["DJANGO_DEBUG"] == "False"
    assert env["DJANGO_REQUEST_FIREWALL"] == "True" and env["DJANGO_BEHIND_PROXY"] == "True"
    assert env["DJANGO_SECURE_COOKIES"] == "True" and env["DJANGO_NO_INDEX"] == "True"
    assert env["DEMO_ACCESS_PASSWORD"] == "abcd-efgh"
    assert env["SCAN_ALLOWED_FORMATS"] == "png,jpeg"
    assert env["DJANGO_ALLOWED_HOSTS"].startswith(".trycloudflare.com")
    assert "*" not in env["DJANGO_ALLOWED_HOSTS"]
    assert env["DJANGO_DB_PATH"] == str(tmp_path / "db.sqlite3")
    assert env["DJANGO_MEDIA_ROOT"] == str(tmp_path / "media")
    assert env["HOME"] == str(tmp_path / "home")
    assert len(env["DJANGO_SECRET_KEY"]) >= 50
    assert share.server_env(tmp_path, "x", False)["DJANGO_SECRET_KEY"] != env["DJANGO_SECRET_KEY"]
    assert share.server_env(tmp_path, "", all_formats=True)["SCAN_ALLOWED_FORMATS"] == ""
    # Nothing from the caller's environment leaks in, apart from a short allow-list.
    assert set(env) - {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM"} == {
        "HOME", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "NO_ALBUMENTATIONS_UPDATE",
        "DJANGO_SETTINGS_MODULE", "DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_BEHIND_PROXY",
        "DJANGO_SECURE_COOKIES", "DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DJANGO_REQUEST_FIREWALL", "DJANGO_NO_INDEX", "DEMO_ACCESS_USER",
        "DEMO_ACCESS_PASSWORD", "DJANGO_DB_PATH", "DJANGO_MEDIA_ROOT", "SCAN_ALLOWED_FORMATS",
    }


def test_server_profile_rules(share):
    project = Path("/Users/someone/code/app")
    profile = share.build_app_profile(project, project / "share_data", Path("/Library/Python/3.9"))
    assert "(deny network-outbound)" in profile
    assert '(deny file-read* (subpath "/Users") (subpath "/Volumes"))' in profile
    assert '(allow file-read* (subpath "/Users/someone/code/app"))' in profile
    for private in (".env", "db.sqlite3", "media", ".git"):
        assert f'"/Users/someone/code/app/{private}"' in profile.split("(deny file-read-data")[1].split("\n")[0]
    assert "(deny file-write*)" in profile and '(subpath "/Users/someone/code/app/share_data")' in profile
    assert "(deny process-exec)" in profile
    # A deny must come before the narrower allow that follows it (later rules win).
    assert profile.index("(deny file-read* ") < profile.index("(allow file-read* ")
    assert profile.index("(allow file-read* ") < profile.index("(deny file-read-data")
    assert profile.index("(deny process-exec)") < profile.index("(allow process-exec")


def test_tunnel_profile_allows_only_the_one_local_port(share):
    profile = share.build_tunnel_profile(Path("/Users/someone/code/app/share_data"),
                                         Path("/opt/homebrew/bin/cloudflared"), 54321)
    assert '(deny network-outbound (remote ip "localhost:*"))' in profile
    assert '(allow network-outbound (remote ip "localhost:54321"))' in profile
    assert '(deny file-read* (subpath "/Users")' in profile
    assert '(allow process-exec (literal "/opt/homebrew/bin/cloudflared"))' in profile


def test_wipe_removes_uploads_and_database(share, tmp_path):
    share.prepare_share_data(tmp_path)
    (tmp_path / "db.sqlite3").write_bytes(b"x")
    for name in ("a", "b"):
        folder = tmp_path / "media" / "scans" / name
        folder.mkdir(parents=True)
        (folder / "mask.png").write_bytes(b"x")
    (tmp_path / "logs" / "server.log").write_text("kept")
    assert share.wipe_visitor_data(tmp_path) == 2
    assert not (tmp_path / "media").exists() and not (tmp_path / "db.sqlite3").exists()
    assert (tmp_path / "logs" / "server.log").read_text() == "kept"
    assert share.wipe_visitor_data(tmp_path) == 0


def test_share_data_is_git_ignored_and_launcher_binds_loopback():
    assert "share_data/" in (REPO_ROOT / ".gitignore").read_text().split()
    source = SHARE_PY.read_text()
    assert 'f"127.0.0.1:{port}"' in source and "0.0.0.0" not in source


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("sandbox-exec"),
                    reason="needs the macOS sandbox")
def test_server_sandbox_really_blocks(share, tmp_path):
    """Run a small Python program under the real profile and see what it may do."""
    share_data = tmp_path / "share_data"
    share_data.mkdir()
    profile = tmp_path / "server.sb"
    profile.write_text(share.build_app_profile(REPO_ROOT, share_data, Path(sys.base_prefix).resolve()))
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, socket, subprocess, sys\n"
        "def t(name, fn):\n"
        "    try:\n        fn(); print(name, 'ALLOWED')\n"
        "    except Exception as e:\n        print(name, 'blocked')\n"
        "home = os.path.expanduser('~')\n"
        "t('list_home', lambda: os.listdir(home))\n"
        "t('read_env', lambda: open('.env').read())\n"
        "t('write_code', lambda: open('scans/_sandbox_probe.py', 'w').write('x'))\n"
        "t('internet', lambda: socket.create_connection(('1.1.1.1', 443), timeout=3))\n"
        "t('shell', lambda: subprocess.run(['/bin/sh', '-c', 'true'], check=True))\n"
        "t('read_code', lambda: open('manage.py').read())\n"
        "t('write_data', lambda: open(sys.argv[1] + '/ok.txt', 'w').write('x'))\n"
        "t('listen_local', lambda: socket.create_server(('127.0.0.1', 0)).close())\n"
    )
    # The probe lives in pytest's temp folder, which is outside /Users and readable.
    result = subprocess.run(
        ["/usr/bin/sandbox-exec", "-f", str(profile), str(REPO_ROOT / ".venv" / "bin" / "python"),
         str(probe), str(share_data)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        env={"HOME": str(Path.home()), "PATH": "/usr/bin:/bin"},
    )
    outcome = dict(line.split() for line in result.stdout.strip().splitlines())
    assert outcome == {
        "list_home": "blocked", "read_env": "blocked", "write_code": "blocked",
        "internet": "blocked", "shell": "blocked",
        "read_code": "ALLOWED", "write_data": "ALLOWED", "listen_local": "ALLOWED",
    }, result.stdout + result.stderr
    assert not (REPO_ROOT / "scans" / "_sandbox_probe.py").exists()
