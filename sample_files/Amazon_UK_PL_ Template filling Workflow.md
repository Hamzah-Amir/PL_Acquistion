# Workflow — Building the Amazon UK Acquisition P&L

**Purpose:** rebuild a fully reconciled 13‑month P&L, COGS, PPC, traffic and fee‑reconciliation model for a UK Amazon FBA acquisition, from raw seller exports. Attach this file **and** the template workbook (`Amazon_UK_PL_TEMPLATE.xlsx`) at the start of a new chat, then upload the source files below. Claude fills the template step by step.

---

## 1. What the user provides

Upload these (one set = the trailing 13 months, e.g. Jun‑2025 → Jun‑2026):

| # | Files | Where in Seller Central | Used for |
|---|---|---|---|
| A | **13 monthly Summary PDFs** | Payments ▸ Reports Repository ▸ Date Range Reports ▸ *Summary* (one per month) | Revenue lines + every Amazon fee. The authoritative source everything reconciles to. |
| B | **13 monthly Transaction CSVs** | Payments ▸ Date Range Reports ▸ *Transaction* (flat file) | Units sold per SKU per month; fee reconciliation. |
| C | **13 monthly Business Reports** | Reports ▸ Business Reports ▸ *Detail Page Sales & Traffic by Child Item* (CSV) | Sessions, page views, conversion, Buy Box %, ASIN count. |
| D | **Seller's evaluation / SellerBoard export** (xlsx) | From the seller | Per‑SKU / per‑family landed cost (COGS rates). |
| E | **PPC invoices** (zip of Amazon advertising tax‑invoice PDFs) | Advertising ▸ Invoices, or from the seller | PPC cost split into net + VAT. |

