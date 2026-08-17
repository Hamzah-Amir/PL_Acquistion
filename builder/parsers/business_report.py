"""Step 6 of the workflow — Business Report CSV -> sessions, page views,
conversion, Buy Box and child-ASIN count.

Amazon exports these named only by download date, so the file carries no clue
which month it covers.  Month assignment is resolved separately (see
``builder.engine.assemble``) by matching each report's units-ordered total
against the units the transaction CSVs report for each month; the user confirms
or overrides that guess in the wizard.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field

PERCENT_RE = re.compile(r"^-?[\d.,]+%$")


def _to_float(value: str | None) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "").replace("£", "").replace("%", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _to_int(value: str | None) -> int:
    return int(round(_to_float(value)))


def _pct(value: str | None) -> float:
    """Percentages come through as '99.89%' -> 0.9989."""
    return _to_float(value) / 100.0


def _pick(header: list[str], *candidates: str) -> int | None:
    lowered = [h.strip().lower() for h in header]
    for candidate in candidates:
        target = candidate.lower()
        for index, name in enumerate(lowered):
            if name == target:
                return index
    for candidate in candidates:
        target = candidate.lower()
        for index, name in enumerate(lowered):
            if name.startswith(target):
                return index
    return None


@dataclass
class BusinessReport:
    """One Business Report file, aggregated across its child ASINs."""

    source: str
    sessions: int = 0
    page_views: int = 0
    units_ordered: int = 0
    ordered_product_sales: float = 0.0
    child_asins: int = 0
    buy_box_weighted: float = 0.0
    rows: list[dict] = field(default_factory=list)

    @property
    def conversion(self) -> float:
        return self.units_ordered / self.sessions if self.sessions else 0.0


def parse_business_report(path: str, source_name: str | None = None) -> BusinessReport:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError(f"{source_name or path} is empty")

    header = rows[0]
    i_child = _pick(header, "(Child) ASIN", "Child ASIN")
    i_title = _pick(header, "Title")
    i_sessions = _pick(header, "Sessions – Total", "Sessions - Total", "Sessions")
    i_views = _pick(header, "Page views – Total", "Page views - Total", "Page Views")
    i_units = _pick(header, "Units ordered", "Units Ordered")
    i_sales = _pick(header, "Ordered Product Sales")
    i_buybox = _pick(
        header,
        "Featured Offer (Buy Box) percentage",
        "Buy Box percentage",
        "Buy Box Percentage",
    )
    if i_sessions is None or i_units is None:
        raise ValueError(
            f"{source_name or path} does not look like a Business Report "
            "(no Sessions / Units ordered columns)"
        )

    report = BusinessReport(source=source_name or path)
    buy_box_numerator = 0.0

    for row in rows[1:]:
        if not row or not any(c.strip() for c in row):
            continue

        def get(index: int | None) -> str:
            if index is None or index >= len(row):
                return ""
            return row[index]

        sessions = _to_int(get(i_sessions))
        units = _to_int(get(i_units))
        views = _to_int(get(i_views))
        buy_box = _pct(get(i_buybox))

        report.sessions += sessions
        report.page_views += views
        report.units_ordered += units
        report.ordered_product_sales += _to_float(get(i_sales))
        report.child_asins += 1
        buy_box_numerator += buy_box * sessions
        report.rows.append(
            {
                "asin": get(i_child).strip(),
                "title": get(i_title).strip(),
                "sessions": sessions,
                "page_views": views,
                "units_ordered": units,
                "buy_box": buy_box,
            }
        )

    # Buy Box is session-weighted, per workflow §6.
    report.buy_box_weighted = (
        buy_box_numerator / report.sessions if report.sessions else 0.0
    )
    report.ordered_product_sales = round(report.ordered_product_sales, 2)
    return report
