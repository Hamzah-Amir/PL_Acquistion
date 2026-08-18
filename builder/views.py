"""The wizard.

Five steps, mirroring the workflow: upload the exports, confirm what was found,
set the cost rates, state the assumptions, then build and download.
"""
from __future__ import annotations

import json
import mimetypes

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import services
from .engine import model as plmodel
from .engine.assemble import month_label
from .models import Job
from .parsers import ingest

STEPS = [
    (Job.Step.UPLOAD, "Upload", "builder:upload"),
    (Job.Step.REVIEW, "Review sources", "builder:review"),
    (Job.Step.COSTS, "Cost rates", "builder:costs"),
    (Job.Step.ASSUMPTIONS, "Assumptions", "builder:assumptions"),
    (Job.Step.RESULT, "Build", "builder:result"),
]


def _steps_context(job: Job | None, current: str) -> list[dict]:
    order = [s[0] for s in STEPS]
    current_index = order.index(current)
    steps = []
    for index, (key, label, route) in enumerate(STEPS):
        steps.append(
            {
                "key": key,
                "label": label,
                "number": index + 1,
                "state": (
                    "current" if index == current_index
                    else "done" if index < current_index
                    else "todo"
                ),
                "url": (
                    reverse(route, args=[job.id])
                    if job and index < current_index and key != Job.Step.UPLOAD
                    else ""
                ),
            }
        )
    return steps


def _require_ready(job: Job):
    """Send the user back to the progress page if the parse is not done."""
    if job.status == Job.Status.FAILED:
        return redirect("builder:processing", job_id=job.id)
    if not job.is_ready:
        return redirect("builder:processing", job_id=job.id)
    return None


def _to_float(value, default=0.0) -> float:
    try:
        text = str(value).replace(",", "").replace("£", "").strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Step 1 — upload
# ---------------------------------------------------------------------------

