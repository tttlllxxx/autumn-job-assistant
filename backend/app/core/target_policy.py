from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class TargetPolicy:
    graduation_year: str = "2027"
    allow_internship: bool = False
    excluded_recruitment: tuple[str, ...] = ("社招", "社会招聘", "日常实习", "暑期实习")
    non_job_titles: frozenset[str] = frozenset({"简历投递时间", "隐私协议", "privacy policy"})

    @staticmethod
    def targets_include_internship(targets: list[str]) -> bool:
        return any(
            "实习" in target
            or re.search(r"(?<![a-z0-9])intern(?:ship)?s?(?![a-z0-9])", target, flags=re.IGNORECASE)
            for target in targets
        )

    @staticmethod
    def is_internship_job(title: str, recruitment_type: str | None) -> bool:
        identity = f"{title}\n{recruitment_type or ''}"
        return "实习" in identity or bool(
            re.search(r"(?<![a-z0-9])intern(?:ship)?s?(?![a-z0-9])", identity, flags=re.IGNORECASE)
        )

    def source_rejection_reason(
        self,
        title: str,
        description: str,
        recruitment_type: str | None = None,
    ) -> str | None:
        title = re.sub(r"\s+", " ", title).strip()
        normalized_title = title.casefold()
        if not self.allow_internship and self.is_internship_job(title, recruitment_type):
            return "实习岗位，不属于秋招正式岗位"
        if normalized_title in self.non_job_titles:
            return "页面导航或隐私条款，不是岗位"
        concrete_role = re.search(
            r"工程师|研究员|开发|研发|算法|架构师|设计师|产品经理|专员|岗位",
            title,
            flags=re.IGNORECASE,
        )
        if not concrete_role and re.fullmatch(r".*(?:赛事|计划|program)", title, flags=re.IGNORECASE):
            return "招聘项目介绍，不是具体岗位"
        if re.search(r"20(?:2[0-6])\s*年?[^\n]{0,12}(?:校园招聘|校招)", title) and self.graduation_year not in title:
            return f"明确属于非 {self.graduation_year} 届招聘批次"
        if re.search(r"<\s*(?:p|a|img|div)\b", description, flags=re.IGNORECASE):
            plain_text = BeautifulSoup(description, "lxml").get_text(" ", strip=True)
            if len(plain_text) < 20:
                return "仅包含活动图片或跳转链接，不是岗位正文"
        return None


TARGET_POLICY = TargetPolicy()
