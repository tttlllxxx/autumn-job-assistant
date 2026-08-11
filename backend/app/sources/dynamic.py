from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from app.sources.base import CrawlContext, JobPayload, JobStub, OfficialSourceAdapter, normalize_url


class PublicJsonSourceAdapter(OfficialSourceAdapter):
    collection_method = "官方 API"

    async def _post_json(self, context: CrawlContext, url: str, data: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                context.request_count += 1
                response = await context.client.post(url, json=data, timeout=context.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("官方接口未返回 JSON 对象")
                if payload.get("success") is False:
                    raise ValueError(str(payload.get("message") or payload.get("errorMsg") or "官方接口返回失败"))
                return payload
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
                last_error = exc
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 429):
                    context.encountered_auth = True
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error


class TencentSourceAdapter(PublicJsonSourceAdapter):
    """Tencent campus jobs only; the global Workday feed is out of scope."""

    parser_version = "2.0"
    mapping_api_url = "https://join.qq.com/api/v1/position/getProjectMapping"
    search_api_url = "https://join.qq.com/api/v1/position/searchPosition"
    detail_api_url = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId"
    legacy_api_url = "https://careers.tencent.com/tencentcareer/api/post/Query"
    detail_url = "https://join.qq.com/post_detail.html?postid={id}"
    target_markers = ("2027", "27届")
    campus_markers = ("校园", "校招", "应届", "毕业生", "实习")
    foreign_markers = (
        "united states", "california", "palo alto", "los angeles", "new york",
        "singapore", "canada", "japan", "korea", "美国", "加拿大", "新加坡", "日本", "韩国",
    )

    def _is_target_record(self, data: dict[str, Any], detail_url: str = "") -> bool:
        raw_url = str(self._first(data, self.url_keys) or detail_url).casefold()
        if "myworkdayjobs.com" in raw_url:
            return False
        text = json.dumps(data, ensure_ascii=False, default=str).casefold()
        location = str(
            self._first(data, ("LocationName", "workCities", "workCityList", "location")) or ""
        ).casefold()
        if any(marker in location for marker in self.foreign_markers):
            return False
        return any(marker in text for marker in self.target_markers) and any(
            marker in text for marker in self.campus_markers
        )

    def _stub_from_object(self, data: dict[str, Any]) -> JobStub | None:
        stub = super()._stub_from_object(data)
        if stub is None or not self._is_target_record(data, stub.detail_url):
            return None
        return stub

    def _api_stub(self, data: dict[str, Any]) -> JobStub | None:
        if not self._is_target_record(data):
            return None
        job_id = str(self._first(data, self.id_keys) or "").strip()
        title = str(self._first(data, self.title_keys) or "").strip()
        if not job_id or not title:
            return None
        url = normalize_url(self.detail_url.format(id=job_id))
        return JobStub(job_id, url, title, data)

    @staticmethod
    def _target_project_mappings(groups: list[Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            for project in group.get("subProjectList") or []:
                if not isinstance(project, dict):
                    continue
                project_name = str(project.get("projectName") or "")
                is_graduate_project = int(project.get("recruitType") or 0) == 1 or "应届生" in project_name
                if not is_graduate_project or "实习" in project_name:
                    continue
                target_text = " ".join(str(project.get(key) or "") for key in (
                    "recruitYear", "projectName", "recruitRangDesc",
                ))
                if "2027" in target_text and project.get("mappingId") is not None:
                    results.append(project)
        return results

    async def _discover_join_api(self, context: CrawlContext) -> list[JobStub]:
        mapping_response = await self._get(context, self.mapping_api_url)
        mapping_payload = mapping_response.json()
        projects = self._target_project_mappings(mapping_payload.get("data") or [])
        results: dict[str, JobStub] = {}
        page_size = min(context.max_jobs, 100)
        for project in projects:
            page = 1
            while len(results) < context.max_jobs:
                payload = await self._post_json(context, self.search_api_url, {
                    "projectIdList": [],
                    "projectMappingIdList": [project["mappingId"]],
                    "keyword": "",
                    "bgList": [],
                    "workCountryType": 0,
                    "workCityList": [],
                    "recruitCityList": [],
                    "positionFidList": [],
                    "pageIndex": page,
                    "pageSize": page_size,
                })
                data = payload.get("data") or {}
                items = data.get("positionList") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    job_id = str(item.get("postId") or "").strip()
                    title = str(item.get("positionTitle") or "").strip()
                    if not job_id or not title:
                        continue
                    raw = {
                        **item,
                        "_target_graduation_year": "2027",
                        "_target_recruitment_type": str(project.get("projectName") or "校园招聘"),
                    }
                    url = normalize_url(self.detail_url.format(id=job_id))
                    results[job_id] = JobStub(job_id, url, title, raw)
                    if len(results) >= context.max_jobs:
                        break
                total = int(data.get("count") or len(items))
                if not items or page * page_size >= total:
                    break
                page += 1
        return list(results.values())

    async def _discover_legacy_api(self, context: CrawlContext) -> list[JobStub]:
        results: dict[str, JobStub] = {}
        page_size = min(context.max_jobs, 100)
        for keyword in self.target_markers:
            page = 1
            while len(results) < context.max_jobs:
                query = urlencode({
                    "keyword": keyword,
                    "pageIndex": page,
                    "pageSize": page_size,
                    "language": "zh-cn",
                    "area": "cn",
                })
                response = await self._get(context, f"{self.legacy_api_url}?{query}")
                payload = response.json()
                data = payload.get("Data") or payload.get("data") or {}
                items = data.get("Posts") or data.get("posts") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    stub = self._api_stub(item)
                    if stub is not None:
                        results[stub.external_job_id] = stub
                        if len(results) >= context.max_jobs:
                            break
                total = int(data.get("Count") or data.get("count") or len(items))
                if not items or page * page_size >= total:
                    break
                page += 1
        return list(results.values())

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        errors: list[Exception] = []
        if urlparse(self.start_url).hostname == "join.qq.com":
            try:
                jobs = await self._discover_join_api(context)
                if jobs:
                    return jobs[: context.max_jobs]
            except Exception as exc:
                errors.append(exc)
        try:
            page_jobs = await super().discover(context)
            if page_jobs:
                return page_jobs[: context.max_jobs]
        except Exception as exc:
            errors.append(exc)
        try:
            return (await self._discover_legacy_api(context))[: context.max_jobs]
        except Exception as exc:
            errors.append(exc)
        if errors:
            raise errors[-1]
        return []

    def _payload_from_raw(self, stub: JobStub) -> JobPayload | None:
        data = stub.raw
        if not data or not self._is_target_record(data, stub.detail_url):
            return None
        title = str(self._first(data, self.title_keys) or stub.title_hint).strip()
        duties = str(
            self._first(data, ("desc", "topicDetail", "Responsibility", "responsibility", "description")) or ""
        ).strip()
        requirements = str(
            self._first(
                data,
                ("request", "topicRequirement", "Requirement", "Qualification", "requirement", "qualification"),
            ) or ""
        ).strip()
        if not title or not (duties or requirements):
            return None
        description = "\n\n".join(
            part for part in (
                f"工作职责\n{duties}" if duties else "",
                f"任职要求\n{requirements}" if requirements else "",
            ) if part
        )
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title,
            department=str(self._first(data, ("tidName", "bgs", *self.department_keys)) or "") or None,
            location=str(self._first(data, ("workCityList", "workCities", *self.location_keys)) or "") or None,
            recruitment_type=str(
                data.get("_target_recruitment_type") or data.get("recruitLabelName") or "校园招聘"
            ),
            graduation_year="2027",
            description=description,
            application_url=stub.detail_url,
            evidence_metadata={"source_url": self.detail_api_url, "parser_version": self.parser_version},
        )

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        payload = self._payload_from_raw(stub)
        if payload is None and stub.raw.get("_target_graduation_year") == "2027":
            query = urlencode({"postId": stub.external_job_id})
            response = await self._get(context, f"{self.detail_api_url}?{query}")
            body = response.json()
            detail = body.get("data") or {}
            if isinstance(detail, dict):
                raw = {**stub.raw, **detail}
                payload = self._payload_from_raw(JobStub(
                    stub.external_job_id,
                    stub.detail_url,
                    stub.title_hint,
                    raw,
                ))
        if payload is None:
            raise ValueError("腾讯岗位不是中国区 2027 届校园招聘岗位，或正文不完整")
        return payload


class AntSourceAdapter(PublicJsonSourceAdapter):
    parser_version = "2.0"
    api_url = "https://hrcareersweb.antgroup.com/api/campus/position/search"

    @staticmethod
    def _is_2027_graduate(item: dict[str, Any]) -> bool:
        batch = str(item.get("batchName") or "")
        title = str(item.get("name") or "")
        graduation_to = str((item.get("graduationTime") or {}).get("to") or "")
        return item.get("batchType") == "graduate" and (
            "2027" in batch or "27届" in title or graduation_to.startswith("2027")
        )

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        results: list[JobStub] = []
        page = 1
        # The current Ant campus API rejects page sizes above 10 even though
        # the generic list UI exposes a larger total count.
        page_size = 10
        while len(results) < context.max_jobs:
            payload = await self._post_json(
                context,
                self.api_url,
                {
                    "channel": "campus_group_official_site",
                    "language": "zh",
                    "regions": "",
                    "subCategories": "",
                    "bgCode": "",
                    "key": "",
                    "pageIndex": page,
                    "pageSize": page_size,
                    "recruitType": [],
                    "batchIds": [],
                },
            )
            items = payload.get("content") or []
            for item in items:
                if not isinstance(item, dict) or not self._is_2027_graduate(item):
                    continue
                job_id = str(item.get("id") or "")
                if not job_id:
                    continue
                detail_url = f"https://talent.antgroup.com/campus-position?positionId={job_id}"
                results.append(JobStub(job_id, detail_url, str(item.get("name") or ""), item))
                if len(results) >= context.max_jobs:
                    break
            total = int(payload.get("totalCount") or len(items))
            if not items or page * page_size >= total:
                break
            page += 1
        return results

    def _payload_from_raw(self, stub: JobStub) -> JobPayload | None:
        data = stub.raw
        title = str(data.get("name") or stub.title_hint).strip()
        description = str(data.get("description") or "").strip()
        requirement = str(data.get("requirement") or "").strip()
        if not title or not (description or requirement):
            return super()._payload_from_raw(stub)
        published_at = None
        if data.get("publishTime"):
            try:
                published_at = datetime.fromisoformat(str(data["publishTime"]))
            except ValueError:
                pass
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title,
            department=str(data.get("categoryName") or "") or None,
            location="、".join(str(item) for item in data.get("workLocations") or []) or None,
            recruitment_type=str(data.get("batchTypeDesc") or "应届生"),
            graduation_year="2027",
            description="\n\n".join(
                part for part in (
                    f"工作职责\n{description}" if description else "",
                    f"任职要求\n{requirement}" if requirement else "",
                ) if part
            ),
            application_url=stub.detail_url,
            published_at=published_at,
            evidence_metadata={"source_url": self.api_url, "parser_version": self.parser_version},
        )


class AlibabaSourceAdapter(PublicJsonSourceAdapter):
    parser_version = "2.0"
    batch_api_url = "https://campus-talent.alibaba.com/searchCondition/listBatch"
    search_api_url = "https://campus-talent.alibaba.com/position/search"
    detail_url = "https://campus-talent.alibaba.com/campus/position/{id}"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        await self._get(context, self.start_url)
        csrf = context.client.cookies.get("XSRF-TOKEN")
        if not csrf:
            raise ValueError("阿里巴巴校招页未返回 CSRF 令牌")
        batches = await self._post_json(context, f"{self.batch_api_url}?_csrf={csrf}", {})
        graduate_batches = (batches.get("content") or {}).get("graduate") or []
        target_batches = [
            item for item in graduate_batches
            if isinstance(item, dict) and "2027" in f"{item.get('name', '')}{item.get('remark', '')}"
        ]
        results: dict[str, JobStub] = {}
        page_size = min(context.max_jobs, 100)
        for batch in target_batches:
            page = 1
            while len(results) < context.max_jobs:
                response = await self._post_json(
                    context,
                    f"{self.search_api_url}?_csrf={csrf}",
                    {
                        "batchId": batch["id"],
                        "pageIndex": page,
                        "pageSize": page_size,
                        "channel": "campus_group_official_site",
                        "language": "zh",
                    },
                )
                content = response.get("content") or {}
                items = content.get("datas") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    job_id = str(item.get("id") or "").strip()
                    title = str(item.get("name") or "").strip()
                    if not job_id or not title:
                        continue
                    raw = {
                        **item,
                        "_target_graduation_year": "2027",
                        "_target_recruitment_type": str(batch.get("name") or "校园招聘"),
                    }
                    results[job_id] = JobStub(
                        job_id,
                        normalize_url(self.detail_url.format(id=job_id)),
                        title,
                        raw,
                    )
                    if len(results) >= context.max_jobs:
                        break
                total = int(content.get("totalCount") or len(items))
                if not items or page * page_size >= total:
                    break
                page += 1
        return list(results.values())

    def _payload_from_raw(self, stub: JobStub) -> JobPayload | None:
        data = stub.raw
        title = str(data.get("name") or stub.title_hint).strip()
        duties = str(data.get("description") or "").strip()
        requirements = str(data.get("requirement") or "").strip()
        if not title or not (duties or requirements):
            return None
        locations = data.get("workLocations") or []
        location = "、".join(str(item) for item in locations) if isinstance(locations, list) else str(locations)
        published_at = None
        timestamp = data.get("publishTime")
        if isinstance(timestamp, (int, float)):
            published_at = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title,
            department=str(data.get("categoryName") or "") or None,
            location=location or None,
            recruitment_type=str(data.get("_target_recruitment_type") or "校园招聘"),
            graduation_year=str(data.get("_target_graduation_year") or "2027"),
            description="\n\n".join(
                part for part in (
                    f"工作职责\n{duties}" if duties else "",
                    f"任职要求\n{requirements}" if requirements else "",
                ) if part
            ),
            application_url=stub.detail_url,
            published_at=published_at,
            evidence_metadata={"source_url": self.search_api_url, "parser_version": self.parser_version},
        )


