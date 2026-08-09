from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup

from app.sources.base import CrawlContext, JobPayload, JobStub, OfficialSourceAdapter, normalize_url


def _plain_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return BeautifulSoup(str(value), "lxml").get_text("\n", strip=True)


def _published_at(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _graduation_year(title: str, description: str) -> str | None:
    match = re.search(r"20(?:2[7-9]|[3-9]\d)", f"{title}\n{description}")
    return match.group(0) if match else None


class AtsSourceAdapter(OfficialSourceAdapter):
    collection_method = "ATS 公开 API"
    ats_name = "ATS"

    def __init__(self, *, api_url: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_url = api_url

    def _payload(
        self,
        stub: JobStub,
        *,
        title: str,
        description: str,
        location: str | None,
        department: str | None,
        recruitment_type: str | None,
        published_at: datetime | None,
    ) -> JobPayload:
        if not title or not description:
            raise ValueError(f"{self.ats_name} 岗位缺少标题或正文")
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title.strip(),
            department=department or None,
            location=location or None,
            recruitment_type=recruitment_type or "招聘官网",
            graduation_year=_graduation_year(title, description),
            description=description.strip(),
            application_url=stub.detail_url,
            published_at=published_at,
            evidence_metadata={
                "source_url": self.api_url,
                "parser_version": self.parser_version,
                "collection_method": self.collection_method,
                "ats": self.ats_name,
            },
        )


class GreenhouseSourceAdapter(AtsSourceAdapter):
    parser_version = "greenhouse-1.0"
    ats_name = "Greenhouse"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        response = await self._get(context, self.api_url)
        jobs = response.json().get("jobs") or []
        results = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            url = str(item.get("absolute_url") or "").strip()
            if job_id and title and url and self._is_official(url):
                results.append(JobStub(job_id, normalize_url(url), title, item))
            if len(results) >= context.max_jobs:
                break
        return results

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        del context
        data = stub.raw
        departments = data.get("departments") or []
        department = "、".join(
            str(item.get("name")) for item in departments if isinstance(item, dict) and item.get("name")
        )
        location = data.get("location") or {}
        return self._payload(
            stub,
            title=str(data.get("title") or stub.title_hint),
            description=_plain_text(data.get("content")),
            location=str(location.get("name") or "") if isinstance(location, dict) else str(location),
            department=department,
            recruitment_type="招聘官网",
            published_at=_published_at(data.get("first_published") or data.get("updated_at")),
        )


class LeverSourceAdapter(AtsSourceAdapter):
    parser_version = "lever-1.0"
    ats_name = "Lever"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        response = await self._get(context, self.api_url)
        jobs = response.json()
        if not isinstance(jobs, list):
            raise ValueError("Lever 接口未返回岗位列表")
        results = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("id") or "").strip()
            title = str(item.get("text") or "").strip()
            url = str(item.get("hostedUrl") or item.get("applyUrl") or "").strip()
            if job_id and title and url and self._is_official(url):
                results.append(JobStub(job_id, normalize_url(url), title, item))
            if len(results) >= context.max_jobs:
                break
        return results

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        del context
        data = stub.raw
        categories = data.get("categories") or {}
        list_text = []
        for section in data.get("lists") or []:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("text") or "").strip()
            content = _plain_text(section.get("content"))
            if content:
                list_text.append("\n".join(part for part in (heading, content) if part))
        description = _plain_text(data.get("descriptionPlain") or data.get("description"))
        description = "\n\n".join(part for part in (description, *list_text) if part)
        return self._payload(
            stub,
            title=str(data.get("text") or stub.title_hint),
            description=description,
            location=str(categories.get("location") or "") if isinstance(categories, dict) else "",
            department=str(categories.get("team") or "") if isinstance(categories, dict) else "",
            recruitment_type=str(categories.get("commitment") or "招聘官网") if isinstance(categories, dict) else None,
            published_at=_published_at(data.get("createdAt")),
        )


class AshbySourceAdapter(AtsSourceAdapter):
    parser_version = "ashby-1.0"
    ats_name = "Ashby"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        response = await self._get(context, self.api_url)
        jobs = response.json().get("jobs") or []
        results = []
        for item in jobs:
            if not isinstance(item, dict):
                continue
            url = str(item.get("jobUrl") or item.get("applyUrl") or "").strip()
            job_id = str(item.get("id") or self._external_id_from_url(url)).strip() if url else ""
            title = str(item.get("title") or "").strip()
            if job_id and title and url and self._is_official(url):
                results.append(JobStub(job_id, normalize_url(url), title, item))
            if len(results) >= context.max_jobs:
                break
        return results

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        del context
        data = stub.raw
        secondary_locations = data.get("secondaryLocations") or []
        locations = [str(data.get("location") or "").strip()]
        locations.extend(
            str(item.get("location") or "").strip()
            for item in secondary_locations
            if isinstance(item, dict)
        )
        location = "、".join(dict.fromkeys(item for item in locations if item))
        department = str(data.get("department") or data.get("team") or "")
        description = _plain_text(data.get("descriptionPlain") or data.get("descriptionHtml"))
        return self._payload(
            stub,
            title=str(data.get("title") or stub.title_hint),
            description=description,
            location=location,
            department=department,
            recruitment_type=str(data.get("employmentType") or "招聘官网"),
            published_at=_published_at(data.get("publishedAt")),
        )


