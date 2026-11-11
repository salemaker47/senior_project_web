/*
 * Result page: interactive overlay.
 *
 * Without JavaScript the page shows overlay.png as rendered by the server.
 * With it, the mask is painted red on a canvas above the original image and
 * the slider sets how strongly it shows.
 */
(function () {
  "use strict";
  var viewer = document.querySelector("[data-viewer]");
  var sliderBox = document.querySelector("[data-slider]");
  if (!viewer || !sliderBox) { return; }

  var slider = sliderBox.querySelector('input[type="range"]');
  var output = sliderBox.querySelector("output");
  var fallback = viewer.querySelector("[data-viewer-fallback]");
  var RED = [229, 57, 53];

  var mask = new Image();
  mask.onload = function () {
    var canvas = document.createElement("canvas");
    canvas.width = mask.naturalWidth;
    canvas.height = mask.naturalHeight;
    canvas.className = "viewer__tint";
    canvas.setAttribute("aria-hidden", "true");
    var context = canvas.getContext("2d");
    var pixels;
    try {
      context.drawImage(mask, 0, 0);
      pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    } catch (error) {
      return;                               // keep the server-rendered overlay
    }
    var data = pixels.data;
    for (var i = 0; i < data.length; i += 4) {
      var on = data[i] > 127;
      data[i] = RED[0];
      data[i + 1] = RED[1];
      data[i + 2] = RED[2];
      data[i + 3] = on ? 255 : 0;
    }
    context.putImageData(pixels, 0, 0);

    var base = new Image();
    base.onload = function () {
      base.alt = fallback.alt;
      base.width = mask.naturalWidth;
      base.height = mask.naturalHeight;
      viewer.replaceChild(base, fallback);
      viewer.appendChild(canvas);
      viewer.classList.add("is-interactive");
      sliderBox.hidden = false;
      apply();
    };
    base.src = viewer.getAttribute("data-original");
  };
  mask.src = viewer.getAttribute("data-mask");

  function apply() {
    var value = parseInt(slider.value, 10);
    output.textContent = value + "%";
    var canvas = viewer.querySelector("canvas");
    if (canvas) { canvas.style.opacity = String(value / 100); }
  }

  slider.addEventListener("input", apply);
})();
