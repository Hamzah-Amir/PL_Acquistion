"""Turn a set of discovered source files into the structured data the workbook
needs — workflow steps 1-7, plus the month/SKU inference the wizard asks the
user to confirm.

Everything here is plain JSON-able dicts so a parse can be stored against the
job and re-used across wizard steps without re-reading 130 files.
"""
from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from ..parsers import (
    business_report,
    evaluation,
    ingest,
    ppc_invoice,
    summary_pdf,
    transactions,
)

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(month_key: str) -> str:
    """``2025-08`` -> ``Aug-25``."""
    year, month = month_key.split("-")
    return f"{MONTH_ABBR[int(month) - 1]}-{year[2:]}"


def _merge_families_by_title(
    mapping: dict[str, str], titles: dict[str, str], units: dict[str, int]
) -> dict[str, str]:
    """Fold together families that are selling the same product.

    Amazon's giveaway SKUs are named after the promotion rather than the
    product (``amzn.gr.Amazon.Found.B09QT67W6-...``), so name-based grouping
    misses them — but their listing title still matches the parent product.
    """
    def key(title: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:40]

    # The heaviest-selling family for each title becomes the survivor.
    winner: dict[str, str] = {}
    weight: dict[str, int] = {}
    for sku, family in mapping.items():
        title_key = key(titles.get(sku, ""))
        if len(title_key) < 20:  # too short to be a confident match
            continue
        size = units.get(sku, 0)
        family_weight = weight.get(family, 0) + size
        weight[family] = family_weight
        if title_key not in winner or family_weight > weight.get(winner[title_key], 0):
            winner[title_key] = family

    merged = dict(mapping)
    for sku, family in mapping.items():
        title_key = key(titles.get(sku, ""))
        target = winner.get(title_key)
        if target and target != family:
            merged[sku] = target
    return merged


def _families_from_skus(skus: list[tuple[str, int]]) -> dict[str, str]:
    """Propose a product family per SKU (workflow §4 — proposed here, confirmed
    by the user in the wizard).

    Two passes.  First, a SKU that literally contains a higher-volume SKU is a
    variant of it — this is how Amazon's own giveaway and promotion SKUs are
    named (``amzn.gr.B-001-<random>-VG`` belongs to ``B-001``).  Whatever is
    left is grouped on its longest alphabetic run, which catches colour and size
    variants like ``15k-loom-purple`` / ``15k-pink-loom``.
    """
    # Biggest sellers first, so a variant attaches to the real parent product.
    ranked = [s for s, _ in sorted(skus, key=lambda kv: (-kv[1], len(kv[0])))]
    parent: dict[str, str] = {}
    for sku in ranked:
        lowered = sku.lower()
        for candidate in ranked:
            if candidate is sku or candidate in parent:
                continue
            if len(candidate) >= 3 and candidate.lower() in lowered and candidate != sku:
                parent[sku] = candidate
                break

    roots = [s for s in ranked if s not in parent]

    def words_of(sku: str) -> list[str]:
        return [w.lower() for w in re.split(r"[^A-Za-z]+", sku) if len(w) > 2]

    # How many SKUs each word appears in.  The product name recurs across its
    # variants ("loom" in 15k-pink-loom / 15k-loom-purple / 15k loom blue) while
    # the colour or size does not, so the most shared word names the family.
    frequency: dict[str, int] = defaultdict(int)
    for sku in roots:
        for word in set(words_of(sku)):
            frequency[word] += 1

    def stem(sku: str) -> str:
        words = words_of(sku)
        if not words:
            return sku.strip() or "Other"
        return max(words, key=lambda w: (frequency[w], len(w)))

    groups: dict[str, list[str]] = defaultdict(list)
    for sku in roots:
        groups[stem(sku)].append(sku)

    mapping: dict[str, str] = {}
    for key, members in groups.items():
        # A stem shared by several SKUs is a real family; a lone SKU is its own.
        name = key.title() if len(members) > 1 else members[0]
        for sku in members:
            mapping[sku] = name

    # Variants inherit their parent's family (following the chain to the root).
    for sku in ranked:
        if sku in mapping:
            continue
        root, seen = sku, {sku}
        while root in parent and parent[root] not in seen:
            root = parent[root]
            seen.add(root)
        mapping[sku] = mapping.get(root, root)
    return mapping


