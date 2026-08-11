import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, jsonBody } from "../api";
import { AsyncState, Status } from "../components/AsyncState";
import { type Notice, TaskNotice } from "../components/TaskNotice";
import { formatShanghaiTime } from "../time";
import { taskKeys, useTaskPending } from "../taskState";
import type { Source } from "../types";

export function Sources() {
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [customCompany, setCustomCompany] = useState("");
  const [customUrl, setCustomUrl] = useState("");
  const [editingSource, setEditingSource] = useState<string | null>(null);
  const [sourceEntry, setSourceEntry] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const client = useQueryClient();
  const sources = useQuery<Source[]>({ queryKey: ["sources"], queryFn: () => api("/api/sources") });
  const run = useMutation({
    mutationKey: taskKeys.sourceRun,
    mutationFn: (keys?: string[]) => api<{ results: Array<{ source_key: string; success: boolean; discovered: number; accepted: number; rejected: number; error: string | null }> }>(
      "/api/sources/run",
      jsonBody({ source_keys: keys, allow_browser: true, max_jobs_per_source: 500 }),
    ),
    onMutate: () => setNotice(null),
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: ["sources"] });
      void client.invalidateQueries({ queryKey: ["jobs"] });
      const succeeded = result.results.filter((item) => item.success).length;
      setNotice({
        kind: succeeded === result.results.length ? "success" : "warning",
        message: `来源任务完成：${succeeded}/${result.results.length} 个来源采集成功。`,
      });
    },
    onError: (error) => setNotice({ kind: "error", message: `来源更新失败：${error.message}` }),
  });
  const custom = useMutation({
    mutationKey: taskKeys.customSourceParse,
    mutationFn: () => api<{ success: boolean; discovered: number; new: number; error: string | null }>(
      "/api/sources/custom",
      jsonBody({ company: customCompany, official_entry: customUrl }),
    ),
    onSuccess: (result) => {
      setCustomCompany(""); setCustomUrl("");
      void client.invalidateQueries({ queryKey: ["sources"] });
      void client.invalidateQueries({ queryKey: ["jobs"] });
      setNotice({
        kind: result.success ? "success" : "warning",
        message: result.success
          ? `公司已添加并解析完成：发现 ${result.discovered} 个岗位，新增 ${result.new} 个。`
          : `公司已保存，但本次未解析到完整岗位：${result.error ?? "可稍后单独运行"}`,
      });
    },
    onError: (error) => setNotice({ kind: "error", message: `添加公司失败：${error.message}` }),
  });
  const remove = useMutation({
    mutationFn: (key: string) => api(`/api/sources/custom/${key}`, { method: "DELETE" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["sources"] });
      setNotice({ kind: "success", message: "自定义来源已移除，历史岗位仍保留在岗位库中。" });
    },
    onError: (error) => setNotice({ kind: "error", message: `移除来源失败：${error.message}` }),
  });
  const updateSource = useMutation({
    mutationKey: taskKeys.sourceEntryUpdate,
    mutationFn: ({ sourceKey, officialEntry }: { sourceKey: string; officialEntry: string }) => api<{ success: boolean; discovered: number; new: number; error: string | null }>(
      `/api/sources/${sourceKey}`,
      { ...jsonBody({ official_entry: officialEntry }), method: "PATCH" },
    ),
    onSuccess: (result) => {
      setEditingSource(null); setSourceEntry("");
      void client.invalidateQueries({ queryKey: ["sources"] });
      void client.invalidateQueries({ queryKey: ["jobs"] });
      setNotice({
        kind: result.success ? "success" : "warning",
        message: result.success
          ? `官方入口已更新并解析完成：发现 ${result.discovered} 个岗位，新增 ${result.new} 个。`
          : `官方入口已更新，但本次解析失败：${result.error ?? "可稍后单独运行"}`,
      });
    },
    onError: (error) => setNotice({ kind: "error", message: `官方入口更新失败：${error.message}` }),
  });
  const manual = useMutation({
    mutationFn: () => api("/api/jobs/import", jsonBody({ company, title, url, description })),
    onSuccess: () => {
      setCompany(""); setTitle(""); setUrl(""); setDescription("");
      void client.invalidateQueries({ queryKey: ["jobs"] });
      setNotice({ kind: "success", message: "岗位已保存。" });
    },
  });
  const lastRun = sources.data?.map((item) => item.last_run_at).filter(Boolean).sort().at(-1) ?? null;
  const runPending = useTaskPending(taskKeys.sourceRun);
  const customPending = useTaskPending(taskKeys.customSourceParse);
  const sourceUpdatePending = useTaskPending(taskKeys.sourceEntryUpdate);

  return <>
    <header className="page-head"><div><p className="eyebrow">OFFICIAL SOURCES</p><h1>来源健康</h1><p>优先调用招聘系统的公开接口；无法识别时再解析官方网页和浏览器响应。</p><small className="last-updated">上次更新：{formatShanghaiTime(lastRun)}</small></div><button onClick={() => run.mutate(undefined)} disabled={runPending}>{runPending ? "采集中…" : "立即采集全部"}</button></header>
    <TaskNotice notice={notice} onClose={() => setNotice(null)} />
    {run.error && <p role="alert" className="error-text">{run.error.message}</p>}
    <AsyncState loading={sources.isLoading} error={sources.error} empty={!sources.data?.length}><div className="source-grid">{sources.data?.map((source) => <article className="panel source" key={source.source_key}><div><h2>{source.display_name}{source.custom && <small className="source-badge">自定义</small>}<small className="source-badge">{source.collection_method}</small></h2><Status value={source.status} /></div><div className="source-counts"><strong>{source.active_job_count}</strong><span>个有效岗位</span><small>上次发现 {source.last_discovered_count} 个</small><small>接受 {source.last_accepted_count ?? 0} 个 · 拒绝 {source.last_rejected_count ?? 0} 个</small></div>{(source.last_rejected_count ?? 0) > 0 && <details><summary>查看拒绝原因</summary>{Object.entries(source.last_rejection_reasons ?? {}).map(([reason, count]) => <p className="muted" key={reason}>{reason}：{count}</p>)}</details>}{source.year_unverified_count > 0 && <p className="warning">其中 {source.year_unverified_count} 个岗位的 {source.target_graduation_year ?? "2027"} 届资格待确认</p>}{editingSource === source.source_key ? <form className="source-entry-editor" onSubmit={(event) => { event.preventDefault(); updateSource.mutate({ sourceKey: source.source_key, officialEntry: sourceEntry }); }}><label htmlFor={`source-entry-${source.source_key}`}>{source.display_name} 官方入口</label><input id={`source-entry-${source.source_key}`} type="url" required pattern="https://.*" value={sourceEntry} onChange={(event) => setSourceEntry(event.target.value)} /><div className="actions"><button disabled={sourceUpdatePending}>{sourceUpdatePending ? "更新并解析中…" : "保存并重新解析"}</button><button type="button" className="secondary" disabled={sourceUpdatePending} onClick={() => { setEditingSource(null); setSourceEntry(""); }}>取消</button></div></form> : <a href={source.official_entry} target="_blank" rel="noreferrer">官方入口</a>}<p>上次完成：{formatShanghaiTime(source.last_run_at)}</p><p>上次成功：{formatShanghaiTime(source.last_success_at)}</p><p>连续失败：{source.consecutive_failures}</p>{source.last_error && <p className="warning">{source.last_error}</p>}<div className="actions"><button className="secondary" disabled={runPending || sourceUpdatePending} onClick={() => run.mutate([source.source_key])}>{runPending ? "运行中…" : "单独运行"}</button>{editingSource !== source.source_key && <button className="secondary" disabled={sourceUpdatePending} onClick={() => { setEditingSource(source.source_key); setSourceEntry(source.official_entry); }}>修改官方入口</button>}{source.custom && <button className="danger-link" disabled={remove.isPending || sourceUpdatePending} onClick={() => window.confirm("移除后将不再自动采集，历史岗位会保留。继续？") && remove.mutate(source.source_key)}>移除来源</button>}</div></article>)}</div></AsyncState>
    {run.data && <section className="panel"><h2>本次结果</h2>{run.data.results.map((item) => <div className="row-link" key={item.source_key}><span>{item.source_key}</span><span>{item.success ? `发现 ${item.discovered} · 接受 ${item.accepted} · 拒绝 ${item.rejected}` : item.error ?? "失败"}</span></div>)}</section>}
    <section className="panel"><h2>添加公司来源</h2><p className="muted">填写公司官方招聘页；支持自动识别 Moka、Greenhouse、Lever 和 Ashby，其他站点会解析官方网页及浏览器响应。如官网跳转到第三方 ATS，请填写跳转后的招聘链接。</p><form onSubmit={(event) => { event.preventDefault(); custom.mutate(); }}><label htmlFor="custom-company">公司名称</label><input id="custom-company" required value={customCompany} onChange={(event) => setCustomCompany(event.target.value)} /><label htmlFor="custom-url">官方招聘入口</label><input id="custom-url" type="url" required pattern="https://.*" placeholder="https://careers.example.com/jobs" value={customUrl} onChange={(event) => setCustomUrl(event.target.value)} /><button disabled={customPending}>{customPending ? "正在解析…" : "添加并解析岗位"}</button></form></section>
    <section className="panel"><h2>手工录入官方 JD</h2><p className="muted">当官方站点需要登录或采集失败时，可粘贴官方岗位链接和完整 JD；文本会按不可信输入隔离处理。</p><form onSubmit={(event) => { event.preventDefault(); manual.mutate(); }}><label htmlFor="manual-company">公司</label><input id="manual-company" required value={company} onChange={(event) => setCompany(event.target.value)} /><label htmlFor="manual-title">岗位名称</label><input id="manual-title" required value={title} onChange={(event) => setTitle(event.target.value)} /><label htmlFor="manual-url">官方岗位链接</label><input id="manual-url" type="url" required value={url} onChange={(event) => setUrl(event.target.value)} /><label htmlFor="manual-description">完整 JD（至少 20 字）</label><textarea id="manual-description" required minLength={20} value={description} onChange={(event) => setDescription(event.target.value)} /><button disabled={manual.isPending}>{manual.isPending ? "保存中…" : "保存手工岗位"}</button>{manual.error && <p role="alert" className="error-text">{manual.error.message}</p>}</form></section>
  </>;
}
