(function () {
  "use strict";
  var key = "sentinel-theme";
  var theme = null;
  try {
    var forced = new URLSearchParams(window.location.search).get("theme");
    if (forced === "light" || forced === "dark") {
      theme = forced;
      window.localStorage.setItem(key, forced);
    }
  } catch (_error) {
    theme = null;
  }
  if (theme !== "light" && theme !== "dark") {
    try {
      theme = window.localStorage.getItem(key);
    } catch (_error) {
      theme = null;
    }
  }
  if (theme !== "light" && theme !== "dark") {
    try {
      theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    } catch (_error) {
      theme = "dark";
    }
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
})();
