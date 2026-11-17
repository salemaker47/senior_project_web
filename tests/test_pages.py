"""
deploy/pages/: the static front-door page for the permanent github.io address.

The page reads status.json and either forwards the visitor to the current
sharing link or says the demo is offline. These tests check the files
themselves, and run the page's decision function in a real browser when Chrome
is installed (skipped otherwise).
"""

from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from inference import DISCLAIMER

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGES = REPO_ROOT / "deploy" / "pages"
SHARE_PY = REPO_ROOT / "deploy" / "tunnel" / "share.py"

INDEX = (PAGES / "index.html").read_text(encoding="utf-8")
DOOR_JS = (PAGES / "door.js").read_text(encoding="utf-8")
DOOR_CSS = (PAGES / "door.css").read_text(encoding="utf-8")
EXAMPLE = json.loads((PAGES / "status.example.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def share():
    spec = importlib.util.spec_from_file_location("share", SHARE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _js_string(name: str) -> str:
    """The value of `var NAME = "...";` in door.js, with JavaScript's backslash escapes undone."""
    literal = re.search(rf'var {name} = "([^"\n]+)";', DOOR_JS).group(1)
    return literal.replace("\\\\", "\\")


def _js_regex(name: str) -> str:
    """The source of `var NAME = /.../;` in door.js."""
    return re.search(rf"var {name} = /(.+?)/;", DOOR_JS).group(1)


# --------------------------------------------------------------------------- #
# The files
# --------------------------------------------------------------------------- #
def test_the_page_is_made_of_plain_local_files():
    assert {p.name for p in PAGES.iterdir()} >= {"index.html", "door.css", "door.js", "status.example.json"}
    # Every file the page loads is a relative path inside its own folder.
    loaded = re.findall(r'\b(?:src|href)="([^"]*)"', INDEX)
    assert sorted(loaded) == ["door.css", "door.js"]
    for name in loaded:
        assert (PAGES / name).is_file()


def test_no_inline_script_or_style():
    assert re.findall(r"<script\b[^>]*>(.*?)</script>", INDEX, flags=re.S) == [""]      # one script, empty body
    assert "<style" not in INDEX.lower()
    assert not re.search(r"\sstyle\s*=", INDEX)
    assert not re.search(r"\son[a-z]+\s*=", INDEX)                                      # onclick= and friends
    policy = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', INDEX).group(1)
    assert "default-src 'none'" in policy and "script-src 'self'" in policy and "connect-src 'self'" in policy
    assert "unsafe" not in policy and "*" not in policy


def test_no_outside_address_in_any_file():
    # The only address-like text is the pattern of the sharing link in door.js.
    js_without_pattern = "\n".join(line for line in DOOR_JS.splitlines() if "var ADDRESS_PATTERN" not in line)
    for name, text in (("index.html", INDEX), ("door.css", DOOR_CSS), ("door.js", js_without_pattern)):
        assert "://" not in text, name
        assert not re.search(r"""["'(]\s*//""", text), name                            # //host/file
    assert "@import" not in DOOR_CSS and "url(" not in DOOR_CSS


def test_page_text():
    assert DISCLAIMER in INDEX
    assert "<noscript>" in INDEX
    assert 'name="robots" content="noindex' in INDEX
    # The page tells visitors they need a code; it never asks for it or holds it.
    assert "access code from the owner" in INDEX
    assert "<form" not in INDEX and "<input" not in INDEX
    assert "password" not in (INDEX + DOOR_JS).lower()
    for element in ("door", "state-checking", "state-online", "state-offline", "open-link",
                    "stay-button", "forward-note", "forward-count", "until-note", "until-time",
                    "checked-time"):
        assert f'id="{element}"' in INDEX and f'getElementById("{element}")' in DOOR_JS, element
    # The link gets its address from the script only, after the address was checked.
    assert "href" not in re.search(r'<a\b[^>]*id="open-link"[^>]*>', INDEX).group(0)


# --------------------------------------------------------------------------- #
# Agreement with the launcher
# --------------------------------------------------------------------------- #
def test_address_pattern_is_the_launchers_pattern_anchored(share):
    pattern = _js_string("ADDRESS_PATTERN")
    assert pattern == "^" + share.TUNNEL_URL_RE.pattern + "$"
    accepts = ["https://some-random-words.trycloudflare.com", "https://a.trycloudflare.com"]
    refuses = [
        "http://some-random-words.trycloudflare.com",            # not https
        "https://example.com",
        "https://trycloudflare.com",                             # no name in front
        "https://a.b.trycloudflare.com",
        "https://a.trycloudflare.com.evil.example",
        "https://a.trycloudflare.com/path",
        "https://a.trycloudflare.com@evil.example",
        "https://evil.example/?next=https://a.trycloudflare.com",
        "https://A.trycloudflare.com",
        "https://-a.trycloudflare.com",
        "javascript:alert(1)",
        "",
    ]
    for address in accepts:
        assert re.fullmatch(pattern, address), address
    for address in refuses:
        assert not re.fullmatch(pattern, address), address


def test_session_length_and_time_format_fit_the_launcher(share):
    believed_hours = int(re.search(r"var MAX_SESSION_HOURS = (\d+);", DOOR_JS).group(1))
    assert share.MAX_HOURS < believed_hours <= share.MAX_HOURS + 2
    time_re = _js_regex("TIME_RE")
    assert re.fullmatch(time_re, "2026-11-17T21:30:00Z")
    for wrong in ("2026-11-17 21:30:00", "2026-11-17T21:30:00+00:00", "2026-11-17T21:30Z", "tomorrow"):
        assert not re.fullmatch(time_re, wrong), wrong


def test_status_example_has_the_documented_format():
    assert set(EXAMPLE) == {"online", "url", "until", "updated"}
    assert EXAMPLE["online"] is True
    assert re.fullmatch(_js_string("ADDRESS_PATTERN"), EXAMPLE["url"])
    time_re = _js_regex("TIME_RE")
    assert re.fullmatch(time_re, EXAMPLE["until"]) and re.fullmatch(time_re, EXAMPLE["updated"])


def test_a_local_status_file_cannot_be_committed_by_accident():
    assert "deploy/pages/status.json" in (REPO_ROOT / ".gitignore").read_text().splitlines()


# --------------------------------------------------------------------------- #
# decide() in a real browser
# --------------------------------------------------------------------------- #
NOW = "2026-11-17T18:00:00Z"
GOOD = "https://some-random-words.trycloudflare.com"
SOON = "2026-11-17T19:00:00Z"


def _status(**changes):
    status = {"online": True, "url": GOOD, "until": SOON, "updated": NOW}
    status.update(changes)
    return status


DECIDE_CASES = [
    # (what, status, expected state)
    ("sharing, one hour left", _status(), "online"),
    ("sharing, twelve hours left", _status(until="2026-11-18T06:00:00Z"), "online"),
    ("stopped", {"online": False, "url": "", "until": "", "updated": NOW}, "offline"),
    ("online is the word true, not the value", _status(online="true"), "offline"),
    ("online is 1", _status(online=1), "offline"),
    ("stop time has passed", _status(until="2026-11-17T17:59:59Z"), "offline"),
    ("stop time is this very moment", _status(until=NOW), "offline"),
    ("stop time is unbelievably far away", _status(until="2026-11-18T08:00:00Z"), "offline"),
    ("stop time years away", _status(until="2099-01-01T00:00:00Z"), "offline"),
    ("stop time in another format", _status(until="2026-11-17 19:00:00"), "offline"),
    ("stop time is a word", _status(until="tomorrow"), "offline"),
    ("stop time is a number", _status(until=1794942000000), "offline"),
    ("stop time missing", {"online": True, "url": GOOD}, "offline"),
    ("address missing", {"online": True, "until": SOON}, "offline"),
    ("address not https", _status(url="http://some-random-words.trycloudflare.com"), "offline"),
    ("foreign address", _status(url="https://example.com"), "offline"),
    ("look-alike address", _status(url="https://a.trycloudflare.com.evil.example"), "offline"),
    ("address with a path", _status(url=GOOD + "/somewhere"), "offline"),
    ("address with a login part", _status(url="https://a.trycloudflare.com@evil.example"), "offline"),
    ("address hidden in a query", _status(url="https://evil.example/?u=" + GOOD), "offline"),
    ("address followed by a line break", _status(url=GOOD + "\n"), "offline"),
    ("address in capitals", _status(url=GOOD.upper()), "offline"),
    ("script address", _status(url="javascript:alert(1)"), "offline"),
    ("address is a list", _status(url=[GOOD]), "offline"),
    ("very long address", _status(url="https://" + "a" * 200 + ".trycloudflare.com"), "offline"),
    ("no file (null)", None, "offline"),
    ("a list", [_status()], "offline"),
    ("a string", "online", "offline"),
    ("a number", 1, "offline"),
    ("empty object", {}, "offline"),
]


def _find_chrome():
    candidates = [
        os.environ.get("CHROME_BIN"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def test_decide_in_a_real_browser(tmp_path):
    chrome = _find_chrome()
    if chrome is None:
        pytest.skip("Chrome is not installed; decide() in door.js is not exercised")

    # A page without the door's elements: door.js then only defines frontDoor.decide.
    harness = tmp_path / "harness.html"
    harness.write_text(
        "<!doctype html><meta charset='utf-8'><pre id='out'>not run</pre>\n"
        f"<script src='{(PAGES / 'door.js').as_uri()}'></script>\n"
        "<script>\n"
        f"var cases = {json.dumps([status for _, status, _ in DECIDE_CASES])};\n"
        f"var now = Date.parse({json.dumps(NOW)});\n"
        "var results = cases.map(function (status) { return window.frontDoor.decide(status, now); });\n"
        "document.getElementById('out').textContent = JSON.stringify(results);\n"
        "</script>\n",
        encoding="utf-8",
    )
    try:
        run = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={tmp_path / 'profile'}", "--virtual-time-budget=1000",
             "--dump-dom", harness.as_uri()],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Chrome could not be run here: {exc}")
    found = re.search(r'<pre id="out">(.*?)</pre>', run.stdout, flags=re.S)
    if found is None:
        pytest.skip("Chrome gave no page output here")
    assert found.group(1) != "not run", "door.js did not load or failed in the browser"

    results = json.loads(html.unescape(found.group(1)))
    assert len(results) == len(DECIDE_CASES)
    for (what, _status_value, expected), result in zip(DECIDE_CASES, results):
        assert result["state"] == expected, what
        if expected == "online":
            assert result["url"] == GOOD, what
            assert set(result) == {"state", "url", "until"}, what
        else:
            assert result == {"state": "offline"}, what