class KuaishouSourceAdapter(PublicJsonSourceAdapter):
    parser_version = "2.0"
    api_url = "https://campus.kuaishou.cn/recruit/campus/e/api/v1/open/positions/simple"
    detail_url = "https://campus.kuaishou.cn/recruit/campus/e/#/campus/job-info/{id}"
    project_code = "20271779425607"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        results: dict[str, JobStub] = {}
        page = 1
        page_size = 10
        while len(results) < context.max_jobs:
            payload = await self._post_json(context, self.api_url, {
                "recruitSubProjectCodes": [self.project_code],
                "pageSize": page_size,
                "pageNum": page,
            })
            data = payload.get("result") or {}
            items = data.get("list") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("id") or "").strip()
                title = str(item.get("name") or "").strip()
                if not job_id or not title:
                    continue
                results[job_id] = JobStub(
                    job_id,
                    normalize_url(self.detail_url.format(id=job_id)),
                    title,
                    item,
                )
                if len(results) >= context.max_jobs:
                    break
            total_pages = int(data.get("pages") or page)
            if not items or page >= total_pages:
                break
            page += 1
        return list(results.values())

    def _payload_from_raw(self, stub: JobStub) -> JobPayload | None:
        data = stub.raw
        title = str(data.get("name") or stub.title_hint).strip()
        duties = str(data.get("description") or "").strip()
        requirements = str(data.get("positionDemand") or "").strip()
        if not title or not (duties or requirements):
            return None
        location = "、".join(
            str(item.get("name") or item.get("label") or "")
            for item in data.get("workLocationDicts") or []
            if isinstance(item, dict) and (item.get("name") or item.get("label"))
        )
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title,
            department=str(data.get("departmentName") or "") or None,
            location=location or str(data.get("workLocationCode") or "") or None,
            recruitment_type="校园招聘",
            graduation_year="2027",
            description="\n\n".join(
                part for part in (
                    f"工作职责\n{duties}" if duties else "",
                    f"任职要求\n{requirements}" if requirements else "",
                ) if part
            ),
            application_url=stub.detail_url,
            evidence_metadata={"source_url": self.api_url, "parser_version": self.parser_version},
        )