def parse_sources(extraction: ingest.Extraction, progress=None) -> dict:
    """Run every parser over the discovered files and return a JSON-able parse."""
    warnings: list[str] = list(extraction.warnings)
    errors: list[str] = []

    summary_files = extraction.of_kind(ingest.KIND_SUMMARY)
    txn_files = extraction.of_kind(ingest.KIND_TRANSACTION)
    br_files = extraction.of_kind(ingest.KIND_BUSINESS)
    inv_files = extraction.of_kind(ingest.KIND_INVOICE)
    eval_files = extraction.of_kind(ingest.KIND_EVALUATION)

    total = sum(map(len, (summary_files, txn_files, br_files, inv_files, eval_files)))
    done = 0

    def tick(stage: str):
        nonlocal done
        done += 1
        if progress:
            progress(done, total, stage)

    # --- Step 1: Summary PDFs -------------------------------------------
    months: dict[str, dict] = {}
    seller = {"display_name": "", "legal_name": ""}
    for f in summary_files:
        try:
            parsed = summary_pdf.parse_summary_pdf(f.path, f.relative)
        except Exception as exc:
            errors.append(f"Summary PDF {f.relative}: {exc}")
            tick("summary")
            continue
        if parsed.month_key in months:
            warnings.append(
                f"Two Summary PDFs cover {month_label(parsed.month_key)}; "
                f"using {f.relative}"
            )
        seller["display_name"] = seller["display_name"] or parsed.display_name
        seller["legal_name"] = seller["legal_name"] or parsed.legal_name
        months[parsed.month_key] = {
            "key": parsed.month_key,
            "label": month_label(parsed.month_key),
            "source": f.relative,
            "income_total": parsed.income_total,
            "expenses_total": parsed.expenses_total,
            "lines": parsed.lines,
            "product_sales_fba": parsed.get("product_sales_fba"),
            "product_sales_sf": parsed.get("product_sales_sf"),
            "refund_fba": parsed.get("refund_fba"),
            "refund_sf": parsed.get("refund_sf"),
            "delivery_credit_refunds": parsed.get("delivery_credit_refunds"),
            "postage_credits": parsed.get("postage_credits"),
            "inventory_credit": parsed.get("inventory_credit"),
            "giftwrap_credits": parsed.get("giftwrap_credits"),
            "promo_rebates": parsed.get("promo_rebates"),
            "promo_rebate_refunds": parsed.get("promo_rebate_refunds"),
            "selling_fees_fba": parsed.get("selling_fees_fba"),
            "selling_fees_sf": parsed.get("selling_fees_sf"),
            "selling_fee_refunds": parsed.get("selling_fee_refunds"),
            "fba_txn_fees": parsed.get("fba_txn_fees"),
            "fba_txn_fee_refunds": parsed.get("fba_txn_fee_refunds"),
            "other_txn_fees": parsed.get("other_txn_fees"),
            "other_txn_fee_refunds": parsed.get("other_txn_fee_refunds"),
            "storage_inbound": parsed.get("storage_inbound"),
            "service_fees": parsed.get("service_fees"),
            "refund_admin_fees": parsed.get("refund_admin_fees"),
            "delivery_label_purchases": parsed.get("delivery_label_purchases"),
            "adjustments": parsed.get("adjustments"),
            "cost_of_advertising": parsed.get("cost_of_advertising"),
            "residual_income": parsed.residual_income,
            "residual_expense": parsed.residual_expense,
            "sales_tax": parsed.sales_tax,
            "tax_withheld": parsed.tax_withheld,
            "tax_total": parsed.tax_total,
            "gross_sales": parsed.gross_sales,
            "net_sales": parsed.net_sales,
            "income_difference": parsed.income_difference,
            "expenses_difference": parsed.expenses_difference,
        }
        tick("summary")

    # --- Step 3: Transaction CSVs ---------------------------------------
    txn: dict[str, dict] = {}
    sku_units: dict[str, dict[str, int]] = defaultdict(dict)
    sku_sales: dict[str, dict[str, float]] = defaultdict(dict)
    sku_tax: dict[str, dict[str, float]] = defaultdict(dict)
    sku_titles: dict[str, str] = {}
    for f in txn_files:
        try:
            parsed_months = transactions.parse_transaction_csv(f.path, f.relative)
        except Exception as exc:
            errors.append(f"Transaction CSV {f.relative}: {exc}")
            tick("transactions")
            continue
        for m in parsed_months:
            if m.month_key in txn:
                warnings.append(
                    f"Two transaction exports cover {month_label(m.month_key)}; "
                    f"using {f.relative}"
                )
            txn[m.month_key] = {
                "key": m.month_key,
                "label": month_label(m.month_key),
                "source": f.relative,
                "net_units": m.net_units,
                "order_units": m.order_units,
                "refund_units": m.refund_units,
                "csv_selling_fees": m.csv_selling_fees,
                "csv_selling_fee_refunds": m.csv_selling_fee_refunds,
                "csv_fba_fees": m.csv_fba_fees,
                "csv_fba_fee_refunds": m.csv_fba_fee_refunds,
                "csv_storage_fees": m.csv_storage_fees,
                "csv_other_txn_fees": m.csv_other_txn_fees,
                "subscription_fees": m.subscription_fees,
                "deal_fees": m.deal_fees,
                "coupon_fees": m.coupon_fees,
                "other_service_fees": m.other_service_fees,
                "advertising_cost": m.advertising_cost,
                "domestic_sales": m.domestic_sales,
                "facilitated_sales": m.facilitated_sales,
            }
            for sku, units in m.units_by_sku.items():
                sku_units[sku][m.month_key] = units
            for sku, sales in m.sales_by_sku.items():
                sku_sales[sku][m.month_key] = sales
            for sku, tax in m.sales_tax_by_sku.items():
                sku_tax[sku][m.month_key] = tax
            for sku, title in m.titles_by_sku.items():
                sku_titles.setdefault(sku, title)
        tick("transactions")

    # --- Step 6: Business Reports ---------------------------------------
    reports = []
    for f in br_files:
        try:
            b = business_report.parse_business_report(f.path, f.relative)
        except Exception as exc:
            errors.append(f"Business Report {f.relative}: {exc}")
            tick("business")
            continue
        reports.append(
            {
                "source": f.relative,
                "name": f.relative.rsplit("/", 1)[-1],
                "sessions": b.sessions,
                "page_views": b.page_views,
                "units_ordered": b.units_ordered,
                "ordered_product_sales": b.ordered_product_sales,
                "child_asins": b.child_asins,
                "buy_box": round(b.buy_box_weighted, 4),
                "conversion": round(b.conversion, 4),
            }
        )
        tick("business")

    # --- Step 7: PPC invoices (parallel; ~100 PDFs) ----------------------
    invoices: list[ppc_invoice.PPCInvoice] = []
    if inv_files:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(ppc_invoice.parse_ppc_invoice, f.path, f.relative): f
                for f in inv_files
            }
            for future in as_completed(futures):
                f = futures[future]
                try:
                    parsed_invoice = future.result()
                    if parsed_invoice:
                        invoices.append(parsed_invoice)
                    else:
                        warnings.append(f"No invoice number found in {f.relative}")
                except Exception as exc:
                    errors.append(f"PPC invoice {f.relative}: {exc}")
                tick("invoices")

    unique_invoices = ppc_invoice.deduplicate(invoices)
    duplicate_count = len(invoices) - len(unique_invoices)
    invoice_rows = [
        {
            "number": i.invoice_number,
            "date": i.invoice_date.isoformat() if i.invoice_date else "",
            "date_display": i.invoice_date.strftime("%d-%m-%Y") if i.invoice_date else "",
            "period": i.period_label,
            "net": i.net,
            "vat": i.vat,
            "gross": i.gross,
            "month": i.month_key,
            "vat_rate_ok": i.vat_rate_ok,
        }
        for i in unique_invoices
    ]

    # --- Step 4: evaluation / SellerBoard cost rates ---------------------
    cost_rows = []
    for f in eval_files:
        try:
            for row in evaluation.parse_evaluation(f.path, f.relative):
                cost_rows.append(
                    {
                        "product": row.product,
                        "units": row.units,
                        "cost_of_goods": row.cost_of_goods,
                        "landed_cost": row.landed_cost,
                        "sheet": row.sheet,
                        "source": f.relative,
                    }
                )
        except Exception as exc:
            warnings.append(f"Could not read {f.relative} as an evaluation sheet: {exc}")
        tick("evaluation")

    # --- SKU roll-up and proposed families -------------------------------
    all_skus = sorted(set(sku_units) | set(sku_sales))
    total_units = {sku: sum(sku_units.get(sku, {}).values()) for sku in all_skus}
    proposed = _families_from_skus([(sku, total_units[sku]) for sku in all_skus])
    proposed = _merge_families_by_title(proposed, sku_titles, total_units)
    # SKU revenue is reported gross: product sales plus the tax collected on
    # them, which is what the buyer actually paid.
    skus = []
    for sku in all_skus:
        net_by_month = sku_sales.get(sku, {})
        tax_by_month = sku_tax.get(sku, {})
        gross_by_month = {
            key: round(net_by_month.get(key, 0.0) + tax_by_month.get(key, 0.0), 2)
            for key in set(net_by_month) | set(tax_by_month)
        }
        skus.append(
            {
                "sku": sku,
                "title": sku_titles.get(sku, ""),
                "family": proposed.get(sku, sku),
                "units_by_month": sku_units.get(sku, {}),
                "sales_by_month": gross_by_month,
                "sales_ex_tax_by_month": net_by_month,
                "sales_tax_by_month": tax_by_month,
                "total_units": total_units[sku],
                "total_sales": round(sum(gross_by_month.values()), 2),
            }
        )
    skus.sort(key=lambda s: s["total_sales"], reverse=True)

    month_keys = sorted(months)
    return {
        "seller": seller,
        "month_keys": month_keys,
        "months": months,
        "transactions": txn,
        "business_reports": reports,
        "business_report_map": suggest_report_months(reports, txn, month_keys),
        "invoices": invoice_rows,
        "invoice_duplicates": duplicate_count,
        "cost_rows": cost_rows,
        "skus": skus,
        # Surfaced on the review step so the user can spot a file that was
        # uploaded but silently ignored (campaign reports, stray screenshots).
        "unknown_files": [
            {"name": f.relative, "note": f.note}
            for f in extraction.of_kind(ingest.KIND_UNKNOWN)
        ],
        "warnings": warnings,
        "errors": errors,
        "counts": {
            "summary": len(summary_files),
            "transaction": len(txn_files),
            "business": len(br_files),
            "invoice": len(inv_files),
            "evaluation": len(eval_files),
            "unknown": len(extraction.of_kind(ingest.KIND_UNKNOWN)),
        },
    }


