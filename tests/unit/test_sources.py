import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.sources.base import CrawlContext, OfficialSourceAdapter, normalize_url
from app.sources.dynamic import AntSourceAdapter, MihoyoSourceAdapter, NeteaseSourceAdapter
from app.sources.registry import REGISTRY, SOURCE_FIELD_MAPS
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
    assert isinstance(REGISTRY["netease"], NeteaseSourceAdapter)
    assert isinstance(REGISTRY["mihoyo"], MihoyoSourceAdapter)


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
                "RecruitPostName": "AI 后端工程师",
                "Responsibility": "建设大模型应用平台",
                "LocationName": "深圳",
                "PostURL": "https://tencent.wd1.myworkdayjobs.com/zh-CN/Tencent_Careers/job/TX-1",
            },
            "TX-1",
            "AI 后端工程师",
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
