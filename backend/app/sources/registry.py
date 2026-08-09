import copy
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.entities import AppSetting
from app.sources.ats import build_ats_adapter
from app.sources.base import OfficialSourceAdapter
from app.sources.dynamic import AntSourceAdapter, MihoyoSourceAdapter, NeteaseSourceAdapter, TencentSourceAdapter


CUSTOM_SOURCES_KEY = "custom_sources"
SOURCE_ENTRY_OVERRIDES_KEY = "source_entry_overrides"
CUSTOM_DETAIL_TOKENS = ("job", "position", "career", "recruit", "campus", "detail", "apply")


SOURCE_SPECS = (
    ("bytedance", "字节跳动", "https://jobs.bytedance.com/campus/position", ("jobs.bytedance.com",), ("/position/",), "https://jobs.bytedance.com/campus/position/{id}/detail"),
    ("alibaba", "阿里巴巴", "https://campus-talent.alibaba.com/campus/position-list", ("campus-talent.alibaba.com", "talent.alibaba.com"), ("position", "job"), "https://campus-talent.alibaba.com/campus/position/{id}"),
    ("tencent", "腾讯", "https://join.qq.com/post.html?query=p_1", ("careers.tencent.com", "join.qq.com"), ("position", "job", "post"), None),
    ("baidu", "百度", "https://talent.baidu.com/jobs/list?projectType=1", ("talent.baidu.com",), ("/jobs/detail/",), "https://talent.baidu.com/jobs/detail/GRADUATE/{id}"),
    ("meituan", "美团", "https://zhaopin.meituan.com/web/position?hiringType=1_1", ("zhaopin.meituan.com",), ("position/detail", "jobUnionId"), "https://zhaopin.meituan.com/web/position/detail?jobUnionId={id}"),
    ("xiaohongshu", "小红书", "https://job.xiaohongshu.com/campus/position", ("job.xiaohongshu.com",), ("/position/",), "https://job.xiaohongshu.com/campus/position/{id}"),
    ("kuaishou", "快手", "https://campus.kuaishou.cn/recruit/campus/e/#/campus/jobs?recruitSubProjectCodes=20271779425607", ("campus.kuaishou.cn",), ("position", "job", "detail"), None),
    ("huawei", "华为", "https://career.huawei.com/cn/campus-recruitment-job-list", ("career.huawei.com", "apigw-dgg-b0.huawei.com"), ("job-details",), "https://career.huawei.com/cn/job-details?advertisementId={id}"),
    ("ant", "蚂蚁集团", "https://talent.antgroup.com/campus-full-list", ("talent.antgroup.com", "hrcareersweb.antgroup.com"), ("position", "job"), None),
    ("jd", "京东", "https://campus.jd.com/#/jobs", ("campus.jd.com",), ("job", "position"), "https://campus.jd.com/#/jobs"),
    ("didi", "滴滴", "https://campus.didiglobal.com/campus_apply/didiglobal/96064", ("campus.didiglobal.com", "talent.didiglobal.com", "app.mokahr.com"), ("/jobs/", "/p/", "job"), None),
    ("netease", "网易", "https://campus.game.163.com/app/job/position?id=102", ("campus.163.com", "campus.game.163.com"), ("position", "job"), None),
    ("mihoyo", "米哈游", "https://jobs.mihoyo.com/#/campus/position", ("campus.mihoyo.com", "jobs.mihoyo.com", "ats.openout.mihoyo.com"), ("position", "job"), None),
    ("bilibili", "哔哩哔哩", "https://jobs.bilibili.com/campus/positions?type=3", ("jobs.bilibili.com",), ("position", "job"), "https://jobs.bilibili.com/campus/positions?type=3"),
    ("ctrip", "携程", "https://careers.ctrip.com/#/campus", ("careers.ctrip.com", "app.mokahr.com"), ("/jobs", "position"), None),
)

SOURCE_FIELD_MAPS = {
    "bytedance": {"title": ("title",), "id": ("id",), "description": ("description",), "location": ("city_info", "location")},
    "alibaba": {"title": ("positionName", "name"), "id": ("positionId", "id"), "description": ("description", "requirement"), "location": ("workLocation", "location")},
    "tencent": {"title": ("positionTitle", "RecruitPostName"), "id": ("postId", "RecruitPostId", "PostId"), "url": ("PostURL",), "description": ("desc", "topicDetail", "Responsibility"), "location": ("workCityList", "workCities", "LocationName")},
    "baidu": {"title": ("jobName", "name"), "id": ("jobId", "id"), "description": ("jobDescription", "description"), "location": ("workLocation", "location")},
    "meituan": {"title": ("name", "title"), "id": ("jobUnionId", "id"), "description": ("jobDescription", "description", "responsibility"), "location": ("city", "location")},
    "xiaohongshu": {"title": ("positionName", "name"), "id": ("positionId", "id"), "description": ("jobDescription", "description"), "location": ("workLocation", "location")},
    "kuaishou": {"title": ("name",), "id": ("id", "code"), "description": ("description", "positionDemand"), "location": ("workLocationDicts", "workLocationCode")},
    "huawei": {"title": ("jobName", "jobname", "externalJobName"), "id": ("advertisementId", "jobId"), "description": ("jobResponsibilities", "jobDemand", "jobRequire"), "location": ("jobPlaceName", "jobAddress")},
    "ant": {"title": ("title", "name"), "id": ("jobCode", "id"), "description": ("content", "description"), "location": ("workplace", "location")},
    "jd": {"title": ("positionName",), "id": ("publishId",), "description": ("workContent", "qualification"), "location": ("workCity",)},
    "didi": {"title": ("jobName", "name"), "id": ("jobId", "id"), "description": ("description", "responsibility"), "location": ("location", "workLocation")},
    "netease": {"title": ("positionName", "jobName"), "id": ("positionId", "jobId", "id"), "description": ("description", "duty"), "location": ("city", "location")},
    "mihoyo": {"title": ("title",), "id": ("id",), "description": ("jobSummary",), "location": ("addressDetailList", "address")},
    "bilibili": {"title": ("positionName",), "id": ("id",), "description": ("positionDescription",), "location": ("workLocation",)},
    "ctrip": {"title": ("jobName", "name"), "id": ("jobId", "id"), "description": ("description", "jobDescription"), "location": ("workLocation", "location")},
}


