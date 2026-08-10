import { Fragment, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { AsyncState } from "../components/AsyncState";
import { formatShanghaiTime } from "../time";
import type { Application, Page } from "../types";

const statuses = ["待投递", "已投递", "笔试中", "面试中", "HR 面", "人才库", "Offer 待确认", "Offer 已接收", "Offer 已拒绝", "未通过", "已撤回", "已终止"];
const stages = ["投递", "笔试", "一面", "二面", "三面", "终面", "HR 面", "Offer"];
const results = ["待处理", "待约", "已约", "进行中", "通过", "未通过", "终止", "撤回"];
const terminalStatuses = new Set(["Offer 已接收", "Offer 已拒绝", "未通过", "已撤回", "已终止"]);

type EditableField = "status" | "current_stage" | "stage_result" | "next_action" | "next_action_at" | "channel" | "contact" | "interview_time" | "referral_code" | "result" | "notes";
type ApplicationUpdate = { id: number; changes: Partial<Pick<Application, EditableField>> };
type SortMode = "updated" | "deadline" | "position" | "company";
type SortDirection = "asc" | "desc";

type NewApplication = {
  company: string;
  position: string;
  base_location: string;
  channel: string;
  url: string;
  applied_date: string | null;
  status: string;
  current_stage: string;
  stage_result: string;
  next_action: string;
  next_action_at: string | null;
  notes: string;
};

const emptyDraft: NewApplication = {
  company: "",
  position: "",
  base_location: "",
  channel: "官网",
  url: "",
  applied_date: null,
  status: "待投递",
  current_stage: "投递",
  stage_result: "待处理",
  next_action: "",
  next_action_at: null,
  notes: "",
};

function localDateTime(value: string | null | undefined): string {
  return value ? value.slice(0, 16) : "";
}

function deadlineClass(value: string | null): string {
  if (!value) return "";
  const remaining = new Date(value).getTime() - Date.now();
  if (remaining < 0) return "overdue";
  return remaining <= 3 * 24 * 60 * 60 * 1000 ? "due-soon" : "";
}

function optimisticApplication(payload: NewApplication, id: number): Application {
  return {
    id,
    job_id: null,
    company: payload.company,
    channel: payload.channel,
    position: payload.position,
    position_type: "",
    department: "",
    url: payload.url,
    base_location: payload.base_location,
    applied_date: payload.applied_date,
    status: payload.status,
    current_stage: payload.current_stage,
    stage_result: payload.stage_result,
    next_action: payload.next_action,
    next_action_at: payload.next_action_at,
    progress_updated_at: new Date().toISOString(),
    referral_code: "",
    contact: "",
    interview_time: null,
    result: "",
    notes: payload.notes,
    created_at: new Date().toISOString(),
  };
}

export function Applications() {
  const [showCreate, setShowCreate] = useState(false);
  const [draft, setDraft] = useState<NewApplication>(emptyDraft);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("全部状态");
  const [stageFilter, setStageFilter] = useState("全部阶段");
  const [sortMode, setSortMode] = useState<SortMode>("updated");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const location = useLocation();
  const client = useQueryClient();
  const items = useQuery<Page<Application>>({ queryKey: ["applications"], queryFn: () => api("/api/applications?page_size=200") });

  useEffect(() => {
    if (!items.isSuccess || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [items.isSuccess, location.hash]);

  const create = useMutation<Application, Error, NewApplication, { previous?: Page<Application>; tempId: number }>({
    mutationFn: (payload) => api("/api/applications", { method: "POST", body: JSON.stringify(payload) }),
    onMutate: async (payload) => {
      await client.cancelQueries({ queryKey: ["applications"] });
      const previous = client.getQueryData<Page<Application>>(["applications"]);
      const tempId = -Date.now();
      client.setQueryData<Page<Application>>(["applications"], (current) => ({
        items: [optimisticApplication(payload, tempId), ...(current?.items ?? [])],
        total: (current?.total ?? 0) + 1,
        page: 1,
        page_size: current?.page_size ?? 200,
      }));
      return { previous, tempId };
    },
    onError: (_error, _payload, context) => client.setQueryData(["applications"], context?.previous),
    onSuccess: (saved, _payload, context) => {
      client.setQueryData<Page<Application>>(["applications"], (current) => current
        ? { ...current, items: current.items.map((item) => item.id === context?.tempId ? saved : item) }
        : current);
      setDraft(emptyDraft);
      setShowCreate(false);
    },
    onSettled: () => void client.invalidateQueries({ queryKey: ["applications"] }),
  });

  const update = useMutation<Application, Error, ApplicationUpdate, { previous?: Page<Application> }>({
    mutationFn: ({ id, changes }) => api(`/api/applications/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
    onMutate: async ({ id, changes }) => {
      await client.cancelQueries({ queryKey: ["applications"] });
      const previous = client.getQueryData<Page<Application>>(["applications"]);
      client.setQueryData<Page<Application>>(["applications"], (current) => current
        ? { ...current, items: current.items.map((item) => item.id === id ? { ...item, ...changes } : item) }
        : current);
      return { previous };
    },
    onError: (_error, _variables, context) => client.setQueryData(["applications"], context?.previous),
    onSuccess: (saved) => client.setQueryData<Page<Application>>(["applications"], (current) => current
      ? { ...current, items: current.items.map((item) => item.id === saved.id ? saved : item) }
      : current),
    onSettled: () => void client.invalidateQueries({ queryKey: ["applications"] }),
  });

  const deleteApplication = useMutation<{ removed: number }, Error, number, { previous?: Page<Application> }>({
    mutationFn: (id) => api(`/api/applications/${id}`, { method: "DELETE" }),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: ["applications"] });
      const previous = client.getQueryData<Page<Application>>(["applications"]);
      client.setQueryData<Page<Application>>(["applications"], (current) => current
        ? { ...current, items: current.items.filter((item) => item.id !== id), total: Math.max(0, current.total - 1) }
        : current);
      if (expandedId === id) setExpandedId(null);
      return { previous };
    },
    onError: (_error, _id, context) => client.setQueryData(["applications"], context?.previous),
    onSettled: () => void client.invalidateQueries({ queryKey: ["applications"] }),
  });

  const allItems = items.data?.items ?? [];
  const visibleItems = useMemo(() => {
    const keyword = search.trim().toLocaleLowerCase();
    return allItems
      .filter((item) => !keyword || `${item.company} ${item.position} ${item.department} ${item.base_location}`.toLocaleLowerCase().includes(keyword))
      .filter((item) => statusFilter === "全部状态" || item.status === statusFilter)
      .filter((item) => stageFilter === "全部阶段" || item.current_stage === stageFilter)
      .sort((left, right) => {
        const direction = sortDirection === "asc" ? 1 : -1;
        if (sortMode === "company") {
          return direction * `${left.company}${left.position}`.localeCompare(`${right.company}${right.position}`, "zh-CN");
        }
        if (sortMode === "position") {
          return direction * `${left.position}${left.company}`.localeCompare(`${right.position}${right.company}`, "zh-CN");
        }
        if (sortMode === "deadline") {
          if (!left.next_action_at && !right.next_action_at) return 0;
          if (!left.next_action_at) return 1;
          if (!right.next_action_at) return -1;
          return direction * (new Date(left.next_action_at).getTime() - new Date(right.next_action_at).getTime());
        }
        return direction * (
          new Date(left.progress_updated_at ?? left.created_at).getTime()
          - new Date(right.progress_updated_at ?? right.created_at).getTime()
        );
      });
  }, [allItems, search, sortDirection, sortMode, stageFilter, statusFilter]);

  const resetControls = () => {
    setSearch("");
    setStatusFilter("全部状态");
    setStageFilter("全部阶段");
    setSortMode("updated");
    setSortDirection("desc");
  };
  const controlsChanged = Boolean(search.trim())
    || statusFilter !== "全部状态"
    || stageFilter !== "全部阶段"
    || sortMode !== "updated"
    || sortDirection !== "desc";

  const activeCount = allItems.filter((item) => !terminalStatuses.has(item.status)).length;
  const actionCount = allItems.filter((item) => !terminalStatuses.has(item.status) && (item.next_action ?? "").trim()).length;
  const urgentCount = allItems.filter((item) => {
    if (terminalStatuses.has(item.status) || !item.next_action_at) return false;
    const remaining = new Date(item.next_action_at).getTime() - Date.now();
    return remaining <= 3 * 24 * 60 * 60 * 1000;
  }).length;
  const setField = (field: keyof NewApplication, value: string | null) => setDraft((current) => ({ ...current, [field]: value }));
  const saveText = (item: Application, field: EditableField, value: string | null) => {
    if (value !== item[field]) update.mutate({ id: item.id, changes: { [field]: value } });
  };

  return <>
    <header className="page-head"><div><p className="eyebrow">申请进度</p><h1>投递进度表</h1><p>每个岗位一行，集中处理当前阶段、下一步和关键时间。</p></div><div className="board-head-actions"><span className="live-indicator"><i />实时保存</span><button onClick={() => setShowCreate((value) => !value)}>{showCreate ? "收起" : "＋ 新增投递"}</button></div></header>

    {showCreate && <section className="panel create-application-panel"><div className="section-title"><div><p className="panel-kicker">新机会</p><h2>添加到投递进度表</h2></div></div><form onSubmit={(event) => { event.preventDefault(); create.mutate(draft); }}><div className="application-form-grid"><label className="field" htmlFor="application-company"><span>公司</span><input id="application-company" required autoFocus value={draft.company} onChange={(event) => setField("company", event.target.value)} placeholder="公司名称" /></label><label className="field" htmlFor="application-position"><span>岗位</span><input id="application-position" required value={draft.position} onChange={(event) => setField("position", event.target.value)} placeholder="岗位名称" /></label><label className="field" htmlFor="application-location"><span>地点</span><input id="application-location" value={draft.base_location} onChange={(event) => setField("base_location", event.target.value)} placeholder="例如：上海" /></label><label className="field" htmlFor="application-channel"><span>投递渠道</span><input id="application-channel" value={draft.channel} onChange={(event) => setField("channel", event.target.value)} placeholder="官网 / 内推" /></label><label className="field" htmlFor="application-date"><span>投递日期</span><input id="application-date" type="date" value={draft.applied_date ?? ""} onChange={(event) => setField("applied_date", event.target.value || null)} /></label><label className="field" htmlFor="application-status"><span>初始状态</span><select id="application-status" value={draft.status} onChange={(event) => setField("status", event.target.value)}>{statuses.map((status) => <option key={status}>{status}</option>)}</select></label><label className="field" htmlFor="application-next-action"><span>下一步行动</span><input id="application-next-action" value={draft.next_action} onChange={(event) => setField("next_action", event.target.value)} placeholder="例如：完成笔试" /></label><label className="field" htmlFor="application-next-action-at"><span>行动截止时间</span><input id="application-next-action-at" type="datetime-local" value={draft.next_action_at ?? ""} onChange={(event) => setField("next_action_at", event.target.value || null)} /></label><label className="field full" htmlFor="application-url"><span>岗位链接</span><input id="application-url" type="url" value={draft.url} onChange={(event) => setField("url", event.target.value)} placeholder="https://..." /></label><label className="field full" htmlFor="application-notes"><span>备注</span><textarea id="application-notes" value={draft.notes} onChange={(event) => setField("notes", event.target.value)} placeholder="内推人、面试准备或补充信息" /></label></div><div className="form-actions"><button disabled={create.isPending}>{create.isPending ? "保存中…" : "保存到进度表"}</button><button type="button" className="secondary" onClick={() => { setDraft(emptyDraft); setShowCreate(false); }}>取消</button></div>{create.error && <p className="error-text" role="alert">{create.error.message}</p>}</form></section>}

    <section className="application-summary" aria-label="投递概览"><article><span>全部岗位</span><strong>{allItems.length}</strong></article><article><span>进行中</span><strong>{activeCount}</strong></article><article><span>已有下一步</span><strong>{actionCount}</strong></article><article className={urgentCount ? "attention" : ""}><span>临近或已超期</span><strong>{urgentCount}</strong></article></section>

    <section className="application-controls" aria-label="筛选投递">
      <label className="application-search"><span className="sr-only">搜索岗位或公司</span><input aria-label="搜索岗位或公司" type="search" placeholder="搜索岗位、公司、部门或城市" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <label><span className="sr-only">按状态筛选</span><select aria-label="按状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option>全部状态</option>{statuses.map((status) => <option key={status}>{status}</option>)}</select></label>
      <label><span className="sr-only">按阶段筛选</span><select aria-label="按阶段筛选" value={stageFilter} onChange={(event) => setStageFilter(event.target.value)}><option>全部阶段</option>{stages.map((stage) => <option key={stage}>{stage}</option>)}</select></label>
      <label><span className="sr-only">排序方式</span><select aria-label="排序方式" value={sortMode} onChange={(event) => { const nextMode = event.target.value as SortMode; setSortMode(nextMode); setSortDirection(nextMode === "updated" ? "desc" : "asc"); }}><option value="updated">最近更新</option><option value="deadline">截止时间</option><option value="position">岗位名称</option><option value="company">公司名称</option></select></label>
      <button type="button" className="secondary application-sort-direction" aria-label={`当前${sortDirection === "asc" ? "升序" : "降序"}，点击切换`} onClick={() => setSortDirection((current) => current === "asc" ? "desc" : "asc")}>{sortDirection === "asc" ? "↑ 升序" : "↓ 降序"}</button>
      <span>{visibleItems.length} / {allItems.length} 个岗位</span>
      <button type="button" className="text-button application-reset-controls" disabled={!controlsChanged} onClick={resetControls}>重置</button>
    </section>

    {(update.error && !update.isPending) && <p className="error-text" role="alert">更新失败，已恢复原状态：{update.error.message}</p>}
    {(deleteApplication.error && !deleteApplication.isPending) && <p className="error-text" role="alert">删除失败，已恢复投递记录：{deleteApplication.error.message}</p>}
    <AsyncState loading={items.isLoading} error={items.error} empty={!allItems.length}>
      {visibleItems.length ? <div className="application-table-shell"><table className="application-table"><thead><tr><th>岗位</th><th>状态</th><th>当前进度</th><th>下一步行动</th><th>截止时间</th><th>最近更新</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{visibleItems.map((item) => {
        const saving = update.isPending && update.variables?.id === item.id;
        const deleting = deleteApplication.isPending && deleteApplication.variables === item.id;
        const expanded = expandedId === item.id;
        return <Fragment key={item.id}><tr id={`application-${item.id}`} className={`${saving || deleting || item.id < 0 ? "saving" : ""} ${terminalStatuses.has(item.status) ? "terminal" : ""}`}><td data-label="岗位"><div className="application-job"><strong>{item.position}</strong></div></td><td data-label="状态"><select aria-label={`${item.position} 状态`} value={item.status} disabled={item.id < 0} onChange={(event) => update.mutate({ id: item.id, changes: { status: event.target.value } })}>{statuses.map((value) => <option key={value}>{value}</option>)}</select></td><td data-label="当前进度"><div className="progress-selects"><select aria-label={`${item.position} 当前阶段`} value={item.current_stage} disabled={item.id < 0} onChange={(event) => update.mutate({ id: item.id, changes: { current_stage: event.target.value } })}>{stages.map((value) => <option key={value}>{value}</option>)}</select><select aria-label={`${item.position} 阶段结果`} value={item.stage_result} disabled={item.id < 0} onChange={(event) => update.mutate({ id: item.id, changes: { stage_result: event.target.value } })}>{results.map((value) => <option key={value}>{value}</option>)}</select></div></td><td data-label="下一步行动"><input className="table-text-input" aria-label={`${item.position} 下一步行动`} defaultValue={item.next_action} disabled={item.id < 0} placeholder="填写下一步" onBlur={(event) => saveText(item, "next_action", event.target.value.trim())} /></td><td data-label="截止时间"><input className={`table-date-input ${deadlineClass(item.next_action_at)}`} aria-label={`${item.position} 截止时间`} type="datetime-local" value={localDateTime(item.next_action_at)} disabled={item.id < 0} onChange={(event) => update.mutate({ id: item.id, changes: { next_action_at: event.target.value || null } })} /></td><td data-label="最近更新"><span className="application-updated">{formatShanghaiTime(item.progress_updated_at ?? item.created_at, "尚未更新")}</span>{saving && <small className="saving-label">保存中…</small>}{deleting && <small className="saving-label">删除中…</small>}</td><td className="application-row-action"><div className="application-row-actions"><button className="text-button" disabled={deleting} aria-expanded={expanded} onClick={() => setExpandedId(expanded ? null : item.id)}>{expanded ? "收起" : "详情"}</button><button className="danger-link" disabled={deleting || item.id < 0} aria-label={`删除 ${item.position}`} onClick={() => window.confirm(`确认从投递进度中删除“${item.position}”？`) && deleteApplication.mutate(item.id)}>删除</button></div></td></tr>{expanded && <tr className="application-detail-row"><td colSpan={7}><div className="application-detail"><div className="application-detail-meta"><p><span>投递渠道</span><b>{item.channel || "未填写"}</b></p><p><span>业务部门</span><b>{item.department || "未填写"}</b></p><p><span>岗位类型</span><b>{item.position_type || "未填写"}</b></p><p><span>投递日期</span><b>{item.applied_date || "未填写"}</b></p></div><div className="application-detail-form"><label><span>联系人 / 内推人</span><input defaultValue={item.contact} onBlur={(event) => saveText(item, "contact", event.target.value.trim())} /></label><label><span>面试时间</span><input type="datetime-local" value={localDateTime(item.interview_time)} onChange={(event) => update.mutate({ id: item.id, changes: { interview_time: event.target.value || null } })} /></label><label><span>内推码</span><input defaultValue={item.referral_code} onBlur={(event) => saveText(item, "referral_code", event.target.value.trim())} /></label><label><span>最终结果</span><input defaultValue={item.result} onBlur={(event) => saveText(item, "result", event.target.value.trim())} /></label><label className="full"><span>备注</span><textarea defaultValue={item.notes} onBlur={(event) => saveText(item, "notes", event.target.value.trim())} /></label></div><div className="application-detail-actions">{item.job_id && <Link className="button secondary" to={`/jobs/${item.job_id}`}>查看岗位详情</Link>}{item.url && <a className="button secondary" href={item.url} target="_blank" rel="noreferrer">打开官方职位 ↗</a>}</div></div></td></tr>}</Fragment>;
      })}</tbody></table></div> : <section className="panel application-filter-empty"><p>没有符合当前筛选条件的岗位。</p><button className="secondary" onClick={resetControls}>清除筛选</button></section>}
    </AsyncState>
  </>;
}
