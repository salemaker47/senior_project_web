"""
scans/firewall.py — request firewall for the times the site is reachable from
the internet (see deploy/tunnel/). Off by default; localhost use is unchanged.

It is the first middleware, so a refused request never reaches the session,
the forms or the model. Checks, in this order:

  1. ban list      an address that keeps misbehaving is refused for a while
  2. method        only GET, HEAD and POST exist on this site
  3. path          over-long or malformed paths, and the paths scanners probe
                   (/.env, /wp-admin, *.php, ...) are answered with a bare 404
  4. access code   optional HTTP Basic password for the whole site; wrong
                   passwords count towards a ban (brute-force protection)
  5. rate limits   requests per minute per address; uploads per minute and per
                   hour per address; uploads per minute for everyone together

Refusals are plain-text responses: no templates, no session, no cookies.
State is kept in memory, which fits the single server process this app runs.

The visitor's address is taken from the tunnel's `CF-Connecting-IP` header only
when the connection itself comes from this machine (the tunnel client); the
header cannot be forged from outside, because the server listens on 127.0.0.1.
"""

from __future__ import annotations

import base64
import hmac
import ipaddress
import logging
import re
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger("scans.firewall")

ALLOWED_METHODS = ("GET", "HEAD", "POST")
MAX_PATH_LENGTH = 512
MAX_QUERY_LENGTH = 1024
LOOPBACK = ("127.0.0.1", "::1", "")

# What vulnerability scanners ask for. None of it exists here.
_PROBE_RE = re.compile(
    r"(\.(php\d?|aspx?|jsp|cgi|pl|sh|sql|bak|old|swp|ini|yml|yaml|toml|pem|key|log|git|svn|env|htaccess|htpasswd)(/|$))"
    r"|(^/(wp-|wordpress|phpmyadmin|admin|cgi-bin|node_modules|actuator|autodiscover|telescope|_profiler))"
    r"|(^/(pma|vendor|solr|console|manager|owa|debug|api|graphql|login|shell)(/|$))"
    r"|(/\.[^/]+)"                      # any dot-file or dot-folder
    r"|(\.\.)|(//)|(%00)|(\\)",
    re.IGNORECASE,
)
_UPLOAD_PATHS = ("/upload/",)


