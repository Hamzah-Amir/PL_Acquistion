"""Step 3 of the workflow — monthly Transaction CSV -> units, SKU revenue and
the fee cross-checks.

The export carries ~9 preamble rows before the real header, which begins
``date/time,settlement id,type,...``.
"""
from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

HEADER_FIRST_CELL = "date/time"
MAX_PREAMBLE_ROWS = 40

# Amazon names these exports after the window they cover, e.g.
# "2025Aug1-2025Aug31CustomTransaction.csv".
FILENAME_RANGE_RE = re.compile(
    r"(\d{4})([A-Za-z]{3})(\d{1,2})\s*-\s*(\d{4})([A-Za-z]{3})(\d{1,2})", re.I
)

DATE_FORMATS = (
    "%d %b %Y %H:%M:%S %Z",
    "%d %b %Y %H:%M:%S UTC",
    "%d.%m.%Y %H:%M:%S %Z",
)
DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})")
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Service-fee descriptions Amazon bundles into the single "Service fees" line on
# the Summary PDF (workflow §6).  Everything else falls through to "other".
SUBSCRIPTION_PATTERNS = ("subscription",)
DEAL_PATTERNS = ("deal fee", "lightning deal", "best deal", "deal performance", "7 day deal")
COUPON_PATTERNS = ("coupon",)


def _to_float(value: str | None) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _to_int(value: str | None) -> int:
    return int(round(_to_float(value)))


def filename_month(name: str) -> str | None:
    """Return the single month a transaction export covers, from its filename.

    Amazon's monthly exports are windowed on local (BST/GMT) time while the rows
    are stamped in UTC, so the first and last rows of a month spill into the
    neighbouring month.  When the filename says the file *is* one month, that
    beats bucketing rows by their posted date.  Multi-month date-range exports
    return ``None`` and fall back to per-row bucketing.
    """
    match = FILENAME_RANGE_RE.search(name or "")
    if not match:
        return None
    y1, m1, _, y2, m2, _ = match.groups()
    month1 = MONTHS.get(m1.lower()[:3])
    month2 = MONTHS.get(m2.lower()[:3])
    if not month1 or not month2:
        return None
    if (y1, month1) != (y2, month2):
        return None
    return f"{int(y1):04d}-{month1:02d}"


def parse_posted_date(value: str) -> date | None:
    match = DATE_RE.search(value or "")
    if not match:
        return None
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name.lower()[:3])
    if not month:
        return None
    return date(int(year), month, int(day))


@dataclass
class TransactionMonth:
    """Everything the P&L needs out of one month of transaction lines."""

    source: str
    month_key: str
    units_by_sku: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    # Product sales excluding tax, and the tax collected alongside it.  Gross
    # (VAT-inclusive) SKU revenue is the sum of the two.
    sales_by_sku: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    sales_tax_by_sku: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    titles_by_sku: dict[str, str] = field(default_factory=dict)
    order_units: int = 0
    refund_units: int = 0
    # Fee ties (workflow §4).  Order and refund lines are kept apart because the
    # Summary PDF prints them as separate rows (fees vs fee refunds).
    csv_selling_fees: float = 0.0
    csv_selling_fee_refunds: float = 0.0
    csv_fba_fees: float = 0.0
    csv_fba_fee_refunds: float = 0.0
    csv_storage_fees: float = 0.0
    csv_other_txn_fees: float = 0.0
    # "Service fees" split (workflow §6)
    subscription_fees: float = 0.0
    deal_fees: float = 0.0
    coupon_fees: float = 0.0
    other_service_fees: float = 0.0
    advertising_cost: float = 0.0
    domestic_sales: float = 0.0
    facilitated_sales: float = 0.0
    row_count: int = 0

    @property
    def net_units(self) -> int:
        return self.order_units - self.refund_units

    @property
    def total_sales(self) -> float:
        return round(sum(self.sales_by_sku.values()), 2)


def _classify_service_fee(description: str) -> str:
    text = (description or "").lower()
    if any(p in text for p in SUBSCRIPTION_PATTERNS):
        return "subscription"
    if any(p in text for p in DEAL_PATTERNS):
        return "deal"
    if any(p in text for p in COUPON_PATTERNS):
        return "coupon"
    return "other"


def _find_header(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows[:MAX_PREAMBLE_ROWS]):
        if row and row[0].strip().lower().lstrip("﻿") == HEADER_FIRST_CELL:
            return index
    raise ValueError("Could not find the 'date/time' header row in the transaction CSV")


