import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, jsonBody } from "../api";
import { AsyncState } from "../components/AsyncState";

type Budget = { month: string; budget_rmb: number; used_rmb: number; remaining_rmb: number; llm_enabled: boolean; degraded_reason: string | null; pricing_configured: boolean; llm_provider: string; cost_note: string | null };
type Preferences = { degraded_summary_enabled: boolean; llm_provider: "auto" | "api" | "codex" | "disabled"; effective_llm_provider: string; llm_available: boolean; llm_reason: string | null };
type Evaluation = { status: string; labels: number; required_labels: number; precision_at_10: number | null; unlabeled_top10_job_ids: number[] };
type LLMConfig = { llm_base_url: string | null; llm_model: string | null; llm_input_price_rmb_per_million: number | null; llm_output_price_rmb_per_million: number | null; llm_monthly_budget_rmb: number; api_key_configured: boolean; api_key_source: "local" | "environment" | null };
type LLMConfigUpdate = {
  llm_base_url: string | null;
  llm_api_key: string | null;
  llm_model: string | null;
  llm_input_price_rmb_per_million: number | null;
  llm_output_price_rmb_per_million: number | null;
  llm_monthly_budget_rmb: number | null;
};

const emptyForm = { baseUrl: "", apiKey: "", model: "", inputPrice: "", outputPrice: "", budget: "50" };

