from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup


@dataclass
class CrawlContext:
    client: httpx.AsyncClient
    allow_browser: bool = False
    timeout_seconds: float = 20
    max_jobs: int = 500
    request_count: int = 0
    encountered_auth: bool = False


@dataclass(frozen=True)
class JobStub:
    external_job_id: str
    detail_url: str
    title_hint: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobPayload:
    external_job_id: str
    title: str
    department: str | None
    location: str | None
    recruitment_type: str | None
    graduation_year: str | None
    description: str
    application_url: str
    published_at: datetime | None = None
    evidence_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceProbeResult:
    ok: bool
    status: str
    job_count: int
    field_completeness: float
    message: str = ""
    encountered_auth: bool = False


class JobSourceAdapter(Protocol):
    source_key: str
    display_name: str
    parser_version: str

    async def discover(self, context: CrawlContext) -> list[JobStub]: ...
    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload: ...
    async def probe(self, context: CrawlContext) -> SourceProbeResult: ...


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
    query_parts = []
    for part in parsed.query.split("&"):
        if part and not re.match(r"(?i)(utm_|spm=|referer|ref=|share|channel|token)", part):
            query_parts.append(part)
    spa_route = parsed.fragment if parsed.fragment.startswith("/") else ""
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "&".join(sorted(query_parts)), spa_route))


