"""Step 7 of the workflow — Amazon advertising tax-invoice PDFs.

Each invoice is ``net x 1.20``; VAT = gross - net.  Invoices are deduplicated by
invoice number (the same PDF is often present in several export folders) and
bucketed by invoice date.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from . import pdftext

INVOICE_NUMBER_RE = re.compile(r"Invoice Number\s+([A-Za-z0-9]+)")
INVOICE_DATE_RE = re.compile(r"Invoice Date\s+(\d{2})-(\d{2})-(\d{4})")
INVOICE_PERIOD_RE = re.compile(
    r"Invoice Period\s+(\d{2}-\d{2}-\d{4})\s*-\s*(\d{2}-\d{2}-\d{4})"
)
SUBTOTAL_RE = re.compile(r"^Subtotal\s+(-?[\d,]+\.\d{2})", re.M)
# "Tax Subtotal 64.85" on newer invoices, "VAT (20%) - UNITED KINGDOM 1.17" on older.
VAT_RE = re.compile(r"^Tax Subtotal\s+(-?[\d,]+\.\d{2})", re.M)
VAT_FALLBACK_RE = re.compile(r"^VAT\s*\(\d+%\)[^\d\-]*(-?[\d,]+\.\d{2})", re.M)
TOTAL_RE = re.compile(r"^Total Amount Due\s+(-?[\d,]+\.\d{2})", re.M)
CURRENCY_RE = re.compile(r"Invoice Currency\s+([A-Z]{3})")


def _money(text: str | None) -> float:
    if not text:
        return 0.0
    return round(float(text.replace(",", "")), 2)


@dataclass
class PPCInvoice:
    invoice_number: str
    invoice_date: date | None
    period_start: str = ""
    period_end: str = ""
    net: float = 0.0
    vat: float = 0.0
    gross: float = 0.0
    currency: str = "GBP"
    source: str = ""

    @property
    def month_key(self) -> str:
        if not self.invoice_date:
            return ""
        return f"{self.invoice_date.year:04d}-{self.invoice_date.month:02d}"

    @property
    def period_label(self) -> str:
        if self.period_start and self.period_end:
            return f"{self.period_start} - {self.period_end}"
        return ""

    @property
    def vat_rate_ok(self) -> bool:
        """The workflow uses the invoices to validate the 20% split."""
        if self.net <= 0:
            return True
        return abs(self.vat - self.net * 0.20) <= max(0.02, self.net * 0.001)


def _read(text: str) -> tuple[float, float, float]:
    net = _money(m.group(1)) if (m := SUBTOTAL_RE.search(text)) else 0.0
    vat = _money(m.group(1)) if (m := VAT_RE.search(text)) else 0.0
    if not vat and (m := VAT_FALLBACK_RE.search(text)):
        vat = _money(m.group(1))
    gross = _money(m.group(1)) if (m := TOTAL_RE.search(text)) else 0.0
    return net, vat, gross


def parse_ppc_invoice(path: str, source_name: str | None = None) -> PPCInvoice | None:
    # Almost every invoice carries its totals on page 1; only pay for the rest
    # of the document when something is missing.
    text = pdftext.first_page_text(path)
    if not INVOICE_NUMBER_RE.search(text) or not all(_read(text)):
        text = pdftext.full_text(path) or text

    number_match = INVOICE_NUMBER_RE.search(text)
    if not number_match:
        return None

    invoice_date = None
    if m := INVOICE_DATE_RE.search(text):
        day, month, year = m.groups()
        invoice_date = date(int(year), int(month), int(day))

    invoice = PPCInvoice(
        invoice_number=number_match.group(1).strip(),
        invoice_date=invoice_date,
        source=source_name or path,
    )
    if m := INVOICE_PERIOD_RE.search(text):
        invoice.period_start, invoice.period_end = m.groups()
    if m := CURRENCY_RE.search(text):
        invoice.currency = m.group(1)

    invoice.net, invoice.vat, invoice.gross = _read(text)

    if not invoice.gross:
        invoice.gross = round(invoice.net + invoice.vat, 2)
    if not invoice.vat:
        invoice.vat = round(invoice.gross - invoice.net, 2)

    return invoice


def deduplicate(invoices: list[PPCInvoice]) -> list[PPCInvoice]:
    """Keep one copy per invoice number, preferring the fullest parse."""
    best: dict[str, PPCInvoice] = {}
    for invoice in invoices:
        existing = best.get(invoice.invoice_number)
        if existing is None or (not existing.invoice_date and invoice.invoice_date):
            best[invoice.invoice_number] = invoice
    return sorted(
        best.values(), key=lambda i: (i.invoice_date or date.min, i.invoice_number)
    )