export function Settings() {
  const [backupFile, setBackupFile] = useState<File | null>(null);
  const [apiForm, setApiForm] = useState(emptyForm);
  const client = useQueryClient();
  const budget = useQuery<Budget>({ queryKey: ["budget"], queryFn: () => api("/api/settings/budget") });
  const preferences = useQuery<Preferences>({ queryKey: ["preferences"], queryFn: () => api("/api/settings/preferences") });
  const llmConfig = useQuery<LLMConfig>({ queryKey: ["llm-config"], queryFn: () => api("/api/settings/llm") });
  const evaluation = useQuery<Evaluation>({ queryKey: ["evaluation"], queryFn: () => api("/api/evaluation") });

  useEffect(() => {
    if (!llmConfig.data) return;
    setApiForm({
      baseUrl: llmConfig.data.llm_base_url ?? "",
      apiKey: "",
      model: llmConfig.data.llm_model ?? "",
      inputPrice: llmConfig.data.llm_input_price_rmb_per_million?.toString() ?? "",
      outputPrice: llmConfig.data.llm_output_price_rmb_per_million?.toString() ?? "",
      budget: llmConfig.data.llm_monthly_budget_rmb.toString(),
    });
  }, [llmConfig.data]);

  const feishu = useMutation({ mutationFn: () => api<{ success: boolean }>("/api/settings/feishu/test", jsonBody({})) });
  const backup = useMutation({ mutationFn: () => api<{ backup_id: string }>("/api/backups", jsonBody({})) });
  const restore = useMutation({
    mutationFn: async () => {
      if (!backupFile) throw new Error("请选择备份 ZIP");
      const form = new FormData();
      form.append("file", backupFile);
      return api<{ restored_counts: Record<string, number> }>("/api/restore", { method: "POST", body: form });
    },
    onSuccess: () => void client.invalidateQueries(),
  });
  const updatePreferences = useMutation({
    mutationFn: (changes: Partial<Pick<Preferences, "degraded_summary_enabled" | "llm_provider">>) => api<Preferences>("/api/settings/preferences", { method: "PATCH", body: JSON.stringify(changes) }),
    onSuccess: (data) => {
      client.setQueryData(["preferences"], data);
      void client.invalidateQueries({ queryKey: ["budget"] });
    },
  });
  const updateLLMConfig = useMutation({
    mutationFn: (changes: Partial<LLMConfigUpdate>) => api<LLMConfig>("/api/settings/llm", { method: "PATCH", body: JSON.stringify(changes) }),
    onSuccess: (data) => {
      client.setQueryData(["llm-config"], data);
      setApiForm((current) => ({ ...current, apiKey: "" }));
      void client.invalidateQueries({ queryKey: ["preferences"] });
      void client.invalidateQueries({ queryKey: ["budget"] });
    },
  });

  const setField = (field: keyof typeof apiForm, value: string) => setApiForm((current) => ({ ...current, [field]: value }));
  const nullableNumber = (value: string) => value.trim() === "" ? null : Number(value);
  const saveAPIConfig = () => {
    const changes: Partial<LLMConfigUpdate> = {
      llm_base_url: apiForm.baseUrl.trim() || null,
      llm_model: apiForm.model.trim() || null,
      llm_input_price_rmb_per_million: nullableNumber(apiForm.inputPrice),
      llm_output_price_rmb_per_million: nullableNumber(apiForm.outputPrice),
      llm_monthly_budget_rmb: nullableNumber(apiForm.budget),
    };
    if (apiForm.apiKey.trim()) changes.llm_api_key = apiForm.apiKey.trim();
    updateLLMConfig.mutate(changes);
  };

  return <>
    <header className="page-head"><div><p className="eyebrow">系统设置</p><h1>模型、预算与数据</h1><p>配置模型调用方式，管理成本与本地数据备份。</p></div></header>

    <AsyncState loading={budget.isLoading || preferences.isLoading || llmConfig.isLoading} error={(budget.error ?? preferences.error ?? llmConfig.error) as Error | null}>
      <section className="panel settings-provider">
        <div><p className="panel-kicker">调用方式</p><h2>模型提供方</h2><p className="muted">API 配置完整时，“自动”会优先调用 API，否则使用本机 Codex。</p></div>
        <div className="provider-control"><label htmlFor="llm-provider">当前选择</label><select id="llm-provider" value={preferences.data?.llm_provider ?? "auto"} disabled={updatePreferences.isPending} onChange={(event) => updatePreferences.mutate({ llm_provider: event.target.value as Preferences["llm_provider"] })}><option value="auto">自动选择</option><option value="codex">Codex 本地登录</option><option value="api">OpenAI-compatible API</option><option value="disabled">关闭模型</option></select><small>当前生效：{preferences.data?.effective_llm_provider ?? "检测中"}</small></div>
      </section>

      <section className="panel api-config-panel">
        <div className="section-title"><div><p className="panel-kicker">OpenAI Compatible</p><h2>API 配置</h2></div>{llmConfig.data?.api_key_configured && <span className="configured-state"><i />Key 已配置（{llmConfig.data.api_key_source === "local" ? "页面" : "环境变量"}）</span>}</div>
        <p className="muted config-note">配置只保存在当前设备。API Key 不会回显，也不会写入备份文件。</p>
        <form className="api-config-form" onSubmit={(event) => { event.preventDefault(); saveAPIConfig(); }}>
          <div className="settings-form-grid">
            <label className="field full" htmlFor="llm-base-url"><span>API Base URL</span><input id="llm-base-url" type="url" value={apiForm.baseUrl} onChange={(event) => setField("baseUrl", event.target.value)} placeholder="https://api.openai.com/v1" /><small>不包含末尾的 /chat/completions</small></label>
            <label className="field" htmlFor="llm-api-key"><span>API Key</span><input id="llm-api-key" type="password" autoComplete="off" value={apiForm.apiKey} onChange={(event) => setField("apiKey", event.target.value)} placeholder={llmConfig.data?.api_key_configured ? "已配置；留空则保持不变" : "sk-..."} /></label>
            <label className="field" htmlFor="llm-model"><span>模型名称</span><input id="llm-model" value={apiForm.model} onChange={(event) => setField("model", event.target.value)} placeholder="gpt-5-mini" /></label>
            <label className="field" htmlFor="llm-input-price"><span>输入价格（元 / 百万 token）</span><input id="llm-input-price" type="number" min="0" step="any" value={apiForm.inputPrice} onChange={(event) => setField("inputPrice", event.target.value)} placeholder="0" /></label>
            <label className="field" htmlFor="llm-output-price"><span>输出价格（元 / 百万 token）</span><input id="llm-output-price" type="number" min="0" step="any" value={apiForm.outputPrice} onChange={(event) => setField("outputPrice", event.target.value)} placeholder="0" /></label>
            <label className="field" htmlFor="llm-budget"><span>每月预算（元）</span><input id="llm-budget" type="number" min="0" step="any" required value={apiForm.budget} onChange={(event) => setField("budget", event.target.value)} /></label>
          </div>
          <div className="form-actions"><button disabled={updateLLMConfig.isPending}>{updateLLMConfig.isPending ? "保存中…" : "保存 API 配置"}</button>{llmConfig.data?.api_key_configured && <button type="button" className="danger-link" disabled={updateLLMConfig.isPending} onClick={() => window.confirm("确认清除已保存的 API Key？") && updateLLMConfig.mutate({ llm_api_key: null })}>清除 Key</button>}{updateLLMConfig.isSuccess && <span className="success">配置已保存</span>}</div>
          {updateLLMConfig.error && <p className="error-text" role="alert">{updateLLMConfig.error.message}</p>}
        </form>
      </section>

      <div className="grid two"><section className="panel"><p className="panel-kicker">本月用量</p><h2>LLM API 预算</h2><div className="budget"><strong>¥{budget.data?.used_rmb.toFixed(4)}</strong><span>/ ¥{budget.data?.budget_rmb.toFixed(2)} · 剩余 ¥{budget.data?.remaining_rmb.toFixed(4)}</span></div><progress max={budget.data?.budget_rmb || 1} value={budget.data?.used_rmb ?? 0} aria-label="本月 LLM API 预算使用量" />{budget.data?.cost_note && <p className="muted">{budget.data.cost_note}</p>}{!budget.data?.llm_enabled && <p className="warning">降级模式：{budget.data?.degraded_reason}</p>}<label className="check-row"><input type="checkbox" checked={preferences.data?.degraded_summary_enabled ?? false} disabled={updatePreferences.isPending} onChange={(event) => updatePreferences.mutate({ degraded_summary_enabled: event.target.checked })} />允许飞书发送降级 Top3 摘要</label>{updatePreferences.error && <p className="error-text" role="alert">{updatePreferences.error.message}</p>}</section>
      <section className="panel"><p className="panel-kicker">推荐质量</p><h2>精度样本</h2>{evaluation.isLoading ? <p>统计中…</p> : evaluation.error ? <p className="error-text">{evaluation.error.message}</p> : <><p>已判断 {evaluation.data?.labels ?? 0} / {evaluation.data?.required_labels ?? 50} 个岗位</p><progress max={evaluation.data?.required_labels ?? 50} value={evaluation.data?.labels ?? 0} aria-label="推荐精度样本收集进度" />{evaluation.data?.precision_at_10 == null ? <p className="muted">继续在岗位详情选择“符合/不符合”；当前 Top10 也必须全部判断。</p> : <p className={evaluation.data.precision_at_10 >= .7 ? "success" : "warning"}>Precision@10：{(evaluation.data.precision_at_10 * 100).toFixed(0)}%</p>}</>}</section></div>
    </AsyncState>

    <div className="grid two"><section className="panel"><p className="panel-kicker">通知</p><h2>飞书 Webhook</h2><p className="muted">测试消息不包含姓名、联系方式或简历正文。</p><button className="secondary" onClick={() => feishu.mutate()} disabled={feishu.isPending}>测试 Webhook</button>{feishu.data && <p className="success">测试成功</p>}{feishu.error && <p className="error-text" role="alert">{feishu.error.message}</p>}</section>
    <section className="panel"><p className="panel-kicker">数据安全</p><h2>创建备份</h2><p className="muted">包含业务数据和简历文件，不包含密码、会话与密钥。</p><button className="secondary" onClick={() => backup.mutate()} disabled={backup.isPending}>创建版本化 ZIP</button>{backup.data && <p className="success">已创建：<a href={`/api/backups/${backup.data.backup_id}/download`}>下载备份</a></p>}{backup.error && <p className="error-text" role="alert">{backup.error.message}</p>}</section></div>
    <section className="panel danger-zone"><p className="panel-kicker">谨慎操作</p><h2>恢复备份</h2><p>恢复会替换画像、岗位、推荐、投递和简历版本；当前密钥保持不变。</p><div className="inline-form"><label htmlFor="backup-zip">备份 ZIP</label><input id="backup-zip" type="file" accept=".zip,application/zip" onChange={(event) => setBackupFile(event.target.files?.[0] ?? null)} /><button className="danger" disabled={!backupFile || restore.isPending} onClick={() => window.confirm("确认验证并恢复该备份？当前业务数据将被替换。") && restore.mutate()}>验证并恢复</button></div>{restore.data && <p className="success">恢复完成，共 {Object.values(restore.data.restored_counts).reduce((a, b) => a + b, 0)} 条/项。</p>}{restore.error && <p className="error-text" role="alert">{restore.error.message}</p>}</section>
  </>;
}
