import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.api import sources as source_api
from app.models.entities import JobPosting, SourceRun
from app.schemas.jobs import SourceUpdate
from app.sources.ats import AshbySourceAdapter, GreenhouseSourceAdapter, LeverSourceAdapter, MokaSourceAdapter
from app.sources.base import CrawlContext, OfficialSourceAdapter, normalize_url
from app.sources.dynamic import (
    AlibabaSourceAdapter,
    AntSourceAdapter,
    KuaishouSourceAdapter,
    MeituanSourceAdapter,
    MihoyoSourceAdapter,
    NeteaseSourceAdapter,
    TencentSourceAdapter,
)
from app.sources.registry import (
    REGISTRY,
    SOURCE_FIELD_MAPS,
    build_custom_adapter,
    get_registry,
    save_custom_source_configs,
    save_source_entry_overrides,
)
from app.cli.live_sources import main as live_sources_main


SOURCE_FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources" / "official_snapshots.json"


def test_registry_contains_exactly_fifteen_target_companies() -> None:
    assert len(REGISTRY) == 15
    assert {adapter.display_name for adapter in REGISTRY.values()} == {
        "字节跳动", "阿里巴巴", "腾讯", "百度", "美团", "小红书", "快手", "华为",
        "蚂蚁集团", "京东", "滴滴", "网易", "米哈游", "哔哩哔哩", "携程",
    }
    assert REGISTRY["kuaishou"].start_url.startswith("https://campus.kuaishou.cn/")
    assert set(SOURCE_FIELD_MAPS) == set(REGISTRY)
    assert all({"title", "id", "description", "location"}.issubset(adapter.field_map) for adapter in REGISTRY.values())
    assert isinstance(REGISTRY["ant"], AntSourceAdapter)
    assert isinstance(REGISTRY["alibaba"], AlibabaSourceAdapter)
    assert isinstance(REGISTRY["kuaishou"], KuaishouSourceAdapter)
    assert isinstance(REGISTRY["tencent"], TencentSourceAdapter)
    assert isinstance(REGISTRY["meituan"], MeituanSourceAdapter)
    assert isinstance(REGISTRY["netease"], NeteaseSourceAdapter)
    assert isinstance(REGISTRY["mihoyo"], MihoyoSourceAdapter)
    assert isinstance(REGISTRY["didi"], MokaSourceAdapter)


def test_custom_source_is_persisted_and_merged_without_changing_builtin_registry() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        save_custom_source_configs(db, [{
            "source_key": "custom_fictional",
            "display_name": "虚构公司",
            "official_entry": "https://careers.example.invalid/jobs",
        }])
        combined = get_registry(db)

    assert len(REGISTRY) == 15
    assert len(combined) == 16
    assert combined["custom_fictional"].display_name == "虚构公司"
    assert combined["custom_fictional"]._is_official("https://careers.example.invalid/jobs/1")


@pytest.mark.parametrize(
    ("url", "adapter_type", "api_url"),
    [
        (
            "https://job-boards.greenhouse.io/example",
            GreenhouseSourceAdapter,
            "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true",
        ),
        (
            "https://jobs.lever.co/example",
            LeverSourceAdapter,
            "https://api.lever.co/v0/postings/example",
        ),
        (
            "https://jobs.ashbyhq.com/example",
            AshbySourceAdapter,
            "https://api.ashbyhq.com/posting-api/job-board/example",
        ),
        (
            "https://app.mokahr.com/campus_apply/example/12345",
            MokaSourceAdapter,
            "https://api.mokahr.com/api-platform/v1/jobs/example",
        ),
    ],
)
def test_custom_source_automatically_selects_public_ats_adapter(
    url: str,
    adapter_type: type[OfficialSourceAdapter],
    api_url: str,
) -> None:
    adapter = build_custom_adapter({
        "source_key": "custom_fixture",
        "display_name": "虚构公司",
        "official_entry": url,
    })

    assert isinstance(adapter, adapter_type)
    assert adapter.api_url == api_url
    assert adapter.collection_method == "ATS 公开 API"


