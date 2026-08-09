from __future__ import annotations

import json
import re

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import JobPosting


def measure_duplicates(jobs: list[JobPosting]) -> dict:
    seen_source_ids: set[tuple[str, str]] = set()
    seen_urls: set[str] = set()
    seen_composites: set[tuple[str, str, str, str]] = set()
    duplicate_ids: set[int] = set()
    for job in sorted(jobs, key=lambda item: item.id):
        source_id = (job.source_key, job.external_job_id)
        normalized_title = re.sub(r"\s+", "", job.title).casefold()
        composite = (
            job.company.casefold(),
            normalized_title,
            (job.location or "").strip().casefold(),
            job.description_hash,
        )
        shared_url = bool(job.evidence_metadata.get("shared_listing_url", False))
        duplicate = source_id in seen_source_ids or composite in seen_composites
        if not shared_url:
            duplicate = duplicate or job.normalized_url in seen_urls
            seen_urls.add(job.normalized_url)
        if duplicate:
            duplicate_ids.add(job.id)
        seen_source_ids.add(source_id)
        seen_composites.add(composite)
    total = len(jobs)
    duplicate_count = len(duplicate_ids)
    return {
        "status": "passed" if total > 0 and duplicate_count / total < 0.01 else "failed",
        "jobs": total,
        "duplicates": duplicate_count,
        "duplicate_rate": duplicate_count / total if total else None,
        "duplicate_job_ids": sorted(duplicate_ids),
    }


def main() -> int:
    with SessionLocal() as db:
        jobs = list(db.scalars(select(JobPosting).order_by(JobPosting.id)).all())
    result = measure_duplicates(jobs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

