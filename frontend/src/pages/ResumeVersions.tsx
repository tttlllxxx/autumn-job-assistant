import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { AsyncState, Status } from "../components/AsyncState";
import type { ResumeVersion } from "../types";

export function ResumeVersions() {
  const versions = useQuery<ResumeVersion[]>({ queryKey: ["resume-versions"], queryFn: () => api("/api/resume-versions") });
  return <><header className="page-head"><div><p className="eyebrow">FACT-GROUNDED RESUMES</p><h1>定制简历</h1><p>每个事实性句子必须关联已确认事实，验证失败不生成 PDF。</p></div></header><AsyncState loading={versions.isLoading} error={versions.error} empty={!versions.data?.length}><div className="card-list">{versions.data?.map((version) => <article className="panel version" key={version.id}><div><h2>版本 #{version.id}</h2><p>目标岗位 #{version.job_id} · {new Date(version.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}</p><p>已关联 {version.fact_ids.length} 条事实</p></div><Status value={version.status} />{version.has_pdf && <a className="button secondary" href={`/api/resume-versions/${version.id}/download`}>下载 PDF</a>} {version.status !== "completed" && <pre>{JSON.stringify(version.validation_result, null, 2)}</pre>}</article>)}</div></AsyncState></>;
}
