from app.sources.base import OfficialSourceAdapter
from app.sources.dynamic import AntSourceAdapter, MihoyoSourceAdapter, NeteaseSourceAdapter


SOURCE_SPECS = (
    ("bytedance", "字节跳动", "https://jobs.bytedance.com/campus/position", ("jobs.bytedance.com",), ("/position/",), "https://jobs.bytedance.com/campus/position/{id}/detail"),
    ("alibaba", "阿里巴巴", "https://campus-talent.alibaba.com/campus/position-list", ("campus-talent.alibaba.com", "talent.alibaba.com"), ("position", "job"), "https://campus-talent.alibaba.com/campus/position/{id}"),
    ("tencent", "腾讯", "https://careers.tencent.com/campusrecruit.html", ("careers.tencent.com", "join.qq.com", "tencent.wd1.myworkdayjobs.com"), ("position", "job", "post"), None),
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
    "tencent": {"title": ("RecruitPostName",), "id": ("RecruitPostId", "PostId"), "url": ("PostURL",), "description": ("Responsibility",), "location": ("LocationName",)},
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
    adapter_types = {"ant": AntSourceAdapter, "netease": NeteaseSourceAdapter, "mihoyo": MihoyoSourceAdapter}
    return {
        key: adapter_types.get(key, OfficialSourceAdapter)(
            source_key=key,
            display_name=name,
            start_url=url,
            allowed_domains=domains,
            detail_tokens=tokens,
            detail_url_template=template,
            field_map=SOURCE_FIELD_MAPS[key],
        )
        for key, name, url, domains, tokens, template in SOURCE_SPECS
    }


REGISTRY = build_registry()
