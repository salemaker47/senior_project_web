#!/usr/bin/env python
"""
Share the site from this computer through a temporary public link.

    .venv/bin/python deploy/tunnel/share.py              # 3 hours, with an access code
    .venv/bin/python deploy/tunnel/share.py --hours 1
    .venv/bin/python deploy/tunnel/share.py --open       # no access code (anyone with the link)

Press Ctrl+C to stop. Everything visitors uploaded is deleted when it stops.

What it does, and the layers that protect this computer (see SHARING.md):

  1. No open port.   The server listens on 127.0.0.1 only. The link is made by
                     an OUTBOUND connection from this Mac to Cloudflare, so
                     nothing on the network or the router is opened.
  2. One door.       The tunnel may talk to that one local port and to nothing
                     else on this Mac (enforced by a sandbox).
  3. Access code.    Visitors need a code that is generated for each session;
                     wrong guesses get an address banned.
  4. Request firewall (scans/firewall.py): rate limits, bans, scanner paths
                     refused, only GET/HEAD/POST.
  5. Small surface.  Only PNG and JPEG uploads are accepted, 20 MB at most.
  6. Sandboxed server. The server process cannot read your home folder (only
                     this project's code and the model), cannot write outside
                     share_data/, cannot reach the internet and cannot start
                     other programs.
  7. Separate data.  Its own database, upload folder and secret key; your local
                     ones are not even readable from inside the sandbox.
  8. Limited time.   It stops by itself after --hours, and wipes the uploads.

Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

PROJECT = Path(__file__).resolve().parents[2]
SHARE_DATA = PROJECT / "share_data"
TUNNEL_HOST_SUFFIX = ".trycloudflare.com"
TUNNEL_URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
TUNNEL_READY_RE = re.compile(r"Registered tunnel connection", re.IGNORECASE)
CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"        # no look-alikes (0/o, 1/l/i)
ACCESS_USER = "demo"
DEFAULT_HOURS = 3.0
MAX_HOURS = 12.0


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def make_access_code(groups: int = 2, size: int = 4) -> str:
    """For example `k7m2-xq9d`: easy to type on a phone, about 40 bits."""
    return "-".join("".join(secrets.choice(CODE_ALPHABET) for _ in range(size)) for _ in range(groups))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def parse_tunnel_url(text: str) -> Optional[str]:
    match = TUNNEL_URL_RE.search(text)
    return match.group(0) if match else None


def find_cloudflared() -> Optional[str]:
    found = shutil.which("cloudflared")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared"):
        if os.path.exists(candidate):
            return candidate
    return None


def _ancestors(path: Path) -> List[Path]:
    """Parent folders of `path` up to the root, nearest last: needed for path lookups."""
    return [p for p in reversed(path.parents) if str(p) != "/"]


def _q(path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


# --------------------------------------------------------------------------- #
# Sandbox profiles (macOS sandbox-exec). Later rules override earlier ones.
# --------------------------------------------------------------------------- #
def build_app_profile(project: Path, share_data: Path, python_prefix: Path) -> str:
    """The web server: project code readable, share_data writable, no internet, no other programs."""
    metadata = " ".join(f"(literal {_q(p)})" for p in _ancestors(project))
    private = " ".join([
        f"(literal {_q(project / '.env')})",            # local secret key
        f"(literal {_q(project / 'db.sqlite3')})",      # local database
        f"(subpath {_q(project / 'media')})",           # local uploads
        f"(subpath {_q(project / '.git')})",
    ])
    return f"""(version 1)
(allow default)

;; Network: answer on this machine only, never call out.
(deny network-outbound)
(allow network-outbound (remote ip "localhost:*"))
(deny network-inbound)
(allow network-inbound (local ip "localhost:*"))

;; Reading: nothing under /Users except this project; not its private files.
(deny file-read* (subpath "/Users") (subpath "/Volumes"))
(allow file-read* (subpath {_q(project)}))
(allow file-read-metadata {metadata})
(deny file-read-data {private})