def parse_transaction_csv(
    path: str, source_name: str | None = None, month_hint: str | None = None
) -> list[TransactionMonth]:
    """Parse a transaction export into one :class:`TransactionMonth` per month.

    A single-month export is assigned wholly to its month (see
    :func:`filename_month`); a multi-month date-range export is bucketed row by
    row on the posted date.
    """
    forced_month = month_hint or filename_month(os.path.basename(source_name or path))

    with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle))

    header_index = _find_header(rows)
    header = [c.strip().lower() for c in rows[header_index]]
    col = {name: i for i, name in enumerate(header)}

    def cell(row: list[str], name: str) -> str:
        index = col.get(name)
        if index is None or index >= len(row):
            return ""
        return row[index]

    months: dict[str, TransactionMonth] = {}

    for row in rows[header_index + 1:]:
        if not row or not any(c.strip() for c in row):
            continue
        posted = parse_posted_date(cell(row, "date/time"))
        if posted is None and not forced_month:
            continue
        key = forced_month or f"{posted.year:04d}-{posted.month:02d}"
        month = months.get(key)
        if month is None:
            month = months[key] = TransactionMonth(
                source=source_name or path, month_key=key
            )
        month.row_count += 1

        txn_type = (cell(row, "type") or "").strip()
        sku = (cell(row, "sku") or "").strip()
        description = cell(row, "description")
        quantity = _to_int(cell(row, "quantity"))
        product_sales = _to_float(cell(row, "product sales"))
        product_sales_tax = _to_float(cell(row, "product sales tax"))
        selling_fees = _to_float(cell(row, "selling fees"))
        fba_fees = _to_float(cell(row, "fba fees"))

        if txn_type == "Order":
            month.order_units += quantity
            if sku:
                month.units_by_sku[sku] += quantity
                month.sales_by_sku[sku] += product_sales
                month.sales_tax_by_sku[sku] += product_sales_tax
                if description and sku not in month.titles_by_sku:
                    month.titles_by_sku[sku] = description
            month.csv_selling_fees += selling_fees
            month.csv_fba_fees += fba_fees
            month.csv_other_txn_fees += _to_float(cell(row, "other transaction fees"))
            model = (cell(row, "tax collection model") or "").strip()
            if model:
                month.facilitated_sales += product_sales
            else:
                month.domestic_sales += product_sales
        elif txn_type == "Refund":
            # Refund rows carry a POSITIVE quantity with negative product sales,
            # so units must be subtracted while sales are added.
            month.refund_units += quantity
            if sku:
                month.units_by_sku[sku] -= quantity
                month.sales_by_sku[sku] += product_sales
                month.sales_tax_by_sku[sku] += product_sales_tax
            month.csv_selling_fee_refunds += selling_fees
            month.csv_fba_fee_refunds += fba_fees
            month.csv_other_txn_fees += _to_float(cell(row, "other transaction fees"))
        elif txn_type == "FBA Inventory Fee":
            month.csv_storage_fees += _to_float(cell(row, "other"))
        elif txn_type == "Service Fee":
            amount = _to_float(cell(row, "other")) or selling_fees
            if "advertis" in (description or "").lower():
                month.advertising_cost += amount
                continue
            bucket = _classify_service_fee(description)
            if bucket == "subscription":
                month.subscription_fees += amount
            elif bucket == "deal":
                month.deal_fees += amount
            elif bucket == "coupon":
                month.coupon_fees += amount
            else:
                month.other_service_fees += amount

    for month in months.values():
        month.csv_selling_fees = round(month.csv_selling_fees, 2)
        month.csv_selling_fee_refunds = round(month.csv_selling_fee_refunds, 2)
        month.csv_fba_fees = round(month.csv_fba_fees, 2)
        month.csv_fba_fee_refunds = round(month.csv_fba_fee_refunds, 2)
        month.csv_storage_fees = round(month.csv_storage_fees, 2)
        month.csv_other_txn_fees = round(month.csv_other_txn_fees, 2)
        month.subscription_fees = round(month.subscription_fees, 2)
        month.deal_fees = round(month.deal_fees, 2)
        month.coupon_fees = round(month.coupon_fees, 2)
        month.other_service_fees = round(month.other_service_fees, 2)
        month.advertising_cost = round(month.advertising_cost, 2)
        month.domestic_sales = round(month.domestic_sales, 2)
        month.facilitated_sales = round(month.facilitated_sales, 2)
        month.units_by_sku = {k: v for k, v in month.units_by_sku.items()}
        month.sales_by_sku = {k: round(v, 2) for k, v in month.sales_by_sku.items()}
        month.sales_tax_by_sku = {
            k: round(v, 2) for k, v in month.sales_tax_by_sku.items()
        }

    return sorted(months.values(), key=lambda m: m.month_key)
