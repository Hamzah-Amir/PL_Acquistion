"""A P&L restricted to a chosen set of SKUs.

The result is a parse in exactly the shape ``assemble.parse_sources`` returns,
so the existing model and workbook code run on it unchanged.

Per-SKU data comes straight from the transaction CSVs: units, product sales,
tax, and referral / FBA / other transaction fees.  Account-level lines that
Amazon never ties to a SKU (storage, service and subscription fees, promo
rebates, credits, adjustments) are allocated by the selected SKUs' share of
total product sales.  Advertising is the one line the transaction data does
not split cleanly, so it is TACoS-allocated: each month's TACoS (advertising
÷ net sales, from the Summary PDF) times the selected SKUs' net sales.
"""
from __future__ import annotations

ACCOUNT_LEVEL_KEYS = (
    "postage_credits", "inventory_credit", "giftwrap_credits",
    "promo_rebates", "promo_rebate_refunds", "delivery_credit_refunds",
    "residual_income", "storage_inbound", "service_fees", "refund_admin_fees",
    "delivery_label_purchases", "adjustments", "residual_expense", "tax_withheld",
)

TXN_ACCOUNT_KEYS = (
    "subscription_fees", "deal_fees", "coupon_fees", "other_service_fees",
    "csv_storage_fees",
)


def _share(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def subset_parse(parse: dict, selected: set[str]) -> dict:
    skus = [s for s in parse["skus"] if s["sku"] in selected]
    keys = parse["month_keys"]

    months: dict[str, dict] = {}
    transactions: dict[str, dict] = {}
    for key in keys:
        source = parse["months"].get(key, {})
        txn = parse["transactions"].get(key, {})

        total_net = sum(s["sales_ex_tax_by_month"].get(key, 0.0) for s in parse["skus"])
        sub_net = sum(s["sales_ex_tax_by_month"].get(key, 0.0) for s in skus)
        share = _share(sub_net, total_net)

        fees = {"referral": 0.0, "fba": 0.0, "other": 0.0}
        for s in skus:
            for name, value in s.get("fees_by_month", {}).get(key, {}).items():
                fees[name] += value
        sub_units = sum(s["units_by_month"].get(key, 0) for s in skus)
        sub_tax = sum(s["sales_tax_by_month"].get(key, 0.0) for s in skus)

        net_sales_summary = source.get("net_sales", 0.0)
        tacos = _share(-source.get("cost_of_advertising", 0.0), net_sales_summary)
        sub_ppc = -round(tacos * sub_net, 2)

        month = dict(source)
        month.update({
            "product_sales_fba": round(sub_net, 2),
            "product_sales_sf": 0.0,
            "refund_fba": 0.0,
            "refund_sf": 0.0,
            "selling_fees_fba": round(fees["referral"], 2),
            "selling_fees_sf": 0.0,
            "selling_fee_refunds": 0.0,
            "fba_txn_fees": round(fees["fba"], 2),
            "fba_txn_fee_refunds": 0.0,
            "other_txn_fees": round(fees["other"], 2),
            "other_txn_fee_refunds": 0.0,
            "cost_of_advertising": sub_ppc,
            "sales_tax": round(sub_tax, 2),
        })
        for k in ACCOUNT_LEVEL_KEYS:
            month[k] = round(source.get(k, 0.0) * share, 2)

        month["income_total"] = round(sum(
            month.get(k, 0.0) for k in (
                "product_sales_fba", "product_sales_sf", "postage_credits",
                "inventory_credit", "giftwrap_credits", "promo_rebates",
                "promo_rebate_refunds", "refund_fba", "refund_sf",
                "delivery_credit_refunds", "residual_income",
            )
        ), 2)
        month["expenses_total"] = round(sum(
            month.get(k, 0.0) for k in (
                "selling_fees_fba", "selling_fees_sf", "selling_fee_refunds",
                "fba_txn_fees", "fba_txn_fee_refunds", "other_txn_fees",
                "other_txn_fee_refunds", "storage_inbound", "service_fees",
                "refund_admin_fees", "delivery_label_purchases", "adjustments",
                "cost_of_advertising", "residual_expense",
            )
        ), 2)
        months[key] = month

        txn_month = dict(txn)
        txn_month.update({
            "net_units": sub_units,
            "order_units": sub_units,
            "refund_units": 0,
            "csv_selling_fees": round(fees["referral"], 2),
            "csv_selling_fee_refunds": 0.0,
            "csv_fba_fees": round(fees["fba"], 2),
            "csv_fba_fee_refunds": 0.0,
            "csv_other_txn_fees": round(fees["other"], 2),
        })
        for k in TXN_ACCOUNT_KEYS:
            txn_month[k] = round(txn.get(k, 0.0) * share, 2)
        transactions[key] = txn_month

    subset_skus = [
        {
            **s,
            "sales_by_month": {
                k: round(s["sales_ex_tax_by_month"].get(k, 0.0)
                         + s["sales_tax_by_month"].get(k, 0.0), 2)
                for k in set(s["sales_ex_tax_by_month"]) | set(s["sales_tax_by_month"])
            },
            "total_sales": round(
                sum(s["sales_ex_tax_by_month"].values())
                + sum(s["sales_tax_by_month"].values()), 2
            ),
        }
        for s in skus
    ]

    return {
        **parse,
        "months": months,
        "transactions": transactions,
        "skus": subset_skus,
    }