class _State:
    """Counters shared by all threads of the one server process."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: Dict[str, Deque[float]] = defaultdict(deque)
        self.uploads: Dict[str, Deque[float]] = defaultdict(deque)
        self.all_uploads: Deque[float] = deque()
        self.strikes: Dict[str, Deque[float]] = defaultdict(deque)
        self.banned_until: Dict[str, float] = {}
        self.last_prune = 0.0

    def reset(self) -> None:
        with self.lock:
            self.requests.clear(); self.uploads.clear(); self.all_uploads.clear()
            self.strikes.clear(); self.banned_until.clear()


STATE = _State()


def _trim(times: Deque[float], now: float, window: float) -> None:
    while times and now - times[0] > window:
        times.popleft()


def client_ip(request) -> str:
    """The visitor's address; the tunnel's header is believed only from loopback."""
    remote = request.META.get("REMOTE_ADDR", "") or ""
    if settings.BEHIND_PROXY and remote in LOOPBACK:
        forwarded = request.META.get("HTTP_CF_CONNECTING_IP") or (
            request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0]
        )
        forwarded = forwarded.strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return remote or "unknown"


def _plain(status: int, text: str, **headers: str) -> HttpResponse:
    response = HttpResponse(text + "\n", status=status, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    for name, value in headers.items():
        response[name.replace("_", "-")] = value
    return response


class RequestFirewallMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.REQUEST_FIREWALL:
            refusal = self.check(request)
            if refusal is not None:
                return refusal
        return self.get_response(request)

    # ----------------------------------------------------------------------- #
    def check(self, request) -> Optional[HttpResponse]:
        now = time.time()
        ip = client_ip(request)
        state = STATE

        with state.lock:
            self._prune(state, now)
            until = state.banned_until.get(ip, 0.0)
            if until > now:
                return _plain(429, "Too many bad requests from your address. Try again later.",
                              Retry_After=str(int(until - now) + 1))

        if request.method not in ALLOWED_METHODS:
            self._strike(ip, now, f"method {request.method}")
            return _plain(405, "Method not allowed.", Allow=", ".join(ALLOWED_METHODS))

        path = request.path
        query = request.META.get("QUERY_STRING", "")
        if len(path) > MAX_PATH_LENGTH or len(query) > MAX_QUERY_LENGTH or "\x00" in path:
            self._strike(ip, now, "malformed path")
            return _plain(400, "Bad request.")
        if _PROBE_RE.search(path) and path != "/robots.txt":
            self._strike(ip, now, f"probe {path[:80]}")
            return _plain(404, "Not found.")

        if settings.ACCESS_PASSWORD:
            verdict = self._check_access(request)
            if verdict is not True:
                if verdict == "wrong":
                    self._strike(ip, now, "wrong access code")
                return _plain(401, "This demo needs its access code.",
                              WWW_Authenticate='Basic realm="Brain MRI demo", charset="UTF-8"')

        limited = self._rate_limit(request, ip, now)
        if limited is not None:
            return limited
        return None

    # ----------------------------------------------------------------------- #
    @staticmethod
    def _check_access(request):
        """True, "missing" (browser has not asked yet) or "wrong"."""
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.lower().startswith("basic "):
            return "missing"
        try:
            user, _, password = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
        except Exception:  # noqa: BLE001 - any undecodable header is simply wrong
            return "wrong"
        ok_user = hmac.compare_digest(user.encode(), settings.ACCESS_USER.encode())
        ok_pass = hmac.compare_digest(password.encode(), settings.ACCESS_PASSWORD.encode())
        return True if (ok_user and ok_pass) else "wrong"

    def _rate_limit(self, request, ip: str, now: float) -> Optional[HttpResponse]:
        state = STATE
        is_upload = request.method == "POST" and request.path in _UPLOAD_PATHS
        with state.lock:
            times = state.requests[ip]
            _trim(times, now, 60.0)
            if len(times) >= settings.FIREWALL_REQUESTS_PER_MINUTE:
                over = True
            else:
                times.append(now)
                over = False
            if not over and is_upload:
                mine = state.uploads[ip]
                _trim(mine, now, 3600.0)
                everyone = state.all_uploads
                _trim(everyone, now, 60.0)
                last_minute = sum(1 for t in mine if now - t <= 60.0)
                if (last_minute >= settings.FIREWALL_UPLOADS_PER_MINUTE
                        or len(mine) >= settings.FIREWALL_UPLOADS_PER_HOUR
                        or len(everyone) >= settings.FIREWALL_GLOBAL_UPLOADS_PER_MINUTE):
                    logger.warning("upload limit reached for %s", ip)
                    return _plain(429, "Upload limit reached. Please wait a few minutes.",
                                  Retry_After="120")
                mine.append(now)
                everyone.append(now)
        if over:
            self._strike(ip, now, "rate limit")
            return _plain(429, "Too many requests. Please slow down.", Retry_After="30")
        return None

    @staticmethod
    def _strike(ip: str, now: float, reason: str) -> None:
        state = STATE
        with state.lock:
            strikes = state.strikes[ip]
            _trim(strikes, now, float(settings.FIREWALL_BAN_SECONDS))
            strikes.append(now)
            banned = len(strikes) >= settings.FIREWALL_STRIKES_BEFORE_BAN
            if banned:
                state.banned_until[ip] = now + settings.FIREWALL_BAN_SECONDS
                strikes.clear()
        if banned:
            logger.warning("BANNED %s for %d s (last: %s)", ip, settings.FIREWALL_BAN_SECONDS, reason)
        else:
            logger.warning("refused %s: %s", ip, reason)

    @staticmethod
    def _prune(state: _State, now: float) -> None:
        """Forget addresses that have been quiet, so memory stays small. Lock is held."""
        if now - state.last_prune < 60.0:
            return
        state.last_prune = now
        for table, window in ((state.requests, 60.0), (state.uploads, 3600.0),
                              (state.strikes, float(settings.FIREWALL_BAN_SECONDS))):
            for key in [k for k, times in table.items() if not times or now - times[-1] > window]:
                del table[key]
        for key in [k for k, until in state.banned_until.items() if until <= now]:
            del state.banned_until[key]
