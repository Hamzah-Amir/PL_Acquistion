"""Step 1 of the workflow — monthly Summary PDF -> revenue & fee line items.

The Summary PDF is a two-column layout: Income on the left half of the page,
Expenses on the right.  Plain text extraction interleaves the two columns, so we
split on the x-coordinate first and only then rebuild lines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import pdfplumber

# Page is 792pt wide; income labels start at x~20, expense labels at x~406.
COLUMN_SPLIT = 395.0
# Within each column, values are right-aligned well clear of the label text.
LEFT_VALUE_X = 200.0
RIGHT_VALUE_X = 640.0
LINE_TOLERANCE = 4.0

NUMBER = re.compile(r"^-?[\d,]+\.?\d*$")

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
PERIOD_RE = re.compile(
    r"Account activity from\s+([A-Za-z]{3})\w*\s+(\d{1,2}),\s*(\d{4})", re.I
)

# Canonical key -> the label Amazon prints.  Matching is done on a normalised
# (lowercased, punctuation-stripped) form so minor wording drift still lands.
INCOME_LABELS = {
    "product_sales_sf": "seller fulfilled product sales",
    "refund_sf": "seller fulfilled product sale refunds",
    "product_sales_fba": "fba product sales",
    "refund_fba": "fba product sale refunds",
    "inventory_credit": "fba inventory credit",
    "liquidation_proceeds": "fba liquidation proceeds",
    "liquidation_adjustments": "fba liquidations proceeds adjustments",
    "postage_credits": "postage credits",
    "delivery_credit_refunds": "delivery credit refunds",
    "giftwrap_credits": "gift wrap credits",
    "giftwrap_credit_refunds": "gift wrap credit refunds",
    "promo_rebates": "promotional rebates",
    "promo_rebate_refunds": "promotional rebate refunds",
    "atoz_claims": "a to z guarantee claims",
    "chargebacks": "chargebacks",
    "shipping_reimbursement": "amazon shipping reimbursement",
    "safet_reimbursement": "safe t reimbursement",
    "receivables_reversals": "receivables reversals",
    "commingling_vat_income": "commingling vat",
}

EXPENSE_LABELS = {
    "selling_fees_sf": "seller fulfilled selling fees",
    "selling_fees_fba": "fba selling fees",
    "selling_fee_refunds": "selling fee refunds",
    "fba_txn_fees": "fba transaction fees",
    "fba_txn_fee_refunds": "fba transaction fee refunds",
    "other_txn_fees": "other transaction fees",
    "other_txn_fee_refunds": "other transaction fee refunds",
    "storage_inbound": "fba inventory and inbound services fees",
    "delivery_label_purchases": "delivery label purchases",
    "delivery_label_refunds": "delivery label refunds",
    "carrier_label_adjustments": "carrier delivery label adjustments",
    "service_fees": "service fees",
    "refund_admin_fees": "refund administration fees",
    "adjustments": "adjustments",
    "cost_of_advertising": "cost of advertising",
    "refund_for_advertiser": "refund for advertiser",
    "commingling_vat_expense": "commingling vat",
    "liquidations_fees": "liquidations fees",
    "shipping_charges": "amazon shipping charges",
    "receivables_deductions": "receivables deductions",
}

# Lines that roll up into Net Sales on the P&L, by template column.
PRODUCT_SALES_KEYS = ("product_sales_fba", "product_sales_sf")
RETURNS_KEYS = ("refund_fba", "refund_sf", "delivery_credit_refunds")
OTHER_INCOME_KEYS = ("postage_credits", "inventory_credit", "giftwrap_credits")
PROMO_KEYS = ("promo_rebates", "promo_rebate_refunds")
# Everything else on the Income side is swept into a residual bucket so that
# Net Sales always ties to the printed Income total (workflow §4).
RESIDUAL_INCOME_KEYS = tuple(
    k for k in INCOME_LABELS
    if k not in PRODUCT_SALES_KEYS + RETURNS_KEYS + OTHER_INCOME_KEYS + PROMO_KEYS
)

REFERRAL_KEYS = ("selling_fees_fba", "selling_fees_sf", "selling_fee_refunds")
FBA_FEE_KEYS = ("fba_txn_fees", "fba_txn_fee_refunds")
OTHER_FEE_KEYS = (
    "other_txn_fees", "other_txn_fee_refunds", "service_fees",
    "refund_admin_fees", "delivery_label_purchases", "adjustments",
)
RESIDUAL_EXPENSE_KEYS = tuple(
    k for k in EXPENSE_LABELS
    if k not in REFERRAL_KEYS + FBA_FEE_KEYS + OTHER_FEE_KEYS
    + ("storage_inbound", "cost_of_advertising")
)

# The Tax block sits below Expenses on the right of the page.  Amazon reports it
# separately from Income, so it never enters the Income reconciliation — but it
# is the VAT the customer actually paid, which makes Income + Tax the gross,
# VAT-inclusive sales figure.
TAX_LABELS = {
    "taxes_collected": "product delivery and gift wrap taxes collected",
    "taxes_refunded": "product delivery and gift wrap taxes refunded",
    "tax_withheld": "amazon obligated tax withheld",
}


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower()).strip()


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", _normalise(text))


@dataclass
class SummaryMonth:
    """One month's Income & Expenses lines, straight off the Summary PDF."""

    source: str
    period_start: date
    period_end: date
    display_name: str = ""
    legal_name: str = ""
    income_total: float = 0.0
    expenses_total: float = 0.0
    tax_total: float = 0.0
    lines: dict[str, float] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)

    @property
    def month_key(self) -> str:
        return f"{self.period_start.year:04d}-{self.period_start.month:02d}"

    def get(self, *keys: str) -> float:
        return round(sum(self.lines.get(k, 0.0) for k in keys), 2)

    # --- the roll-ups the P&L needs -------------------------------------
    @property
    def product_sales(self) -> float:
        return self.get(*PRODUCT_SALES_KEYS)

    @property
    def returns_refunds(self) -> float:
        return self.get(*RETURNS_KEYS)

    @property
    def other_income(self) -> float:
        return self.get(*OTHER_INCOME_KEYS)

    @property
    def promo_net(self) -> float:
        return self.get(*PROMO_KEYS)

    @property
    def residual_income(self) -> float:
        return self.get(*RESIDUAL_INCOME_KEYS)

    @property
    def residual_expense(self) -> float:
        return self.get(*RESIDUAL_EXPENSE_KEYS)

    @property
    def net_sales(self) -> float:
        return round(
            self.product_sales + self.other_income + self.promo_net
            + self.returns_refunds + self.residual_income, 2
        )

    @property
    def sales_tax(self) -> float:
        """Net sales tax Amazon collected from buyers on the seller's behalf.

        Excludes tax Amazon is obligated to remit itself (the marketplace
        facilitator lines) — that never reaches the seller and is not their
        output VAT.
        """
        return self.get("taxes_collected", "taxes_refunded")

    @property
    def tax_withheld(self) -> float:
        return self.get("tax_withheld")

    @property
    def gross_sales(self) -> float:
        """Net Sales plus the VAT the customer paid — the VAT-inclusive figure."""
        return round(self.net_sales + self.sales_tax, 2)

    @property
    def income_difference(self) -> float:
        return round(self.net_sales - self.income_total, 2)

    @property
    def total_fees_and_ads(self) -> float:
        return round(
            self.get(*REFERRAL_KEYS) + self.get(*FBA_FEE_KEYS)
            + self.get("storage_inbound") + self.get(*OTHER_FEE_KEYS)
            + self.residual_expense + self.get("cost_of_advertising"), 2
        )

    @property
    def expenses_difference(self) -> float:
        return round(self.total_fees_and_ads - self.expenses_total, 2)