class MokaSourceAdapter(AtsSourceAdapter):
    parser_version = "moka-1.0"
    ats_name = "Moka"

    def __init__(self, *, organization: str, site_id: str | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.organization = organization
        self.site_id = site_id

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        results: list[JobStub] = []
        page_size = min(context.max_jobs, 100)
        offset = 0
        while len(results) < context.max_jobs:
            query: dict[str, str | int] = {
                "mode": "campus",
                "status": "open",
                "limit": page_size,
                "offset": offset,
            }
            if self.site_id:
                query["siteId"] = self.site_id
            response = await self._get(context, f"{self.api_url}?{urlencode(query)}")
            body = response.json()
            jobs = body.get("jobs") or []
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("id") or "").strip()
                title = str(item.get("title") or "").strip()
                if not job_id or not title:
                    continue
                base_url = self.start_url.split("#", 1)[0].rstrip("/")
                detail_url = normalize_url(f"{base_url}#/job/{job_id}/apply")
                results.append(JobStub(job_id, detail_url, title, item))
                if len(results) >= context.max_jobs:
                    break
            total = int(body.get("total") or len(jobs))
            offset += len(jobs)
            if not jobs or offset >= total:
                break
        return results

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        del context
        data = stub.raw
        locations = []
        for item in data.get("locations") or []:
            if isinstance(item, dict):
                value = item.get("name") or item.get("city")
            else:
                value = item
            if value:
                locations.append(str(value))
        department = data.get("department") or data.get("zhineng") or {}
        department_name = department.get("name") if isinstance(department, dict) else department
        return self._payload(
            stub,
            title=str(data.get("title") or stub.title_hint),
            description=_plain_text(data.get("description")),
            location="、".join(dict.fromkeys(locations)),
            department=str(department_name or ""),
            recruitment_type=f"校园招聘 · {data.get('commitment') or '职位'}",
            published_at=_published_at(data.get("publishedAt") or data.get("createdAt")),
        )


def build_ats_adapter(
    *,
    source_key: str,
    display_name: str,
    start_url: str,
    field_map: dict[str, tuple[str, ...]] | None = None,
) -> AtsSourceAdapter | None:
    parsed = urlparse(start_url)
    host = (parsed.hostname or "").casefold()
    parts = [part for part in parsed.path.split("/") if part]

    moka_match = re.search(r"/(campus_apply)/([^/?#]+)(?:/([^/?#]+))?", parsed.path)
    if moka_match:
        organization = moka_match.group(2)
        site_id = moka_match.group(3)
        return MokaSourceAdapter(
            source_key=source_key,
            display_name=display_name,
            start_url=start_url,
            api_url=f"https://api.mokahr.com/api-platform/v1/jobs/{organization}",
            organization=organization,
            site_id=site_id,
            allowed_domains=tuple(dict.fromkeys((host, "app.mokahr.com", "api.mokahr.com"))),
            detail_tokens=("/job/",),
            field_map=field_map,
        )

    greenhouse_hosts = {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "job-boards.eu.greenhouse.io",
        "boards-api.greenhouse.io",
    }
    if host in greenhouse_hosts:
        if host == "boards-api.greenhouse.io":
            board = parts[2] if len(parts) >= 4 and parts[:2] == ["v1", "boards"] else ""
        else:
            board = parts[0] if parts else ""
        if board:
            return GreenhouseSourceAdapter(
                source_key=source_key,
                display_name=display_name,
                start_url=start_url,
                api_url=f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
                allowed_domains=tuple(greenhouse_hosts),
                detail_tokens=("/jobs/",),
                field_map=field_map,
            )

    lever_match = re.fullmatch(r"jobs\.(?:(eu)\.)?lever\.co", host)
    api_lever_match = re.fullmatch(r"api\.(?:(eu)\.)?lever\.co", host)
    match = lever_match or api_lever_match
    if match and parts:
        organization = parts[2] if api_lever_match and len(parts) >= 3 and parts[:2] == ["v0", "postings"] else parts[0]
        if organization:
            region = "eu." if match.group(1) else ""
            return LeverSourceAdapter(
                source_key=source_key,
                display_name=display_name,
                start_url=start_url,
                api_url=f"https://api.{region}lever.co/v0/postings/{organization}",
                allowed_domains=("jobs.lever.co", "jobs.eu.lever.co", "api.lever.co", "api.eu.lever.co"),
                detail_tokens=("/",),
                field_map=field_map,
            )

    if host in {"jobs.ashbyhq.com", "api.ashbyhq.com"}:
        if host == "api.ashbyhq.com":
            board = parts[2] if len(parts) >= 3 and parts[:2] == ["posting-api", "job-board"] else ""
        else:
            board = parts[0] if parts else ""
        if board:
            return AshbySourceAdapter(
                source_key=source_key,
                display_name=display_name,
                start_url=start_url,
                api_url=f"https://api.ashbyhq.com/posting-api/job-board/{board}",
                allowed_domains=("jobs.ashbyhq.com", "api.ashbyhq.com"),
                detail_tokens=("/",),
                field_map=field_map,
            )

    return None
