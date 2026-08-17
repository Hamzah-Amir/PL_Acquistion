/* Monthly chart: net-profit bars with a net-sales line, drawn as inline SVG so
   no charting library is needed. Hovering a month shows its full breakdown. */
(function () {
  "use strict";

  var data = window.PL && window.PL.json("chart-data");
  var host = document.getElementById("chart");
  if (!data || !host || !data.labels.length) return;

  var W = 900, H = 260;
  var padL = 56, padR = 16, padT = 14, padB = 30;
  var plotW = W - padL - padR, plotH = H - padT - padB;
  var n = data.labels.length;
  var slot = plotW / n;
  var barW = Math.min(34, slot * 0.56);

  var profits = data.profit;
  var sales = data.netSales;
  var lo = Math.min(0, Math.min.apply(null, profits));
  var hi = Math.max(0, Math.max.apply(null, profits));
  var salesMax = Math.max.apply(null, sales) || 1;
  if (hi === lo) hi = lo + 1;
  var pad = (hi - lo) * 0.12;
  lo -= pad; hi += pad;

  function yProfit(v) { return padT + plotH - ((v - lo) / (hi - lo)) * plotH; }
  function ySales(v) { return padT + plotH - (v / salesMax) * plotH * 0.92; }
  function xCentre(i) { return padL + slot * i + slot / 2; }

  var svg = ['<svg class="chart" viewBox="0 0 ' + W + " " + H +
    '" role="img" aria-label="Net profit and net sales by month">'];

  // Zero line and value ticks.
  var zeroY = yProfit(0);
  svg.push('<line class="zero" x1="' + padL + '" y1="' + zeroY +
    '" x2="' + (W - padR) + '" y2="' + zeroY + '"/>');
  [lo, (lo + hi) / 2, hi].forEach(function (value) {
    var y = yProfit(value);
    svg.push('<text class="tick" x="' + (padL - 8) + '" y="' + (y + 3) +
      '" text-anchor="end">' + Math.round(value / 1000) + "k</text>");
  });

  // Bars.
  for (var i = 0; i < n; i++) {
    var v = profits[i];
    var y = yProfit(Math.max(v, 0));
    var h = Math.abs(yProfit(v) - zeroY);
    var cls = (v < 0 ? "bar-neg" : "bar-pos") + (data.inTtm[i] ? "" : " bar-dim");
    svg.push('<rect class="' + cls + '" x="' + (xCentre(i) - barW / 2) +
      '" y="' + y + '" width="' + barW + '" height="' + Math.max(h, 1) +
      '" rx="2"/>');
  }

  // Net-sales line on its own scale.
  var path = sales.map(function (value, index) {
    return (index ? "L" : "M") + xCentre(index) + " " + ySales(value);
  }).join(" ");
  svg.push('<path class="line" d="' + path + '"/>');
  sales.forEach(function (value, index) {
    svg.push('<circle class="point" cx="' + xCentre(index) + '" cy="' +
      ySales(value) + '" r="2.5"/>');
  });

  // Month labels, thinned out when there is no room.
  var every = n > 9 ? 2 : 1;
  data.labels.forEach(function (text, index) {
    if (index % every) return;
    svg.push('<text class="tick" x="' + xCentre(index) + '" y="' + (H - 10) +
      '" text-anchor="middle">' + text + "</text>");
  });

  // Invisible hover targets last, so they sit on top.
  for (var j = 0; j < n; j++) {
    svg.push('<rect class="hit" data-index="' + j + '" x="' + (padL + slot * j) +
      '" y="' + padT + '" width="' + slot + '" height="' + plotH + '"/>');
  }
  svg.push("</svg>");
  host.innerHTML = svg.join("");

  var M = window.PL.money;
  host.querySelectorAll(".hit").forEach(function (target) {
    target.addEventListener("mousemove", function (event) {
      var i = parseInt(target.dataset.index, 10);
      window.PL.showTip(
        "<b>" + data.labels[i] + "</b>" + (data.inTtm[i] ? "" : " (outside TTM)") +
        "<br>Net sales " + M(data.netSales[i], 0) +
        "<br>Amazon fees " + M(-data.fees[i], 0) +
        "<br>PPC " + M(-data.ppc[i], 0) +
        "<br>COGS " + M(-data.cogs[i], 0) +
        "<br>Units " + window.PL.number(data.units[i]) +
        "<br><b>Profit " + M(data.profit[i], 0) + "</b>",
        event.clientX, event.clientY
      );
    });
    target.addEventListener("mouseleave", window.PL.hideTip);
  });
})();
