from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class TargetPolicy:
    graduation_year: str = "2027"
    excluded_recruitment: tuple[str, ...] = ("社招", "社会招聘", "日常实习", "暑期实习")
    non_job_titles: frozenset[str] = frozenset({"简历投递时间", "隐私协议", "privacy policy"})

    def source_rejection_reason(self, title: str, description: str) -> str | None:
        title = re.sub(r"\s+", " ", title).strip()
        normalized_title = title.casefold()
        if normalized_title in self.non_job_titles:
            return "页面导航或隐私条款，不是岗位"
        if re.fullmatch(r".*(?:赛事|计划|program)", title, flags=re.IGNORECASE):
            return "招聘项目介绍，不是具体岗位"
        if re.search(r"20(?:2[0-6])\s*年?[^\n]{0,12}(?:校园招聘|校招)", title) and self.graduation_year not in title:
            return f"明确属于非 {self.graduation_year} 届招聘批次"
        if re.search(r"<\s*(?:p|a|img|div)\b", description, flags=re.IGNORECASE):
            plain_text = BeautifulSoup(description, "lxml").get_text(" ", strip=True)
            if len(plain_text) < 20:
                return "仅包含活动图片或跳转链接，不是岗位正文"
        return None


TARGET_POLICY = TargetPolicy()