class MeituanSourceAdapter(PublicJsonSourceAdapter):
    parser_version = "2.0"
    api_url = "https://zhaopin.meituan.com/api/official/job/getJobList"
    detail_url = "https://zhaopin.meituan.com/web/position/detail?jobUnionId={id}"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        results: list[JobStub] = []
        page = 1
        page_size = 10
        while len(results) < context.max_jobs:
            payload = await self._post_json(context, self.api_url, {
                "page": {"pageNo": page, "pageSize": page_size},
                "jobShareType": "1",
                "keywords": "",
                "cityList": [],
                "department": [],
                "jfJgList": [{"code": "11001", "subCode": []}],
                "jobType": [{"code": "1", "subCode": ["1"]}, {"code": "4", "subCode": ["1"]}],
                "typeCode": ["1", "1"],
                "specialCode": ["1", "3"],
                "u_query_id": "",
                "r_query_id": "",
            })
            data = payload.get("data") or {}
            items = data.get("list") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("jobUnionId") or "").strip()
                title = str(item.get("name") or "").strip()
                if not job_id or not title or item.get("jobStatus") not in (None, "000"):
                    continue
                results.append(JobStub(
                    job_id,
                    normalize_url(self.detail_url.format(id=job_id)),
                    title,
                    item,
                ))
                if len(results) >= context.max_jobs:
                    break
            page_info = data.get("page") or {}
            total_pages = int(page_info.get("totalPage") or page)
            if not items or page >= total_pages:
                break
            page += 1
        return results

    def _payload_from_raw(self, stub: JobStub) -> JobPayload | None:
        data = stub.raw
        title = str(data.get("name") or stub.title_hint).strip()
        duties = str(
            data.get("jobDuty") or data.get("desc") or data.get("responsibility") or data.get("description") or ""
        ).strip()
        requirements = str(data.get("jobRequirement") or data.get("requirement") or "").strip()
        if not title or not (duties or requirements):
            return None
        cities = "、".join(
            str(item.get("name"))
            for item in data.get("cityList") or []
            if isinstance(item, dict) and item.get("name")
        )
        departments = "、".join(
            str(item.get("name"))
            for item in data.get("department") or []
            if isinstance(item, dict) and item.get("name")
        )
        published_at = None
        timestamp = data.get("firstPostTime") or data.get("refreshTime")
        if isinstance(timestamp, (int, float)):
            published_at = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
        description = "\n\n".join(
            part for part in (
                f"工作职责\n{duties}" if duties else "",
                f"任职要求\n{requirements}" if requirements else "",
            ) if part
        )
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title,
            department=departments or str(data.get("jobFamilyGroup") or data.get("jobFamily") or "") or None,
            location=cities or None,
            recruitment_type="校园招聘",
            graduation_year="2027" if "2027" in f"{title}\n{description}" else None,
            description=description,
            application_url=stub.detail_url,
            published_at=published_at,
            evidence_metadata={"source_url": self.api_url, "parser_version": self.parser_version},
        )

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        del context
        payload = self._payload_from_raw(stub)
        if payload is None:
            raise ValueError("美团校园岗位缺少职责和任职要求")
        return payload