def test_builtin_source_entry_override_is_persisted_without_mutating_registry() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    original = REGISTRY["bytedance"].start_url
    updated = "https://jobs.bytedance.com/campus/new-entry"
    with Session(engine) as db:
        save_source_entry_overrides(db, {"bytedance": updated})
        combined = get_registry(db)

    assert combined["bytedance"].start_url == updated
    assert combined["bytedance"]._is_official("https://jobs.bytedance.com/campus/position/1")
    assert REGISTRY["bytedance"].start_url == original


def test_source_list_includes_active_latest_and_unverified_counts() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            JobPosting(
                company="字节跳动", source_key="bytedance", external_job_id="J1", title="虚构岗位一",
                description="虚构岗位正文一", normalized_url="https://jobs.bytedance.com/campus/position/1",
                description_hash="1" * 64, graduation_year="2027", closed=False,
            ),
            JobPosting(
                company="字节跳动", source_key="bytedance", external_job_id="J2", title="虚构岗位二",
                description="虚构岗位正文二", normalized_url="https://jobs.bytedance.com/campus/position/2",
                description_hash="2" * 64, graduation_year=None, closed=False,
            ),
            JobPosting(
                company="字节跳动", source_key="bytedance", external_job_id="J3", title="已关闭岗位",
                description="已关闭岗位正文", normalized_url="https://jobs.bytedance.com/campus/position/3",
                description_hash="3" * 64, graduation_year="2027", closed=True,
            ),
            SourceRun(
                source_key="bytedance", adapter_version="fixture", success=True,
                discovered_count=7, finished_at=datetime.now(UTC),
            ),
        ])
        db.commit()
        items = source_api.list_sources(page=1, page_size=50, status=None, _=SimpleNamespace(), db=db)

    bytedance = next(item for item in items if item["source_key"] == "bytedance")
    assert bytedance["active_job_count"] == 2
    assert bytedance["year_unverified_count"] == 1
    assert bytedance["last_discovered_count"] == 7
    assert bytedance["collection_method"] == "官方网页"


@pytest.mark.asyncio
async def test_greenhouse_public_api_maps_complete_job() -> None:
    adapter = build_custom_adapter({
        "source_key": "custom_greenhouse",
        "display_name": "虚构公司",
        "official_entry": "https://job-boards.greenhouse.io/example",
    })
    response = {"jobs": [{
        "id": 101,
        "title": "2027 New Grad Software Engineer",
        "absolute_url": "https://job-boards.greenhouse.io/example/jobs/101",
        "content": "<p>Build reliable AI services with Python.</p>",
        "location": {"name": "Shanghai"},
        "departments": [{"name": "Engineering"}],
        "first_published": "2026-08-01T08:00:00Z",
    }]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json=response)
    )) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await adapter.discover(context)
        payload = await adapter.fetch_detail(stubs[0], context)

    assert payload.external_job_id == "101"
    assert payload.graduation_year == "2027"
    assert payload.location == "Shanghai"
    assert payload.department == "Engineering"
    assert payload.description == "Build reliable AI services with Python."


@pytest.mark.asyncio
async def test_lever_public_api_keeps_description_sections() -> None:
    adapter = build_custom_adapter({
        "source_key": "custom_lever",
        "display_name": "虚构公司",
        "official_entry": "https://jobs.lever.co/example",
    })
    response = [{
        "id": "lever-101",
        "text": "Software Engineer, University Graduate 2027",
        "hostedUrl": "https://jobs.lever.co/example/lever-101",
        "descriptionPlain": "Build the search platform.",
        "lists": [{"text": "Requirements", "content": "<ul><li>Python</li><li>SQL</li></ul>"}],
        "categories": {"location": "Beijing", "team": "Search", "commitment": "Full-time"},
        "createdAt": 1785542400000,
    }]
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json=response)
    )) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await adapter.discover(context)
        payload = await adapter.fetch_detail(stubs[0], context)

    assert payload.external_job_id == "lever-101"
    assert payload.department == "Search"
    assert "Requirements" in payload.description
    assert "Python" in payload.description
    assert payload.published_at is not None


