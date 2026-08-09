import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { AsyncState } from "../components/AsyncState";
import type { Application, Page } from "../types";

const statuses = ["待投递", "已投递", "笔试中", "面试中", "HR 面", "人才库", "Offer 待确认", "Offer 已接收", "Offer 已拒绝", "未通过", "已撤回", "已终止"];
const stages = ["投递", "笔试", "一面", "二面", "三面", "终面", "HR 面", "Offer"];
const results = ["待处理", "待约", "已约", "进行中", "通过", "未通过", "终止", "撤回"];

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
  notes: "",
};

export function Applications() {
  const [showCreate, setShowCreate] = useState(false);
  const [draft, setDraft] = useState<NewApplication>(emptyDraft);
  const client = useQueryClient();
  const items = useQuery<Page<Application>>({ queryKey: ["applications"], queryFn: () => api("/api/applications?page_size=200") });

  const create = useMutation<Application, Error, NewApplication, { previous?: Page<Application>; tempId: number }>({
    mutationFn: (payload) => api("/api/applications", { method: "POST", body: JSON.stringify(payload) }),
    onMutate: async (payload) => {
      await client.cancelQueries({ queryKey: ["applications"] });
      const previous = client.getQueryData<Page<Application>>(["applications"]);
      const tempId = -Date.now();
      const optimistic: Application = { id: tempId, company: payload.company, position: payload.position, status: payload.status, current_stage: payload.current_stage, stage_result: payload.stage_result, base_location: payload.base_location, notes: payload.notes };
      client.setQueryData<Page<Application>>(["applications"], (current) => ({ items: [optimistic, ...(current?.items ?? [])], total: (current?.total ?? 0) + 1, page: 1, page_size: current?.page_size ?? 200 }));
      return { previous, tempId };
    },
    onError: (_error, _payload, context) => client.setQueryData(["applications"], context?.previous),
    onSuccess: (saved, _payload, context) => {
      client.setQueryData<Page<Application>>(["applications"], (current) => current ? { ...current, items: current.items.map((item) => item.id === context?.tempId ? saved : item) } : current);
      setDraft(emptyDraft);
      setShowCreate(false);
    },
    onSettled: () => void client.invalidateQueries({ queryKey: ["applications"] }),
  });

  const update = useMutation<Application, Error, { id: number; changes: Partial<Pick<Application, "status" | "current_stage" | "stage_result">> }, { previous?: Page<Application> }>({
    mutationFn: ({ id, changes }) => api(`/api/applications/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),
    onMutate: async ({ id, changes }) => {
      await client.cancelQueries({ queryKey: ["applications"] });
      const previous = client.getQueryData<Page<Application>>(["applications"]);
      client.setQueryData<Page<Application>>(["applications"], (current) => current ? { ...current, items: current.items.map((item) => item.id === id ? { ...item, ...changes } : item) } : current);
      return { previous };
    },
    onError: (_error, _variables, context) => client.setQueryData(["applications"], context?.previous),
    onSuccess: (saved) => client.setQueryData<Page<Application>>(["applications"], (current) => current ? { ...current, items: current.items.map((item) => item.id === saved.id ? saved : item) } : current),
    onSettled: () => void client.invalidateQueries({ queryKey: ["applications"] }),
  });

  const setField = (field: keyof NewApplication, value: string | null) => setDraft((current) => ({ ...current, [field]: value }));

  return <>
    <header className="page-head"><div><p className="eyebrow">申请进度</p><h1>投递看板</h1><p>所有投递都在这里创建和推进，状态变化会即时保存。</p></div><div className="board-head-actions"><span className="live-indicator"><i />实时保存</span><button onClick={() => setShowCreate((value) => !value)}>{showCreate ? "收起" : "＋ 新增投递"}</button></div></header>

    {showCreate && <section className="panel create-application-panel"><div className="section-title"><div><p className="panel-kicker">新机会</p><h2>添加到投递看板</h2></div></div><form onSubmit={(event) => { event.preventDefault(); create.mutate(draft); }}><div className="application-form-grid"><label className="field" htmlFor="application-company"><span>公司</span><input id="application-company" required autoFocus value={draft.company} onChange={(event) => setField("company", event.target.value)} placeholder="公司名称" /></label><label className="field" htmlFor="application-position"><span>岗位</span><input id="application-position" required value={draft.position} onChange={(event) => setField("position", event.target.value)} placeholder="岗位名称" /></label><label className="field" htmlFor="application-location"><span>地点</span><input id="application-location" value={draft.base_location} onChange={(event) => setField("base_location", event.target.value)} placeholder="例如：上海" /></label><label className="field" htmlFor="application-channel"><span>投递渠道</span><input id="application-channel" value={draft.channel} onChange={(event) => setField("channel", event.target.value)} placeholder="官网 / 内推" /></label><label className="field" htmlFor="application-date"><span>投递日期</span><input id="application-date" type="date" value={draft.applied_date ?? ""} onChange={(event) => setField("applied_date", event.target.value || null)} /></label><label className="field" htmlFor="application-status"><span>初始状态</span><select id="application-status" value={draft.status} onChange={(event) => setField("status", event.target.value)}>{statuses.map((status) => <option key={status}>{status}</option>)}</select></label><label className="field full" htmlFor="application-url"><span>岗位链接</span><input id="application-url" type="url" value={draft.url} onChange={(event) => setField("url", event.target.value)} placeholder="https://..." /></label><label className="field full" htmlFor="application-notes"><span>备注</span><textarea id="application-notes" value={draft.notes} onChange={(event) => setField("notes", event.target.value)} placeholder="内推人、截止日期或下一步计划" /></label></div><div className="form-actions"><button disabled={create.isPending}>{create.isPending ? "保存中…" : "保存到看板"}</button><button type="button" className="secondary" onClick={() => { setDraft(emptyDraft); setShowCreate(false); }}>取消</button></div>{create.error && <p className="error-text" role="alert">{create.error.message}</p>}</form></section>}

    {(update.error && !update.isPending) && <p className="error-text" role="alert">更新失败，已恢复原状态：{update.error.message}</p>}
    <div className="board-toolbar"><span>{items.data?.total ?? 0} 个机会</span><span>修改状态、阶段或结果后自动保存</span></div>
    <AsyncState loading={items.isLoading} error={items.error}><div className="board">{statuses.map((status) => { const columnItems = items.data?.items.filter((item) => item.status === status) ?? []; return <section key={status}><div className="board-column-title"><h2>{status}</h2><span>{columnItems.length}</span></div>{columnItems.length ? columnItems.map((item) => <article key={item.id} className={item.id < 0 ? "saving" : ""}><div className="application-card-head"><span className="company-mark">{item.company.slice(0, 1)}</span><div><strong>{item.company}</strong><p>{item.position}</p></div></div>{item.base_location && <small className="application-meta">⌖ {item.base_location}</small>}<label>状态<select aria-label={`${item.company} 状态`} value={item.status} disabled={item.id < 0} onChange={(event) => update.mutate({ id: item.id, changes: { status: event.target.value } })}>{statuses.map((value) => <option key={value}>{value}</option>)}</select></label><label>阶段<select aria-label={`${item.company} 当前阶段`} value={item.current_stage} disabled={item.id < 0} onChange={(event) => update.mutate({ id: item.id, changes: { current_stage: event.target.value } })}>{stages.map((value) => <option key={value}>{value}</option>)}</select></label><label>结果<select aria-label={`${item.company} 阶段结果`} value={item.stage_result} disabled={item.id < 0} onChange={(event) => update.mutate({ id: item.id, changes: { stage_result: event.target.value } })}>{results.map((value) => <option key={value}>{value}</option>)}</select></label>{item.id < 0 && <small className="saving-label">正在保存…</small>}</article>) : <p className="board-empty">暂无记录</p>}</section>; })}</div></AsyncState>
  </>;
}
