"""Unpack whatever the user uploaded and work out what each file is.

Users upload nested zips (a zip of zips of zips), so extraction recurses.  File
kind is decided by content, not by name — Amazon's export filenames are not
reliable (Business Reports are named only by download date, PPC invoices by an
opaque document id).
"""
from __future__ import annotations

import os
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

MAX_ZIP_DEPTH = 6
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # refuse absurd zip bombs
SKIP_DIRS = {"__MACOSX"}

KIND_SUMMARY = "summary_pdf"
KIND_TRANSACTION = "transaction_csv"
KIND_BUSINESS = "business_report"
KIND_INVOICE = "ppc_invoice"
KIND_EVALUATION = "evaluation"
KIND_UNKNOWN = "unknown"

KIND_LABELS = {
    KIND_SUMMARY: "Summary PDF",
    KIND_TRANSACTION: "Transaction CSV",
    KIND_BUSINESS: "Business Report",
    KIND_INVOICE: "PPC invoice",
    KIND_EVALUATION: "Evaluation / SellerBoard",
    KIND_UNKNOWN: "Unrecognised",
}


@dataclass
class DiscoveredFile:
    path: str
    relative: str
    kind: str = KIND_UNKNOWN
    note: str = ""


@dataclass
class Extraction:
    root: str
    files: list[DiscoveredFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[DiscoveredFile]:
        return [f for f in self.files if f.kind == kind]


def _safe_join(root: str, name: str) -> str | None:
    """Guard against zip path traversal (``../``, absolute members)."""
    target = os.path.normpath(os.path.join(root, name))
    if not os.path.abspath(target).startswith(os.path.abspath(root) + os.sep):
        return None
    return target


def extract_archives(root: str) -> list[str]:
    """Recursively expand every zip found under *root*, in place."""
    warnings: list[str] = []
    total_bytes = 0

    for depth in range(MAX_ZIP_DEPTH):
        archives = [
            os.path.join(dirpath, name)
            for dirpath, _, filenames in os.walk(root)
            for name in filenames
            if name.lower().endswith(".zip")
        ]
        if not archives:
            break
        for archive in archives:
            target = os.path.join(
                os.path.dirname(archive),
                os.path.splitext(os.path.basename(archive))[0] + "__unzipped",
            )
            try:
                with zipfile.ZipFile(archive) as zf:
                    for member in zf.infolist():
                        if member.is_dir():
                            continue
                        parts = member.filename.replace("\\", "/").split("/")
                        if any(p in SKIP_DIRS for p in parts) or parts[-1].startswith("._"):
                            continue
                        total_bytes += member.file_size
                        if total_bytes > MAX_TOTAL_BYTES:
                            raise ValueError("Uploaded archives expand to over 2 GB")
                        destination = _safe_join(target, member.filename)
                        if destination is None:
                            warnings.append(
                                f"Skipped unsafe path in {os.path.basename(archive)}: "
                                f"{member.filename}"
                            )
                            continue
                        os.makedirs(os.path.dirname(destination), exist_ok=True)
                        with zf.open(member) as src, open(destination, "wb") as dst:
                            dst.write(src.read())
            except zipfile.BadZipFile:
                warnings.append(f"{os.path.basename(archive)} is not a readable zip")
            finally:
                try:
                    os.remove(archive)
                except OSError:
                    pass
    else:
        warnings.append(f"Stopped unpacking after {MAX_ZIP_DEPTH} levels of nesting")

    return warnings


def _sniff_pdf(path: str) -> tuple[str, str]:
    """Summary PDFs and PPC invoices are both PDFs; read the first page."""
    from . import pdftext

    text = pdftext.first_page_text(path)
    if not text.strip():
        return KIND_UNKNOWN, "no extractable text (scanned or image-only PDF?)"

    if "Account activity from" in text and "Summaries" in text:
        return KIND_SUMMARY, ""
    if "Tax Invoice" in text or "Invoice Number" in text:
        return KIND_INVOICE, ""
    return KIND_UNKNOWN, "PDF is neither a Summary nor an advertising invoice"


def _sniff_csv(path: str) -> tuple[str, str]:
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            head = "".join(next(handle, "") for _ in range(40)).lower()
    except OSError as exc:
        return KIND_UNKNOWN, str(exc)

    if "date/time" in head and "settlement id" in head:
        return KIND_TRANSACTION, ""
    if "(child) asin" in head or ("sessions" in head and "units ordered" in head):
        return KIND_BUSINESS, ""
    if "campaign name" in head or "impressions" in head:
        return KIND_UNKNOWN, "advertising campaign report — not used by this model"
    return KIND_UNKNOWN, "CSV header not recognised"


def classify(path: str) -> tuple[str, str]:
    extension = os.path.splitext(path)[1].lower()
    if extension == ".pdf":
        return _sniff_pdf(path)
    if extension == ".csv":
        return _sniff_csv(path)
    if extension in {".xlsx", ".xlsm"}:
        return KIND_EVALUATION, ""
    return KIND_UNKNOWN, f"{extension or 'no extension'} is not a supported file type"


def discover(root: str, progress=None) -> Extraction:
    """Unpack archives under *root*, then classify every file found.

    Classification is I/O- and parse-bound over ~130 files, so it runs on a
    thread pool; *progress* is called as ``progress(done, total)``.
    """
    extraction = Extraction(root=root)
    extraction.warnings.extend(extract_archives(root))

    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if not name.startswith("._"):
                paths.append(os.path.join(dirpath, name))

    results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=min(8, (os.cpu_count() or 2) * 2)) as pool:
        futures = {pool.submit(classify, p): p for p in paths}
        for done, future in enumerate(as_completed(futures), start=1):
            path = futures[future]
            try:
                results[path] = future.result()
            except Exception as exc:
                results[path] = (KIND_UNKNOWN, f"failed to read ({exc})")
            if progress:
                progress(done, len(paths))

    for path in paths:
        kind, note = results.get(path, (KIND_UNKNOWN, "not inspected"))
        extraction.files.append(
            DiscoveredFile(
                path=path,
                relative=os.path.relpath(path, root).replace("\\", "/"),
                kind=kind,
                note=note,
            )
        )

    return extraction