;; Writing: only the sharing data folder and temporary files.
(deny file-write*)
(allow file-write* (subpath {_q(share_data)}) (subpath "/private/tmp") (subpath "/private/var/folders")
       (literal "/dev/null") (literal "/dev/tty") (literal "/dev/dtracehelper") (regex #"^/dev/ttys[0-9]+$"))

;; Programs: only this Python.
(deny process-exec)
(allow process-exec (subpath {_q(python_prefix)}) (subpath {_q(project / '.venv' / 'bin')}))
"""


def build_tunnel_profile(share_data: Path, cloudflared: Path, port: int) -> str:
    """The tunnel client: internet yes, but on this Mac only our one port, and no personal files."""
    home = share_data / "tunnel_home"
    metadata = " ".join(f"(literal {_q(p)})" for p in _ancestors(home))
    return f"""(version 1)
(allow default)

;; On this machine the tunnel may talk to the demo server's port and nothing else.
(deny network-outbound (remote ip "localhost:*"))
(allow network-outbound (remote ip "localhost:{port}"))
;; It may listen only on the local address (its own status endpoint), never on the network.
(deny network-inbound)
(allow network-inbound (local ip "localhost:*"))

;; No personal files.
(deny file-read* (subpath "/Users") (subpath "/Volumes"))
(allow file-read* (subpath {_q(home)}))
(allow file-read-metadata {metadata})
(deny file-write*)
(allow file-write* (subpath {_q(home)}) (subpath "/private/tmp") (subpath "/private/var/folders")
       (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/ttys[0-9]+$"))

;; No other programs.
(deny process-exec)
(allow process-exec (literal {_q(cloudflared)}))
"""


# --------------------------------------------------------------------------- #
# Environment of the shared server
# --------------------------------------------------------------------------- #
def server_env(share_data: Path, access_code: str, all_formats: bool) -> Dict[str, str]:
    keep = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update({
        "HOME": str(share_data / "home"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "NO_ALBUMENTATIONS_UPDATE": "1",
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),          # new for every session
        "DJANGO_DEBUG": "False",
        "DJANGO_BEHIND_PROXY": "True",
        "DJANGO_SECURE_COOKIES": "True",
        "DJANGO_ALLOWED_HOSTS": f"{TUNNEL_HOST_SUFFIX},localhost,127.0.0.1",
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"https://*{TUNNEL_HOST_SUFFIX}",
        "DJANGO_REQUEST_FIREWALL": "True",
        "DJANGO_NO_INDEX": "True",
        "DEMO_ACCESS_USER": ACCESS_USER,
        "DEMO_ACCESS_PASSWORD": access_code,
        "DJANGO_DB_PATH": str(share_data / "db.sqlite3"),
        "DJANGO_MEDIA_ROOT": str(share_data / "media"),
        "SCAN_ALLOWED_FORMATS": "" if all_formats else "png,jpeg",
    })
    return env


def sandboxed(command: List[str], profile_path: Optional[Path]) -> List[str]:
    return ["/usr/bin/sandbox-exec", "-f", str(profile_path)] + command if profile_path else command


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #
def say(message: str = "") -> None:
    print(message, flush=True)


def _http_status(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 8.0) -> int:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:  # noqa: BLE001 - not reachable yet
        return 0


def _basic_header(code: str) -> Dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{ACCESS_USER}:{code}".encode()).decode()}


def _stop(process: Optional[subprocess.Popen], name: str) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    say(f"  stopped {name}")


def _count(path: Path, needle: str = "") -> int:
    if not path.is_file():
        return 0
    with open(path, errors="replace") as f:
        return sum(1 for line in f if needle in line)


def prepare_share_data(share_data: Path) -> None:
    """Fresh database and upload folder for this session; logs of the last session are replaced."""
    for name in ("db.sqlite3", "db.sqlite3-journal"):
        (share_data / name).unlink(missing_ok=True)
    for name in ("media", "home", "tunnel_home", "logs"):
        shutil.rmtree(share_data / name, ignore_errors=True)
    for name in ("media", "home", "tunnel_home", "logs"):
        (share_data / name).mkdir(parents=True, exist_ok=True)
    share_data.chmod(0o700)


def wipe_visitor_data(share_data: Path) -> int:
    """Delete uploads and the session database. Returns the number of scan folders removed."""
    scans = share_data / "media" / "scans"
    count = sum(1 for p in scans.iterdir() if p.is_dir()) if scans.is_dir() else 0
    shutil.rmtree(share_data / "media", ignore_errors=True)
    for name in ("db.sqlite3", "db.sqlite3-journal"):
        (share_data / name).unlink(missing_ok=True)
    shutil.rmtree(share_data / "home", ignore_errors=True)
    shutil.rmtree(share_data / "tunnel_home", ignore_errors=True)
    return count


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Share the demo through a temporary public link.")
    parser.add_argument("--hours", type=float, default=DEFAULT_HOURS,
                        help=f"stop automatically after this many hours (default {DEFAULT_HOURS:g}, max {MAX_HOURS:g})")
    parser.add_argument("--open", action="store_true", help="no access code: anyone with the link gets in")
    parser.add_argument("--all-formats", action="store_true",
                        help="also accept .mat, .h5, TIFF and DICOM uploads (more file parsers exposed)")
    parser.add_argument("--no-sandbox", action="store_true", help="do not sandbox the server and the tunnel")
    args = parser.parse_args(argv)
    if not 0 < args.hours <= MAX_HOURS:
        parser.error(f"--hours must be between 0 and {MAX_HOURS:g}")

    python = str(PROJECT / ".venv" / "bin" / "python")
    cloudflared = find_cloudflared()
    if not os.path.exists(python):
        say(f"error: {python} not found. Set the project up first (see README.md).")
        return 2
    if cloudflared is None:
        say("error: the tunnel tool is not installed. Install it with:  brew install cloudflared")
        return 2
    pid_file = SHARE_DATA / "share.pid"
    if pid_file.is_file():
        try:
            os.kill(int(pid_file.read_text().strip()), 0)
            say("error: a sharing session is already running. Stop it with Ctrl+C in its terminal.")
            return 2
        except (OSError, ValueError):
            pass

    use_sandbox = not args.no_sandbox and os.path.exists("/usr/bin/sandbox-exec")
    SHARE_DATA.mkdir(exist_ok=True)
    prepare_share_data(SHARE_DATA)
    pid_file.write_text(f"{os.getpid()}\n")

    port = find_free_port()
    access_code = "" if args.open else make_access_code()
    env = server_env(SHARE_DATA, access_code, args.all_formats)
    logs = SHARE_DATA / "logs"

    app_profile = tunnel_profile = None
    if use_sandbox:
        app_profile = SHARE_DATA / "server.sb"
        app_profile.write_text(build_app_profile(PROJECT, SHARE_DATA, Path(sys.base_prefix).resolve()))
        tunnel_profile = SHARE_DATA / "tunnel.sb"
        tunnel_profile.write_text(build_tunnel_profile(SHARE_DATA, Path(cloudflared).resolve(), port))

    server = tunnel = awake = None
    stopping = {"flag": False}

    def request_stop(signum, frame):
        stopping["flag"] = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        say("Preparing the shared copy of the site ...")
        migrate = subprocess.run(
            sandboxed([python, "manage.py", "migrate", "--noinput"], app_profile),
            cwd=PROJECT, env=env, capture_output=True, text=True,
        )
        if migrate.returncode != 0:
            say("error: could not prepare the database:\n" + (migrate.stderr or migrate.stdout)[-1500:])
            return 1

        server_log = open(logs / "server.log", "w")
        server = subprocess.Popen(
            sandboxed([
                python, "-m", "gunicorn", "config.wsgi:application",
                "--bind", f"127.0.0.1:{port}",                 # this machine only
                "--workers", "1", "--threads", "4", "--timeout", "60", "--keep-alive", "5",
                "--limit-request-line", "4094", "--limit-request-fields", "60",
                "--limit-request-field_size", "8190",
                "--worker-tmp-dir", str(SHARE_DATA / "home"),
                "--access-logfile", str(logs / "access.log"), "--error-logfile", "-",
            ], app_profile),
            cwd=PROJECT, env=env, stdout=server_log, stderr=subprocess.STDOUT,
        )
        local = f"http://127.0.0.1:{port}/"
        headers = _basic_header(access_code) if access_code else {}
        for _ in range(120):
            if stopping["flag"] or server.poll() is not None:
                break
            if _http_status(local, headers, timeout=3) == 200:
                break
            time.sleep(0.5)
        else:
            say("error: the server did not start. See share_data/logs/server.log")
            return 1
        if server.poll() is not None:
            say("error: the server stopped while starting. Last lines of share_data/logs/server.log:")
            say((logs / "server.log").read_text(errors="replace")[-1500:])
            return 1

        say("Opening the tunnel ...")
        tunnel_env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR", "TERM")}
        tunnel_env["HOME"] = str(SHARE_DATA / "tunnel_home")
        tunnel_log_path = logs / "tunnel.log"
        tunnel_log = open(tunnel_log_path, "w")
        tunnel = subprocess.Popen(
            sandboxed([cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                      tunnel_profile),
            cwd=SHARE_DATA / "tunnel_home", env=tunnel_env, stdout=tunnel_log, stderr=subprocess.STDOUT,
        )
        url = None
        for _ in range(120):
            if stopping["flag"] or tunnel.poll() is not None:
                break
            url = parse_tunnel_url(tunnel_log_path.read_text(errors="replace"))
            if url:
                break
            time.sleep(0.5)
        if not url:
            say("error: the tunnel did not give a link. Last lines of share_data/logs/tunnel.log:")
            say(tunnel_log_path.read_text(errors="replace")[-1500:])
            return 1

        # Wait until Cloudflare confirms the connection. Do NOT look the new name
        # up here: asking before it exists makes this Mac remember "not found"
        # for minutes, and then the link fails on this Mac only.
        registered = False
        for _ in range(120):
            if stopping["flag"] or tunnel.poll() is not None:
                break
            if TUNNEL_READY_RE.search(tunnel_log_path.read_text(errors="replace")):
                registered = True
                break
            time.sleep(0.5)

        try:
            awake = subprocess.Popen(["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())])
        except OSError:
            awake = None

        until = datetime.now() + timedelta(hours=args.hours)
        lines = ["", "=" * 64, "  The demo is shared.", "",
                 f"  Link:         {url}"]
        if access_code:
            lines += [f"  User name:    {ACCESS_USER}", f"  Access code:  {access_code}"]
        else:
            lines += ["  Access code:  none (--open): anyone with the link gets in"]
        lines += ["",
                  f"  Stops by itself at {until:%H:%M} (in {args.hours:g} h). Press Ctrl+C to stop now.",
                  f"  Sandbox: {'on' if use_sandbox else 'OFF'}   Uploads: "
                  f"{'all formats' if args.all_formats else 'PNG and JPEG only'}",
                  "  Keep this window open and the laptop awake and plugged in.",
                  "=" * 64, ""]
        say("\n".join(lines))
        if registered:
            say("The link can take up to a minute to start working. If a browser says the")
            say("address cannot be found, wait a little and reload.\n")
        else:
            say("note: Cloudflare has not confirmed the connection yet. If the link does not")
            say("work within two minutes, stop with Ctrl+C and start again.\n")

        while not stopping["flag"] and datetime.now() < until:
            if server.poll() is not None:
                say("The server stopped unexpectedly. See share_data/logs/server.log")
                break
            if tunnel.poll() is not None:
                say("The tunnel closed. See share_data/logs/tunnel.log")
                break
            time.sleep(1.0)
        else:
            if not stopping["flag"]:
                say(f"Time limit of {args.hours:g} h reached.")
        return 0
    finally:
        say("\nStopping ...")
        _stop(tunnel, "the tunnel (the link no longer works)")      # close the door first
        _stop(server, "the server")
        if awake is not None and awake.poll() is None:
            awake.terminate()
        requests = _count(logs / "access.log")
        refused = _count(logs / "server.log", "scans.firewall")
        banned = _count(logs / "server.log", "BANNED")
        removed = wipe_visitor_data(SHARE_DATA)
        pid_file.unlink(missing_ok=True)
        say(f"  requests served: {requests}   refused by the firewall: {refused}   addresses banned: {banned}")
        say(f"  visitor uploads deleted: {removed} scan(s); the session database is deleted")
        say(f"  logs of this session: {logs}")


if __name__ == "__main__":
    sys.exit(main())
