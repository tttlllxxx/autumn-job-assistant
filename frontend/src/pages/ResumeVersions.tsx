import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { AsyncState } from "../components/AsyncState";
import { formatShanghaiTime } from "../time";
import type { TailorAdviceSummary } from "../types";

export function ResumeVersions() {
  const advice = useQuery<TailorAdviceSummary[]>({ queryKey: ["tailor-advice-list"], queryFn: () => api("/api/tailor-advice") });

  return <>
    <header className="page-head"><div><p className="eyebrow">JOB-SPECIFIC ADVICE</p><h1>简历修改建议</h1><p>只收录你在岗位推荐页主动生成的岗位建议。</p><small className="last-updated">不再自动生成或保存定制简历文件</small></div></header>
    <section className="panel"><div className="section-title"><div><p className="panel-kicker">已生成</p><h2>按岗位查看建议</h2></div><span>{advice.data?.length ?? 0} 个</span></div>
      <AsyncState loading={advice.isLoading} error={advice.error} empty={!advice.data?.length}><div className="tailor-job-list">{advice.data?.map((item) => <Link className="tailor-job-card" to={`/resumes/jobs/${item.job.id}`} key={item.job.id}><span className="company-mark">{item.job.company.slice(0, 1)}</span><span><small>{item.job.company}</small><strong>{item.job.title}</strong><p>{item.suggestion_count} 条建议 · {formatShanghaiTime(item.updated_at)}</p></span><span className="tailor-card-action">查看修改建议 →</span></Link>)}</div></AsyncState>
    </section>
  </>;
}