@pytest.mark.asyncio
async def test_ashby_public_api_combines_secondary_locations() -> None:
    adapter = build_custom_adapter({
        "source_key": "custom_ashby",
        "display_name": "虚构公司",
        "official_entry": "https://jobs.ashbyhq.com/example",
    })
    response = {"jobs": [{
        "id": "ashby-101",
        "title": "2027 Graduate AI Engineer",
        "jobUrl": "https://jobs.ashbyhq.com/example/ashby-101",
        "descriptionHtml": "<p>Develop and evaluate model-serving systems.</p>",
        "location": "Shanghai",
        "secondaryLocations": [{"location": "Beijing"}, {"location": "Shanghai"}],
        "department": "AI Platform",
        "employmentType": "FullTime",
        "publishedAt": "2026-08-02T08:00:00Z",
    }]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, json=response)
    )) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await adapter.discover(context)
        payload = await adapter.fetch_detail(stubs[0], context)

    assert payload.external_job_id == "ashby-101"
    assert payload.location == "Shanghai、Beijing"
    assert payload.department == "AI Platform"
    assert payload.graduation_year == "2027"


@pytest.mark.asyncio
async def test_moka_public_campus_api_paginates_and_maps_complete_job() -> None:
    adapter = REGISTRY["didi"]
    response = {"total": 1, "jobs": [{
        "id": "moka-101",
        "title": "2027未来精英-大模型工程师",
        "description": "<p>负责大模型训练与服务平台开发。</p><p>要求熟悉 Python。</p>",
        "locations": [{"name": "北京"}, {"name": "上海"}],
        "department": {"id": 1, "name": "自动驾驶"},
        "commitment": "全职",
        "publishedAt": "2026-05-12T11:45:14.000Z",
    }]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.mokahr.com"
        assert request.url.params["mode"] == "campus"
        assert request.url.params["status"] == "open"
        assert request.url.params["siteId"] == "96064"
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await adapter.discover(context)
        payload = await adapter.fetch_detail(stubs[0], context)

    assert payload.external_job_id == "moka-101"
    assert payload.location == "北京、上海"
    assert payload.department == "自动驾驶"
    assert payload.recruitment_type == "校园招聘 · 全职"
    assert payload.graduation_year == "2027"
    assert "熟悉 Python" in payload.description


@pytest.mark.asyncio
async def test_source_entry_update_persists_and_runs_source(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    calls: list[str] = []

    async def fake_run_source(_db, source_key: str, **_kwargs):
        calls.append(source_key)
        return SimpleNamespace(
            success=True,
            discovered_count=5,
            new_count=2,
            updated_count=1,
            error_message=None,
            finished_at=None,
        )

    monkeypatch.setattr(source_api, "run_source", fake_run_source)
    with Session(engine) as db:
        result = await source_api.update_source_entry(
            "bytedance",
            SourceUpdate(official_entry="https://jobs.bytedance.com/campus/new-entry"),
            db,
        )
        assert get_registry(db)["bytedance"].start_url == "https://jobs.bytedance.com/campus/new-entry"

    assert calls == ["bytedance"]
    assert result["success"] is True
    assert result["discovered"] == 5


def test_embedded_official_json_maps_fields_and_rejects_foreign_url() -> None:
    adapter = OfficialSourceAdapter(
        source_key="fixture",
        display_name="虚构公司",
        start_url="https://careers.example.invalid/jobs",
        allowed_domains=("careers.example.invalid",),
        detail_tokens=("/jobs/",),
    )
    data = {
        "jobs": [
            {
                "jobId": "J1001",
                "jobName": "AI 后端开发工程师",
                "jobDescription": "负责虚构 RAG 平台的开发与测试",
                "workLocation": "北京市",
                "detailUrl": "/jobs/J1001",
            },
            {
                "jobId": "BAD",
                "jobName": "恶意链接",
                "jobDescription": "该对象不应进入结果",
                "detailUrl": "https://evil.invalid/jobs/BAD",
            },
        ]
    }
    html = f'<script type="application/json">{json.dumps(data, ensure_ascii=False)}</script>'
    stubs = adapter.parse_document(html, adapter.start_url)
    assert len(stubs) == 1
    assert stubs[0].external_job_id == "J1001"
    assert stubs[0].detail_url == "https://careers.example.invalid/jobs/J1001"


def test_navigation_config_is_not_misclassified_as_a_job() -> None:
    adapter = REGISTRY["huawei"]

    assert adapter._stub_from_object(
        {"title": "校园招聘", "url": "https://career.huawei.com/cn/campus-recruitment"}
    ) is None


def test_nested_office_address_is_not_misclassified_as_a_job() -> None:
    adapter = REGISTRY["bytedance"]

    assert adapter._stub_from_object({
        "id": "7449297142948937732",
        "name": "中国大陆北京市海淀区海淀大街3号",
        "city": {"name": "北京"},
        "district": {"name": "海淀区"},
        "state": {"name": "北京"},
        "country": {"name": "中国大陆"},
    }) is None


def test_recruitment_navigation_links_are_not_jobs() -> None:
    adapter = REGISTRY["kuaishou"]
    html = '<a href="/recruit/campus/e/#/campus/jobs?recruitSubProjectCodes=2027">应届招聘</a>'

    assert adapter.parse_document(html, adapter.start_url) == []


@pytest.mark.asyncio
async def test_discovery_deduplicates_anchor_and_embedded_json_by_external_id() -> None:
    adapter = OfficialSourceAdapter(
        source_key="fixture",
        display_name="虚构公司",
        start_url="https://jobs.example.invalid/list",
        allowed_domains=("jobs.example.invalid",),
        detail_tokens=("/position/",),
        detail_url_template="https://jobs.example.invalid/position/{id}",
    )
    html = """
        <a href="/position/J1001?from=list">虚构岗位 展开详情</a>
        <script type="application/json">
        {"jobs":[{"jobId":"J1001","jobName":"虚构岗位","jobDescription":"负责虚构平台开发"}]}
        </script>
    """
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, text=html)
    )) as client:
        stubs = await adapter.discover(CrawlContext(client=client))

    assert len(stubs) == 1
    assert stubs[0].external_job_id == "J1001"
    assert stubs[0].raw["jobDescription"] == "负责虚构平台开发"


