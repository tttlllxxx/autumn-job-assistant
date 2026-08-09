import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, jsonBody } from "../api";
import { AsyncState, Status } from "../components/AsyncState";
import type { Page, Recommendation } from "../types";

type RecommendationStatus = "recommended" | "pending" | "filtered" | "all";
type Pipeline = { vector?: string; vector_detail?: string; llm?: string; llm_detail?: string };

const tabs: { value: RecommendationStatus; label: string }[] = [
  { value: "recommended", label: "推荐" },
  { value: "pending", label: "待确认" },
  { value: "filtered", label: "已过滤" },
  { value: "all", label: "全部" },
];

const filterLabels: Record<string, string> = {
  open: "岗位已关闭",
  recruitment_type: "不是目标招聘类型",
  graduation_year: "毕业年份不符合",
  excluded_keywords: "命中排除关键词",
  technical_direction: "未识别为技术方向",
};

function reasonFor(rec: Recommendation): string | null {
  if (!rec.hard_filter_passed) {
    const failed = Object.entries(rec.hard_filter_details)
      .filter(([, passed]) => !passed)
      .map(([key]) => filterLabels[key] ?? key);
    return failed.join("、") || "未通过硬条件";
  }
  if (rec.qualification_pending) return "招聘类型或毕业年份仍需确认";
  const pipeline = (rec.evidence.pipeline ?? {}) as Pipeline;
  if (pipeline.llm && pipeline.llm !== "completed") return `模型：${pipeline.llm_detail ?? pipeline.llm}`;
  if (pipeline.vector === "failed") return `向量：${pipeline.vector_detail ?? "不可用"}`;
  return null;
}

export function Recommendations() {
  const client = useQueryClient();
  const [status, setStatus] = useState<RecommendationStatus>("recommended");
  const recs = useQuery<Page<Recommendation>>({
    queryKey: ["recommendations", status],
    queryFn: () => api(`/api/recommendations?page_size=200&status=${status}`),
  });
  const recompute = useMutation({
    mutationFn: () => api<Record<string, string | number>>("/api/recommendations/recompute", jsonBody({})),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["recommendations"] }),
  });

  return <>
    <header className="page-head">
      <div>
        <p className="eyebrow">岗位匹配</p>
        <h1>为你筛出的机会</h1>
        <p>岗位详情与推荐结果一体返回；过滤、资格待定和模型降级都有明确原因。</p>
      </div>
      <button onClick={() => recompute.mutate()} disabled={recompute.isPending}>
        {recompute.isPending ? "正在计算…" : "更新推荐"}
      </button>
    </header>
    {recompute.error && <p role="alert" className="error-text">{recompute.error.message}</p>}
    {recompute.data && <p className={String(recompute.data.llm_status).startsWith("completed") ? "run-result success" : "run-result warning"}>
      已处理 {recompute.data.jobs} 个岗位；合格 {recompute.data.eligible} 个。向量：{recompute.data.vector_status}；LLM：{recompute.data.llm_status}
    </p>}
    <div className="recommendation-tabs" role="tablist" aria-label="推荐状态">
      {tabs.map((tab) => <button
        className={status === tab.value ? "active" : ""}
        key={tab.value}
        onClick={() => setStatus(tab.value)}
        role="tab"
        aria-selected={status === tab.value}
      >{tab.label}<span>{recs.data?.counts?.[tab.value] ?? 0}</span></button>)}
    </div>
    <AsyncState loading={recs.isLoading} error={recs.error} empty={!recs.data?.items.length}>
      <div className="list-toolbar"><span>当前视图 {recs.data?.total ?? 0} 个岗位</span><span>按综合匹配度排序</span></div>
      <div className="card-list">{recs.data?.items.map((rec, index) => {
        const job = rec.job;
        const reason = reasonFor(rec);
        return <Link className="recommendation-card" to={`/jobs/${rec.job_id}`} key={rec.id}>
          <span className="rank">{String(index + 1).padStart(2, "0")}</span>
          <span className="company-mark">{job.company.slice(0, 1)}</span>
          <div className="recommendation-main">
            <p>{job.company}</p>
            <h2>{job.title}</h2>
            <small>{job.location ?? "地点待确认"}<i>·</i>{rec.qualification_pending ? "资格待确认" : "资格明确"}</small>
            {reason && <small className="pipeline-note">{reason}</small>}
          </div>
          <div className="score"><strong>{rec.final_score.toFixed(1)}</strong><span>综合匹配</span></div>
          <div className="score-details">
            <span>规则 {rec.rule_score.toFixed(1)}</span><span>向量 {rec.vector_score.toFixed(1)}</span><span>LLM {rec.llm_score?.toFixed(1) ?? "—"}</span><Status value={rec.rerank_status} />
          </div>
          <span className="card-arrow" aria-hidden="true">→</span>
        </Link>;
      })}</div>
    </AsyncState>
  </>;
}
