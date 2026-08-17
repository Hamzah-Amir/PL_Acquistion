"""The P&L model itself — workflow §2 conventions, §3 steps 2/5/8 and the §4
verification checklist.

Costs are negative and revenue positive throughout.  Amazon fees and PPC are
VAT-inclusive: ex-VAT = amount / 1.2, VAT = amount - ex-VAT, so the two halves
always re-sum to the inclusive figure.
"""
from __future__ import annotations

from dataclasses import dataclass, field

VAT_DIVISOR = 1.2
TOLERANCE = 0.005  # half a penny

# VAT schemes the user can pick between.
SCHEME_NONE = "0"      # not registered — no output VAT, input VAT irrecoverable
SCHEME_FLAT = "7.5"    # flat rate — output VAT on turnover, input VAT irrecoverable
SCHEME_STANDARD = "20"  # standard — output VAT less reclaimable input VAT

VAT_SCHEMES = {
    SCHEME_NONE: "0% — not registered (input VAT is a cost)",
    SCHEME_FLAT: "7.5% — flat rate (input VAT is a cost)",
    SCHEME_STANDARD: "20% — standard (input VAT reclaimable)",
}


def normalise_scheme(settings: dict) -> str:
    """Read the VAT scheme, tolerating the older boolean 'vat_registered' flag."""
    scheme = str(settings.get("vat_scheme") or "").strip()
    if scheme in VAT_SCHEMES:
        return scheme
    return SCHEME_STANDARD if settings.get("vat_registered") else SCHEME_NONE


def ex_vat(amount: float) -> float:
    return round(amount / VAT_DIVISOR, 2)


def vat_part(amount: float) -> float:
    """VAT is the residual, so ex-VAT + VAT == the inclusive amount exactly."""
    return round(amount - ex_vat(amount), 2)


def vat_of_inclusive(amount: float) -> float:
    """VAT component of a 20%-inclusive amount (amount x 20/120)."""
    return round(amount / 6, 2)


