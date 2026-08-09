import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { AsyncState } from "../components/AsyncState";
import { formatShanghaiTime } from "../time";
import type { TailorAdvice as TailorAdviceType } from "../types";

export function TailorAdvice() {
  const { id } = useParams();
  const jobId = Number(id);
  const advice = useQuery<TailorAdviceType>({
    queryKey: ["tailor-advice", jobId],
    queryFn: () => api(`/api/jobs/${jobId}/tailor-advice`),
    enabled: Number.isFinite(jobId),
  });
  return <>
    <header className="page-head job-head"><div><p className="eyebrow">岗位专属建议</p><h1>{advice.data?.job.title ?? "正在读取修改建议…"}</h1><p>{advice.data?.job.company}{advice.data?.job.location && <><i>·</i>{advice.data.job.location}</>}</p>{advice.data && <small className="last-updated">依据推荐 v{advice.data.recommendation_version} · {formatShanghaiTime(advice.data.updated_at)}</small>}</div><div className="actions"><Link className="button secondary" to="/resumes">返回修改建议</Link></div></header>
    <AsyncState loading={advice.isLoading} error={advice.error} empty={!advice.data?.suggestions.length}><section className="panel"><div className="section-title"><div><p className="panel-kicker">逐条修改</p><h2>简历修改建议</h2></div><span>{advice.data?.suggestions.length ?? 0} 条</span></div><div className="advice-list">{advice.data?.suggestions.map((item, index) => <article className="advice-card" key={`${item.section}-${index}`}><div className="advice-index">{String(index + 1).padStart(2, "0")}</div><div><p className="panel-kicker">{item.section}</p><h3>{item.action}</h3><div className="advice-compare"><div className="advice-current"><small>修改前</small><p className="pre-wrap">{item.current_text}</p></div><div className="advice-after"><small>修改后示例</small><p className="pre-wrap">{item.suggested_text}</p></div></div><p className="advice-rationale"><b>为什么这样改：</b>{item.rationale}</p>{item.jd_quote && <blockquote>JD 原文：{item.jd_quote}</blockquote>}</div></article>)}</div></section></AsyncState>
    {!!advice.data?.gaps.length && <section className="panel warning-panel"><h2>缺口处理</h2><p>仅在你确实有相关经历时补充；否则保留为面试准备项，不得写入简历。</p><ul>{advice.data.gaps.map((gap) => <li key={gap}>{gap}</li>)}</ul></section>}
  </>;
}
