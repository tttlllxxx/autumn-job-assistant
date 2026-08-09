from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

from app.models.entities import Application

CSV_HEADERS = [
    "公司名", "投递渠道", "岗位", "岗位类型", "业务线/部门", "链接", "Base地", "投递日期", "状态",
    "当前阶段", "阶段结果", "当前进度更新时间", "内推码", "联系人/内推人", "面试时间", "结果", "备注",
]
FIELD_MAP = {
    "公司名": "company", "投递渠道": "channel", "岗位": "position", "岗位类型": "position_type",
    "业务线/部门": "department", "链接": "url", "Base地": "base_location", "投递日期": "applied_date",
    "状态": "status", "当前阶段": "current_stage", "阶段结果": "stage_result",
    "当前进度更新时间": "progress_updated_at", "内推码": "referral_code", "联系人/内推人": "contact",
    "面试时间": "interview_time", "结果": "result", "备注": "notes",
}
STATUS_VALUES = {
    "待投递", "已投递", "笔试中", "面试中", "HR 面", "人才库", "Offer 待确认", "Offer 已接收",
    "Offer 已拒绝", "未通过", "已撤回", "已终止",
}
STAGE_VALUES = {"投递", "笔试", "一面", "二面", "三面", "终面", "HR 面", "Offer"}
STAGE_RESULT_VALUES = {"待处理", "待约", "已约", "进行中", "通过", "未通过", "终止", "撤回"}


def _date(value: str) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("日期应为 YYYY-MM-DD、YYYY/MM/DD 或 YYYY.MM.DD")


def _datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    raise ValueError("时间应为 ISO 8601 或 YYYY-MM-DD HH:MM")


def parse_csv(content: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV 必须使用 UTF-8 编码") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != CSV_HEADERS:
        raise ValueError("CSV 表头或列顺序不符合模板")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for number, raw in enumerate(reader, start=2):
        row = {key: (value if value is not None else "") for key, value in raw.items()}
        row_errors = []
        for header, allowed in (("状态", STATUS_VALUES), ("当前阶段", STAGE_VALUES), ("阶段结果", STAGE_RESULT_VALUES)):
            if row[header] and row[header] not in allowed:
                row_errors.append({"column": header, "value": row[header], "message": "不在允许的枚举中"})
        converted = {FIELD_MAP[header]: row[header] for header in CSV_HEADERS}
        try:
            converted["applied_date"] = _date(row["投递日期"])
        except ValueError as exc:
            row_errors.append({"column": "投递日期", "value": row["投递日期"], "message": str(exc)})
        for header, field in (("当前进度更新时间", "progress_updated_at"), ("面试时间", "interview_time")):
            try:
                converted[field] = _datetime(row[header])
            except ValueError as exc:
                row_errors.append({"column": header, "value": row[header], "message": str(exc)})
        if row_errors:
            errors.append({"row": number, "errors": row_errors})
        else:
            converted["raw_values"] = row
            rows.append(converted)
    return rows, errors


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ")
    return str(value)


def export_csv(applications: list[Application]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    for application in applications:
        values = {}
        for header, field in FIELD_MAP.items():
            current = getattr(application, field)
            raw = application.raw_values.get(header) if application.raw_values else None
            values[header] = raw if raw is not None else _string_value(current)
        writer.writerow(values)
    return "\ufeff" + output.getvalue()
