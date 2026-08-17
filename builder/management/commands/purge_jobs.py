"""Delete old jobs and the uploaded seller data they hold.

Uploads contain a seller's full financial history, so they should not sit on
disk indefinitely.  Run this on a schedule (Task Scheduler / cron).
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from builder.models import Job


class Command(BaseCommand):
    help = "Delete jobs (and their uploaded files) older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=settings.PL_JOB_RETENTION_HOURS,
            help="Retention window in hours (default: PL_JOB_RETENTION_HOURS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be deleted without deleting it.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["hours"])
        stale = Job.objects.filter(created_at__lt=cutoff)
        count = stale.count()

        if options["dry_run"]:
            for job in stale:
                self.stdout.write(f"would delete {job.id} (created {job.created_at:%Y-%m-%d %H:%M})")
            self.stdout.write(self.style.WARNING(f"{count} job(s) would be deleted."))
            return

        for job in stale:
            job.delete()  # also removes the workspace directory
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} job(s) older than {options['hours']}h."))