class MihoyoSourceAdapter(PublicJsonSourceAdapter):
    parser_version = "2.0"
    list_api_url = "https://ats.openout.mihoyo.com/ats-portal/v1/job/list"
    detail_api_url = "https://ats.openout.mihoyo.com/ats-portal/v1/job/info"

    @staticmethod
    def _is_2027(item: dict[str, Any]) -> bool:
        return "2027" in f"{item.get('projectName', '')}{item.get('objectName', '')}"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        results: list[JobStub] = []
        page = 1
        page_size = 100
        while len(results) < context.max_jobs:
            payload = await self._post_json(
                context,
                self.list_api_url,
                {"pageNo": page, "pageSize": page_size, "channelDetailIds": [1], "hireType": 1},
            )
            data = payload.get("data") or {}
            items = data.get("list") or []
            for item in items:
                if not isinstance(item, dict) or not self._is_2027(item):
                    continue
                job_id = str(item.get("id") or "")
                if not job_id:
                    continue
                url = f"https://jobs.mihoyo.com/#/campus/position/{job_id}"
                results.append(JobStub(job_id, url, str(item.get("title") or ""), item))
                if len(results) >= context.max_jobs:
                    break
            total = int(data.get("total") or len(items))
            if not items or page * page_size >= total:
                break
            page += 1
        return results

    async def fetch_detail(self, stub: JobStub, context: CrawlContext) -> JobPayload:
        response = await self._post_json(
            context,
            self.detail_api_url,
            {"id": stub.external_job_id, "channelDetailIds": [1], "hireType": 1},
        )
        data = response.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError("米哈游岗位详情缺失")
        title = str(data.get("title") or stub.title_hint).strip()
        sections = (
            ("工作职责", data.get("description")),
            ("任职要求", data.get("jobRequire")),
            ("加分项", data.get("addition")),
            ("投递说明", data.get("deliveryInstructions")),
        )
        description = "\n\n".join(f"{label}\n{value}" for label, value in sections if value)
        if not title or not description:
            raise ValueError("米哈游官方详情缺少标题或岗位正文")
        locations = data.get("addressDetailList") or []
        location = "、".join(
            str(item.get("addressDetail") or "") for item in locations if isinstance(item, dict) and item.get("addressDetail")
        ) or None
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title,
            department=str(data.get("competencyType") or "") or None,
            location=location,
            recruitment_type=str(data.get("hireTypeName") or "校园招聘"),
            graduation_year="2027" if self._is_2027(data) else None,
            description=description,
            application_url=stub.detail_url,
            evidence_metadata={"source_url": self.detail_api_url, "parser_version": self.parser_version},
        )


