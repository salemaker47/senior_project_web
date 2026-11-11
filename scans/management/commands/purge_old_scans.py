"""
python manage.py purge_old_scans --days 7

Housekeeping for the demo server. Removes, in this order:

  1. expired sessions (Django's `clearsessions`);
  2. scans older than `--days` days, with their predictions and files;
  3. scans whose session no longer exists (expired, or cleared by the visitor's
     browser and then purged): nobody can open them any more;
  4. folders under media/scans/ that belong to no scan (left by a crash).

`--dry-run` only reports what would be removed. Safe to run from cron.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from scans import services
from scans.models import Scan

# A folder without a scan row is only "stray" once it is this old.
STRAY_GRACE = timedelta(hours=1)


class Command(BaseCommand):
    help = "Delete scans older than --days days (rows and files), scans without a session, and expired sessions."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7,
                            help="delete scans uploaded more than this many days ago (default 7)")
        parser.add_argument("--dry-run", action="store_true",
                            help="report what would be deleted without deleting anything")

    def handle(self, *args, days: int, dry_run: bool, **options):
        if days < 0:
            raise CommandError("--days must be 0 or more")
        now = timezone.now()
        cutoff = now - timedelta(days=days)

        # 1. Expired sessions.
        expired = Session.objects.filter(expire_date__lt=now)
        n_sessions = expired.count()
        if not dry_run:
            expired.delete()

        # 2. Old scans.  3. Scans whose session is gone (expired ones count as gone).
        live_keys = set(
            Session.objects.filter(expire_date__gte=now).values_list("session_key", flat=True)
        )
        old, orphaned = [], []
        for scan in Scan.objects.all():
            if scan.created_at < cutoff:
                old.append(scan)
            elif scan.session_key not in live_keys:
                orphaned.append(scan)
        # 4. Folders without a scan row (judged before anything is deleted).
        known_ids = {str(pk) for pk in Scan.objects.values_list("pk", flat=True)}
        stray = self._stray_folders(known_ids, older_than=now - STRAY_GRACE)

        if not dry_run:
            for scan in old + orphaned:
                services.delete_scan(scan)
            for folder in stray:
                shutil.rmtree(folder, ignore_errors=True)

        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(
            f"{verb}: {len(old)} scan(s) older than {days} day(s), "
            f"{len(orphaned)} scan(s) without a session, "
            f"{len(stray)} stray folder(s), {n_sessions} expired session(s)."
        )

    @staticmethod
    def _stray_folders(known_ids: set, older_than) -> list:
        root = Path(settings.MEDIA_ROOT) / services.SCANS_SUBDIR
        if not root.is_dir():
            return []
        stray = []
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            if folder.name in known_ids:
                continue
            try:
                uuid.UUID(folder.name)          # only ever touch folders we created
            except ValueError:
                continue
            # An upload in progress has its folder a moment before its row.
            if folder.stat().st_mtime >= older_than.timestamp():
                continue
            stray.append(folder)
        return stray