@dataclass
class MonthRow:
    key: str
    label: str

    product_sales: float = 0.0
    other_income: float = 0.0
    promo_net: float = 0.0
    returns_refunds: float = 0.0
    income_total: float = 0.0
    # Sales tax Amazon collected from buyers.  Reported below the Income
    # reconciliation because Amazon totals it separately from Income.
    sales_tax: float = 0.0
    tax_withheld: float = 0.0

    referral_ex: float = 0.0
    referral_vat: float = 0.0
    fba_ex: float = 0.0
    fba_vat: float = 0.0
    storage: float = 0.0
    other_fees: float = 0.0

    ppc_ex: float = 0.0
    ppc_vat: float = 0.0
    expenses_total: float = 0.0

    units: int = 0
    cogs: float = 0.0
    # Import VAT inside the landed cost.  If the user's rate already includes
    # VAT this is COGS / 6; if it excludes VAT the rate is grossed up by 20%
    # first, which comes to the same thing.
    cogs_vat: float = 0.0
    # Input VAT buried in the VAT-inclusive Amazon fees and PPC.  Reported on
    # every scheme, but only the standard scheme nets it off the VAT bill — on
    # the other two it is already inside the cost lines, so adding it to profit
    # would double-count it.
    input_vat: float = 0.0
    output_vat: float = 0.0
    opex: float = 0.0

    # Traffic (workflow §6)
    sessions: int = 0
    page_views: int = 0
    units_ordered: int = 0
    buy_box: float = 0.0
    child_asins: int = 0
    has_traffic: bool = False

    # Fee reconciliation detail (workflow §4 / §6)
    csv_referral: float = 0.0
    csv_fba: float = 0.0
    csv_storage: float = 0.0
    summary_referral: float = 0.0
    summary_fba: float = 0.0
    summary_storage: float = 0.0
    other_txn_fees: float = 0.0
    other_txn_fee_refunds: float = 0.0
    subscription_fees: float = 0.0
    deal_fees: float = 0.0
    coupon_fees: float = 0.0
    other_service_fees: float = 0.0
    refund_admin_fees: float = 0.0
    delivery_labels: float = 0.0
    adjustments: float = 0.0
    residual_expense: float = 0.0

    ppc_invoice_net: float = 0.0
    ppc_invoice_gross: float = 0.0
    ppc_invoice_count: int = 0

    has_transactions: bool = False

    @property
    def net_sales(self) -> float:
        return round(
            self.product_sales + self.other_income + self.promo_net + self.returns_refunds, 2
        )

    @property
    def gross_sales(self) -> float:
        """Sales including the tax the buyer paid — the VAT-inclusive figure the
        output-VAT formulas divide into."""
        return round(self.net_sales + self.sales_tax, 2)

    @property
    def income_difference(self) -> float:
        return round(self.net_sales - self.income_total, 2)

    @property
    def referral_incl(self) -> float:
        return round(self.referral_ex + self.referral_vat, 2)

    @property
    def fba_incl(self) -> float:
        return round(self.fba_ex + self.fba_vat, 2)

    @property
    def total_fees(self) -> float:
        return round(
            self.referral_ex + self.referral_vat + self.fba_ex + self.fba_vat
            + self.storage + self.other_fees, 2
        )

    @property
    def total_ppc(self) -> float:
        return round(self.ppc_ex + self.ppc_vat, 2)

    @property
    def expenses_difference(self) -> float:
        return round(self.total_fees + self.total_ppc - self.expenses_total, 2)

    @property
    def net_profit(self) -> float:
        return round(
            self.net_sales + self.total_fees + self.total_ppc
            + self.cogs + self.output_vat + self.opex, 2
        )

    @property
    def avg_selling_price(self) -> float:
        """Gross of tax — what the buyer paid per unit."""
        return round(self.gross_sales / self.units, 2) if self.units else 0.0

    @property
    def conversion(self) -> float:
        return self.units_ordered / self.sessions if self.sessions else 0.0

    @property
    def total_other_fees_components(self) -> float:
        return round(
            self.other_txn_fees + self.other_txn_fee_refunds + self.subscription_fees
            + self.deal_fees + self.coupon_fees + self.other_service_fees
            + self.refund_admin_fees + self.delivery_labels + self.adjustments
            + self.residual_expense, 2
        )


@dataclass
class Check:
    name: str
    detail: str
    passed: bool
    severity: str = "error"  # "error" blocks the golden rule; "warning" informs


@dataclass
class SkuRow:
    sku: str
    title: str
    family: str
    rate: float
    units_by_month: dict[str, int]
    sales_by_month: dict[str, float]

    def units(self, key: str) -> int:
        return self.units_by_month.get(key, 0)

    def sales(self, key: str) -> float:
        return self.sales_by_month.get(key, 0.0)


@dataclass
class PLModel:
    months: list[MonthRow]
    skus: list[SkuRow]
    families: dict[str, float]
    invoices: list[dict]
    checks: list[Check] = field(default_factory=list)
    settings: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    seller: dict = field(default_factory=dict)

    @property
    def ttm(self) -> list[MonthRow]:
        """TTM = the most recent 12 of the 13 months (drop the oldest)."""
        return self.months[-12:] if len(self.months) > 12 else self.months

    def ttm_sum(self, attribute: str) -> float:
        return round(sum(getattr(m, attribute) for m in self.ttm), 2)

    @property
    def ttm_units(self) -> int:
        return sum(m.units for m in self.ttm)

    @property
    def blended_landed_cost(self) -> float:
        units = self.ttm_units
        return round(-self.ttm_sum("cogs") / units, 4) if units else 0.0

    @property
    def scheme(self) -> str:
        return normalise_scheme(self.settings)

    @property
    def scheme_label(self) -> str:
        return VAT_SCHEMES.get(self.scheme, self.scheme)

    @property
    def input_vat_is_reclaimable(self) -> bool:
        return self.scheme == SCHEME_STANDARD

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "error")