def _cluster_lines(words: list[dict]) -> list[list[dict]]:
    """Group words into visual lines, tolerant of the ~2pt baseline jitter
    between a wrapped label and its right-aligned value."""
    rows: list[list[dict]] = []
    anchors: list[float] = []
    for word in sorted(words, key=lambda w: w["top"]):
        if rows and abs(word["top"] - anchors[-1]) <= LINE_TOLERANCE:
            rows[-1].append(word)
        else:
            rows.append([word])
            anchors.append(word["top"])
    return rows


def _read_column(words: list[dict], value_x: float) -> list[tuple[str, list[float]]]:
    parsed = []
    for row in _cluster_lines(words):
        row = sorted(row, key=lambda w: w["x0"])
        label = " ".join(w["text"] for w in row if w["x0"] < value_x)
        values = [
            float(w["text"].replace(",", ""))
            for w in row
            if w["x0"] >= value_x and NUMBER.match(w["text"])
        ]
        if label.strip():
            parsed.append((label.strip(), values))
    return parsed


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    from datetime import timedelta

    return date(year, month + 1, 1) - timedelta(days=1)


def parse_summary_pdf(path: str, source_name: str | None = None) -> SummaryMonth:
    """Read one monthly Summary PDF into a :class:`SummaryMonth`."""
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        text = page.extract_text() or ""

    match = PERIOD_RE.search(text)
    if not match:
        raise ValueError(f"Could not read the reporting period from {source_name or path}")
    month = MONTHS[match.group(1).lower()[:3]]
    year = int(match.group(3))
    start = date(year, month, 1)

    result = SummaryMonth(
        source=source_name or path,
        period_start=start,
        period_end=_month_end(year, month),
    )
    if m := re.search(r"Display name:\s*(.+)", text):
        result.display_name = m.group(1).strip()
    if m := re.search(r"Legal name:\s*(.+)", text):
        result.legal_name = m.group(1).strip()

    left = _read_column([w for w in words if w["x0"] < COLUMN_SPLIT], LEFT_VALUE_X)
    right = _read_column([w for w in words if w["x0"] >= COLUMN_SPLIT], RIGHT_VALUE_X)

    income_lookup = {_squash(v): k for k, v in INCOME_LABELS.items()}
    tax_lookup = {_squash(v): k for k, v in TAX_LABELS.items()}
    # The Tax block shares the right-hand column with Expenses.
    expense_lookup = {_squash(v): k for k, v in EXPENSE_LABELS.items()}
    expense_lookup.update(tax_lookup)

    for rows, lookup, totals_label in (
        (left, income_lookup, "income"),
        (right, expense_lookup, "expenses"),
    ):
        for label, values in rows:
            key = _squash(label)
            if not values:
                continue
            if key == totals_label:
                # The "Totals" block prints the authoritative Income/Expenses figure.
                total = values[0]
                if totals_label == "income":
                    result.income_total = total
                else:
                    result.expenses_total = total
                continue
            if key == "tax":
                result.tax_total = values[0]
                continue
            if key in ("subtotals", "transfers"):
                continue
            if key in lookup:
                # Debit and credit columns both appear on some rows; they net out.
                result.lines[lookup[key]] = round(sum(values), 2)
            elif key not in ("income", "expenses"):
                result.unmatched.append(label)

    return result
