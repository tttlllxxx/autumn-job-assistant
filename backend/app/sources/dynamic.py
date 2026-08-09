from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from app.sources.base import CrawlContext, JobPayload, JobStub, OfficialSourceAdapter


class PublicJsonSourceAdapter(OfficialSourceAdapter):
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
