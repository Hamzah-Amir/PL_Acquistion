#!/usr/bin/env python
"""Interactive command-line runner for the Amazon UK acquisition P&L.

Point it at a zip (or a folder) of seller exports, answer a few questions, and
it writes the filled workbook.

    .venv\\Scripts\\python.exe run_pl.py
    .venv\\Scripts\\python.exe run_pl.py "sample_files\\New zip.zip"
    .venv\\Scripts\\python.exe run_pl.py path\\to\\exports -o out.xlsx

Everything except the answers you type comes from the uploaded files.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
import time
import warnings

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

# Product titles and the pound sign are UTF-8; Windows consoles often are not.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plbuilder.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from builder.engine import assemble, model as plmodel, workbook  # noqa: E402
from builder.parsers import ingest  # noqa: E402

DEFAULT_SOURCE = os.path.join(BASE_DIR, "sample_files", "New zip.zip")

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

BOLD, DIM, GREEN, YELLOW, RED, CYAN, RESET = (
    ("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m")
    if sys.stdout.isatty() and os.name != "nt" or os.environ.get("ANSICON")
    else ("", "", "", "", "", "", "")
)


def heading(text: str) -> None:
    print(f"\n{BOLD}{text}{RESET}")
    print("-" * len(text))


def money(value: float) -> str:
    return f"{'-' if value < 0 else ''}£{abs(value):,.2f}"


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        answer = input(f"{prompt}{suffix}: ").strip()
        if answer:
            return answer
        if default is not None:
            return default
        print("  Please enter a value.")


def ask_yes_no(prompt: str, default: bool | None = None) -> bool:
    hint = "Y/n" if default is True else "y/N" if default is False else "y/n"
    while True:
        answer = input(f"{prompt} ({hint}): ").strip().lower()
        if not answer and default is not None:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("  Please answer y or n.")


def ask_money(prompt: str, default: float | None = None) -> float:
    while True:
        raw = ask(prompt, "" if default is None else f"{default:g}")
        cleaned = raw.replace(",", "").replace("£", "").strip()
        if not cleaned:
            return default or 0.0
        try:
            value = float(cleaned)
        except ValueError:
            print("  Enter a number, for example 3.50")
            continue
        if value < 0:
            print("  Enter a positive amount.")
            continue
        return value


def ask_choice(prompt: str, options: list[tuple[str, str]], default: str) -> str:
    print(f"\n{prompt}")
    for key, label in options:
        marker = "*" if key == default else " "
        print(f"  {marker} {key} — {label}")
    valid = {key for key, _ in options}
    while True:
        answer = input(f"Choose [{default}]: ").strip() or default
        if answer in valid:
            return answer
        print(f"  Pick one of: {', '.join(sorted(valid))}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def collect_sources(source: str, workspace: str) -> None:
    """Copy the user's zip or folder into a scratch workspace."""
    target = os.path.join(workspace, "sources")
    os.makedirs(target, exist_ok=True)
    if os.path.isdir(source):
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        shutil.copy(source, os.path.join(target, os.path.basename(source)))


def read_sources(workspace: str) -> dict:
    root = os.path.join(workspace, "sources")
    state = {"last": 0.0}

    def show(done: int, total: int, stage: str = "identifying"):
        now = time.time()
        if now - state["last"] < 0.2 and done < total:
            return
        state["last"] = now
        width = 32
        filled = int(width * done / max(total, 1))
        bar = "#" * filled + "." * (width - filled)
        print(f"\r  [{bar}] {done}/{total} {stage:<28}", end="", flush=True)

    print("\nUnpacking archives and identifying files…")
    extraction = ingest.discover(root, progress=lambda d, t: show(d, t, "identifying files"))
    print()

    labels = {
        "summary": "Summary PDFs",
        "transactions": "transaction CSVs",
        "business": "Business Reports",
        "invoices": "advertising invoices",
        "evaluation": "evaluation sheet",
    }
    print("Reading source files…")
    parse = assemble.parse_sources(
        extraction, progress=lambda d, t, s: show(d, t, labels.get(s, s))
    )
    print("\n")
    return parse


