/* Upload form: size check before sending, and a busy state while the model runs. */
(function () {
  "use strict";
  var form = document.querySelector("[data-upload-form]");
  if (!form) { return; }

  var input = form.querySelector('input[type="file"]');
  var warning = form.querySelector("[data-size-warning]");
  var submit = form.querySelector("[data-submit]");
  var busy = form.querySelector("[data-busy]");
  var maxBytes = parseInt(form.getAttribute("data-max-bytes"), 10) || 0;
  var maxMb = form.getAttribute("data-max-mb");

  function tooLarge() {
    var file = input.files && input.files[0];
    return Boolean(file && maxBytes && file.size > maxBytes);
  }

  function refresh() {
    if (tooLarge()) {
      var mb = (input.files[0].size / (1024 * 1024)).toFixed(1);
      warning.textContent = "This file is " + mb + " MB. The limit for a 2D scan is " + maxMb + " MB.";
      warning.hidden = false;
    } else {
      warning.hidden = true;
    }
  }

  input.addEventListener("change", refresh);

  form.addEventListener("submit", function (event) {
    if (tooLarge()) {
      event.preventDefault();
      refresh();
      input.focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = "Predicting…";
    busy.hidden = false;
  });

  // Coming back with the browser's Back button must not leave the form locked.
  window.addEventListener("pageshow", function () {
    submit.disabled = false;
    submit.textContent = "Predict tumor mask";
    busy.hidden = true;
  });
})();
