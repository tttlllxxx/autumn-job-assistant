from app.cli.duplicate_rate import measure_duplicates
from app.models.entities import JobPosting


def job(
    job_id: int,
    external_id: str,
    *,
    url: str,
    title: str = "虚构 RAG 工程师",
    shared: bool = False,
) -> JobPosting:
    return JobPosting(
        id=job_id,
        company="虚构公司",
        source_key="fixture",
        external_job_id=external_id,
        title=title,
        location="上海",
        description="虚构岗位正文",
        normalized_url=url,
        description_hash="a" * 64,
        evidence_metadata={"shared_listing_url": shared},
    )


def test_duplicate_audit_uses_priority_keys_but_allows_shared_listing_urls() -> None:
    listing = "https://example.invalid/campus/jobs"
    distinct_shared = [
        job(1, "J1", url=listing, title="虚构 RAG 工程师", shared=True),
        job(2, "J2", url=listing, title="虚构 安全工程师", shared=True),
    ]
    assert measure_duplicates(distinct_shared) == {
        "status": "passed",
        "jobs": 2,
        "duplicates": 0,
        "duplicate_rate": 0,
        "duplicate_job_ids": [],
    }

    duplicated = distinct_shared + [job(3, "J3", url="https://example.invalid/jobs/3")]
    result = measure_duplicates(duplicated)
    assert result["duplicates"] == 1
    assert result["duplicate_job_ids"] == [3]
    assert result["status"] == "failed"