def test_baidu_javascript_initial_data_tolerates_undefined_and_maps_complete_job() -> None:
    adapter = REGISTRY["baidu"]
    html = """
        <script>
        window.__USE_SSR__=true; window.__INITIAL_DATA__ =
        {"listData":{"listDetailData":[{
          "jobId":"baidu-101","name":"北京-虚构后端开发工程师(J100101)",
          "workContent":"负责核心系统开发","serviceCondition":"熟悉 Python 与分布式系统",
          "workPlace":"北京市","projectType":"校招"
        }],"projectType": undefined}}; window.prefix="/jobs";
        </script>
    """

    stubs = adapter.parse_document(html, adapter.start_url)
    payload = adapter._payload_from_raw(stubs[0])

    assert len(stubs) == 1
    assert payload is not None
    assert payload.external_job_id == "baidu-101"
    assert payload.location == "北京市"
    assert "熟悉 Python" in payload.description


def test_external_id_comes_from_query_or_non_generic_path_segment() -> None:
    assert OfficialSourceAdapter._external_id_from_url(
        "https://jobs.example.invalid/position/7669996401640835333/detail"
    ) == "7669996401640835333"
    assert OfficialSourceAdapter._external_id_from_url(
        "https://jobs.example.invalid/position/detail?jobUnionId=J1001"
    ) == "J1001"


