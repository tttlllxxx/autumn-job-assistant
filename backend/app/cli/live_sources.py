from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

import httpx

from app.core.database import Base, SessionLocal, engine
from app.models.entities import SourceHealth
from app.sources.base import CrawlContext
from app.sources.registry import REGISTRY
from app.sources.runner import USER_AGENT


async def main() -> int:
    if os.getenv("RUN_LIVE_SOURCES") != "1":
        print("实时来源验收未运行：请显式设置 RUN_LIVE_SOURCES=1 后重试。")
        return 2
    Base.metadata.create_all(engine)
    rows = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for key, adapter in REGISTRY.items():
            result = await adapter.probe(CrawlContext(client=client, allow_browser=True, max_jobs=100))
            accepted = bool(result.ok and result.job_count > 0 and result.field_completeness >= 0.95)
            rows.append(
                {
                    "source_key": key,
                    "company": adapter.display_name,
                    "official_entry": adapter.start_url,
                    "method": "HTTP + embedded JSON + Playwright network capture",
                    "status": result.status,
                    "job_count": result.job_count,
                    "field_completeness": result.field_completeness,
                    "accepted": accepted,
                    "reason": result.message,
                }
            )
            with SessionLocal() as db:
                health = db.get(SourceHealth, key) or SourceHealth(source_key=key, consecutive_failures=0)
                health.status = result.status
                health.stable_for_acceptance = accepted
                health.last_error = None if accepted else result.message
                if accepted:
                    health.last_success_at = datetime.now(UTC)
                    health.consecutive_failures = 0
                else:
                    health.consecutive_failures = (health.consecutive_failures or 0) + 1
                db.add(health)
                db.commit()
    print("| 公司 | 官方入口 | 状态 | 岗位数 | 字段完整率 | 计入验收 | 失败原因/兜底 |")
    print("|---|---|---:|---:|---:|---:|---|")
    for row in rows:
        fallback = row["reason"] or ("—" if row["accepted"] else "可在控制台手工导入 URL/JD")
        print(
            f"| {row['company']} | {row['official_entry']} | {row['status']} | {row['job_count']} | "
            f"{row['field_completeness']:.0%} | {'是' if row['accepted'] else '否'} | {fallback} |"
        )
    accepted_count = sum(row["accepted"] for row in rows)
    print(f"\n实时验收：{accepted_count}/15 家通过（要求至少 12 家）。")
    print(json.dumps({"checked_at": datetime.now(UTC).isoformat(), "accepted": accepted_count, "rows": rows}, ensure_ascii=False))
    return 0 if accepted_count >= 12 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