**Decisions the user must state** (put answers in the template's `Assumptions`):
- **VAT registered?** If not, output VAT = £0 and no input‑VAT is reclaimable (fees/PPC/COGS stay VAT‑inclusive). If registered, apply output VAT ≈ NetSales ÷ 6 and model input‑VAT reclaim.
- **Off‑Amazon operating costs** to include (agency fee, software, VAs, prep, freight, insurance) — or none.
- **Asking price** (optional) for the valuation multiple — or leave blank.
- **Per‑SKU → product‑family mapping** if any SKU is ambiguous (Claude proposes; user confirms).

---

## 2. Conventions (apply throughout)

- **Costs are negative**; revenue positive. Net Sales + (all negative costs) = profit.
- **VAT split:** Amazon fees & PPC are VAT‑inclusive. ex‑VAT = amount ÷ 1.2; VAT = amount − ex‑VAT (so the two always re‑sum to the inclusive figure).
- **TTM** = the most recent 12 of the 13 months (drop the oldest).
- **Colour key:** blue = hard input from a source file; black = formula; green = cross‑sheet/other‑source link; yellow = editable assumption.
- **Golden rule — reconcile everything.** Every month must tie to Amazon's own totals (see §4).

---

## 3. Step‑by‑step for Claude

**Step 1 — Summary PDFs → monthly revenue & fees.** From each month's Summary PDF, read the Income and Expenses line items into `Inputs_Monthly` (one row per month). Capture: product sales (FBA + seller‑fulfilled), product‑sale refunds, delivery credit refunds, postage credits, FBA inventory credit, gift‑wrap credit refunds, promotional rebates + refunds, and the printed **Income total**; then FBA selling fees, seller‑fulfilled selling fees, selling‑fee refunds, FBA transaction fees + refunds, other transaction fees + refunds, FBA inventory & inbound (storage), service fees, refund administration fees, delivery‑label purchases, adjustments, Cost of Advertising, and the printed **Expenses total**.

**Step 2 — P&L revenue & fees.** In the P&L, group and **split**:
- Product Sales = FBA + SF; Other Income = postage + inventory credit + gift‑wrap; Promo (net) = rebates + refunds; Returns & Refunds = product refunds + delivery credit refunds. Net Sales = their sum → must equal the PDF Income total.
- **Referral / Selling Fees** = FBA selling + SF selling + selling‑fee refunds → split into ex‑VAT and VAT @20%.
- **FBA Fulfilment Fees** = FBA transaction fees + refunds → split ex‑VAT / VAT @20%.
- **Storage & Inbound** = FBA inventory & inbound (inclusive).
- **Other Fees** = other txn + other txn refunds + service fees + refund admin + delivery label + adjustments (inclusive).

**Step 3 — Transaction CSVs → units & fee checks.** Skip the ~9 preamble rows (header row begins `date/time,settlement id,type,…`). Per SKU per month, **net units = Σ quantity where type=Order − Σ quantity where type=Refund**. Also confirm: order‑line `selling fees` ties to the Summary referral debit; the `fba fees` column ties to Summary FBA transaction fees; `FBA Inventory Fee` rows tie to Summary storage. Note the CSV files a periodic "Amazon Fees" charge (deal/subscription/coupon) into its selling‑fees column — it belongs in **Other Fees**, not referral.

**Step 4 — Evaluation sheet → cost rates.** From the SellerBoard/evaluation P&L, compute each product's landed cost = its Cost‑of‑Goods ÷ its units. Group into families (e.g. loom kit, fidget pen, refill/glow, plus any single‑SKU products). Put these in the **Cost Rate Table** on `Inputs_Units`. If the seller quotes a single blanket figure, still derive per‑family rates from their COGS column and flag any discrepancy (a blanket rate weighted by the real sales mix is usually very different).

**Step 5 — COGS (bottom‑up).** On `Inputs_Units`, each SKU's £/unit references its family rate. Monthly COGS = Σ over SKUs (net units × rate). The P&L COGS line links to these monthly totals. Report the blended £/unit (= total COGS ÷ total units) and reconcile it to the seller's implied rate.

**Step 6 — Business Reports → traffic.** Per month sum sessions, page views, units ordered; conversion = units ÷ sessions; Buy Box = session‑weighted; count child ASINs. Flag any Buy‑Box drop or conversion slide.

**Step 7 — PPC invoices → net/VAT.** Read every invoice PDF (dedupe by invoice number). VAT = gross − net (each invoice = net × 1.20). Bucket by invoice date; reconcile monthly gross to the Summary "Cost of Advertising". **Use the settlement monthly figure in the P&L** (it reconciles to Expenses totals), split ex‑VAT (÷1.2) / VAT (÷6); the invoices validate the 20% split and provide the audit trail.

**Step 8 — Apply user decisions.** Set the VAT toggle (output VAT £0 if unregistered), enter any off‑Amazon operating cost, and the asking price if provided.

**Step 9 — Build tabs, then verify.** Produce the tabs in §5, run a recalc, and confirm every reconciliation in §4 is zero before presenting.

---

## 4. Verification checklist (must all pass)

- [ ] **Income check** — for every month, Net Sales − (PDF Income total) = **0**.
- [ ] **Expenses check** — for every month, (Total Amazon Fees + PPC) − (PDF Expenses total) = **0**.
- [ ] **COGS** — Σ(units × rate) blended £/unit reconciles to the seller's implied rate; note any gap.
- [ ] **PPC** — invoice gross ties to settlement advertising for most months; explain any timing gaps.
- [ ] **Fee ties** — referral, FBA and storage each tie between Summary PDF and transaction CSV.
- [ ] **Other Fees** — Subscription + Deal + Coupon + other components sum to the P&L Other Fees line.
- [ ] Recalc reports **0 formula errors**.

---

## 5. Tab reference (what the finished workbook contains)

1. **Status & Missing** — what's loaded, what's still needed, key flags.
2. **P&L** — 13 months + TTM: revenue, fees (referral/FBA split net+VAT, storage, other), PPC (split net+VAT), COGS, output VAT, net profit, metrics, assumptions, income/expense check rows.
3. **SKU Concentration** — revenue by SKU and product family; top‑SKU / top‑5 share.
4. **COGS Build** — units per SKU per month × the editable Cost Rate Table → monthly COGS.
5. **PPC Invoices** — every invoice (date, period, net, VAT, gross); monthly totals vs settlement.
6. **Fee Reconciliation** — referral / FBA / storage: Summary vs CSV; Other Fees split into Subscription / Deal / Coupon / other, with a chart.
7. **Traffic & Conversion** — sessions, page views, conversion, Buy Box, ASIN count.
8. **Summary** — TTM KPIs, sensitivity (landed cost × VAT status), YoY, concentration.

---

## 6. Notes / gotchas learned

- Referral (selling) fees post erratically month‑to‑month (settlement timing) — trust the 12‑month total, not any single month.
- "Service fees" on the Summary bundles the **£30/mo subscription + Deal fees + Coupon fees** — split them; Deal fees mark the months a paid Deal was run.
- Product titles can contain words like "Deal", so match fee rows by transaction *type*, not just description.
- If TTM turnover > £90k the buyer will likely have to VAT‑register — model the output‑VAT scenario even if the seller currently isn't registered.
- The sale may be **asset‑only** (brand + ASINs), not the Seller Central account — confirm what transfers.
