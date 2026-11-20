/*
 * Front door of the demo, served as a static page by GitHub Pages.
 *
 * The demo itself runs on the owner's computer and gets a new address every
 * time it is shared. The sharing launcher writes that address into
 * status.json next to this file. This script reads the file and either sends
 * the visitor on to the demo or says that it is offline.
 *
 * It never knows, asks for or stores the access code.
 */
(function () {
  "use strict";

  // The only kind of address a visitor is ever sent to. Same pattern as
  // TUNNEL_URL_RE in deploy/tunnel/share.py, anchored at both ends
  // (tests/test_pages.py keeps the two equal).
  var ADDRESS_PATTERN = "^https://[a-z0-9][a-z0-9-]*\\.trycloudflare\\.com$";
  var ADDRESS_RE = new RegExp(ADDRESS_PATTERN);
  var MAX_ADDRESS_LENGTH = 100;
  var TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;     // UTC, as the launcher writes it
  // A session lasts 12 hours at most (MAX_HOURS in share.py). A stop time
  // further away than this is not believed.
  var MAX_SESSION_HOURS = 13;
  var RECHECK_SECONDS = 30;
  var FORWARD_SECONDS = 5;

  /*
   * status: the parsed content of status.json (anything at all).
   * nowMs:  the current time in milliseconds.
   * Returns {state: "online", url, until} or {state: "offline"}.
   * "online" needs all of: online is true, the address fits the pattern, and
   * the stop time is a valid time in the near future.
   */
  function decide(status, nowMs) {
    var offline = { state: "offline" };
    if (status === null || typeof status !== "object" || Array.isArray(status)) { return offline; }
    if (status.online !== true) { return offline; }
    if (typeof status.url !== "string" || status.url.length > MAX_ADDRESS_LENGTH) { return offline; }
    if (!ADDRESS_RE.test(status.url)) { return offline; }
    if (typeof status.until !== "string" || !TIME_RE.test(status.until)) { return offline; }
    var until = Date.parse(status.until);
    if (isNaN(until) || until <= nowMs) { return offline; }
    if (until - nowMs > MAX_SESSION_HOURS * 3600 * 1000) { return offline; }
    return { state: "online", url: status.url, until: until };
  }

  window.frontDoor = { decide: decide, ADDRESS_PATTERN: ADDRESS_PATTERN };

  var door = document.getElementById("door");
  if (!door) { return; }                       // loaded by the test page: only decide() is wanted

  var panels = {
    checking: document.getElementById("state-checking"),
    online: document.getElementById("state-online"),
    offline: document.getElementById("state-offline")
  };
  var openLink = document.getElementById("open-link");
  var stayButton = document.getElementById("stay-button");
  var forwardNote = document.getElementById("forward-note");
  var forwardCount = document.getElementById("forward-count");
  var untilNote = document.getElementById("until-note");
  var untilTime = document.getElementById("until-time");
  var checkedTime = document.getElementById("checked-time");

  var shownUrl = null;        // the address currently offered
  var forwardTimer = null;
  var stayed = false;         // the visitor chose to stay: never forward by itself again

  function clock(ms) {
    return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function show(name) {
    Object.keys(panels).forEach(function (key) { panels[key].hidden = key !== name; });
    door.setAttribute("data-state", name);
  }

  function stopForward() {
    if (forwardTimer !== null) { window.clearInterval(forwardTimer); forwardTimer = null; }
    forwardNote.hidden = true;
    stayButton.hidden = true;
  }

  function startForward(url) {
    var left = FORWARD_SECONDS;
    function label() { forwardCount.textContent = left + (left === 1 ? " second" : " seconds"); }
    label();
    forwardNote.hidden = false;
    stayButton.hidden = false;
    forwardTimer = window.setInterval(function () {
      left -= 1;
      if (left > 0) { label(); return; }
      stopForward();
      // replace(): "Back" in the demo then leaves this page instead of bouncing forward again.
      window.location.replace(url);
    }, 1000);
  }

  function apply(decision) {
    if (decision.state !== "online") {
      stopForward();
      shownUrl = null;
      openLink.removeAttribute("href");
      checkedTime.textContent = clock(Date.now());
      show("offline");
      return;
    }
    if (decision.url !== shownUrl) {
      stopForward();
      shownUrl = decision.url;
      openLink.setAttribute("href", decision.url);
      untilTime.textContent = clock(decision.until);
      untilNote.hidden = false;
      if (!stayed) { startForward(decision.url); }
    }
    show("online");
  }

  function check() {
    // The query string makes every request a new address, so an old copy is never reused.
    window.fetch("status.json?t=" + Date.now(), { cache: "no-store", credentials: "omit" })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (status) { apply(decide(status, Date.now())); })
      .catch(function () { apply({ state: "offline" }); });
  }

  stayButton.addEventListener("click", function () {
    stayed = true;
    stopForward();
  });
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { check(); }         // timers are slowed down in background tabs
  });
  window.setInterval(check, RECHECK_SECONDS * 1000);
  check();
})();
