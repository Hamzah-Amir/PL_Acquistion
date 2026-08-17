"""One row per P&L build.

A job owns a workspace directory holding the uploaded (and unpacked) source
files, the cached parse of those files, and the user's decisions.  Keeping the
parse on the row means the wizard's later steps never re-read the ~130 source
files — only the final workbook write depends on the user's answers.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone


class Job(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        EXTRACTING = "extracting", "Unpacking archives"
        PARSING = "parsing", "Reading source files"
        READY = "ready", "Ready for review"
        FAILED = "failed", "Failed"

    class Step(models.TextChoices):
        UPLOAD = "upload", "Upload"
        REVIEW = "review", "Review sources"
        COSTS = "costs", "Cost rates"
        ASSUMPTIONS = "assumptions", "Assumptions"
        RESULT = "result", "Build"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    step = models.CharField(max_length=20, choices=Step.choices, default=Step.UPLOAD)

    progress = models.PositiveSmallIntegerField(default=0)
    progress_message = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)

    # Cached output of builder.engine.assemble.parse_sources.
    parse = models.JSONField(null=True, blank=True)
    # The user's decisions (workflow §1 "Decisions the user must state").
    choices = models.JSONField(default=dict, blank=True)

    output_name = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Job {self.id} ({self.status})"

    # --- filesystem ------------------------------------------------------
    @property
    def workspace(self) -> Path:
        return Path(settings.PL_WORKSPACE_ROOT) / str(self.id)

    @property
    def uploads_dir(self) -> Path:
        return self.workspace / "sources"

    @property
    def output_path(self) -> Path:
        return self.workspace / "Amazon_UK_PL_FILLED.xlsx"

    def ensure_workspace(self) -> Path:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        return self.workspace

    def delete_workspace(self) -> None:
        shutil.rmtree(self.workspace, ignore_errors=True)

    def delete(self, *args, **kwargs):
        self.delete_workspace()
        return super().delete(*args, **kwargs)

    # --- convenience -----------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self.status == self.Status.READY and bool(self.parse)

    @property
    def is_working(self) -> bool:
        return self.status in {self.Status.EXTRACTING, self.Status.PARSING}

    @property
    def has_output(self) -> bool:
        return self.output_path.exists()

    def set_progress(self, percent: int, message: str) -> None:
        Job.objects.filter(pk=self.pk).update(
            progress=max(0, min(100, int(percent))),
            progress_message=message[:255],
            updated_at=timezone.now(),
        )
