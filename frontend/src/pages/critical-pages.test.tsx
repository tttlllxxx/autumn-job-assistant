import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { App } from "../App";
import { Applications } from "./Applications";
import { Dashboard } from "./Dashboard";
import { JobDetail } from "./JobDetail";
import { Profile } from "./Profile";
import { Recommendations } from "./Recommendations";
import { Settings } from "./Settings";
import { Sources } from "./Sources";

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

  it("投递看板展示全部状态并通过 PATCH 更新记录", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const application = {
      id: 1,
      company: "虚构科技",
      position: "RAG 工程师",
      status: "已投递",
      current_stage: "投递",
      stage_result: "待处理",
      base_location: "北京",
      notes: "",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.startsWith("/api/applications/") && init?.method === "PATCH") {
        return jsonResponse({ ...application, status: "面试中" });
      }
      return jsonResponse({ items: [application], total: 1, page: 1, page_size: 200 });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Applications />);
    expect(await screen.findByText("虚构科技")).toBeInTheDocument();
    expect(screen.queryByLabelText("导入 CSV")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "导出 CSV" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Offer 已接收" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "已终止" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("虚构科技 状态"), { target: { value: "面试中" } });
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
  });

  it("可在看板内部新建投递并立即渲染", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const saved = { id: 2, company: "内部创建公司", position: "AI 工程师", status: "待投递", current_stage: "投递", stage_result: "待处理", base_location: "深圳", notes: "", created_at: "2026-08-06T00:00:00Z" };
    let created = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/applications" && init?.method === "POST") { created = true; return jsonResponse(saved); }
      return jsonResponse({ items: created ? [saved] : [], total: created ? 1 : 0, page: 1, page_size: 200 });
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Applications />);
    await screen.findByText("0 个机会");
    fireEvent.click(screen.getByRole("button", { name: "＋ 新增投递" }));
    fireEvent.change(screen.getByLabelText("公司"), { target: { value: "内部创建公司" } });
    fireEvent.change(screen.getByLabelText("岗位"), { target: { value: "AI 工程师" } });
    fireEvent.change(screen.getByLabelText("地点"), { target: { value: "深圳" } });
    fireEvent.click(screen.getByRole("button", { name: "保存到看板" }));

    expect(await screen.findByText("内部创建公司")).toBeInTheDocument();
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
    fireEvent.change(directions, { target: { value: "RAG 工程、AI Agent 开发" } });
    fireEvent.click(screen.getByRole("button", { name: "保存画像偏好" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/profile",
      expect.objectContaining({ method: "PATCH", body: expect.stringContaining("AI Agent 开发") }),
    ));
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

  it("可在设置页保存 API 配置且不要求重新输入已有 Key", async () => {
    localStorage.setItem("csrf_token", "fictional-csrf");
    const llmConfig = { llm_base_url: "https://api.example.invalid/v1", llm_model: "old-model", llm_input_price_rmb_per_million: 1, llm_output_price_rmb_per_million: 2, llm_monthly_budget_rmb: 50, api_key_configured: true, api_key_source: "local" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/settings/llm" && init?.method === "PATCH") return jsonResponse({ ...llmConfig, llm_model: "new-model" });
      if (path === "/api/settings/llm") return jsonResponse(llmConfig);
      if (path === "/api/settings/preferences") return jsonResponse({ degraded_summary_enabled: false, llm_provider: "auto", effective_llm_provider: "api", llm_available: true, llm_reason: null });
      if (path === "/api/settings/budget") return jsonResponse({ month: "2026-08", budget_rmb: 50, used_rmb: 0, remaining_rmb: 50, llm_enabled: true, degraded_reason: null, pricing_configured: true, llm_provider: "api", cost_note: null });
      if (path === "/api/evaluation") return jsonResponse({ status: "collecting", labels: 0, required_labels: 50, precision_at_10: null, unlabeled_top10_job_ids: [] });
      return jsonResponse({});
    });
    globalThis.fetch = fetchMock as typeof fetch;

    renderWithClient(<Settings />);
    const model = await screen.findByLabelText("模型名称");
    expect(screen.getByPlaceholderText("已配置；留空则保持不变")).toHaveValue("");
    fireEvent.change(model, { target: { value: "new-model" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 API 配置" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/llm",
      expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"llm_model":"new-model"') }),
    ));
    const patchCall = fetchMock.mock.calls.find(([path, init]) => String(path) === "/api/settings/llm" && init?.method === "PATCH");
    expect(String(patchCall?.[1]?.body)).not.toContain("llm_api_key");
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
