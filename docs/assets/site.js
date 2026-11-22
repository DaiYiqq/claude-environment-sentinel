(function () {
  "use strict";

  var root = document.documentElement;
  var toggle = document.getElementById("theme-toggle");
  var meta = document.querySelector('meta[name="theme-color"]');

  function apply(theme) {
    var normalized = theme === "light" ? "light" : "dark";
    root.dataset.theme = normalized;
    root.style.colorScheme = normalized;
    if (toggle) {
      toggle.textContent = normalized === "dark" ? "浅色" : "深色";
      toggle.setAttribute("aria-label", normalized === "dark" ? "切换到浅色模式" : "切换到深色模式");
    }
    if (meta) meta.setAttribute("content", normalized === "dark" ? "#07111f" : "#f4f8fc");
  }

  apply(root.dataset.theme || "dark");

  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = root.dataset.theme === "light" ? "dark" : "light";
      apply(next);
      try {
        localStorage.setItem("sentinel-site-theme", next);
      } catch (_error) {
        // Storage may be disabled; the current page still switches.
      }
    });
  }

  var year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());

  if ("IntersectionObserver" in window && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var cards = document.querySelectorAll(".card, .section-heading, .download");
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    cards.forEach(function (card) {
      card.classList.add("reveal");
      observer.observe(card);
    });
  }
})();
