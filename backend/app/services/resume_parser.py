from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import fitz

PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
    "id_number": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
}
ADDRESS_PATTERN = re.compile(r"(?:住址|地址)\s*[：:]\s*([^\n]{4,80})")
NAME_LINE = re.compile(r"^(?:姓名\s*[：:]\s*)?([\u4e00-\u9fff]{2,4})$")
INJECTION_MARKERS = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?previous|system\s*prompt|developer\s*message|忽略(?:以上|之前).*指令|系统提示词)"
)


@dataclass(frozen=True)
class ParsedLine:
    text: str
    page_number: int | None
    line_number: int | None
    emphasized: bool = False


@dataclass(frozen=True)
class ParsedResume:
    lines: list[ParsedLine]
    redacted_text: str
    pii: dict[str, list[str]]
    warnings: list[str]


def _redact(text: str) -> tuple[str, dict[str, list[str]]]:
    pii: dict[str, list[str]] = {key: [] for key in (*PII_PATTERNS, "address", "name")}
    redacted = text
    for key, pattern in PII_PATTERNS.items():
        matches = list(dict.fromkeys(pattern.findall(redacted)))
        pii[key].extend(matches)
        redacted = pattern.sub(f"[{key.upper()}]", redacted)
    for match in ADDRESS_PATTERN.finditer(redacted):
        pii["address"].append(match.group(1).strip())
    redacted = ADDRESS_PATTERN.sub("地址：[ADDRESS]", redacted)
    lines = redacted.splitlines()
    for index, line in enumerate(lines[:5]):
        match = NAME_LINE.match(line.strip())
        if match and not any(word in line for word in ("项目", "教育", "技能", "经历")):
            pii["name"].append(match.group(1))
            lines[index] = line.replace(match.group(1), "[NAME]")
            break
    return "\n".join(lines), {key: values for key, values in pii.items() if values}


def _markdown_lines(text: str) -> list[ParsedLine]:
    return [
        ParsedLine(
            line,
            None,
            number,
            emphasized=bool(re.match(r"^\s*#{2,}\s+", line) or re.fullmatch(r"\s*\*\*.+\*\*\s*", line)),
        )
        for number, line in enumerate(text.splitlines(), start=1)
    ]


def _pdf_lines(path: Path) -> list[ParsedLine]:
    result: list[ParsedLine] = []
    with fitz.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            # PDF content streams are often stored in drawing order instead of
            # visual reading order.  Sorting by coordinates keeps section
            # headings before the facts that visually follow them.
            rows: list[dict[str, object]] = []
            for block in page.get_text("dict", sort=True)["blocks"]:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(str(span.get("text", "")) for span in spans).strip()
                    if not text:
                        continue
                    total_chars = sum(len(str(span.get("text", ""))) for span in spans) or 1
                    bold_chars = sum(
                        len(str(span.get("text", "")))
                        for span in spans
                        if "bold" in str(span.get("font", "")).lower() or int(span.get("flags", 0)) & 16
                    )
                    rows.append({
                        "text": text,
                        "x": float(line["bbox"][0]),
                        "y": float(line["bbox"][1]),
                        "emphasized": bold_chars / total_chars >= 0.7,
                    })
            rows.sort(key=lambda row: (round(float(row["y"]), 1), float(row["x"])))
            visual_rows: list[dict[str, object]] = []
            for row in rows:
                if visual_rows and abs(float(row["y"]) - float(visual_rows[-1]["y"])) <= 2:
                    visual_rows[-1]["text"] = f"{visual_rows[-1]['text']} {row['text']}"
                    visual_rows[-1]["emphasized"] = bool(visual_rows[-1]["emphasized"]) or bool(row["emphasized"])
                    continue
                visual_rows.append(dict(row))
            for line_number, row in enumerate(visual_rows, start=1):
                result.append(
                    ParsedLine(str(row["text"]), page_number, line_number, bool(row["emphasized"]))
                )
    if not any(item.text.strip() for item in result):
        raise ValueError("该 PDF 未检测到可复制文本，暂不支持 OCR；请上传可复制文本的 PDF 或 Markdown")
    return result


def parse_resume(path: Path, media_type: str) -> ParsedResume:
    if media_type == "text/markdown":
        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Markdown 必须使用 UTF-8 编码") from exc
        lines = _markdown_lines(raw_text)
    elif media_type == "application/pdf":
        try:
            lines = _pdf_lines(path)
        except fitz.FileDataError as exc:
            raise ValueError("PDF 文件损坏或格式不受支持") from exc
        raw_text = "\n".join(item.text for item in lines)
    else:
        raise ValueError("仅支持 PDF 或 Markdown 简历")

    if not raw_text.strip():
        raise ValueError("简历内容为空")
    redacted, pii = _redact(raw_text)
    redacted_lines = redacted.splitlines()
    mapped = [
        ParsedLine(
            redacted_lines[index] if index < len(redacted_lines) else "",
            line.page_number,
            line.line_number,
            line.emphasized,
        )
        for index, line in enumerate(lines)
    ]
    warnings = []
    if INJECTION_MARKERS.search(raw_text):
        warnings.append("检测到疑似提示词指令，已按普通简历文本隔离处理")
    return ParsedResume(lines=mapped, redacted_text=redacted, pii=pii, warnings=warnings)


def category_for_heading(heading: str) -> str | None:
    value = re.sub(r"[#*\s：:]", "", heading)
    patterns = {
        "project": r"^(?:个人)?项目(?:经历|经验|实践|作品)?$",
        "education": r"^(?:教育|学历)(?:背景|经历|信息)?$",
        "experience": r"^(?:工作|实习|实践)(?:经历|经验)?$|^工作与实习经历$",
        "skill": r"^(?:专业|个人|技术|职业)?(?:技能|技术)(?:与工具|清单|栈|能力)?$",
        "award": r"^(?:奖项|荣誉)(?:证书|经历|成果)?$",
    }
    for category, pattern in patterns.items():
        if re.fullmatch(pattern, value):
            return category
    return None


def extract_atomic_facts(parsed: ParsedResume) -> list[dict[str, object]]:
    category = "other"
    facts: list[dict[str, object]] = []
    seen: set[str] = set()
    grouped_lines: list[tuple[str, ParsedLine]] = []
    grouped_category: str | None = None
    group_has_title = False

    def add_fact(text: str, item: ParsedLine, fact_category: str, *, max_length: int = 300) -> None:
        normalized = re.sub(r"[ \t]+", " ", text).strip()
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if content_hash in seen:
            return
        seen.add(content_hash)
        confidence = 1.0
        if len(normalized) < 6 or len(normalized) > max_length or "�" in normalized:
            confidence = 0.5
        facts.append({
            "category": fact_category,
            "text": normalized,
            "page_number": item.page_number,
            "line_number": item.line_number,
            "content_hash": content_hash,
            "confidence": confidence,
        })

    def flush_group() -> None:
        nonlocal grouped_lines, grouped_category, group_has_title
        if grouped_lines and grouped_category:
            add_fact(
                "\n".join(text for text, _ in grouped_lines),
                grouped_lines[0][1],
                grouped_category,
                max_length=2000,
            )
        grouped_lines = []
        grouped_category = None
        group_has_title = False

    for item in parsed.lines:
        line = re.sub(r"^[\s#>*•·\-]+", "", item.text).strip()
        if not line or line in {"[NAME]", "个人简历", "简历"}:
            continue
        if re.fullmatch(r"(?:姓名|邮箱|电话|手机|住址|地址)?\s*[：:]?\s*\[(?:NAME|EMAIL|PHONE|ADDRESS|ID_NUMBER)\]", line):
            continue
        heading_category = category_for_heading(line)
        if heading_category:
            flush_group()
            category = heading_category
            continue
        normalized = re.sub(r"\s+", " ", line)
        if category in {"project", "experience", "skill"}:
            if grouped_category and grouped_category != category:
                flush_group()
            if category in {"project", "experience"} and item.emphasized and grouped_lines and group_has_title:
                flush_group()
            grouped_category = category
            grouped_lines.append((normalized, item))
            group_has_title = group_has_title or item.emphasized
            continue
        flush_group()
        add_fact(normalized, item, category)
    flush_group()
    return facts
