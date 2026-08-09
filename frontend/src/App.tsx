import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, jsonBody } from "./api";
import { Layout } from "./components/Layout";
import { Applications } from "./pages/Applications";
import { Dashboard } from "./pages/Dashboard";
import { JobDetail } from "./pages/JobDetail";
import { Profile } from "./pages/Profile";
import { Recommendations } from "./pages/Recommendations";
import { ResumeVersions } from "./pages/ResumeVersions";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { Sources } from "./pages/Sources";
import { TailorAdvice } from "./pages/TailorAdvice";

function LocalSessionLayout() {
  const session = useQuery<{ authenticated: boolean; csrf_token: string }>({
    queryKey: ["local-session"],
    queryFn: async () => {
      const result = await api<{ authenticated: boolean; csrf_token: string }>("/api/auth/local-session", jsonBody({}));
      localStorage.setItem("csrf_token", result.csrf_token);
      return result;
    },
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (session.isLoading) return <div className="splash"><span className="splash-mark">秋</span><p>正在准备你的工作台…</p></div>;
  if (session.isError) return <div className="splash error"><span className="splash-mark">!</span><p>{session.error.message}</p><button onClick={() => void session.refetch()}>重新连接</button></div>;
  return <Layout />;
}

export function App() {
  return <Routes><Route element={<LocalSessionLayout />}><Route path="/" element={<Dashboard />} /><Route path="/setup" element={<Setup />} /><Route path="/profile" element={<Profile />} /><Route path="/recommendations" element={<Recommendations />} /><Route path="/jobs/:id" element={<JobDetail />} /><Route path="/sources" element={<Sources />} /><Route path="/applications" element={<Applications />} /><Route path="/resumes" element={<ResumeVersions />} /><Route path="/resumes/jobs/:id" element={<TailorAdvice />} /><Route path="/settings" element={<Settings />} /></Route><Route path="*" element={<Navigate to="/" replace />} /></Routes>;
}
