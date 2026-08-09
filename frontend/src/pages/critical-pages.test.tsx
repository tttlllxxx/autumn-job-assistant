import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { App } from "../App";
import { Applications } from "./Applications";
import { Dashboard } from "./Dashboard";
import { JobDetail } from "./JobDetail";
import { Profile } from "./Profile";
import { Recommendations } from "./Recommendations";
import { ResumeVersions } from "./ResumeVersions";
import { Settings } from "./Settings";
import { Sources } from "./Sources";
import { TailorAdvice } from "./TailorAdvice";

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
}

function renderWithClient(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("关键页面交互", () => {
  it("打开应用后自动建立本地会话并进入仪表盘", async () => {
    const profile = { id: 1, target_directions: [], skills: [], education_level: null, experience_summary: "", project_summary: "", target_cities: [], remote_preference: null, exclude_keywords: [], confirmed: false, version: 1, updated_at: "2026-08-05T00:00:00Z" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/auth/local-session") return jsonResponse({ authenticated: true, csrf_token: "fictional-csrf" });
      if (path === "/api/profile") return jsonResponse(profile);
      if (path === "/api/sources") return jsonResponse([]);
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 10 });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter initialEntries={["/"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "今天，从合适的机会开始" })).toBeInTheDocument();
    expect(localStorage.getItem("csrf_token")).toBe("fictional-csrf");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/local-session",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("投递进度表以岗位为行并通过 PATCH 实时更新", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    let deleted = false;
    const application = {
      id: 1,
      job_id: 7,
      company: "虚构科技",
      position: "RAG 工程师",
      status: "已投递",
      current_stage: "投递",
      stage_result: "待处理",
      base_location: "北京",
      next_action: "准备笔试",
      next_action_at: "2026-08-12T18:00:00",
      progress_updated_at: "2026-08-09T08:00:00Z",
      created_at: "2026-08-08T08:00:00Z",
      channel: "官网",
      department: "AI 平台",
      position_type: "校园招聘",
      applied_date: "2026-08-08",
      url: "https://jobs.example.invalid/7",
      contact: "",
      interview_time: null,
      referral_code: "",
      result: "",
      notes: "",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.startsWith("/api/applications/") && init?.method === "PATCH") {
        return jsonResponse({ ...application, ...JSON.parse(String(init.body)) });
      }
      if (path === "/api/applications/1" && init?.method === "DELETE") {
        deleted = true;
        return jsonResponse({ removed: 1 });
      }
      return jsonResponse({ items: deleted ? [] : [application], total: deleted ? 0 : 1, page: 1, page_size: 200 });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter><Applications /></MemoryRouter>);
    expect(await screen.findByText("RAG 工程师")).toBeInTheDocument();
    expect(screen.queryByText(/虚构科技/)).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "下一步行动" })).toBeInTheDocument();
    expect(screen.getByLabelText("RAG 工程师 当前阶段")).toHaveValue("投递");
    expect(screen.getByLabelText("RAG 工程师 下一步行动")).toHaveValue("准备笔试");
    expect(screen.queryByLabelText("导入 CSV")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "导出 CSV" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("RAG 工程师 状态"), { target: { value: "面试中" } });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/applications/1",
        expect.objectContaining({
          method: "PATCH",
          headers: expect.any(Headers),
          body: JSON.stringify({ status: "面试中" }),
        }),
      );
    });
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(new Headers(patchCall?.[1]?.headers).get("X-CSRF-Token")).toBe("fictional-csrf");

    fireEvent.change(screen.getByLabelText("RAG 工程师 下一步行动"), { target: { value: "完成在线测评" } });
    fireEvent.blur(screen.getByLabelText("RAG 工程师 下一步行动"));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/applications/1",
        expect.objectContaining({ method: "PATCH", body: JSON.stringify({ next_action: "完成在线测评" }) }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    expect(screen.getByText("AI 平台")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看岗位详情" })).toHaveAttribute("href", "/jobs/7");

    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "删除 RAG 工程师" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/applications/1",
      expect.objectContaining({ method: "DELETE" }),
    ));
    await waitFor(() => expect(screen.queryByText("RAG 工程师")).not.toBeInTheDocument());
  });

  it("可在进度表内部新建投递并立即渲染", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const saved = { id: 2, company: "内部创建公司", position: "AI 工程师", status: "待投递", current_stage: "投递", stage_result: "待处理", base_location: "深圳", notes: "", created_at: "2026-08-06T00:00:00Z" };
    let created = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/applications" && init?.method === "POST") { created = true; return jsonResponse(saved); }
      return jsonResponse({ items: created ? [saved] : [], total: created ? 1 : 0, page: 1, page_size: 200 });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter><Applications /></MemoryRouter>);
    await screen.findByText("全部岗位");
    expect(screen.getByText("全部岗位").parentElement).toHaveTextContent("0");
    fireEvent.click(screen.getByRole("button", { name: "＋ 新增投递" }));
    fireEvent.change(screen.getByLabelText("公司"), { target: { value: "内部创建公司" } });
    fireEvent.change(screen.getByLabelText("岗位"), { target: { value: "AI 工程师" } });
    fireEvent.change(screen.getByLabelText("地点"), { target: { value: "深圳" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到进度表" }));

    expect(await screen.findByText("AI 工程师")).toBeInTheDocument();
    expect(screen.queryByText(/内部创建公司/)).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/applications",
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"company":"内部创建公司"') }),
    ));
  });

  it("保存画像偏好后要求重新确认", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const profile = { id: 1, target_directions: ["RAG 工程"], skills: ["Python"], education_level: null, experience_summary: "", project_summary: "", target_cities: ["上海"], remote_preference: null, exclude_keywords: [], confirmed: true, version: 1, updated_at: "2026-08-05T00:00:00Z" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/resumes") return jsonResponse([]);
      if (init?.method === "PATCH") return jsonResponse({ ...profile, confirmed: false, version: 2 });
      return jsonResponse(profile);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Profile />);
    const directions = await screen.findByLabelText("目标方向（用逗号或顿号分隔）");
    expect(directions).toBeDisabled();
    expect(screen.queryByText(/v1/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存画像偏好" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "修改画像" }));
    expect(directions).not.toBeDisabled();
    fireEvent.change(directions, { target: { value: "RAG 工程、AI Agent 开发" } });
    fireEvent.click(screen.getByRole("button", { name: "保存画像偏好" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/profile",
      expect.objectContaining({ method: "PATCH", body: expect.stringContaining("AI Agent 开发") }),
    ));
    await waitFor(() => expect(directions).toBeDisabled());
  });

  it("来源失败时可手工保存官方 JD", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/sources") return jsonResponse([]);
      if (String(input) === "/api/jobs/import" && init?.method === "POST") return jsonResponse({ id: 9 });
      return jsonResponse({});
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Sources />);
    fireEvent.change(screen.getByLabelText("公司"), { target: { value: "虚构科技" } });
    fireEvent.change(screen.getByLabelText("岗位名称"), { target: { value: "AI 后端工程师" } });
    fireEvent.change(screen.getByLabelText("官方岗位链接"), { target: { value: "https://example.invalid/jobs/9" } });
    fireEvent.change(screen.getByLabelText("完整 JD（至少 20 字）"), { target: { value: "负责使用 Python 构建完整的 RAG 服务和评估流水线。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存手工岗位" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/import",
      expect.objectContaining({ method: "POST", body: expect.stringContaining("AI 后端工程师") }),
    ));
    expect(await screen.findByText("岗位已保存。")).toBeInTheDocument();
  });

  it("来源卡片展示有效岗位数和上次发现数", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const source = {
      source_key: "fictional",
      display_name: "虚构科技",
      official_entry: "https://jobs.example.invalid/campus",
      status: "healthy",
      last_success_at: "2026-08-09T00:00:00Z",
      last_run_at: "2026-08-09T00:00:00Z",
      active_job_count: 12,
      year_unverified_count: 3,
      last_discovered_count: 15,
      consecutive_failures: 0,
      last_error: null,
      stable_for_acceptance: false,
      custom: false,
    };
    globalThis.fetch = vi.fn(async () => jsonResponse([source])) as typeof fetch;

    renderWithClient(<Sources />);

    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.getByText("个有效岗位")).toBeInTheDocument();
    expect(screen.getByText("上次发现 15 个")).toBeInTheDocument();
    expect(screen.getByText("其中 3 个岗位的 2027 届资格待确认")).toBeInTheDocument();
  });

  it("可查看脱敏 Key 并在不修改 Key 时保存 API 配置", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const llmConfig = { llm_base_url: "https://api.example.invalid/v1", llm_model: "old-model", llm_input_price_rmb_per_million: 1, llm_output_price_rmb_per_million: 2, llm_monthly_budget_rmb: 50, api_key_configured: true, api_key_source: "local", active_api_key_id: "key-1", api_keys: [{ id: "key-1", label: "DeepSeek 主 Key", masked: "sk-•••1234", source: "local", active: true, created_at: "2026-08-09T00:00:00Z" }, { id: "key-2", label: "DeepSeek 备用 Key", masked: "sk-•••5678", source: "local", active: false, created_at: "2026-08-09T00:00:00Z" }] };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/settings/llm/keys/key-2/activate" && init?.method === "POST") return jsonResponse({ ...llmConfig, active_api_key_id: "key-2", api_keys: llmConfig.api_keys.map((item) => ({ ...item, active: item.id === "key-2" })) });
      if (path === "/api/settings/llm" && init?.method === "PATCH") return jsonResponse({ ...llmConfig, llm_model: "new-model" });
      if (path === "/api/settings/llm") return jsonResponse(llmConfig);
      if (path === "/api/settings/preferences") return jsonResponse({ degraded_summary_enabled: false, llm_provider: "auto", effective_llm_provider: "api", llm_available: true, llm_reason: null });
      if (path === "/api/settings/budget") return jsonResponse({ month: "2026-08", budget_rmb: 50, used_rmb: 0, remaining_rmb: 50, llm_enabled: true, degraded_reason: null, pricing_configured: true, llm_provider: "api", cost_note: null });
      if (path === "/api/evaluation") return jsonResponse({ status: "collecting", labels: 0, required_labels: 50, precision_at_10: null, unlabeled_top10_job_ids: [] });
      return jsonResponse({});
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Settings />);
    expect(screen.queryByLabelText("模型名称")).not.toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "DeepSeek 主 Key · sk-•••1234" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("当前使用的 API Key"), { target: { value: "key-2" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/settings/llm/keys/key-2/activate", expect.objectContaining({ method: "POST" })));
    fireEvent.click(screen.getByRole("button", { name: "编辑 API 配置" }));
    const model = await screen.findByLabelText("模型名称");
    expect(screen.getByLabelText("Key 名称")).toHaveValue("old-model");
    fireEvent.change(model, { target: { value: "new-model" } });
    expect(screen.getByLabelText("Key 名称")).toHaveValue("new-model");
    fireEvent.click(screen.getByRole("button", { name: "保存 API 配置" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/llm",
      expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"llm_model":"new-model"') }),
    ));
    const patchCall = fetchMock.mock.calls.find(([path, init]) => String(path) === "/api/settings/llm" && init?.method === "PATCH");
    expect(String(patchCall?.[1]?.body)).not.toContain("llm_api_key");
  });

  it("识别已知官方模型并自动补全空白价格", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const llmConfig = { llm_base_url: "https://api.deepseek.com", llm_model: "deepseek-v4-flash", llm_input_price_rmb_per_million: null, llm_output_price_rmb_per_million: null, llm_monthly_budget_rmb: 50, api_key_configured: true, api_key_source: "local" };
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.startsWith("/api/settings/llm/pricing-suggestion")) return jsonResponse({ matched: true, provider: "DeepSeek", model: "deepseek-v4-flash", input_price_rmb_per_million: 1.008, output_price_rmb_per_million: 2.016, pricing_basis: "官方标准价", source_url: "https://api-docs.deepseek.com/quick_start/pricing", verified_on: "2026-08-09", usd_to_rmb_rate: 7.2 });
      if (path === "/api/settings/llm") return jsonResponse(llmConfig);
      if (path === "/api/settings/preferences") return jsonResponse({ degraded_summary_enabled: false, llm_provider: "auto", effective_llm_provider: "api", llm_available: false, llm_reason: "未配置 token 价格" });
      if (path === "/api/settings/budget") return jsonResponse({ month: "2026-08", budget_rmb: 50, used_rmb: 0, remaining_rmb: 50, llm_enabled: false, degraded_reason: "未配置 token 价格", pricing_configured: false, llm_provider: "api", cost_note: null });
      if (path === "/api/evaluation") return jsonResponse({ status: "collecting", labels: 0, required_labels: 50, precision_at_10: null, unlabeled_top10_job_ids: [] });
      return jsonResponse({});
    }) as typeof fetch;

    renderWithClient(<Settings />);

    fireEvent.click(await screen.findByRole("button", { name: "编辑 API 配置" }));
    await waitFor(() => expect(screen.getByLabelText("输入价格（元 / 百万 token）")).toHaveValue(1.008));
    expect(screen.getByLabelText("输出价格（元 / 百万 token）")).toHaveValue(2.016);
    expect(screen.getByLabelText("Key 名称")).toHaveValue("deepseek-v4-flash");
    expect(screen.getByText("已识别 DeepSeek 参考价格")).toBeInTheDocument();
  });

  it("岗位符合判断作为评测样本提交且不调整权重", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const job = { id: 1, company: "虚构科技", title: "RAG 工程师", location: "上海", recruitment_type: "校园招聘", graduation_year: "2027", description: "使用 Python 构建 RAG 平台", normalized_url: "https://example.invalid/jobs/1", closed: false, qualification_confirmed: true, source_key: "manual" };
    const recommendation = { id: 1, job_id: 1, hard_filter_passed: true, hard_filter_details: { open: true }, qualification_pending: false, rule_score: 25, vector_score: 20, llm_score: 30, final_score: 75, rerank_status: "completed", evidence: { fact_texts: ["使用 Python 构建完整项目"], matching_facts: [] }, model_name: "fictional", prompt_version: "v1", scoring_version: "v1" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/jobs/1") return jsonResponse(job);
      if (path.startsWith("/api/recommendations")) return jsonResponse({ items: [recommendation], total: 1, page: 1, page_size: 100 });
      if (path.startsWith("/api/feedback/weights")) return jsonResponse({ total_weight: 0, limit: 5, suitability: null });
      if (path === "/api/jobs/1/feedback" && init?.method === "POST") return jsonResponse({ job_id: 1, suitability: "suitable" });
      return jsonResponse({});
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter initialEntries={["/jobs/1"]}><Routes><Route path="/jobs/:id" element={<JobDetail />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "符合" }));

    expect(screen.queryByText(/fact_ids/)).not.toBeInTheDocument();
    expect(screen.getByText("使用 Python 构建完整项目")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "匹配说明" })).not.toBeInTheDocument();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/1/feedback",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "suitable" }) }),
    ));
  });

  it("岗位详情已存在投递记录时可跳转到对应进度", async () => {
    const job = { id: 1, company: "虚构科技", title: "RAG 工程师", location: "上海", description: "岗位原文", normalized_url: "https://example.invalid/jobs/1", closed: false, qualification_confirmed: true, source_key: "manual" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/jobs/1") return jsonResponse(job);
      if (path.startsWith("/api/recommendations")) return jsonResponse({ items: [], total: 0, page: 1, page_size: 100 });
      if (path.startsWith("/api/feedback/weights")) return jsonResponse({ total_weight: 0, limit: 5, suitability: null });
      if (path === "/api/applications?job_id=1") return jsonResponse({ items: [{ id: 9, job_id: 1 }], total: 1, page: 1, page_size: 50 });
      return jsonResponse({});
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter initialEntries={["/jobs/1"]}><Routes>
      <Route path="/jobs/:id" element={<JobDetail />} />
      <Route path="/applications" element={<h1>对应投递进度</h1>} />
    </Routes></MemoryRouter>);

    const link = await screen.findByRole("link", { name: "查看投递进度" });
    expect(link).toHaveAttribute("href", "/applications#application-9");
    fireEvent.click(link);
    expect(await screen.findByRole("heading", { name: "对应投递进度" })).toBeInTheDocument();
  });

  it("人工确认资格后立即移出待确认并显示反馈", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    let confirmed = false;
    const job = { id: 1, company: "虚构科技", title: "RAG 工程师", location: "上海", recruitment_type: null, graduation_year: null, description: "使用 Python 构建 RAG 平台", normalized_url: "https://example.invalid/jobs/1", closed: false, qualification_confirmed: false, source_key: "manual" };
    const recommendation = { id: 1, job_id: 1, hard_filter_passed: true, hard_filter_details: { open: true }, qualification_pending: true, rule_score: 20, vector_score: 20, llm_score: null, final_score: 40, rerank_status: "local_only", evidence: { pipeline: { llm: "skipped" } }, model_name: null, prompt_version: "v1", scoring_version: "v1" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/jobs/1/feedback" && init?.method === "POST") { confirmed = true; return jsonResponse({ job_id: 1, qualification_confirmed: true, recommendation_updated: true }); }
      if (path === "/api/jobs/1") return jsonResponse({ ...job, qualification_confirmed: confirmed });
      if (path.startsWith("/api/recommendations")) return jsonResponse({ items: [{ ...recommendation, qualification_pending: !confirmed }], total: 1, page: 1, page_size: 100 });
      if (path.startsWith("/api/feedback/weights")) return jsonResponse({ total_weight: 0, limit: 5, suitability: null });
      return jsonResponse({});
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter initialEntries={["/jobs/1"]}><Routes><Route path="/jobs/:id" element={<JobDetail />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "我已人工确认资格" }));

    expect(await screen.findByText("资格已确认，岗位已移入推荐；更新推荐后会补充模型重排。")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "我已人工确认资格" })).not.toBeInTheDocument());
  });

  it("推荐列表直接使用随推荐返回的岗位详情并切换状态", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const recommendation = {
      id: 1, job_id: 101, hard_filter_passed: true, hard_filter_details: { open: true },
      qualification_pending: false, rule_score: 25, vector_score: 20, llm_score: 30,
      final_score: 75, rerank_status: "completed", evidence: { pipeline: { llm: "completed" } },
      model_name: "fictional", prompt_version: "v1", scoring_version: "v1",
      job: { id: 101, company: "完整岗位公司", title: "算法工程师", location: "上海", source_key: "manual" },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      return jsonResponse({
        items: path.includes("status=pending") ? [] : [recommendation], total: path.includes("status=pending") ? 0 : 1,
        page: 1, page_size: 200, counts: { recommended: 1, pending: 3, filtered: 2, all: 6 },
      });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter><Recommendations /></MemoryRouter>);
    expect(await screen.findByText("完整岗位公司")).toBeInTheDocument();
    expect(screen.queryByText("加载岗位详情")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([path]) => String(path).startsWith("/api/jobs"))).toBe(false);
    fireEvent.click(screen.getByRole("tab", { name: /待确认/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("status=pending"), expect.any(Object),
    ));
  });

  it("推荐页显示上次更新时间并在任务完成后弹出提示", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/recommendations/recompute" && init?.method === "POST") {
        return jsonResponse({ jobs: 12, eligible: 8, llm_status: "completed", vector_status: "ok" });
      }
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 200, counts: {}, updated_at: "2026-08-09T01:02:03Z" });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter><Recommendations /></MemoryRouter>);
    expect(await screen.findByText(/2026\/8\/9/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "更新推荐" }));
    expect(await screen.findByText("推荐更新完成：已处理 12 个岗位，8 个通过硬条件。")).toBeInTheDocument();
  });

  it("推荐计算切换页面后仍保持进行中且不能重复提交", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    let finishRecompute: ((response: Response) => void) | undefined;
    const recomputeResponse = new Promise<Response>((resolve) => { finishRecompute = resolve; });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/recommendations/recompute" && init?.method === "POST") return recomputeResponse;
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 200, counts: {}, updated_at: null });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter initialEntries={["/recommendations"]}><Routes>
      <Route path="/recommendations" element={<><Link to="/other">切到其他页面</Link><Recommendations /></>} />
      <Route path="/other" element={<Link to="/recommendations">返回推荐</Link>} />
    </Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "更新推荐" }));
    expect(await screen.findByRole("button", { name: "正在计算…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("link", { name: "切到其他页面" }));
    fireEvent.click(await screen.findByRole("link", { name: "返回推荐" }));

    expect(await screen.findByRole("button", { name: "正在计算…" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([path]) => String(path) === "/api/recommendations/recompute")).toHaveLength(1);

    await act(async () => finishRecompute?.(jsonResponse({ jobs: 12, eligible: 8, llm_status: "completed", vector_status: "ok" })));
    expect(await screen.findByRole("button", { name: "更新推荐" })).toBeEnabled();
  });

  it("自定义公司来源在提交后立即解析并显示完成提示", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/sources/custom" && init?.method === "POST") {
        return jsonResponse({ success: true, discovered: 6, new: 4, error: null });
      }
      return jsonResponse([]);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Sources />);
    fireEvent.change(screen.getByLabelText("公司名称"), { target: { value: "虚构公司" } });
    fireEvent.change(screen.getByLabelText("官方招聘入口"), { target: { value: "https://careers.example.invalid/jobs" } });
    fireEvent.click(screen.getByRole("button", { name: "添加并解析岗位" }));

    expect(await screen.findByText("公司已添加并解析完成：发现 6 个岗位，新增 4 个。")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sources/custom",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ company: "虚构公司", official_entry: "https://careers.example.invalid/jobs" }) }),
    );
  });

  it("数据来源可修改官方入口并立即重新解析", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    let officialEntry = "https://careers.example.invalid/old";
    const source = { source_key: "custom_fictional", display_name: "虚构公司", official_entry: officialEntry, status: "healthy", last_success_at: null, last_run_at: null, consecutive_failures: 0, last_error: null, stable_for_acceptance: true, custom: true };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/sources/custom_fictional" && init?.method === "PATCH") {
        officialEntry = String(JSON.parse(String(init.body)).official_entry);
        return jsonResponse({ success: true, discovered: 5, new: 2, updated: 1, error: null });
      }
      if (path === "/api/sources") return jsonResponse([{ ...source, official_entry: officialEntry }]);
      return jsonResponse({});
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Sources />);
    fireEvent.click(await screen.findByRole("button", { name: "修改官方入口" }));
    fireEvent.change(screen.getByLabelText("虚构公司 官方入口"), { target: { value: "https://careers.example.invalid/new" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并重新解析" }));

    expect(await screen.findByText("官方入口已更新并解析完成：发现 5 个岗位，新增 2 个。")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/sources/custom_fictional",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ official_entry: "https://careers.example.invalid/new" }) }),
    ));
    expect(await screen.findByRole("link", { name: "官方入口" })).toHaveAttribute("href", "https://careers.example.invalid/new");
  });

  it("修改方案只从岗位详情生成并进入 06 栏显示修改后示例", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    let generated = false;
    const recommendation = {
      id: 1, job_id: 101, hard_filter_passed: true, hard_filter_details: {}, qualification_pending: false,
      rule_score: 25, vector_score: 20, llm_score: 30, final_score: 75, rerank_status: "completed",
      evidence: {}, model_name: "fictional", prompt_version: "v1", scoring_version: "v1", created_at: "2026-08-09T00:00:00Z",
      job: { id: 101, company: "虚构公司", title: "RAG 工程师", location: "上海", source_key: "manual" },
    };
    const advice = {
      job: recommendation.job, recommendation_version: 2, updated_at: "2026-08-09T00:00:00Z", gaps: [],
      suggestions: [{ section: "项目经历", action: "将 RAG 项目前置", current_text: "使用 Python 构建 RAG 项目", suggested_text: "【Python、RAG】使用 Python 构建 RAG 项目", rationale: "与岗位直接匹配", jd_quote: "熟悉 RAG" }],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/jobs/101/tailor-advice" && init?.method === "POST") {
        generated = true;
        return jsonResponse(advice);
      }
      if (path === "/api/jobs/101/tailor-advice") return jsonResponse(advice);
      if (path === "/api/jobs/101") return jsonResponse({ ...recommendation.job, description: "熟悉 RAG", normalized_url: "https://example.invalid/jobs/101", closed: false, qualification_confirmed: true });
      if (path.startsWith("/api/feedback/weights")) return jsonResponse({ total_weight: 0, limit: 5, suitability: null });
      if (path === "/api/tailor-advice") return jsonResponse(generated ? [{ job: recommendation.job, recommendation_version: 2, updated_at: advice.updated_at, suggestion_count: 1 }] : []);
      if (path.startsWith("/api/recommendations")) return jsonResponse({ items: [{ ...recommendation, evidence: generated ? { tailor_advice: {} } : {} }], total: 1, page: 1, page_size: 200, counts: { recommended: 1 } });
      return jsonResponse([]);
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const recommendationsView = renderWithClient(<MemoryRouter><Recommendations /></MemoryRouter>);
    expect(await screen.findByText("RAG 工程师")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /生成修改/ })).not.toBeInTheDocument();
    recommendationsView.unmount();

    vi.spyOn(window, "confirm").mockReturnValue(true);
    const detailView = renderWithClient(<MemoryRouter initialEntries={["/jobs/101"]}><Routes><Route path="/jobs/:id" element={<JobDetail />} /></Routes></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "生成修改方案" }));
    expect(await screen.findByText(/06 修改建议/)).toBeInTheDocument();
    detailView.unmount();

    renderWithClient(<MemoryRouter initialEntries={["/resumes"]}><Routes><Route path="/resumes" element={<ResumeVersions />} /><Route path="/resumes/jobs/:id" element={<TailorAdvice />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("RAG 工程师")).toBeInTheDocument();
    fireEvent.click(screen.getByText("查看修改建议 →"));
    expect(await screen.findByRole("heading", { name: "将 RAG 项目前置" })).toBeInTheDocument();
    expect(screen.getByText("【Python、RAG】使用 Python 构建 RAG 项目")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([path]) => String(path) === "/api/jobs/101/tailor-advice")).toBe(true);
  });

  it("首页高分推荐显示真实岗位名称而不是内部编号", async () => {
    const profile = { id: 1, target_directions: [], skills: [], education_level: null, experience_summary: "", project_summary: "", target_cities: [], remote_preference: null, exclude_keywords: [], confirmed: true, version: 1, updated_at: "2026-08-05T00:00:00Z" };
    const recommendation = {
      id: 1, job_id: 153, hard_filter_passed: true, hard_filter_details: {}, qualification_pending: false,
      rule_score: 20, vector_score: 20, llm_score: 30, final_score: 70, rerank_status: "completed",
      evidence: {}, model_name: "fictional", prompt_version: "v1", scoring_version: "v1",
      job: { id: 153, company: "真实公司", title: "真实算法岗位", location: "北京", source_key: "manual" },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/profile") return jsonResponse(profile);
      if (path === "/api/sources") return jsonResponse([]);
      if (path.startsWith("/api/recommendations")) return jsonResponse({ items: [recommendation], total: 1, page: 1, page_size: 10 });
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 1 });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<MemoryRouter><Dashboard /></MemoryRouter>);

    expect(await screen.findByText("真实算法岗位")).toBeInTheDocument();
    expect(screen.getByText("真实公司")).toBeInTheDocument();
    expect(screen.queryByText("岗位 #153")).not.toBeInTheDocument();
  });
});
