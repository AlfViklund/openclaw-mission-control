"""Evidence retention and cleanup service."""

from __future__ import annotations

import gzip
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

from app.core.time import utcnow

EVIDENCE_DIR = Path(__file__).resolve().parents[4] / "storage" / "evidence"
ARTIFACT_DIR = Path(__file__).resolve().parents[4] / "storage" / "artifacts"
DEFAULT_RETENTION_DAYS = 30


def cleanup_old_evidence(retention_days: int = DEFAULT_RETENTION_DAYS) -> dict:
    """Archive evidence files older than retention period.

    Returns dict with counts of archived and skipped files.
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    archived = 0
    skipped = 0

    for evidence_dir in [EVIDENCE_DIR, ARTIFACT_DIR]:
        if not evidence_dir.exists():
            continue

        for item in evidence_dir.rglob("*"):
            if item.is_file():
                try:
                    mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff:
                        archive_path = item.with_suffix(item.suffix + ".gz")
                        if archive_path.exists():
                            archive_path = item.with_name(f"{item.name}.{int(time.time())}.gz")
                        with item.open("rb") as f_in:
                            with gzip.open(archive_path, "wb") as f_out:
                                shutil.copyfileobj(f_in, f_out)
                        item.unlink()
                        archived += 1
                except (OSError, ValueError):
                    skipped += 1

    return {
        "archived": archived,
        "skipped": skipped,
        "cutoff": cutoff.isoformat(),
        "retention_days": retention_days,
    }