class OfficialSourceAdapter:
    parser_version = "1.1"
    collection_method = "官方网页"
    title_keys = (
        "title", "jobName", "positionName", "name", "postName", "RecruitPostName", "externalJobName", "jobname",
    )
    id_keys = (
        "advertisementId", "jobId", "positionId", "id", "jobCode", "code", "jobUnionId", "RecruitPostId", "PostId",
        "publishId",
    )
    url_keys = ("url", "detailUrl", "applyUrl", "jobUrl", "positionUrl", "PostURL")
    description_keys = (
        "description", "jobDescription", "requirement", "responsibility", "content", "Responsibility", "duty", "qualification",
        "jobDesc", "jobReq", "jobRequire", "workContent", "jobResponsibilities", "jobDemand", "positionDescription",
        "jobSummary",
    )
    location_keys = (
        "location", "workLocation", "city", "address", "workPlace", "LocationName", "workplace", "jobAddress", "cityName",
        "workCity", "jobPlaceName",
    )
    department_keys = (
        "department", "businessUnit", "orgName", "deptName", "BGName", "ComName", "positionDept",
    )
    navigation_titles = frozenset({
        "首页", "职位", "校园招聘", "校招", "社会招聘", "社招", "应届招聘", "实习招聘", "招聘职位",
    })

    def __init__(
        self,
        *,
        source_key: str,
        display_name: str,
        start_url: str,
        allowed_domains: tuple[str, ...],
        detail_tokens: tuple[str, ...],
        default_recruitment_type: str = "校园招聘",
        detail_url_template: str | None = None,
        field_map: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.source_key = source_key
        self.display_name = display_name
        self.start_url = start_url
        self.allowed_domains = allowed_domains
        self.detail_tokens = detail_tokens
        self.default_recruitment_type = default_recruitment_type
        self.detail_url_template = detail_url_template
        self.field_map = field_map or {}
        for category, attribute in (
            ("title", "title_keys"),
            ("id", "id_keys"),
            ("url", "url_keys"),
            ("description", "description_keys"),
            ("location", "location_keys"),
            ("department", "department_keys"),
        ):
            preferred = self.field_map.get(category, ())
            defaults = getattr(self, attribute)
            setattr(self, attribute, tuple(dict.fromkeys((*preferred, *defaults))))

    def _is_official(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)

    def _detail_like(self, url: str) -> bool:
        lowered = url.lower()
        return any(token.lower() in lowered for token in self.detail_tokens)

    @staticmethod
    def _external_id_from_url(url: str) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in ("jobUnionId", "advertisementId", "positionId", "jobId", "id"):
            if query.get(key):
                return query[key][0]
        generic = {"apply", "campus", "detail", "graduate", "job", "jobs", "position", "positions"}
        for segment in reversed([part for part in parsed.path.split("/") if part]):
            if segment.casefold() not in generic:
                return segment
        return normalize_url(url)

    @staticmethod
    def _first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = data.get(key)
            if value not in (None, "", [], {}):
                if isinstance(value, dict):
                    return value.get("name") or value.get("label") or str(value)
                if isinstance(value, list):
                    return "，".join(str(item.get("name", item) if isinstance(item, dict) else item) for item in value)
                return value
        return None

    def _objects(self, node: Any):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from self._objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._objects(value)

    def _stub_from_object(self, data: dict[str, Any]) -> JobStub | None:
        title = self._first(data, self.title_keys)
        external_id = self._first(data, self.id_keys)
        raw_url = self._first(data, self.url_keys)
        if not title or len(str(title)) > 300 or not (external_id or raw_url):
            return None
        has_description = bool(self._first(data, self.description_keys))
        has_department = bool(self._first(data, self.department_keys))
        has_location = bool(self._first(data, self.location_keys))
        explicit_job_id = bool(self._first(data, tuple(
            key for key in self.id_keys if key not in {"id", "code"}
        )))
        looks_like_location_entity = bool({"country", "district", "state"}.intersection(data))
        if looks_like_location_entity and not has_description and not has_department and not explicit_job_id:
            return None
        has_job_fields = has_description or has_location or has_department
        if not raw_url and not has_job_fields:
            return None
        if raw_url:
            url = urljoin(self.start_url, str(raw_url))
        elif self.detail_url_template and external_id:
            url = self.detail_url_template.format(id=external_id)
        else:
            url = self.start_url
        if raw_url and not self._is_official(url):
            return None
        if raw_url and not has_job_fields and not self._detail_like(url):
            return None
        return JobStub(str(external_id or normalize_url(url)), normalize_url(url), str(title).strip(), data)

    @classmethod
    def _navigation_like(cls, title: str) -> bool:
        return re.sub(r"\s+", "", title).casefold() in {
            re.sub(r"\s+", "", item).casefold() for item in cls.navigation_titles
        }

    @staticmethod
    def _plausible_external_id(external_id: str) -> bool:
        return len(external_id) >= 3 or external_id.isdigit()

    @staticmethod
    def _deduplicate_stubs(stubs: list[JobStub]) -> list[JobStub]:
        unique: dict[str, JobStub] = {}
        for stub in stubs:
            current = unique.get(stub.external_job_id)
            if current is None or (stub.raw and not current.raw):
                unique[stub.external_job_id] = stub
        return list(unique.values())

    def parse_document(self, html: str, base_url: str) -> list[JobStub]:
        soup = BeautifulSoup(html, "lxml")
        results: dict[tuple[str, str], JobStub] = {}
        for anchor in soup.select("a[href]"):
            url = normalize_url(urljoin(base_url, str(anchor.get("href"))))
            if self._is_official(url) and self._detail_like(url):
                external_id = self._external_id_from_url(url)
                title = anchor.get_text(" ", strip=True)
                if self._navigation_like(title) or not self._plausible_external_id(external_id):
                    continue
                stub = JobStub(external_id, url, title)
                results[(stub.external_job_id, stub.detail_url)] = stub
        json_nodes: list[Any] = []
        for script in soup.find_all("script"):
            body = script.string or script.get_text()
            if not body or len(body) < 2:
                continue
            candidates = [body.strip()]
            for marker in ("window.__INITIAL_DATA__ =", "window.__INITIAL_STATE__ ="):
                if marker in body:
                    candidates.append(body.split(marker, 1)[1].strip().rstrip(";"))
            for candidate in candidates:
                try:
                    normalized_candidate = re.sub(
                        r":\s*undefined(?=\s*[,}])",
                        ":null",
                        candidate.lstrip(),
                    )
                    node, _ = json.JSONDecoder().raw_decode(normalized_candidate)
                    json_nodes.append(node)
                    break
                except (json.JSONDecodeError, TypeError):
                    continue
        for node in json_nodes:
            for item in self._objects(node):
                stub = self._stub_from_object(item)
                if stub:
                    results[(stub.external_job_id, stub.detail_url)] = stub
        raw = unescape(html).replace("\\/", "/")
        for match in re.findall(r"https?://[^\"'<>\\\s]+", raw):
            url = normalize_url(match.rstrip(",.;)"))
            if self._is_official(url) and self._detail_like(url):
                external_id = self._external_id_from_url(url)
                if self._plausible_external_id(external_id):
                    results[(external_id, url)] = JobStub(external_id, url)
        return list(results.values())

    async def _get(self, context: CrawlContext, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                context.request_count += 1
                response = await context.client.get(url, timeout=context.timeout_seconds, follow_redirects=True)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 429):
                    context.encountered_auth = True
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

    async def _browser_discover(self, context: CrawlContext) -> list[JobStub]:
        if not context.allow_browser:
            return []
        from playwright.async_api import async_playwright
        from app.core.browser import launch_chromium

        captured: list[Any] = []
        async with async_playwright() as playwright:
            browser = await launch_chromium(playwright)
            page = await browser.new_page(user_agent="AutumnJobAssistant/0.1 (personal job search)")

            async def collect(response) -> None:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type and self._is_official(response.url):
                    try:
                        captured.append(await response.json())
                    except Exception:
                        return

            page.on("response", collect)
            page.on("request", lambda _: setattr(context, "request_count", context.request_count + 1))
            await page.goto(self.start_url, wait_until="domcontentloaded", timeout=int(context.timeout_seconds * 1000))
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            html = await page.content()
            await browser.close()
        results = self.parse_document(html, self.start_url)
        for node in captured:
            for item in self._objects(node):
                stub = self._stub_from_object(item)
                if stub:
                    results.append(stub)
        return self._deduplicate_stubs(results)

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        response = await self._get(context, self.start_url)
        results = self.parse_document(response.text, str(response.url))
        has_complete_embedded_job = any(self._payload_from_raw(stub) is not None for stub in results)
        if not results or (context.allow_browser and not has_complete_embedded_job):
            results.extend(await self._browser_discover(context))
        return self._deduplicate_stubs(results)[: context.max_jobs]

    def _payload_from_raw(self, stub: JobStub) -> JobPayload | None:
        data = stub.raw
        if not data:
            return None
        title = self._first(data, self.title_keys) or stub.title_hint
        description_parts = [self._first(data, (key,)) for key in self.description_keys]
        description = "\n".join(str(item) for item in description_parts if item)
        if not title or not description:
            return None
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=str(title).strip(),
            department=str(self._first(data, self.department_keys) or "") or None,
            location=str(self._first(data, self.location_keys) or "") or None,
            recruitment_type=self.default_recruitment_type,
            graduation_year="2027" if "2027" in json.dumps(data, ensure_ascii=False) else None,
            description=str(description).strip(),
            application_url=stub.detail_url,
            evidence_metadata={
                "source_url": self.start_url,
                "parser_version": self.parser_version,
                "shared_listing_url": stub.detail_url == normalize_url(self.start_url),
            },
        )

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        raw_payload = self._payload_from_raw(stub)
        if raw_payload:
            return raw_payload
        response = await self._get(context, stub.detail_url)
        soup = BeautifulSoup(response.text, "lxml")
        title = stub.title_hint or (soup.title.get_text(" ", strip=True) if soup.title else "")
        main = soup.select_one("main") or soup.select_one("article") or soup.body
        description = main.get_text("\n", strip=True) if main else ""
        if (not title or len(description) < 30) and context.allow_browser:
            browser_payload = await self._browser_fetch_detail(stub, context)
            if browser_payload:
                return browser_payload
        if not title or len(description) < 30:
            raise ValueError("官方详情页缺少标题或岗位正文")
        url = normalize_url(str(response.url))
        if not self._is_official(url):
            raise ValueError("申请 URL 不是允许的官方域名")
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title[:255],
            department=None,
            location=None,
            recruitment_type=self.default_recruitment_type,
            graduation_year="2027" if "2027" in description else None,
            description=description,
            application_url=url,
            evidence_metadata={"source_url": stub.detail_url, "parser_version": self.parser_version},
        )

    async def _browser_fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload | None:
        from playwright.async_api import async_playwright
        from app.core.browser import launch_chromium

        captured: list[Any] = []
        async with async_playwright() as playwright:
            browser = await launch_chromium(playwright)
            page = await browser.new_page(user_agent="AutumnJobAssistant/0.1 (personal job search)")

            async def collect(response) -> None:
                if "json" not in response.headers.get("content-type", "") or not self._is_official(response.url):
                    return
                try:
                    captured.append(await response.json())
                except Exception:
                    return

            page.on("response", collect)
            page.on("request", lambda _: setattr(context, "request_count", context.request_count + 1))
            await page.goto(stub.detail_url, wait_until="domcontentloaded", timeout=int(context.timeout_seconds * 1000))
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            await browser.close()
        for node in captured:
            for item in self._objects(node):
                candidate = JobStub(stub.external_job_id, stub.detail_url, stub.title_hint, item)
                payload = self._payload_from_raw(candidate)
                if payload:
                    return payload
        return None

    async def probe(self, context: CrawlContext) -> SourceProbeResult:
        try:
            stubs = await self.discover(context)
            if not stubs:
                return SourceProbeResult(False, "degraded", 0, 0, "官方页面可访问，但未发现可验证岗位")
            payloads: list[JobPayload] = []
            for stub in stubs[:20]:
                try:
                    payloads.append(await self.fetch_detail(stub, context))
                    if len(payloads) >= 3:
                        break
                except (httpx.HTTPError, ValueError):
                    continue
            if not payloads:
                return SourceProbeResult(False, "degraded", len(stubs), 0, "发现候选链接，但详情字段不完整")
            complete = sum(bool(item.title and item.description and item.application_url) for item in payloads) / len(payloads)
            return SourceProbeResult(complete == 1, "healthy" if complete == 1 else "degraded", len(stubs), complete)
        except httpx.HTTPStatusError as exc:
            auth = exc.response.status_code in (401, 403, 429)
            return SourceProbeResult(False, "degraded", 0, 0, f"HTTP {exc.response.status_code}", auth)
        except Exception as exc:
            return SourceProbeResult(False, "error", 0, 0, type(exc).__name__)