def _vat_line(scheme: str, gross_sales: float, input_vat: float) -> float:
    """The VAT charge that hits the P&L, as a cost (negative).

    *gross_sales* is VAT-inclusive (Net Sales plus the tax collected).

    * 0%    — nothing to pay; the irrecoverable input VAT already sits inside
              the VAT-inclusive fee lines, so it is reported but not deducted
              again.
    * 7.5%  — flat rate on turnover: Gross Sales / 107.5 x 7.5.  Input VAT is
              likewise irrecoverable and already inside the cost lines.
    * 20%   — standard: Gross Sales / 6 less the reclaimable input VAT.  If the
              reclaim exceeds the output VAT the result is positive, i.e. a
              repayment due from HMRC.
    """
    if scheme == SCHEME_FLAT:
        return -round(gross_sales / 107.5 * 7.5, 2)
    if scheme == SCHEME_STANDARD:
        # input_vat is negative (a cost); subtracting it credits the reclaim.
        return round(-(gross_sales / 6) - input_vat, 2)
    return 0.0


def build_model(parse: dict, settings: dict) -> PLModel:
    """Combine the parsed sources with the user's decisions into the model."""
    window: list[str] = settings.get("window") or parse["month_keys"]
    families: dict[str, float] = {
        name: float(rate) for name, rate in (settings.get("family_rates") or {}).items()
    }
    sku_family: dict[str, str] = settings.get("sku_families") or {}
    report_map: dict[str, str] = settings.get("report_month_map") or {}
    scheme = normalise_scheme(settings)
    opex_monthly = float(settings.get("opex_monthly") or 0.0)
    # Was any VAT paid on the goods at all?  Zero-rated goods, or a supplier
    # outside the VAT system, mean the rate is used exactly as entered.  If VAT
    # was paid, the rate either already includes it or is grossed up by 20%.
    cogs_vat_paid = settings.get("cogs_vat_paid", True)
    cogs_vat_included = settings.get("cogs_vat_included", True)
    cogs_multiplier = 1.2 if (cogs_vat_paid and not cogs_vat_included) else 1.0

    months_by_key = parse["months"]
    txn_by_key = parse["transactions"]

    traffic_by_month: dict[str, dict] = {}
    for report in parse["business_reports"]:
        key = report_map.get(report["source"])
        if key:
            traffic_by_month[key] = report

    invoices_by_month: dict[str, list[dict]] = {}
    for invoice in parse["invoices"]:
        invoices_by_month.setdefault(invoice["month"], []).append(invoice)

    # --- SKU rows and their cost rate (workflow steps 4 & 5) -------------
    sku_rows: list[SkuRow] = []
    for sku in parse["skus"]:
        family = sku_family.get(sku["sku"], sku["family"])
        sku_rows.append(
            SkuRow(
                sku=sku["sku"],
                title=sku["title"],
                family=family,
                rate=round(families.get(family, 0.0), 4),
                units_by_month={k: int(v) for k, v in sku["units_by_month"].items()},
                sales_by_month={k: float(v) for k, v in sku["sales_by_month"].items()},
            )
        )

    rows: list[MonthRow] = []
    for key in window:
        source = months_by_key.get(key, {})
        txn = txn_by_key.get(key, {})
        row = MonthRow(key=key, label=source.get("label") or key)

        # Step 2 — revenue groupings.  The residual bucket sweeps up the rarely
        # used income lines (A-to-z, chargebacks, SAFE-T, ...) so Net Sales
        # always equals the printed Income total.
        row.product_sales = round(
            source.get("product_sales_fba", 0.0) + source.get("product_sales_sf", 0.0), 2
        )
        row.other_income = round(
            source.get("postage_credits", 0.0) + source.get("inventory_credit", 0.0)
            + source.get("giftwrap_credits", 0.0) + source.get("residual_income", 0.0), 2
        )
        row.promo_net = round(
            source.get("promo_rebates", 0.0) + source.get("promo_rebate_refunds", 0.0), 2
        )
        row.returns_refunds = round(
            source.get("refund_fba", 0.0) + source.get("refund_sf", 0.0)
            + source.get("delivery_credit_refunds", 0.0), 2
        )
        row.income_total = source.get("income_total", 0.0)
        row.expenses_total = source.get("expenses_total", 0.0)
        row.sales_tax = source.get("sales_tax", 0.0)
        row.tax_withheld = source.get("tax_withheld", 0.0)

        # Step 2 — fees, split ex-VAT / VAT @20%.
        referral = round(
            source.get("selling_fees_fba", 0.0) + source.get("selling_fees_sf", 0.0)
            + source.get("selling_fee_refunds", 0.0), 2
        )
        row.referral_ex, row.referral_vat = ex_vat(referral), vat_part(referral)

        fba = round(
            source.get("fba_txn_fees", 0.0) + source.get("fba_txn_fee_refunds", 0.0), 2
        )
        row.fba_ex, row.fba_vat = ex_vat(fba), vat_part(fba)

        row.storage = source.get("storage_inbound", 0.0)
        row.other_txn_fees = source.get("other_txn_fees", 0.0)
        row.other_txn_fee_refunds = source.get("other_txn_fee_refunds", 0.0)
        row.refund_admin_fees = source.get("refund_admin_fees", 0.0)
        row.delivery_labels = source.get("delivery_label_purchases", 0.0)
        row.adjustments = source.get("adjustments", 0.0)
        row.residual_expense = source.get("residual_expense", 0.0)
        row.other_fees = round(
            row.other_txn_fees + row.other_txn_fee_refunds
            + source.get("service_fees", 0.0) + row.refund_admin_fees
            + row.delivery_labels + row.adjustments + row.residual_expense, 2
        )

        # Step 7 — PPC.  The settlement figure drives the P&L because it is what
        # reconciles to the Expenses total; invoices validate the 20% split.
        ppc = source.get("cost_of_advertising", 0.0)
        row.ppc_ex, row.ppc_vat = ex_vat(ppc), vat_part(ppc)

        month_invoices = invoices_by_month.get(key, [])
        row.ppc_invoice_count = len(month_invoices)
        row.ppc_invoice_net = round(sum(i["net"] for i in month_invoices), 2)
        row.ppc_invoice_gross = round(sum(i["gross"] for i in month_invoices), 2)

        # Step 5 — units and bottom-up COGS.
        row.has_transactions = bool(txn)
        row.units = int(txn.get("net_units", 0))
        row.cogs = -round(
            sum(s.units(key) * s.rate for s in sku_rows) * cogs_multiplier, 2
        )
        row.cogs_vat = vat_of_inclusive(row.cogs) if cogs_vat_paid else 0.0

        # The Service fees line is split out of the transaction data (§6).
        row.subscription_fees = txn.get("subscription_fees", 0.0)
        row.deal_fees = txn.get("deal_fees", 0.0)
        row.coupon_fees = txn.get("coupon_fees", 0.0)
        row.other_service_fees = txn.get("other_service_fees", 0.0)
        # Referral ties on the ORDER lines only: Amazon reports the small
        # "selling fee refunds" credit on its own Summary row, and the credit a
        # refund line carries does not equal it. FBA ties on orders + refunds,
        # matching the Summary's fees + fee-refunds pair.
        row.csv_referral = txn.get("csv_selling_fees", 0.0)
        row.csv_fba = round(
            txn.get("csv_fba_fees", 0.0) + txn.get("csv_fba_fee_refunds", 0.0), 2
        )
        row.csv_storage = txn.get("csv_storage_fees", 0.0)
        row.summary_referral = round(
            source.get("selling_fees_fba", 0.0) + source.get("selling_fees_sf", 0.0), 2
        )
        row.summary_fba = fba
        row.summary_storage = source.get("storage_inbound", 0.0)

        # Step 8 — the user's decisions.
        # Input VAT: the 20% buried in every VAT-inclusive Amazon charge.
        # Referral, FBA and PPC are already split; storage and other fees are
        # carried inclusive, so their VAT component is the amount / 6.
        row.input_vat = round(
            row.referral_vat + row.fba_vat + row.ppc_vat
            + vat_of_inclusive(row.storage) + vat_of_inclusive(row.other_fees)
            + row.cogs_vat, 2
        )
        # Output VAT is charged on the VAT-INCLUSIVE sales figure: dividing by 6
        # (or by 107.5) only extracts the tax correctly from a gross amount.
        row.output_vat = _vat_line(scheme, row.gross_sales, row.input_vat)
        row.opex = -round(opex_monthly, 2)

        traffic = traffic_by_month.get(key)
        if traffic:
            row.has_traffic = True
            row.sessions = traffic["sessions"]
            row.page_views = traffic["page_views"]
            row.units_ordered = traffic["units_ordered"]
            row.buy_box = traffic["buy_box"]
            row.child_asins = traffic["child_asins"]

        rows.append(row)

    model = PLModel(
        months=rows,
        skus=sku_rows,
        families=families,
        invoices=parse["invoices"],
        # The workbook writer needs the raw Summary lines and file counts too.
        settings={**settings, "parse": parse},
        warnings=list(parse.get("warnings", [])),
        seller=parse.get("seller", {}),
    )
    model.checks = run_checks(model, parse)
    return model


