"""
compact_annotation_changes — prune old rows from the change feed.

Run from local cron or a Cloudflare Cron Trigger (via /manage/tasks/). A
client whose cursor predates the new horizon receives ``reset: true`` on its
next poll and performs a full resync (snapshot + fresh cursor).
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.annotations.models import AnnotationChange


class Command(BaseCommand):
    help = "Delete AnnotationChange rows older than CHANGE_HORIZON_DAYS."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="Override horizon in days")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        days = options["days"] or int(getattr(settings, "CHANGE_HORIZON_DAYS", 30))
        cutoff = timezone.now() - timedelta(days=days)
        qs = AnnotationChange.objects.filter(created_at__lt=cutoff)
        count = qs.count()
        if options["dry_run"]:
            self.stdout.write(f"Would delete {count} rows older than {cutoff.isoformat()}.")
            return
        deleted = qs.delete()[0]
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {deleted} change rows older than {days} days. "
            "Clients with older cursors will reset and resync."
        ))
