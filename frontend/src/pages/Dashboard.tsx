import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { AsyncState, Status } from "../components/AsyncState";
import type { Application, Job, Page, Profile, Recommendation, Source } from "../types";

export function Dashboard() {
  const profile = useQuery<Profile>({ queryKey: ["profile"], queryFn: () => api("/api/profile"), retry: false });
  const jobs = useQuery<Page<Job>>({ queryKey: ["jobs", "summary"], queryFn: () => api("/api/jobs?page_size=1") });
  const recs = useQuery<Page<Recommendation>>({ queryKey: ["recommendations", "summary"], queryFn: () => api("/api/recommendations?page_size=10&include_pending=false") });
  const sources = useQuery<Source[]>({ queryKey: ["sources"], queryFn: () => api("/api/sources") });
  const applications = useQuery<Page<Application>>({ queryKey: ["applications", "summary"], queryFn: () => api("/api/applications?page_size=1") });
  const profileMissing = profile.error instanceof ApiError && profile.error.status === 404;
  const error = (profileMissing ? null : profile.error) ?? jobs.error ?? recs.error ?? sources.error ?? applications.error;
  const nextStep = profileMissing ? { to: "/setup", title: "导入第一份简历", note: "上传 PDF 或 Markdown，几分钟内建立可追溯的求职画像。" } : !profile.data?.confirmed ? { to: "/profile", title: "确认求职画像", note: "审核简历事实后，系统才能给出可信推荐。" } : !recs.data?.total ? { to: "/recommendations", title: "生成首批推荐", note: "画像已就绪，现在可以计算岗位匹配度。" } : { to: "/recommendations", title: "查看今日推荐", note: "逐个判断是否符合，推荐精度会自动统计。" };
  return <><header className="page-head"><div><p className="eyebrow">个人工作台</p><h1>今天，从合适的机会开始</h1><p>岗位、简历与投递进度都在一个地方。</p></div><Link className="button" to="/sources">采集最新岗位 <span aria-hidden="true">↗</span></Link></header>
    <AsyncState loading={[profile, jobs, recs, sources, applications].some((item) => item.isLoading)} error={error as Error | null}>
      <section className="metrics"><article><span>画像状态</span><strong>{profileMissing ? "未创建" : profile.data?.confirmed ? "已就绪" : "待确认"}</strong><small>{profileMissing ? "先导入一份简历" : profile.data?.confirmed ? "可参与完整匹配" : "完成后解锁推荐"}</small></article><article><span>岗位库</span><strong>{jobs.data?.total ?? 0}</strong><small>已收录的有效岗位</small></article><article><span>推荐结果</span><strong>{recs.data?.total ?? 0}</strong><small>按匹配度排序</small></article><article><span>投递记录</span><strong>{applications.data?.total ?? 0}</strong><small>覆盖全部申请阶段</small></article></section>
      <div className="dashboard-grid"><section className="panel"><div className="section-title"><div><p className="panel-kicker">优先处理</p><h2>高分推荐</h2></div><Link to="/recommendations">查看全部</Link></div>{recs.data?.items.length ? recs.data.items.slice(0, 5).map((rec, index) => <Link className="row-link recommendation-row" key={rec.id} to={`/jobs/${rec.job_id}`}><span className="row-rank">{String(index + 1).padStart(2, "0")}</span><span><b>{rec.job.title}</b><small>{rec.job.company}</small></span><strong>{rec.final_score.toFixed(1)}</strong></Link>) : <div className="empty-inline"><p>还没有推荐结果</p><span>确认画像并运行推荐后，会在这里显示最匹配的岗位。</span></div>}</section>
      <div className="grid"><Link className="next-step" to={nextStep.to}><span className="panel-kicker">下一步</span><strong>{nextStep.title}</strong><p>{nextStep.note}</p><i aria-hidden="true">→</i></Link><section className="panel"><div className="section-title"><h2>来源状态</h2><Link to="/sources">管理来源</Link></div>{sources.data?.slice(0, 5).map((source) => <div className="row-link" key={source.source_key}><span>{source.display_name}</span><Status value={source.status} /></div>)}</section></div></div>
    </AsyncState></>;
}