def upload(request):
    if request.method == "POST":
        files = request.FILES.getlist("sources")
        if not files:
            messages.error(request, "Choose at least one file or archive to upload.")
            return redirect("builder:upload")

        job = Job.objects.create()
        try:
            count, total = services.save_uploads(job, files)
        except ValueError as exc:
            job.delete()
            messages.error(request, str(exc))
            return redirect("builder:upload")

        if not count:
            job.delete()
            messages.error(request, "Nothing was uploaded.")
            return redirect("builder:upload")

        services.start_processing(job)
        return redirect("builder:processing", job_id=job.id)

    return render(
        request,
        "builder/upload.html",
        {
            "steps": _steps_context(None, Job.Step.UPLOAD),
            "recent": Job.objects.filter(status=Job.Status.READY)[:5],
            "max_mb": settings.PL_MAX_UPLOAD_BYTES // (1024 * 1024),
        },
    )


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def processing(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if job.is_ready:
        return redirect("builder:review", job_id=job.id)
    return render(
        request,
        "builder/processing.html",
        {"job": job, "steps": _steps_context(job, Job.Step.UPLOAD)},
    )


@require_GET
def progress(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    return JsonResponse(
        {
            "status": job.status,
            "progress": job.progress,
            "message": job.progress_message,
            "error": job.error,
            "done": job.is_ready,
            "next": reverse("builder:review", args=[job.id]) if job.is_ready else "",
        }
    )


# ---------------------------------------------------------------------------
# Step 2 — review what was found
# ---------------------------------------------------------------------------

def review(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if redirect_response := _require_ready(job):
        return redirect_response

    parse = job.parse
    choices = services.default_choices(parse, job.choices)

    if request.method == "POST":
        window = request.POST.getlist("window")
        window = [k for k in parse["month_keys"] if k in window]
        if not window:
            messages.error(request, "Select at least one month to model.")
            return redirect("builder:review", job_id=job.id)

        report_map = {}
        for report in parse["business_reports"]:
            selected = request.POST.get(f"report__{report['source']}", "")
            if selected in parse["month_keys"]:
                report_map[report["source"]] = selected

        duplicates = [k for k in set(report_map.values()) if list(report_map.values()).count(k) > 1]
        if duplicates:
            messages.error(
                request,
                "Two Business Reports are mapped to the same month ("
                + ", ".join(month_label(k) for k in duplicates)
                + "). Each month can only have one.",
            )
            return redirect("builder:review", job_id=job.id)

        choices.update({"window": window, "report_month_map": report_map})
        job.choices = choices
        job.step = Job.Step.COSTS
        job.save(update_fields=["choices", "step", "updated_at"])
        return redirect("builder:costs", job_id=job.id)

    months = []
    for key in parse["month_keys"]:
        source = parse["months"][key]
        txn = parse["transactions"].get(key)
        months.append(
            {
                "key": key,
                "label": source["label"],
                "selected": key in choices["window"],
                "income_total": source["income_total"],
                "expenses_total": source["expenses_total"],
                "income_ok": abs(source["income_difference"]) < 0.005,
                "expenses_ok": abs(source["expenses_difference"]) < 0.005,
                "has_transactions": bool(txn),
                "units": txn["net_units"] if txn else 0,
                "advertising": source["cost_of_advertising"],
            }
        )

    reports = []
    for report in parse["business_reports"]:
        reports.append(
            {
                **report,
                "selected": choices["report_month_map"].get(report["source"], ""),
            }
        )
    reports.sort(key=lambda r: r["selected"] or "zzz")

    month_options = [
        {"key": k, "label": parse["months"][k]["label"]} for k in parse["month_keys"]
    ]

    return render(
        request,
        "builder/review.html",
        {
            "job": job,
            "steps": _steps_context(job, Job.Step.REVIEW),
            "parse": parse,
            "months": months,
            "reports": reports,
            "month_options": month_options,
            "counts": parse["counts"],
            "kind_labels": ingest.KIND_LABELS,
            "invoice_count": len(parse["invoices"]),
            "warnings": parse.get("warnings", []),
            "errors": parse.get("errors", []),
            "unmatched": parse.get("unknown_files", []),
        },
    )


# ---------------------------------------------------------------------------
# Step 3 — cost rates (workflow steps 4 & 5)
# ---------------------------------------------------------------------------

def costs(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if redirect_response := _require_ready(job):
        return redirect_response

    parse = job.parse
    choices = services.default_choices(parse, job.choices)

    if request.method == "POST":
        sku_families = {}
        for sku in parse["skus"]:
            name = (request.POST.get(f"family__{sku['sku']}") or "").strip()
            sku_families[sku["sku"]] = name or sku["family"]

        rates = {}
        for family in sorted(set(sku_families.values())):
            rates[family] = round(_to_float(request.POST.get(f"rate__{family}")), 4)

        vat_mode = request.POST.get("cogs_vat", "included")
        choices.update(
            {
                "sku_families": sku_families,
                "family_rates": rates,
                "cogs_vat_paid": vat_mode != "none",
                "cogs_vat_included": vat_mode != "excluded",
            }
        )
        job.choices = choices
        job.step = Job.Step.ASSUMPTIONS
        job.save(update_fields=["choices", "step", "updated_at"])
        return redirect("builder:assumptions", job_id=job.id)

    window = set(choices["window"])
    skus = []
    for sku in parse["skus"]:
        units = sum(v for k, v in sku["units_by_month"].items() if k in window)
        sales = round(sum(v for k, v in sku["sales_by_month"].items() if k in window), 2)
        skus.append(
            {
                "sku": sku["sku"],
                "title": (sku["title"] or "")[:90],
                "family": choices["sku_families"].get(sku["sku"], sku["family"]),
                "units": units,
                "sales": sales,
                "asp": round(sales / units, 2) if units else 0.0,
            }
        )
    skus.sort(key=lambda s: s["sales"], reverse=True)

    families = []
    for name in sorted({s["family"] for s in skus}):
        members = [s for s in skus if s["family"] == name]
        families.append(
            {
                "name": name,
                "rate": choices["family_rates"].get(name, 0.0),
                "skus": len(members),
                "units": sum(s["units"] for s in members),
                "sales": round(sum(s["sales"] for s in members), 2),
                "asp": round(
                    sum(s["sales"] for s in members) / sum(s["units"] for s in members), 2
                ) if sum(s["units"] for s in members) else 0.0,
            }
        )

    # Everything the live preview needs, so typing a rate updates COGS, the
    # blended cost and estimated profit without a round trip.
    model = services.build_model(job)
    preview = {
        "families": {f["name"]: f["units"] for f in families},
        "netSales": model.ttm_sum("net_sales"),
        "grossSales": model.ttm_sum("gross_sales"),
        "fees": model.ttm_sum("total_fees"),
        "ppc": model.ttm_sum("total_ppc"),
        "feeInputVat": round(
            model.ttm_sum("input_vat") - model.ttm_sum("cogs_vat"), 2
        ),
        "opex": model.ttm_sum("opex"),
        "units": model.ttm_units,
        "scheme": model.scheme,
    }

    if choices.get("cogs_vat_paid", True):
        vat_mode = "included" if choices.get("cogs_vat_included", True) else "excluded"
    else:
        vat_mode = "none"

    return render(
        request,
        "builder/costs.html",
        {
            "job": job,
            "steps": _steps_context(job, Job.Step.COSTS),
            "skus": skus,
            "families": families,
            "family_names": [f["name"] for f in families],
            "cost_rows": parse.get("cost_rows", [])[:60],
            "has_evaluation": bool(parse.get("cost_rows")),
            "total_units": sum(s["units"] for s in skus),
            "vat_mode": vat_mode,
            "preview_json": json.dumps(preview),
        },
    )


# ---------------------------------------------------------------------------
# Step 4 — the decisions the user must state (workflow §1)
# ---------------------------------------------------------------------------

def assumptions(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if redirect_response := _require_ready(job):
        return redirect_response

    choices = services.default_choices(job.parse, job.choices)

    if request.method == "POST":
        scheme = request.POST.get("vat_scheme")
        choices.update(
            {
                "vat_scheme": scheme if scheme in plmodel.VAT_SCHEMES else plmodel.SCHEME_NONE,
                "opex_monthly": round(_to_float(request.POST.get("opex_monthly")), 2),
                "asking_price": round(_to_float(request.POST.get("asking_price")), 2),
                "business_name": (request.POST.get("business_name") or "").strip()[:150],
            }
        )
        job.choices = choices
        job.step = Job.Step.RESULT
        job.save(update_fields=["choices", "step", "updated_at"])
        return redirect("builder:result", job_id=job.id)

    model = services.build_model(job)
    ttm_sales = model.ttm_sum("net_sales")
    input_vat = -model.ttm_sum("input_vat")

    # Show what each scheme would cost across the TTM, so the choice is informed.
    short_names = {
        plmodel.SCHEME_NONE: "Not registered",
        plmodel.SCHEME_FLAT: "Flat rate",
        plmodel.SCHEME_STANDARD: "Standard",
    }
    scheme_preview = []
    for key, label in plmodel.VAT_SCHEMES.items():
        preview = plmodel.build_model(job.parse, {**choices, "vat_scheme": key})
        scheme_preview.append(
            {
                "key": key,
                "label": label,
                "short": short_names.get(key, key),
                "output_vat": -preview.ttm_sum("output_vat"),
                "profit": preview.ttm_sum("net_profit"),
                "selected": choices.get("vat_scheme") == key,
            }
        )

    return render(
        request,
        "builder/assumptions.html",
        {
            "job": job,
            "steps": _steps_context(job, Job.Step.ASSUMPTIONS),
            "choices": choices,
            "ttm_sales": ttm_sales,
            "over_threshold": ttm_sales > 90000,
            "input_vat": input_vat,
            "schemes": scheme_preview,
            "seller": job.parse.get("seller", {}),
        },
    )


# ---------------------------------------------------------------------------
# Step 5 — build, verify, download
# ---------------------------------------------------------------------------

def result(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if redirect_response := _require_ready(job):
        return redirect_response

    model = services.build_model(job)
    try:
        services.build_output(job)
        job.refresh_from_db()
        build_error = ""
    except Exception as exc:
        build_error = str(exc)

    ttm_sales = model.ttm_sum("net_sales")
    ttm_profit = model.ttm_sum("net_profit")
    asking = float(job.choices.get("asking_price") or 0)

    chart = {
        "labels": [m.label for m in model.months],
        "netSales": [m.net_sales for m in model.months],
        "profit": [m.net_profit for m in model.months],
        "units": [m.units for m in model.months],
        "fees": [-m.total_fees for m in model.months],
        "ppc": [-m.total_ppc for m in model.months],
        "cogs": [-m.cogs for m in model.months],
        "inTtm": [m in model.ttm for m in model.months],
    }
    breakdown = [
        {"label": "Referral / selling fees", "value": -model.ttm_sum("referral_incl")},
        {"label": "FBA fulfilment", "value": -model.ttm_sum("fba_incl")},
        {"label": "Storage & inbound", "value": -model.ttm_sum("storage")},
        {"label": "Other Amazon fees", "value": -model.ttm_sum("other_fees")},
        {"label": "Advertising (PPC)", "value": -model.ttm_sum("total_ppc")},
        {"label": "COGS", "value": -model.ttm_sum("cogs")},
        {"label": "Output VAT", "value": -model.ttm_sum("output_vat")},
        {"label": "Off-Amazon OpEx", "value": -model.ttm_sum("opex")},
    ]

    return render(
        request,
        "builder/result.html",
        {
            "job": job,
            "steps": _steps_context(job, Job.Step.RESULT),
            "model": model,
            "months": model.months,
            "checks": model.checks,
            "passed": model.passed,
            "build_error": build_error,
            "period": f"{model.months[0].label} to {model.months[-1].label}",
            "ttm": {
                "net_sales": ttm_sales,
                "fees": model.ttm_sum("total_fees"),
                "ppc": model.ttm_sum("total_ppc"),
                "cogs": model.ttm_sum("cogs"),
                "input_vat": model.ttm_sum("input_vat"),
                "output_vat": model.ttm_sum("output_vat"),
                "opex": model.ttm_sum("opex"),
                "profit": ttm_profit,
                "units": model.ttm_units,
                "margin": (ttm_profit / ttm_sales) if ttm_sales else 0.0,
                "tacos": (-model.ttm_sum("total_ppc") / ttm_sales) if ttm_sales else 0.0,
                "fee_rate": (-model.ttm_sum("total_fees") / ttm_sales) if ttm_sales else 0.0,
                "landed": model.blended_landed_cost,
                "multiple": (asking / ttm_profit) if asking and ttm_profit > 0 else 0.0,
            },
            "asking_price": asking,
            "chart_json": json.dumps(chart),
            "breakdown": [b for b in breakdown if abs(b["value"]) > 0.005],
            "scheme_label": model.scheme_label,
            "blocking_failures": [
                c for c in model.checks if c.severity == "error" and not c.passed
            ],
        },
    )


@require_GET
def download(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    if not job.has_output:
        raise Http404("This workbook has not been built yet.")
    name = job.output_name or "Amazon_UK_PL_FILLED.xlsx"
    content_type = (
        mimetypes.guess_type(name)[0]
        or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(
        open(job.output_path, "rb"), as_attachment=True,
        filename=name, content_type=content_type,
    )


@require_POST
def discard(request, job_id):
    job = get_object_or_404(Job, pk=job_id)
    job.delete()
    messages.success(request, "Job discarded and its uploaded files deleted.")
    return redirect("builder:upload")