def suggest_report_months(
    reports: list[dict], txn: dict[str, dict], month_keys: list[str]
) -> dict[str, str]:
    """Guess which month each Business Report covers.

    Amazon names these files only by download date, so the month has to be
    inferred.  Units ordered in a Business Report tracks the transaction file's
    unit count closely (it counts orders, before refunds), and the ordering of
    the two series is the same — so ranking both by units and pairing them off
    recovers the mapping.  The user confirms or overrides it in the wizard.
    """
    usable = [k for k in month_keys if k in txn]
    if not reports or not usable:
        return {}

    by_units = sorted(reports, key=lambda r: r["units_ordered"])
    months_by_units = sorted(usable, key=lambda k: txn[k]["order_units"] or txn[k]["net_units"])

    mapping: dict[str, str] = {}
    if len(by_units) == len(months_by_units):
        for report, key in zip(by_units, months_by_units):
            mapping[report["source"]] = key
        return mapping

    # Counts differ — fall back to nearest-unit matching, each month used once.
    remaining = list(months_by_units)
    for report in by_units:
        if not remaining:
            mapping[report["source"]] = ""
            continue
        best = min(
            remaining,
            key=lambda k: abs((txn[k]["order_units"] or 0) - report["units_ordered"]),
        )
        mapping[report["source"]] = best
        remaining.remove(best)
    return mapping
