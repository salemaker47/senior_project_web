/* Site-wide behaviour. No dependencies. */
(function () {
  "use strict";

  // Forms with data-confirm ask before they submit ("Delete my data").
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var message = form.getAttribute && form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });
})();