def run_checks(model: PLModel, parse: dict) -> list[Check]:
    """The workflow §4 verification checklist."""
    checks: list[Check] = []

    # Income check — every month must tie to Amazon's own Income total.
    bad = [m for m in model.months if abs(m.income_difference) > TOLERANCE]
    checks.append(
        Check(
            "Income check",
            "Net Sales equals the Summary PDF Income total for all "
            f"{len(model.months)} months"
            if not bad
            else "Off in " + ", ".join(f"{m.label} ({m.income_difference:+.2f})" for m in bad),
            not bad,
        )
    )

    # Expenses check.
    bad = [m for m in model.months if abs(m.expenses_difference) > TOLERANCE]
    checks.append(
        Check(
            "Expenses check",
            "Total Amazon Fees + PPC equals the Summary PDF Expenses total for all "
            f"{len(model.months)} months"
            if not bad
            else "Off in " + ", ".join(f"{m.label} ({m.expenses_difference:+.2f})" for m in bad),
            not bad,
        )
    )

    # Fee ties — referral, FBA and storage, Summary PDF vs transaction CSV.
    for name, csv_attr, summary_attr in (
        ("Referral fee tie", "csv_referral", "summary_referral"),
        ("FBA fee tie", "csv_fba", "summary_fba"),
        ("Storage fee tie", "csv_storage", "summary_storage"),
    ):
        comparable = [m for m in model.months if m.has_transactions]
        bad = [
            m for m in comparable
            if abs(getattr(m, csv_attr) - getattr(m, summary_attr)) > 0.02
        ]
        if not comparable:
            detail, passed = "No transaction CSVs loaded — not checked", False
        elif bad:
            detail = "Off in " + ", ".join(
                f"{m.label} ({getattr(m, csv_attr) - getattr(m, summary_attr):+.2f})"
                for m in bad
            )
            passed = False
        else:
            detail = f"Summary PDF and transaction CSV agree across {len(comparable)} months"
            passed = True
        checks.append(Check(name, detail, passed, severity="warning" if bad else "error"))

    # Other Fees components must sum to the P&L Other Fees line.
    bad = [
        m for m in model.months
        if abs(m.total_other_fees_components - m.other_fees) > 0.02
    ]
    checks.append(
        Check(
            "Other Fees composition",
            "Subscription + Deal + Coupon + the rest sum to the Other Fees line"
            if not bad
            else "Off in " + ", ".join(f"{m.label}" for m in bad),
            not bad,
            severity="warning",
        )
    )

    # PPC — invoice gross should tie to settlement advertising for most months.
    with_invoices = [m for m in model.months if m.ppc_invoice_count]
    matched = [
        m for m in with_invoices
        if abs(m.ppc_invoice_gross + m.total_ppc) <= 0.02
    ]
    if not with_invoices:
        checks.append(
            Check(
                "PPC invoice tie",
                "No advertising invoices uploaded — the P&L uses the settlement "
                "figure, which still reconciles to the Expenses total",
                True,
                severity="warning",
            )
        )
    else:
        gaps = [m for m in with_invoices if m not in matched]
        checks.append(
            Check(
                "PPC invoice tie",
                f"{len(matched)} of {len(with_invoices)} months tie to the penny"
                + (
                    "; the rest differ by billing-cycle timing at month boundaries ("
                    + ", ".join(m.label for m in gaps) + ")"
                    if gaps else ""
                ),
                len(matched) >= max(1, len(with_invoices) // 2),
                severity="warning",
            )
        )

    # COGS — every SKU that sold must carry a rate.
    unpriced = [
        s.sku for s in model.skus
        if s.rate <= 0 and any(s.units(m.key) for m in model.months)
    ]
    checks.append(
        Check(
            "COGS rates",
            f"Every selling SKU has a landed cost; blended £{model.blended_landed_cost:.2f}/unit"
            if not unpriced
            else f"{len(unpriced)} SKU(s) have no landed cost: "
            + ", ".join(unpriced[:6]) + ("…" if len(unpriced) > 6 else ""),
            not unpriced,
            severity="warning",
        )
    )

    # Units — a month with no transaction CSV cannot carry COGS.
    missing = [m.label for m in model.months if not m.has_transactions]
    if missing:
        checks.append(
            Check(
                "Units coverage",
                "No transaction CSV for " + ", ".join(missing)
                + " — those months show zero units and zero COGS",
                False,
                severity="warning",
            )
        )

    # Traffic coverage.
    missing = [m.label for m in model.months if not m.has_traffic]
    if missing:
        checks.append(
            Check(
                "Traffic coverage",
                "No Business Report mapped to " + ", ".join(missing),
                False,
                severity="warning",
            )
        )

    # VAT — sanity-check the scheme against turnover and flag repayment months.
    ttm_sales = model.ttm_sum("net_sales")
    if model.scheme == SCHEME_NONE and ttm_sales > 90000:
        checks.append(
            Check(
                "VAT scheme",
                f"TTM turnover £{ttm_sales:,.0f} is over the £90k UK registration "
                "threshold but the model is set to 0% (not registered). A buyer "
                f"will likely have to register — that is about £{ttm_sales / 6:,.0f}/yr "
                "of output VAT. Model the 20% case before pricing the deal.",
                False,
                severity="warning",
            )
        )
    elif model.scheme == SCHEME_STANDARD:
        repayments = [m.label for m in model.months if m.output_vat > 0]
        net_vat = model.ttm_sum("output_vat")
        settled = (
            f"a net bill of £{-net_vat:,.0f}" if net_vat < 0
            else f"a net repayment of £{net_vat:,.0f} due from HMRC"
        )
        detail = (
            f"Standard 20%: output VAT £{model.ttm_sum('gross_sales') / 6:,.0f} on "
            f"VAT-inclusive sales of £{model.ttm_sum('gross_sales'):,.0f}, less "
            f"reclaimable input VAT £{-model.ttm_sum('input_vat'):,.0f} = {settled} "
            "across the TTM."
        )
        if repayments:
            detail += (
                f" Input VAT exceeds output VAT in {len(repayments)} of "
                f"{len(model.months)} months ("
                + ", ".join(repayments[:4])
                + ("…" if len(repayments) > 4 else "")
                + "), largely because advertising spend is heavy."
            )
        checks.append(Check("VAT scheme", detail, True,
                            severity="warning" if repayments else "error"))
    else:
        checks.append(
            Check(
                "VAT scheme",
                f"{VAT_SCHEMES[model.scheme]} — input VAT of "
                f"£{-model.ttm_sum('input_vat'):,.0f} across the TTM is irrecoverable "
                "and already sits inside the VAT-inclusive fee and PPC lines, so it "
                "is reported but not deducted a second time.",
                True,
            )
        )

    if parse.get("errors"):
        checks.append(
            Check(
                "Source files",
                f"{len(parse['errors'])} file(s) failed to parse: " + "; ".join(parse["errors"][:3]),
                False,
                severity="warning",
            )
        )

    return checks
