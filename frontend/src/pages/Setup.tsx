import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { AsyncState, Status } from "../components/AsyncState";
import type { Resume } from "../types";

export function Setup() {
  const [file, setFile] = useState<File | null>(null); const client = useQueryClient();
  const resumes = useQuery<Resume[]>({ queryKey: ["resumes"], queryFn: () => api("/api/resumes") });
  const upload = useMutation({ mutationFn: async () => { if (!file) throw new Error("请选择文件"); const form = new FormData(); form.append("file", file); return api<Resume>("/api/resumes", { method: "POST", body: form }); }, onSuccess: () => { void client.invalidateQueries({ queryKey: ["resumes"] }); void client.invalidateQueries({ queryKey: ["profile"] }); } });
  return <><header className="page-head"><div><p className="eyebrow">ONBOARDING</p><h1>导入原始简历</h1><p>支持可复制文本的 PDF 或 UTF-8 Markdown，最多 10 MB。</p></div></header>
    <section className="panel"><form onSubmit={(event) => { event.preventDefault(); upload.mutate(); }}><label htmlFor="resume">简历文件</label><input id="resume" type="file" accept=".pdf,.md,.markdown,application/pdf,text/markdown" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /><button disabled={!file || upload.isPending}>{upload.isPending ? "解析中…" : "上传并解析"}</button>{upload.error && <p role="alert" className="error-text">{upload.error.message}</p>}</form></section>
    <section className="panel"><div className="section-title"><h2>导入历史</h2><Link to="/profile">审核事实 →</Link></div><AsyncState loading={resumes.isLoading} error={resumes.error} empty={!resumes.data?.length}>{resumes.data?.map((resume) => <article className="list-card" key={resume.id}><div><strong>{resume.original_name}</strong><p>{new Date(resume.created_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })} · {resume.facts.length} 条事实</p></div><Status value={resume.parse_status} />{resume.parse_error && <p className="warning full">{resume.parse_error}</p>}</article>)}</AsyncState></section></>;
}