def report_sources(parse: dict) -> None:
    counts = parse["counts"]
    seller = parse.get("seller", {})
    heading("What was found")
    if seller.get("legal_name") or seller.get("display_name"):
        print(f"  Seller       : {seller.get('legal_name', '')} "
              f"({seller.get('display_name', '')})")
    print(f"  Summary PDFs : {counts['summary']}")
    print(f"  Transactions : {counts['transaction']}")
    print(f"  Business rpts: {counts['business']}")
    print(f"  PPC invoices : {len(parse['invoices'])} "
          f"({parse.get('invoice_duplicates', 0)} duplicates removed)")
    print(f"  SKUs         : {len(parse['skus'])}")
    if counts.get("unknown"):
        print(f"  {DIM}Ignored      : {counts['unknown']} unrecognised file(s){RESET}")

    months = parse["month_keys"]
    if months:
        first, last = assemble.month_label(months[0]), assemble.month_label(months[-1])
        print(f"  Months       : {len(months)} ({first} to {last})")

    for problem in parse.get("errors", [])[:5]:
        print(f"  {RED}error{RESET}: {problem}")
    for warning in parse.get("warnings", [])[:5]:
        print(f"  {YELLOW}note{RESET} : {warning}")


def ask_cogs(parse: dict, window: list[str]) -> dict[str, float]:
    """Question 1 — the landed cost per unit."""
    heading("1. Cost of goods (COGS)")
    print("  This is the one figure that is not in any Amazon export.")
    print("  Enter the landed cost per unit — what you pay to get one unit into")
    print("  an Amazon warehouse (product + freight + duty).\n")

    in_window = set(window)
    families: dict[str, dict] = {}
    for sku in parse["skus"]:
        family = sku["family"]
        units = sum(v for k, v in sku["units_by_month"].items() if k in in_window)
        entry = families.setdefault(
            family, {"units": 0, "sales": 0.0, "members": [], "title": "", "best": -1}
        )
        entry["units"] += units
        entry["sales"] += sum(v for k, v in sku["sales_by_month"].items() if k in in_window)
        entry["members"].append(sku["sku"])
        # Name the family after whichever SKU in it sells most.
        if sku["title"] and units > entry["best"]:
            entry["best"] = units
            entry["title"] = sku["title"]

    selling = {n: d for n, d in families.items() if d["units"] > 0} or families
    names = sorted(selling, key=lambda n: -selling[n]["units"])

    def short_title(name: str, width: int = 60) -> str:
        title = selling[name]["title"].strip()
        if not title:
            return "(no product title in the transaction files)"
        return title if len(title) <= width else title[:width - 1].rstrip() + "…"

    print(f"  {len(names)} product family(ies) sold in the modelled period:\n")
    for index, name in enumerate(names, start=1):
        data = selling[name]
        asp = data["sales"] / data["units"] if data["units"] else 0.0
        print(f"  {CYAN}[{index}] {short_title(name, 66)}{RESET}")
        print(f"      SKU code {name[:40]:<40} {data['units']:>7,} units   "
              f"avg sale price {money(asp)}")
        others = [s for s in data["members"] if s != name]
        if others:
            listed = ", ".join(others[:2])
            more = f" +{len(others) - 2} more" if len(others) > 2 else ""
            print(f"      {DIM}also includes: {listed}{more}{RESET}")
        print()

    rates: dict[str, float] = {}
    if len(names) == 1:
        rates[names[0]] = ask_money("  Landed cost per unit (£)")
    else:
        print("  Answer n to price each product separately (recommended),")
        print("  or y to apply one rate to all of them.")
        blanket = ask_yes_no(
            "  Use one blanket rate for every family?", default=False
        )
        if blanket:
            rate = ask_money("  Landed cost per unit (£)")
            rates = {name: rate for name in names}
        else:
            print("\n  Enter the landed cost per unit for each product "
                  "(Enter = 0, skip it):")
            for index, name in enumerate(names, start=1):
                print(f"\n  {CYAN}[{index}] {short_title(name, 66)}{RESET}")
                print(f"      {DIM}SKU {name} · {selling[name]['units']:,} units · "
                      f"sells at {money(selling[name]['sales'] / selling[name]['units'] if selling[name]['units'] else 0)}{RESET}")
                rates[name] = ask_money("      Landed cost per unit (£)", 0.0)

    # Families with no sales in the window still need a key for the rate table.
    for name in families:
        rates.setdefault(name, 0.0)
    return rates


