"""Step 4 of the workflow — the seller's evaluation / SellerBoard export.

We are looking for one thing: a per-product landed cost, derived as
``Cost of Goods / units``.  These exports are hand-made and wildly
inconsistent, so the parser scans every sheet for a row of headers that looks
like (product, units, cost of goods) rather than assuming a fixed layout.
Anything it cannot resolve is left for the user to type in the wizard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import openpyxl

PRODUCT_HINTS = ("product", "sku", "title", "item", "asin", "name")
UNIT_HINTS = ("units", "unit sold", "quantity", "qty", "sold")
COST_HINTS = ("cost of goods", "cogs", "cost of good", "product cost", "landed", "cost")
RATE_HINTS = ("cost per unit", "per unit", "unit cost", "£/unit", "landed cost")

SCAN_ROWS = 40


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower() if value is not None else ""


def _number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d.\-]", "", str(value))
    if not text or text in {"-", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class CostRow:
    product: str
    units: float | None
    cost_of_goods: float | None
    rate: float | None
    sheet: str

    @property
    def landed_cost(self) -> float | None:
        if self.rate is not None and self.rate > 0:
            return round(self.rate, 4)
        if self.cost_of_goods and self.units:
            return round(abs(self.cost_of_goods) / abs(self.units), 4)
        return None


def _match(header: str, hints: tuple[str, ...]) -> bool:
    return any(hint in header for hint in hints)


def parse_evaluation(path: str, source_name: str | None = None) -> list[CostRow]:
    """Best-effort extraction of per-product landed costs."""
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    results: list[CostRow] = []

    for sheet in workbook.worksheets:
        grid = [
            list(row)
            for row in sheet.iter_rows(max_row=SCAN_ROWS + 500, values_only=True)
        ]
        if not grid:
            continue

        header_row = None
        columns: dict[str, int] = {}
        for index, row in enumerate(grid[:SCAN_ROWS]):
            headers = [_text(cell) for cell in row]
            found: dict[str, int] = {}
            for col, header in enumerate(headers):
                if not header:
                    continue
                if "product" not in found and _match(header, PRODUCT_HINTS):
                    found["product"] = col
                if "rate" not in found and _match(header, RATE_HINTS):
                    found["rate"] = col
                elif "units" not in found and _match(header, UNIT_HINTS):
                    found["units"] = col
                elif "cost" not in found and _match(header, COST_HINTS):
                    found["cost"] = col
            if "product" in found and ("cost" in found or "rate" in found):
                header_row, columns = index, found
                break

        if header_row is None:
            continue

        for row in grid[header_row + 1:]:
            if not row:
                continue

            def cell(name: str):
                col = columns.get(name)
                if col is None or col >= len(row):
                    return None
                return row[col]

            product = str(cell("product") or "").strip()
            if not product or _text(product) in {"total", "totals", "grand total"}:
                continue
            entry = CostRow(
                product=product,
                units=_number(cell("units")),
                cost_of_goods=_number(cell("cost")),
                rate=_number(cell("rate")),
                sheet=sheet.title,
            )
            if entry.landed_cost is not None:
                results.append(entry)

    workbook.close()
    return results
