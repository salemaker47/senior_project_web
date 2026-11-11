/*
 * Cookie banner helper. Loaded only while the visitor has not accepted.
 *
 * A decline stores nothing on the server and sets no cookie, so the server
 * cannot remember it. To keep the banner small on the next pages, the choice
 * is noted in this tab's sessionStorage. It never leaves the browser and is
 * gone when the tab closes.
 */
(function () {
  "use strict";
  var KEY = "cookieConsentDeclined";
  var banner = document.getElementById("cookie-banner");
  if (!banner) { return; }

  function read() {
    try { return window.sessionStorage.getItem(KEY) === "1"; } catch (e) { return false; }
  }
  function write(declined) {
    try {
      if (declined) { window.sessionStorage.setItem(KEY, "1"); }
      else { window.sessionStorage.removeItem(KEY); }
    } catch (e) { /* storage blocked: the banner simply stays large */ }
  }

  if (banner.classList.contains("is-declined")) {
    write(true);                       // arrived from the decline redirect
  } else if (read()) {
    banner.classList.add("is-declined");
  }

  document.addEventListener("submit", function (event) {
    var kind = event.target.getAttribute && event.target.getAttribute("data-consent");
    if (kind === "decline") { write(true); }
    if (kind === "accept") { write(false); }
  });
})();