class NeteaseSourceAdapter(OfficialSourceAdapter):
    parser_version = "2.0"
    project_id = 102
    api_url = "https://campus.game.163.com/api/campuspc/position/getJobList"

    async def discover(self, context: CrawlContext) -> list[JobStub]:
        results: list[JobStub] = []
        page = 1
        page_size = min(context.max_jobs, 100)
        while len(results) < context.max_jobs:
            url = f"{self.api_url}?pageSize={page_size}&currentPage={page}&projectId={self.project_id}"
            response = await self._get(context, url)
            payload = response.json()
            data = payload.get("data") or {}
            items = data.get("list") or []
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                job_id = str(item["id"])
                detail_url = f"https://campus.game.163.com/app/job/position?id={self.project_id}"
                results.append(JobStub(job_id, detail_url, str(item.get("positionName") or ""), item))
                if len(results) >= context.max_jobs:
                    break
            pages = int(data.get("pages") or 1)
            if not items or page >= pages:
                break
            page += 1
        return results

    def _payload_from_raw(self, stub: JobStub) -> JobPayload | None:
        data = stub.raw
        title = str(data.get("positionName") or stub.title_hint).strip()
        duties = str(data.get("positionDescription") or "").strip()
        requirements = str(data.get("positionRequirement") or "").strip()
        if not title or not (duties or requirements):
            return super()._payload_from_raw(stub)
        return JobPayload(
            external_job_id=stub.external_job_id,
            title=title,
            department=str(data.get("positionTypeName") or "") or None,
            location=str(data.get("workPlaceName") or "") or None,
            recruitment_type="校园招聘",
            graduation_year="2027",
            description="\n\n".join(
                part for part in (
                    f"工作职责\n{duties}" if duties else "",
                    f"任职要求\n{requirements}" if requirements else "",
                ) if part
            ),
            application_url=stub.detail_url,
            evidence_metadata={
                "source_url": self.api_url,
                "parser_version": self.parser_version,
                "shared_listing_url": True,
                "project_id": self.project_id,
            },
        )