def ask_cogs_vat(rates: dict[str, float]) -> tuple[bool, bool]:
    """Question 3 — was VAT paid on the goods, and if so is it in the rate?

    Returns ``(vat_paid, vat_included)``.
    """
    heading("3. VAT on the cost of goods")
    paid = ask_yes_no("  Have you paid VAT on the COGS?", default=True)

    sample = next((r for r in rates.values() if r), 0.0)
    if not paid:
        print("  -> No VAT on the goods. The cost is used exactly as you entered it")
        print("     and adds nothing to reclaimable input VAT.")
        return False, True

    print("\n  Included  -> the figure you typed is VAT-inclusive; import VAT = COGS / 6")
    print("  Excluded  -> the figure is ex-VAT; 20% is added on top")
    included = ask_yes_no(
        "\n  Is VAT included in the COGS figure you entered?", default=True
    )
    if sample:
        if included:
            print(f"  -> £{sample:,.4f}/unit is the cash cost; "
                  f"£{sample / 6:,.4f} of it is import VAT.")
        else:
            print(f"  -> £{sample:,.4f}/unit becomes £{sample * 1.2:,.4f} incl VAT; "
                  f"£{sample * 0.2:,.4f} is import VAT.")
    return True, included


def ask_vat_scheme() -> str:
    """Question 2 — registration and rate."""
    heading("2. VAT registration")
    if not ask_yes_no("  Is the business VAT registered?", default=True):
        print("  -> 0%: no output VAT. Input VAT stays a cost inside the fees.")
        return plmodel.SCHEME_NONE

    scheme = ask_choice(
        "  Which rate?",
        [
            ("20", "Standard — output VAT = Net Sales / 6, less reclaimable input VAT"),
            ("7.5", "Flat rate — output VAT = Net Sales / 107.5 x 7.5, no reclaim"),
        ],
        default="20",
    )
    if scheme == plmodel.SCHEME_STANDARD:
        print("  -> 20%: input VAT on fees, PPC and COGS is reclaimable.")
    else:
        print("  -> 7.5%: input VAT is NOT reclaimable and stays a cost.")
    return scheme


def ask_extras(parse: dict) -> dict:
    heading("4. Optional extras (press Enter to skip)")
    seller = parse.get("seller", {})
    return {
        "opex_monthly": ask_money("  Off-Amazon operating cost per month (£)", 0.0),
        "asking_price": ask_money("  Asking price for the business (£)", 0.0),
        "business_name": ask(
            "  Business name",
            seller.get("legal_name") or seller.get("display_name") or "Amazon UK",
        ),
    }


