/*
 * Runs on every page. If the site is shown inside a frame (for example the
 * hosting page on huggingface.co), browsers treat its cookie as third-party
 * and drop it, so consent and upload cannot work there. Tell the visitor and
 * offer the site in its own tab. Outside a frame this does nothing.
 */
(function () {
  "use strict";
  var framed;
  try { framed = window.self !== window.top; } catch (e) { framed = true; }
  if (!framed) { return; }

  document.documentElement.classList.add("is-framed");
  var notice = document.getElementById("framed-notice");
  var link = document.getElementById("framed-open");
  if (link) { link.href = window.location.href; }
  if (notice) { notice.hidden = false; }
})();
