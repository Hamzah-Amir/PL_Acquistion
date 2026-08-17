/* Shared behaviour: theme toggle, dismissible alerts, tooltips, formatters. */
(function () {
  "use strict";

  // --- theme ---------------------------------------------------------------
  var root = document.documentElement;
  var stored = null;
  try { stored = localStorage.getItem("pl-theme"); } catch (e) { /* private mode */ }
  if (stored === "dark" || stored === "light") root.setAttribute("data-theme", stored);
  else root.removeAttribute("data-theme");

  function currentlyDark() {
    var explicit = root.getAttribute("data-theme");
    if (explicit) return explicit === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    var label = toggle.querySelector(".theme-label");
    var sync = function () { if (label) label.textContent = currentlyDark() ? "Light" : "Dark"; };
    sync();
    toggle.addEventListener("click", function () {
      var next = currentlyDark() ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("pl-theme", next); } catch (e) { /* ignore */ }
      sync();
    });
  }

  // --- dismissible alerts --------------------------------------------------
  document.addEventListener("click", function (event) {
    if (event.target.classList.contains("alert-close")) {
      var alert = event.target.closest(".alert");
      if (alert) alert.remove();
    }
  });

  // --- shared tooltip ------------------------------------------------------
  var tip = document.createElement("div");
  tip.className = "tooltip";
  tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);

  window.PL = {
    money: function (value, decimals) {
      var d = decimals === undefined ? 2 : decimals;
      var sign = value < 0 ? "-" : "";
      return sign + "£" + Math.abs(value).toLocaleString("en-GB", {
        minimumFractionDigits: d, maximumFractionDigits: d
      });
    },
    percent: function (value, decimals) {
      var d = decimals === undefined ? 1 : decimals;
      return (value * 100).toFixed(d) + "%";
    },
    number: function (value) {
      return Math.round(value).toLocaleString("en-GB");
    },
    showTip: function (html, x, y) {
      tip.innerHTML = html;
      tip.classList.add("show");
      var box = tip.getBoundingClientRect();
      var left = Math.min(Math.max(8, x - box.width / 2), window.innerWidth - box.width - 8);
      var top = y - box.height - 12;
      if (top < 8) top = y + 18;
      tip.style.left = left + "px";
      tip.style.top = top + "px";
    },
    hideTip: function () { tip.classList.remove("show"); },
    json: function (id) {
      var node = document.getElementById(id);
      if (!node) return null;
      try { return JSON.parse(node.textContent); } catch (e) { return null; }
    }
  };
})();