def report_model(model: plmodel.PLModel) -> None:
    heading("Reconciliation (workflow §4)")
    for check in model.checks:
        if check.passed:
            mark, colour = "PASS", GREEN
        elif check.severity == "warning":
            mark, colour = "WARN", YELLOW
        else:
            mark, colour = "FAIL", RED
        print(f"  {colour}[{mark}]{RESET} {check.name}: {check.detail}")

    heading("Monthly P&L")
    header = (f"  {'Month':<8}{'Net sales':>12}{'Fees':>12}{'PPC':>11}"
              f"{'COGS':>11}{'VAT':>11}{'Profit':>12}{'Units':>8}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in model.months:
        print(f"  {row.label:<8}{row.net_sales:>12,.2f}{row.total_fees:>12,.2f}"
              f"{row.total_ppc:>11,.2f}{row.cogs:>11,.2f}{row.output_vat:>11,.2f}"
              f"{row.net_profit:>12,.2f}{row.units:>8,}")
    print("  " + "-" * (len(header) - 2))
    print(f"  {'TTM':<8}{model.ttm_sum('net_sales'):>12,.2f}"
          f"{model.ttm_sum('total_fees'):>12,.2f}{model.ttm_sum('total_ppc'):>11,.2f}"
          f"{model.ttm_sum('cogs'):>11,.2f}{model.ttm_sum('output_vat'):>11,.2f}"
          f"{model.ttm_sum('net_profit'):>12,.2f}{model.ttm_units:>8,}")

    sales = model.ttm_sum("net_sales")
    profit = model.ttm_sum("net_profit")
    heading("TTM summary")
    print(f"  VAT scheme            : {model.scheme_label}")
    print(f"  Net sales (ex-tax)    : {money(sales)}")
    print(f"  Sales tax collected   : {money(model.ttm_sum('sales_tax'))}")
    print(f"  Gross sales (VAT base): {money(model.ttm_sum('gross_sales'))}")
    print(f"  Amazon fees incl VAT  : {money(model.ttm_sum('total_fees'))}"
          f"   ({-model.ttm_sum('total_fees') / sales:.1%} of sales)" if sales else "")
    print(f"  PPC incl VAT          : {money(model.ttm_sum('total_ppc'))}"
          f"   (TACoS {-model.ttm_sum('total_ppc') / sales:.1%})" if sales else "")
    print(f"  COGS incl VAT         : {money(model.ttm_sum('cogs'))}")
    reclaim = "reclaimed" if model.input_vat_is_reclaimable else "irrecoverable, memo only"
    print(f"  Input VAT             : {money(model.ttm_sum('input_vat'))}   ({reclaim})")
    print(f"  Output VAT            : {money(model.ttm_sum('output_vat'))}")
    if model.ttm_sum("opex"):
        print(f"  Off-Amazon OpEx       : {money(model.ttm_sum('opex'))}")
    colour = GREEN if profit >= 0 else RED
    print(f"  {BOLD}NET PROFIT            : {colour}{money(profit)}{RESET}"
          + (f"   (margin {profit / sales:.1%})" if sales else ""))
    print(f"  Units sold            : {model.ttm_units:,}")
    print(f"  Blended landed £/unit : £{model.blended_landed_cost:,.4f}")
    if sales:
        print(f"  {DIM}Referral fee % {-model.ttm_sum('referral_incl') / sales:>7.1%}   "
              f"FBA fee % {-model.ttm_sum('fba_incl') / sales:>7.1%}   "
              f"COGS % {-model.ttm_sum('cogs') / sales:>7.1%}{RESET}")

    asking = float(model.settings.get("asking_price") or 0)
    if asking and profit > 0:
        print(f"  Implied multiple      : {asking / profit:.2f}x on the asking price")
    elif asking:
        print(f"  {YELLOW}Implied multiple      : n/a — net profit is not positive{RESET}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the Amazon UK acquisition P&L from seller exports."
    )
    parser.add_argument(
        "source", nargs="?", default=DEFAULT_SOURCE,
        help="Zip or folder of seller exports (default: the bundled sample).",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Where to write the workbook (default: ./output/<name>.xlsx).",
    )
    parser.add_argument(
        "--keep", action="store_true",
        help="Keep the unpacked working directory for inspection.",
    )
    # Non-interactive equivalents of the questions, for scripting and tests.
    parser.add_argument(
        "--cogs", type=float, metavar="RATE",
        help="Landed cost per unit, applied to every product family. "
             "Supplying this skips the COGS question.",
    )
    parser.add_argument(
        "--vat", choices=["0", "7.5", "20"], metavar="{0,7.5,20}",
        help="VAT scheme. Supplying this skips the registration question.",
    )
    parser.add_argument(
        "--cogs-vat", choices=["none", "included", "excluded"],
        help="VAT on the goods: 'none' if no VAT was paid, otherwise whether "
             "--cogs already includes it. Default: included.",
    )
    parser.add_argument("--opex", type=float, default=None,
                        help="Off-Amazon operating cost per month.")
    parser.add_argument("--price", type=float, default=None,
                        help="Asking price for the business.")
    parser.add_argument("--name", default=None, help="Business name.")
    args = parser.parse_args()

    source = os.path.abspath(args.source)
    if not os.path.exists(source):
        print(f"{RED}Source not found:{RESET} {source}")
        return 1

    print(f"{BOLD}Amazon UK Acquisition P&L builder{RESET}")
    print(f"Source: {source}")

    workspace = tempfile.mkdtemp(prefix="pl-run-")
    try:
        collect_sources(source, workspace)
        parse = read_sources(workspace)

        if not parse["month_keys"]:
            print(f"{RED}No monthly Summary PDFs were found.{RESET}")
            print("The Summary PDF is the source everything else reconciles to.")
            print("Export: Payments > Reports Repository > Date Range Reports > Summary.")
            return 1

        report_sources(parse)

        # Trailing 13 months, per the workflow.
        window = parse["month_keys"][-13:]

        # Asked in the order: what is the COGS, is VAT registered, is VAT in the COGS.
        if args.cogs is not None:
            rates = {s["family"]: args.cogs for s in parse["skus"]}
            print(f"\n1. COGS          : £{args.cogs:,.4f}/unit")
        else:
            rates = ask_cogs(parse, window)

        if args.vat is not None:
            scheme = args.vat
            print(f"2. VAT scheme    : {plmodel.VAT_SCHEMES[scheme]}")
        else:
            scheme = ask_vat_scheme()

        if args.cogs is not None:
            mode = args.cogs_vat or "included"
            cogs_vat_paid = mode != "none"
            cogs_vat_included = mode != "excluded"
            print("3. VAT on COGS   : " + {
                "none": "no VAT paid — cost used as entered",
                "included": "paid, included in the rate (COGS / 6)",
                "excluded": "paid, excluded from the rate (rate x 20%)",
            }[mode])
        else:
            cogs_vat_paid, cogs_vat_included = ask_cogs_vat(rates)

        if args.cogs is not None and args.vat is not None:
            seller = parse.get("seller", {})
            extras = {
                "opex_monthly": args.opex or 0.0,
                "asking_price": args.price or 0.0,
                "business_name": args.name
                or seller.get("legal_name")
                or seller.get("display_name")
                or "Amazon UK",
            }
        else:
            extras = ask_extras(parse)

        choices = {
            "window": window,
            "sku_families": {s["sku"]: s["family"] for s in parse["skus"]},
            "family_rates": rates,
            "cogs_vat_paid": cogs_vat_paid,
            "cogs_vat_included": cogs_vat_included,
            "report_month_map": parse.get("business_report_map", {}),
            "vat_scheme": scheme,
            **extras,
        }

        model = plmodel.build_model(parse, choices)
        report_model(model)

        output = args.output or os.path.join(
            BASE_DIR, "output",
            f"{extras['business_name'].replace(' ', '_')}_PL_"
            f"{model.months[0].label}_to_{model.months[-1].label}.xlsx",
        )
        workbook.build_workbook(model, settings.PL_TEMPLATE_PATH, os.path.abspath(output))

        heading("Workbook written")
        print(f"  {GREEN}{os.path.abspath(output)}{RESET}")
        if args.keep:
            print(f"  {DIM}Working directory kept: {workspace}{RESET}")
        return 0

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    finally:
        if not args.keep:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
