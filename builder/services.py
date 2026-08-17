"""Job orchestration: run the parse off the request thread, derive sensible
defaults for every decision the user has to make, and build the workbook.
"""
from __future__ import annotations

import logging
import re
import threading
import traceback

from django.conf import settings
from django.db import connection

from .engine import assemble, model as plmodel, workbook
from .models import Job
from .parsers import ingest

log = logging.getLogger(__name__)

SAFE_NAME = re.compile(r"[^A-Za-z0-9._ ()-]")


def safe_filename(name: str) -> str:
    """Uploads are written to disk, so strip anything path-like from the name."""
    cleaned = SAFE_NAME.sub("_", (name or "").replace("\\", "/").split("/")[-1]).strip()
    return cleaned[:180] or "upload.bin"


def save_uploads(job: Job, files) -> tuple[int, int]:
    """Stream uploaded files into the job workspace.  Returns (count, bytes)."""
    job.ensure_workspace()
    limit = settings.PL_MAX_UPLOAD_BYTES
    total = 0
    saved = 0
    for upload in files:
        destination = job.uploads_dir / safe_filename(upload.name)
        # Never let two uploads with the same name clobber each other.
        stem, suffix, index = destination.stem, destination.suffix, 1
        while destination.exists():
            destination = destination.with_name(f"{stem}_{index}{suffix}")
            index += 1
        with open(destination, "wb") as handle:
            for chunk in upload.chunks():
                total += len(chunk)
                if total > limit:
                    handle.close()
                    destination.unlink(missing_ok=True)
                    raise ValueError(
                        f"Uploads exceed the {limit // (1024 * 1024)} MB limit."
                    )
                handle.write(chunk)
        saved += 1
    return saved, total


def start_processing(job: Job) -> None:
    """Kick the extract+parse off in a background thread.

    Reading ~130 PDFs and CSVs takes the better part of a minute, which is far
    too long to hold an HTTP request open; the wizard polls the job's progress
    instead.
    """
    Job.objects.filter(pk=job.pk).update(
        status=Job.Status.EXTRACTING, progress=0,
        progress_message="Unpacking archives…", error="",
    )
    thread = threading.Thread(target=_process, args=(str(job.pk),), daemon=True)
    thread.start()


def _process(job_id: str) -> None:
    try:
        job = Job.objects.get(pk=job_id)
    except Job.DoesNotExist:
        return

    try:
        def on_classify(done: int, total: int):
            # Classification is the first half of the progress bar.
            job.set_progress(
                5 + int(35 * done / max(total, 1)),
                f"Identifying source files… {done}/{total}",
            )

        extraction = ingest.discover(str(job.uploads_dir), progress=on_classify)

        Job.objects.filter(pk=job.pk).update(
            status=Job.Status.PARSING, progress=40,
            progress_message="Reading Summary PDFs, transactions and invoices…",
        )

        stage_labels = {
            "summary": "Reading Summary PDFs",
            "transactions": "Reading transaction CSVs",
            "business": "Reading Business Reports",
            "invoices": "Reading advertising invoices",
            "evaluation": "Reading the evaluation sheet",
        }

        def on_parse(done: int, total: int, stage: str):
            job.set_progress(
                40 + int(58 * done / max(total, 1)),
                f"{stage_labels.get(stage, 'Reading files')}… {done}/{total}",
            )

        parse = assemble.parse_sources(extraction, progress=on_parse)

        if not parse["month_keys"]:
            raise ValueError(
                "No monthly Summary PDFs were found. The Summary PDF is the "
                "authoritative source every other file reconciles to — upload "
                "Payments ▸ Reports Repository ▸ Date Range Reports ▸ Summary, "
                "one per month."
            )

        job.refresh_from_db()
        job.parse = parse
        job.choices = default_choices(parse, job.choices)
        job.status = Job.Status.READY
        job.step = Job.Step.REVIEW
        job.progress = 100
        job.progress_message = (
            f"Read {len(parse['month_keys'])} months of data from "
            f"{sum(parse['counts'].values())} files."
        )
        job.save(update_fields=[
            "parse", "choices", "status", "step", "progress",
            "progress_message", "updated_at",
        ])

    except Exception as exc:
        log.exception("Job %s failed", job_id)
        Job.objects.filter(pk=job_id).update(
            status=Job.Status.FAILED,
            error=f"{exc}",
            progress_message="Failed",
        )
    finally:
        connection.close()


def default_choices(parse: dict, existing: dict | None = None) -> dict:
    """Pre-fill every decision so the wizard opens on a working model.

    The user can change any of it; these are proposals, not assumptions baked
    into the output.
    """
    existing = existing or {}
    month_keys = parse["month_keys"]
    # The workflow models the trailing 13 months; keep the newest if more exist.
    window = existing.get("window") or month_keys[-13:]

    families = sorted({s["family"] for s in parse["skus"]})
    rates = dict(existing.get("family_rates") or {})
    for family in families:
        rates.setdefault(family, 0.0)

    # If an evaluation sheet was uploaded, seed each family from the landed cost
    # of the best-matching product row in it.
    for family in families:
        if rates.get(family):
            continue
        suggestion = suggest_rate(family, parse)
        if suggestion:
            rates[family] = suggestion

    seller = parse.get("seller", {})
    return {
        "window": window,
        "sku_families": existing.get("sku_families")
        or {s["sku"]: s["family"] for s in parse["skus"]},
        "family_rates": rates,
        "report_month_map": existing.get("report_month_map")
        or parse.get("business_report_map", {}),
        "vat_scheme": plmodel.normalise_scheme(existing),
        "opex_monthly": existing.get("opex_monthly", 0.0),
        "asking_price": existing.get("asking_price", 0.0),
        "business_name": existing.get("business_name")
        or seller.get("legal_name")
        or seller.get("display_name")
        or "",
    }


def suggest_rate(family: str, parse: dict) -> float:
    """Best landed cost for *family* from the uploaded evaluation sheet, if any."""
    rows = parse.get("cost_rows") or []
    if not rows:
        return 0.0
    target = re.sub(r"[^a-z0-9]", "", family.lower())
    if not target:
        return 0.0
    best, best_score = 0.0, 0
    for row in rows:
        name = re.sub(r"[^a-z0-9]", "", (row.get("product") or "").lower())
        if not name or not row.get("landed_cost"):
            continue
        # Longest shared prefix is a good enough match for these free-text sheets.
        score = len(os_commonprefix(name, target))
        if score >= 4 and score > best_score:
            best, best_score = float(row["landed_cost"]), score
    return round(best, 4)


def os_commonprefix(a: str, b: str) -> str:
    limit = min(len(a), len(b))
    index = 0
    while index < limit and a[index] == b[index]:
        index += 1
    return a[:index]


def build_model(job: Job) -> plmodel.PLModel:
    """Apply the job's current choices to its cached parse."""
    if not job.parse:
        raise ValueError("This job has not finished reading its source files yet.")
    choices = default_choices(job.parse, job.choices)
    return plmodel.build_model(job.parse, choices)


def build_output(job: Job) -> str:
    """Write the finished workbook and record its download name."""
    model = build_model(job)
    path = workbook.build_workbook(
        model, settings.PL_TEMPLATE_PATH, str(job.output_path)
    )
    name = re.sub(r"[^A-Za-z0-9]+", "_", job.choices.get("business_name") or "Amazon_UK")
    first, last = model.months[0].label, model.months[-1].label
    Job.objects.filter(pk=job.pk).update(
        output_name=f"{name.strip('_')}_PL_{first}_to_{last}.xlsx"[:200],
        step=Job.Step.RESULT,
    )
    return path