def build_registry() -> dict[str, OfficialSourceAdapter]:
    adapter_types = {
        "ant": AntSourceAdapter,
        "tencent": TencentSourceAdapter,
        "netease": NeteaseSourceAdapter,
        "mihoyo": MihoyoSourceAdapter,
    }
    registry: dict[str, OfficialSourceAdapter] = {}
    for key, name, url, domains, tokens, template in SOURCE_SPECS:
        adapter_type = adapter_types.get(key)
        ats_adapter = None if adapter_type else build_ats_adapter(
            source_key=key,
            display_name=name,
            start_url=url,
            field_map=SOURCE_FIELD_MAPS[key],
        )
        registry[key] = ats_adapter or (adapter_type or OfficialSourceAdapter)(
            source_key=key,
            display_name=name,
            start_url=url,
            allowed_domains=domains,
            detail_tokens=tokens,
            detail_url_template=template,
            field_map=SOURCE_FIELD_MAPS[key],
        )
    return registry


REGISTRY = build_registry()


def custom_source_configs(db: Session) -> list[dict[str, str]]:
    setting = db.get(AppSetting, CUSTOM_SOURCES_KEY)
    if setting is None or not isinstance(setting.value, list):
        return []
    return [item for item in setting.value if isinstance(item, dict)]


def save_custom_source_configs(db: Session, configs: list[dict[str, str]]) -> None:
    setting = db.get(AppSetting, CUSTOM_SOURCES_KEY) or AppSetting(
        key=CUSTOM_SOURCES_KEY,
        value=[],
        secret=False,
    )
    setting.value = configs
    db.add(setting)
    db.commit()


def source_entry_overrides(db: Session) -> dict[str, str]:
    setting = db.get(AppSetting, SOURCE_ENTRY_OVERRIDES_KEY)
    if setting is None or not isinstance(setting.value, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in setting.value.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def save_source_entry_overrides(db: Session, overrides: dict[str, str]) -> None:
    setting = db.get(AppSetting, SOURCE_ENTRY_OVERRIDES_KEY) or AppSetting(
        key=SOURCE_ENTRY_OVERRIDES_KEY,
        value={},
        secret=False,
    )
    setting.value = overrides
    db.add(setting)
    db.commit()


def _with_official_entry(adapter: OfficialSourceAdapter, official_entry: str) -> OfficialSourceAdapter:
    ats_adapter = build_ats_adapter(
        source_key=adapter.source_key,
        display_name=adapter.display_name,
        start_url=official_entry,
        field_map=adapter.field_map,
    )
    if ats_adapter is not None:
        return ats_adapter
    updated = copy.copy(adapter)
    host = urlparse(official_entry).hostname
    updated.start_url = official_entry
    if host:
        updated.allowed_domains = tuple(dict.fromkeys((*adapter.allowed_domains, host)))
    return updated


def build_custom_adapter(config: dict[str, str]) -> OfficialSourceAdapter:
    start_url = config["official_entry"]
    host = urlparse(start_url).hostname
    if not host:
        raise ValueError("官方招聘入口缺少有效域名")
    ats_adapter = build_ats_adapter(
        source_key=config["source_key"],
        display_name=config["display_name"],
        start_url=start_url,
    )
    if ats_adapter is not None:
        return ats_adapter
    return OfficialSourceAdapter(
        source_key=config["source_key"],
        display_name=config["display_name"],
        start_url=start_url,
        allowed_domains=(host,),
        detail_tokens=CUSTOM_DETAIL_TOKENS,
    )


def get_registry(db: Session) -> dict[str, OfficialSourceAdapter]:
    overrides = source_entry_overrides(db)
    combined = {
        key: _with_official_entry(adapter, overrides[key]) if key in overrides else adapter
        for key, adapter in REGISTRY.items()
    }
    for config in custom_source_configs(db):
        try:
            adapter = build_custom_adapter(config)
        except (KeyError, ValueError):
            continue
        combined[adapter.source_key] = adapter
    return combined