def test_all_fifteen_source_snapshots_satisfy_adapter_contract() -> None:
    snapshots = json.loads(SOURCE_FIXTURES.read_text(encoding="utf-8"))

    assert set(snapshots) == set(REGISTRY)
    for source_key, data in snapshots.items():
        adapter = REGISTRY[source_key]
        stub = adapter._stub_from_object(data)
        assert stub is not None, source_key
        payload = adapter._payload_from_raw(stub)
        assert payload is not None, source_key
        assert payload.external_job_id
        assert payload.title.startswith("虚构"), source_key
        assert payload.description
        assert adapter._is_official(payload.application_url), source_key


@pytest.mark.asyncio
async def test_http_attempts_are_counted_in_crawl_context() -> None:
    adapter = OfficialSourceAdapter(
        source_key="fixture",
        display_name="虚构公司",
        start_url="https://jobs.example.invalid/list",
        allowed_domains=("jobs.example.invalid",),
        detail_tokens=("/jobs/",),
        detail_url_template="https://jobs.example.invalid/jobs/{id}",
    )
    html = '<script type="application/json">{"jobs":[{"id":"J1","title":"虚构岗位","description":"虚构岗位正文"}]}</script>'
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text=html))
    async with httpx.AsyncClient(transport=transport) as client:
        context = CrawlContext(client=client)
        stubs = await adapter.discover(context)

    assert len(stubs) == 1
    assert context.request_count == 1


def test_tencent_rejects_overseas_workday_job() -> None:
    adapter = REGISTRY["tencent"]
    stub = adapter._stub_from_object({
        "RecruitPostId": "R107692",
        "RecruitPostName": "Financial Management and Analysis 2027 Internship",
        "Responsibility": "Support the Palo Alto finance team",
        "RecruitTypeName": "Campus internship",
        "LocationName": "US-California-Palo-Alto",
        "PostURL": "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/R107692",
    })

    assert stub is None


@pytest.mark.asyncio
async def test_tencent_api_keeps_only_china_2027_campus_jobs() -> None:
    mapping_response = {"status": 0, "data": [{"subProjectList": [
        {
            "mappingId": 1,
            "recruitType": 1,
            "projectName": "2026校园招聘",
            "recruitYear": "2026",
            "recruitRangDesc": "毕业时间截至2026年12月31日",
        },
        {
            "mappingId": 14,
            "recruitType": 999,
            "projectName": "青云计划-应届生",
            "recruitYear": "2027",
            "recruitRangDesc": "毕业时间截至2027年12月31日",
        },
    ]}]}
    search_response = {"status": 0, "data": {"count": 1, "positionList": [{
        "postId": "TX-CAMPUS-1",
        "positionTitle": "大模型后台开发工程师",
        "projectName": "青云计划-应届生",
        "recruitLabelName": "应届毕业生 青云计划",
        "workCities": "深圳",
        "bgs": "TEG",
    }]}}
    detail_response = {"status": 0, "data": {
        "postId": "TX-CAMPUS-1",
        "title": "大模型后台开发工程师",
        "topicDetail": "负责大模型服务研发",
        "topicRequirement": "熟悉 Python 与分布式系统",
        "workCityList": ["深圳"],
        "tidName": "青云课题",
    }}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getProjectMapping"):
            return httpx.Response(200, json=mapping_response)
        if request.url.path.endswith("/searchPosition"):
            assert json.loads(request.content)["projectMappingIdList"] == [14]
            return httpx.Response(200, json=search_response)
        assert request.url.path.endswith("/getJobDetailsByPostId")
        return httpx.Response(200, json=detail_response)

    adapter = REGISTRY["tencent"]
    original_start_url = adapter.start_url
    adapter.start_url = "https://join.qq.com/post.html?query=p_1"
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            context = CrawlContext(client=client, max_jobs=10)
            stubs = await adapter.discover(context)
            payload = await adapter.fetch_detail(stubs[0], context)
    finally:
        adapter.start_url = original_start_url

    assert [stub.external_job_id for stub in stubs] == ["TX-CAMPUS-1"]
    assert payload.application_url == "https://join.qq.com/post_detail.html?postid=TX-CAMPUS-1"
    assert payload.location == "深圳"
    assert "熟悉 Python" in payload.description


