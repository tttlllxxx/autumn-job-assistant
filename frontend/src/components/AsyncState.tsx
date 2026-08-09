import type { ReactNode } from "react";

export function AsyncState({ loading, error, empty, children }: { loading?: boolean; error?: Error | null; empty?: boolean; children: ReactNode }) {
  if (loading) return <div className="state" role="status">正在加载…</div>;
  if (error) return <div className="state error" role="alert">{error.message}</div>;
  if (empty) return <div className="state">暂无数据</div>;
  return <>{children}</>;
}

export function Status({ value }: { value: string }) {
  const kind = value === "healthy" || value === "completed" || value === "parsed" ? "good" : value === "unknown" ? "muted" : "warn";
  const labels: Record<string, string> = {
    healthy: "正常",
    completed: "已完成",
    parsed: "已解析",
    unknown: "未检测",
    degraded: "降级",
    failed: "异常",
    pending: "等待中",
    skipped: "已跳过",
    local_only: "本地评分",
    hard_filtered: "已过滤",
    llm_missing: "模型漏项",
    llm_invalid: "证据无效",
    llm_failed: "模型失败",
  };
  return <span className={`badge ${kind}`}>{labels[value] ?? value}</span>;
}
