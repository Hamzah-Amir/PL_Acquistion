/* Poll the job's progress endpoint and drive the ring, message and stage list. */
(function () {
  "use strict";

  var shell = document.getElementById("progress");
  if (!shell) return;

  var url = shell.dataset.url;
  var ring = document.getElementById("ring-bar");
  var pct = document.getElementById("progress-pct");
  var msg = document.getElementById("progress-msg");
  var stages = Array.prototype.slice.call(document.querySelectorAll(".progress-stages li"));
  var failure = document.getElementById("progress-error");

  var radius = ring ? ring.r.baseVal.value : 54;
  var circumference = 2 * Math.PI * radius;
  if (ring) {
    ring.style.strokeDasharray = circumference + " " + circumference;
    ring.style.strokeDashoffset = circumference;
  }

  function paint(value) {
    if (ring) ring.style.strokeDashoffset = circumference * (1 - value / 100);
    if (pct) pct.textContent = Math.round(value) + "%";
  }

  function markStages(value) {
    stages.forEach(function (item) {
      var at = parseFloat(item.dataset.at);
      item.classList.toggle("done", value > at + 18);
      item.classList.toggle("active", value >= at && value <= at + 18);
    });
  }

  var delay = 900;

  function poll() {
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        paint(data.progress || 0);
        markStages(data.progress || 0);
        if (msg && data.message) msg.textContent = data.message;

        if (data.status === "failed") {
          if (failure) {
            failure.hidden = false;
            var detail = failure.querySelector(".detail");
            if (detail) detail.textContent = data.error || "Unknown error.";
          }
          stages.forEach(function (i) { i.classList.remove("active"); });
          return;
        }
        if (data.done && data.next) {
          paint(100);
          window.location.href = data.next;
          return;
        }
        setTimeout(poll, delay);
      })
      .catch(function () {
        // A transient failure while the server is busy parsing; back off.
        delay = Math.min(delay * 1.6, 5000);
        setTimeout(poll, delay);
      });
  }

  poll();
})();