@pytest.mark.asyncio
async def test_ant_public_api_keeps_complete_2027_graduate_jobs_only() -> None:
    response = {
        "content": [
            {
                "id": 27,
                "name": "AI 工程师-27届",
                "batchType": "graduate",
                "batchName": "2027届校园招聘",
                "batchTypeDesc": "应届生",
                "description": "负责大模型平台建设",
                "requirement": "熟悉 Python 和 PyTorch",
                "workLocations": ["杭州", "上海"],
                "categoryName": "技术类",
            },
            {
                "id": 28,
                "name": "AI 实习生",
                "batchType": "trainee",
                "batchName": "实习生专项",
                "description": "这条不应进入 2027 秋招库",
            },
        ],
        "totalCount": 2,
    }
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    async with httpx.AsyncClient(transport=transport) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await REGISTRY["ant"].discover(context)

    assert [stub.external_job_id for stub in stubs] == ["27"]
    payload = REGISTRY["ant"]._payload_from_raw(stubs[0])
    assert payload is not None
    assert payload.graduation_year == "2027"
    assert payload.location == "杭州、上海"
    assert "工作职责" in payload.description and "任职要求" in payload.description


@pytest.mark.asyncio
async def test_alibaba_public_api_discovers_every_page_of_2027_graduate_jobs() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text="<html></html>", headers={
                "set-cookie": "XSRF-TOKEN=test-csrf; Path=/",
            })
        assert request.url.params.get("_csrf") == "test-csrf"
        if request.url.path.endswith("/listBatch"):
            return httpx.Response(200, json={"success": True, "content": {
                "graduate": [{"id": 2027, "name": "阿里巴巴2027届应届生"}],
                "internship": [{"id": 99, "name": "日常实习生"}],
            }})
        body = json.loads(request.content)
        page = body["pageIndex"]
        pages.append(page)
        items = [
            {
                "id": page * 100 + index,
                "name": f"AI Agent 工程师-{page}-{index}",
                "description": "负责构建 Agent 应用",
                "requirement": "熟悉 Python",
                "workLocations": ["杭州"],
                "categoryName": "技术类",
            }
            for index in range(100 if page == 1 else 1)
        ]
        return httpx.Response(200, json={"success": True, "content": {
            "datas": items, "totalCount": 101, "pageSize": body["pageSize"], "currentPage": page,
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await REGISTRY["alibaba"].discover(context)

    assert pages == [1]
    assert len(stubs) == 10

    pages.clear()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = CrawlContext(client=client, max_jobs=250)
        stubs = await REGISTRY["alibaba"].discover(context)
        payload = REGISTRY["alibaba"]._payload_from_raw(stubs[-1])

    assert pages == [1, 2]
    assert len(stubs) == 101
    assert payload is not None
    assert payload.graduation_year == "2027"
    assert payload.location == "杭州"
    assert payload.application_url.endswith("/campus/position/200")


@pytest.mark.asyncio
async def test_kuaishou_public_api_uses_page_num_until_last_page() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        page = body["pageNum"]
        pages.append(page)
        assert body == {
            "recruitSubProjectCodes": ["20271779425607"],
            "pageSize": 10,
            "pageNum": page,
        }
        item = {
            "id": page,
            "name": f"Agent 研发工程师-{page}",
            "description": "负责 Agent 系统研发",
            "positionDemand": "熟悉 Python",
            "departmentName": "技术部",
            "workLocationDicts": [{"name": "北京"}],
        }
        return httpx.Response(200, json={"code": 200, "result": {
            "list": [item], "pages": 2, "pageNum": page, "pageSize": 10,
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = CrawlContext(client=client, max_jobs=20)
        stubs = await REGISTRY["kuaishou"].discover(context)
        payload = REGISTRY["kuaishou"]._payload_from_raw(stubs[-1])

    assert pages == [1, 2]
    assert [stub.external_job_id for stub in stubs] == ["1", "2"]
    assert payload is not None
    assert payload.location == "北京"
    assert payload.application_url.endswith("#/campus/job-info/2")


@pytest.mark.asyncio
async def test_meituan_public_campus_api_excludes_page_config_and_maps_jobs() -> None:
    response = {"status": 1, "message": "成功", "data": {
        "list": [{
            "jobUnionId": "MT-2027-1",
            "name": "大模型算法工程师",
            "jobStatus": "000",
            "jobDuty": "负责大模型训练和智能体系统研发",
            "jobRequirement": "2027届本科及以上学历，熟悉 Python",
            "jobFamily": "技术类",
            "jobFamilyGroup": "算法",
            "cityList": [{"name": "北京市"}, {"name": "上海市"}],
            "department": [],
            "refreshTime": 1786351348000,
        }],
        "page": {"pageNo": 1, "pageSize": 100, "totalPage": 1, "totalCount": 1},
    }}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/api/official/job/getJobList"
        assert body["jobType"] == [{"code": "1", "subCode": ["1"]}, {"code": "4", "subCode": ["1"]}]
        assert body["typeCode"] == ["1", "1"]
        assert body["jfJgList"] == [{"code": "11001", "subCode": []}]
        assert body["specialCode"] == ["1", "3"]
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = CrawlContext(client=client, max_jobs=100)
        stubs = await REGISTRY["meituan"].discover(context)
        payload = await REGISTRY["meituan"].fetch_detail(stubs[0], context)

    assert len(stubs) == 1
    assert payload.external_job_id == "MT-2027-1"
    assert payload.graduation_year == "2027"
    assert payload.location == "北京市、上海市"
    assert payload.department == "算法"
    assert "负责大模型训练" in payload.description
    assert "熟悉 Python" in payload.description


@pytest.mark.asyncio
async def test_meituan_public_api_uses_page_no_until_last_page() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        page = body["page"]["pageNo"]
        pages.append(page)
        return httpx.Response(200, json={"status": 1, "data": {
            "list": [{
                "jobUnionId": f"MT-{page}",
                "name": f"大模型应用工程师-{page}",
                "jobStatus": "000",
                "jobDuty": "负责 Agent 应用研发",
            }],
            "page": {"pageNo": page, "pageSize": 10, "totalPage": 3, "totalCount": 3},
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = CrawlContext(client=client, max_jobs=30)
        stubs = await REGISTRY["meituan"].discover(context)

    assert pages == [1, 2, 3]
    assert [stub.external_job_id for stub in stubs] == ["MT-1", "MT-2", "MT-3"]


@pytest.mark.asyncio
async def test_mihoyo_fetches_full_description_from_job_info_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/job/list"):
            return httpx.Response(200, json={"data": {"list": [{
                "id": "9147", "title": "IP 项目运营", "projectName": "2027届秋招", "objectName": "2027届",
            }], "total": 1}})
        assert json.loads(request.content)["channelDetailIds"] == [1]
        return httpx.Response(200, json={"data": {
            "id": "9147", "title": "IP 项目运营", "projectName": "2027届秋招",
            "description": "负责产品企划和项目交付", "jobRequire": "具备项目管理和沟通能力",
            "addressDetailList": [{"addressDetail": "上海"}], "competencyType": "运营类", "hireTypeName": "校园招聘",
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await REGISTRY["mihoyo"].discover(context)
        payload = await REGISTRY["mihoyo"].fetch_detail(stubs[0], context)

    assert payload.graduation_year == "2027"
    assert payload.location == "上海"
    assert "负责产品企划" in payload.description
    assert "具备项目管理" in payload.description


@pytest.mark.asyncio
async def test_netease_public_2027_project_api_maps_duties_and_requirements() -> None:
    response = {"data": {"pages": 1, "list": [{
        "id": 4764, "positionName": "AI 研究工程师", "positionTypeName": "人工智能",
        "workPlaceName": "杭州,广州", "positionDescription": "研发多模态大模型",
        "positionRequirement": "熟悉 Python 与深度学习框架",
    }]}}
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    async with httpx.AsyncClient(transport=transport) as client:
        context = CrawlContext(client=client, max_jobs=10)
        stubs = await REGISTRY["netease"].discover(context)

    payload = REGISTRY["netease"]._payload_from_raw(stubs[0])
    assert payload is not None
    assert payload.graduation_year == "2027"
    assert payload.location == "杭州,广州"
    assert "研发多模态大模型" in payload.description
    assert "熟悉 Python" in payload.description


def test_live_source_cli_requires_explicit_network_opt_in(monkeypatch, capsys) -> None:
    monkeypatch.delenv("RUN_LIVE_SOURCES", raising=False)

    assert asyncio.run(live_sources_main()) == 2
    assert "RUN_LIVE_SOURCES=1" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("source_key", "data", "expected_id", "expected_title", "expected_location"),
    [
        (
            "tencent",
            {
                "RecruitPostId": "TX-1",
                "RecruitPostName": "AI 后端工程师（2027届校招）",
                "Responsibility": "建设大模型应用平台",
                "RecruitTypeName": "校园招聘",
                "LocationName": "深圳",
                "PostURL": "https://careers.tencent.com/jobdesc.html?postId=TX-1",
            },
            "TX-1",
            "AI 后端工程师（2027届校招）",
            "深圳",
        ),
        (
            "huawei",
            {
                "advertisementId": "HW-ADVERTISEMENT-1",
                "jobId": "HW-1",
                "jobName": "AI 安全工程师",
                "jobResponsibilities": "负责模型安全平台研发",
                "jobDemand": "熟悉 Python",
                "jobPlaceName": "上海",
            },
            "HW-ADVERTISEMENT-1",
            "AI 安全工程师",
            "上海",
        ),
        (
            "jd",
            {
                "publishId": "JD-1",
                "positionName": "RAG 工程师",
                "workContent": "负责检索增强生成系统",
                "qualification": "熟悉向量数据库",
                "workCity": "北京",
                "positionDept": "京东科技",
            },
            "JD-1",
            "RAG 工程师",
            "北京",
        ),
        (
            "bilibili",
            {
                "id": "BILI-1",
                "positionName": "模型安全工程师【2027届】",
                "positionDescription": "负责大模型安全评测与平台研发",
                "workLocation": "上海",
                "postCodeName": "技术类",
            },
            "BILI-1",
            "模型安全工程师【2027届】",
            "上海",
        ),
    ],
)
def test_current_official_response_fields_map_to_complete_payload(
    source_key: str,
    data: dict[str, str],
    expected_id: str,
    expected_title: str,
    expected_location: str,
) -> None:
    adapter = REGISTRY[source_key]
    stub = adapter._stub_from_object(data)

    assert stub is not None
    payload = adapter._payload_from_raw(stub)
    assert payload is not None
    assert payload.external_job_id == expected_id
    assert payload.title == expected_title
    assert payload.location == expected_location
    assert payload.description
    assert adapter._is_official(payload.application_url)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://EXAMPLE.com/jobs/1/?utm_source=x&b=2&a=1#top", "https://example.com/jobs/1?a=1&b=2"),
        ("https://example.com//jobs//1/", "https://example.com/jobs/1"),
        (
            "https://jobs.mihoyo.com/#/campus/position/9147",
            "https://jobs.mihoyo.com/#/campus/position/9147",
        ),
    ],
)
def test_normalize_url_removes_tracking_and_is_stable(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected
