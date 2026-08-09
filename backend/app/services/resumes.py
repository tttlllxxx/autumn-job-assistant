from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CandidateProfile, ResumeDocument, ResumeFact, ResumeParseStatus
from app.services.resume_parser import extract_atomic_facts, parse_resume

ALLOWED_MEDIA = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}

SKILL_TOKENS = (
    "Python", "Java", "Go", "C++", "Rust", "JavaScript", "TypeScript", "React", "Vue",
    "Node.js", "FastAPI", "Django", "Flask", "Spring", "SQL", "MySQL", "PostgreSQL",
    "Redis", "Elasticsearch", "Docker", "Kubernetes", "Linux", "Git", "PyTorch",
    "TensorFlow", "RAG", "Agent", "LLM", "NLP", "计算机视觉", "向量数据库", "大模型",
    "模型安全", "安全研发", "应用安全", "数据安全",
)

DIRECTION_RULES = (
    ("RAG 工程", ("rag", "向量数据库", "检索增强")),
    ("AI Agent 开发", ("agent", "智能体")),
    ("大模型应用开发", ("llm", "大模型", "生成式人工智能")),
    ("算法工程", ("算法", "pytorch", "tensorflow", "nlp", "计算机视觉")),
    ("AI 平台/后端", ("fastapi", "django", "flask", "spring", "后端", "平台")),
    ("模型安全", ("模型安全", "安全评测", "对抗样本")),
    ("安全研发", ("安全研发", "应用安全", "数据安全")),
    ("前端开发", ("react", "vue", "前端")),
)


def media_type_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_MEDIA:
        raise ValueError("仅支持 .pdf、.md 或 .markdown 文件")
    return ALLOWED_MEDIA[suffix]


def stable_fact_id(content_hash: str, document_hash: str, salt: str = "") -> str:
    value = hashlib.sha256(f"{document_hash}:{content_hash}:{salt}".encode()).hexdigest()[:16]
    return f"fact_{value}"


def create_resume(
    db: Session,
    *,
    filename: str,
    content: bytes,
    upload_dir: Path,
) -> ResumeDocument:
    media_type = media_type_for(filename)
    content_hash = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(ResumeDocument).where(ResumeDocument.content_hash == content_hash))
    if existing:
        return existing
    suffix = Path(filename).suffix.lower()
    stored_path = upload_dir / f"{uuid.uuid4().hex}{suffix}"
    stored_path.write_bytes(content)
    document = ResumeDocument(
        original_name=Path(filename).name,
        stored_path=str(stored_path),
        media_type=media_type,
        content_hash=content_hash,
    )
    db.add(document)
    db.flush()
    try:
        parsed = parse_resume(stored_path, media_type)
        facts = extract_atomic_facts(parsed)
        if not facts:
            raise ValueError("没有提取到可审核的简历事实")
        document.redacted_text = parsed.redacted_text
        document.pii_local = parsed.pii
        document.parse_status = (
            ResumeParseStatus.needs_review.value
            if parsed.warnings or any(float(item["confidence"]) < 1 for item in facts)
            else ResumeParseStatus.parsed.value
        )
        document.parse_error = "；".join(parsed.warnings) or None
        for item in facts:
            db.add(
                ResumeFact(
                    fact_id=stable_fact_id(str(item["content_hash"]), content_hash),
                    category=str(item["category"]),
                    original_text=str(item["text"]),
                    redacted_text=str(item["text"]),
                    document_id=document.id,
                    page_number=item["page_number"],
                    line_number=item["line_number"],
                    content_hash=str(item["content_hash"]),
                    confidence=float(item["confidence"]),
                )
            )
    except ValueError as exc:
        document.parse_status = ResumeParseStatus.failed.value
        document.parse_error = str(exc)
    db.commit()
    db.refresh(document)
    return document


def build_profile(db: Session) -> CandidateProfile:
    facts = db.scalars(select(ResumeFact).where(ResumeFact.active.is_(True))).all()
    profile = db.get(CandidateProfile, 1) or CandidateProfile(id=1)
    texts = [fact.redacted_text for fact in facts]
    combined = "\n".join(texts).lower()
    profile.skills = [token for token in SKILL_TOKENS if token.lower() in combined]
    profile.target_directions = [
        direction for direction, markers in DIRECTION_RULES if any(marker in combined for marker in markers)
    ] or ["软件开发"]
    profile.education_level = next(
        (level for level in ("博士", "硕士", "本科", "大专") if any(level in text for text in texts)),
        None,
    )
    profile.experience_summary = "\n".join(fact.redacted_text for fact in facts if fact.category == "experience")
    profile.project_summary = "\n".join(fact.redacted_text for fact in facts if fact.category == "project")
    profile.confirmed = False
    if profile.id is None or db.get(CandidateProfile, 1) is None:
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def reparse_document(db: Session, document: ResumeDocument) -> ResumeDocument:
    parsed = parse_resume(Path(document.stored_path), document.media_type)
    extracted = extract_atomic_facts(parsed)
    if not extracted:
        raise ValueError("没有提取到可审核的简历事实")
    document_facts = list(
        db.scalars(select(ResumeFact).where(ResumeFact.document_id == document.id)).all()
    )
    existing = {fact.content_hash: fact for fact in document_facts}
    extracted_hashes: set[str] = set()
    for item in extracted:
        content_hash = str(item["content_hash"])
        extracted_hashes.add(content_hash)
        fact = existing.get(content_hash)
        if fact is None:
            fact = ResumeFact(
                fact_id=stable_fact_id(content_hash, document.content_hash),
                original_text=str(item["text"]),
                redacted_text=str(item["text"]),
                document_id=document.id,
                content_hash=content_hash,
            )
            db.add(fact)
        fact.category = str(item["category"])
        fact.page_number = item["page_number"]
        fact.line_number = item["line_number"]
        fact.confidence = float(item["confidence"])
    # Coordinate sorting can merge fragments that an older parser emitted as
    # standalone facts. Retire only untouched parser output; user revisions
    # carry supersedes_fact_id and must survive a reparse.
    for fact in document_facts:
        if fact.content_hash not in extracted_hashes and fact.supersedes_fact_id is None:
            fact.active = False
    document.redacted_text = parsed.redacted_text
    document.pii_local = parsed.pii
    document.parse_status = (
        ResumeParseStatus.needs_review.value
        if parsed.warnings or any(float(item["confidence"]) < 1 for item in extracted)
        else ResumeParseStatus.parsed.value
    )
    document.parse_error = "；".join(parsed.warnings) or None
    db.commit()
    db.refresh(document)
    return document


def revise_fact(db: Session, fact: ResumeFact, new_text: str) -> ResumeFact:
    text = re.sub(r"\s+", " ", new_text).strip()
    if not text:
        raise ValueError("事实内容不能为空")
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    fact.active = False
    replacement = ResumeFact(
        fact_id=stable_fact_id(content_hash, fact.document.content_hash, uuid.uuid4().hex),
        category=fact.category,
        original_text=text,
        redacted_text=text,
        document_id=fact.document_id,
        page_number=fact.page_number,
        line_number=fact.line_number,
        content_hash=content_hash,
        active=True,
        confirmed=False,
        confidence=1,
        supersedes_fact_id=fact.fact_id,
    )
    db.add(replacement)
    db.commit()
    db.refresh(replacement)
    return replacement
