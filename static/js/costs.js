/* Live COGS preview.

   Mirrors builder.engine.model in the browser so typing a rate immediately
   shows the resulting COGS, blended cost and estimated profit. The server
   still recomputes everything on submit — this is only a preview. */
(function () {
  "use strict";

  var data = window.PL && window.PL.json("preview-data");
  if (!data) return;

  var inputs = Array.prototype.slice.call(document.querySelectorAll("[data-family]"));
  var vatRadios = Array.prototype.slice.call(document.querySelectorAll("[name='cogs_vat']"));
  var out = {
    cogs: document.getElementById("pv-cogs"),
    blended: document.getElementById("pv-blended"),
    profit: document.getElementById("pv-profit"),
    margin: document.getElementById("pv-margin"),
    cogsPct: document.getElementById("pv-cogs-pct"),
    importVat: document.getElementById("pv-import-vat"),
    warn: document.getElementById("pv-warn")
  };

  function vatMode() {
    for (var i = 0; i < vatRadios.length; i++) {
      if (vatRadios[i].checked) return vatRadios[i].value;
    }
    return "included";
  }

  function recompute() {
    var mode = vatMode();
    var multiplier = mode === "excluded" ? 1.2 : 1.0;
    var cogs = 0;
    var unpriced = 0;

    inputs.forEach(function (input) {
      var units = data.families[input.dataset.family] || 0;
      var rate = parseFloat(input.value);
      if (!isFinite(rate) || rate <= 0) {
        if (units > 0) unpriced += 1;
        rate = 0;
      }
      cogs += units * rate * multiplier;

      var cell = document.querySelector('[data-family-cogs="' + input.dataset.family + '"]');
      if (cell) cell.textContent = window.PL.money(units * rate * multiplier, 0);
    });

    var importVat = mode === "none" ? 0 : cogs / 6;
    var inputVat = data.feeInputVat - importVat;  // both negative in the model
    var outputVat = 0;
    if (data.scheme === "20") outputVat = -(data.grossSales / 6) - inputVat;
    else if (data.scheme === "7.5") outputVat = -(data.grossSales / 107.5 * 7.5);

    var profit = data.netSales + data.fees + data.ppc - cogs + outputVat + data.opex;
    var blended = data.units ? cogs / data.units : 0;

    if (out.cogs) out.cogs.textContent = window.PL.money(-cogs, 0);
    if (out.blended) out.blended.textContent = "£" + blended.toFixed(2);
    if (out.importVat) out.importVat.textContent = window.PL.money(-importVat, 0);
    if (out.cogsPct) {
      out.cogsPct.textContent = data.netSales
        ? window.PL.percent(cogs / data.netSales) + " of net sales" : "—";
    }
    if (out.profit) {
      out.profit.textContent = window.PL.money(profit, 0);
      out.profit.classList.toggle("neg", profit < 0);
      out.profit.classList.toggle("pos", profit >= 0);
    }
    if (out.margin) {
      out.margin.textContent = data.netSales
        ? window.PL.percent(profit / data.netSales) + " margin" : "—";
    }
    if (out.warn) {
      out.warn.hidden = unpriced === 0;
      if (unpriced) {
        out.warn.textContent = unpriced + " product famil" +
          (unpriced === 1 ? "y has" : "ies have") +
          " no landed cost, so COGS is understated.";
      }
    }
  }

  inputs.forEach(function (input) {
    input.addEventListener("input", recompute);
  });
  vatRadios.forEach(function (radio) {
    radio.addEventListener("change", recompute);
  });

  // Apply one rate to every family.
  var blanket = document.getElementById("blanket-rate");
  var apply = document.getElementById("blanket-apply");
  if (apply && blanket) {
    apply.addEventListener("click", function () {
      var rate = parseFloat(blanket.value);
      if (!isFinite(rate) || rate < 0) { blanket.focus(); return; }
      inputs.forEach(function (input) { input.value = rate.toFixed(2); });
      recompute();
    });
  }

  recompute();
})();
