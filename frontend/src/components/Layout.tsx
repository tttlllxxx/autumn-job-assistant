import { NavLink, Outlet } from "react-router-dom";
import { TaskCompletionWatcher } from "./TaskCompletionWatcher";

const links = [
  ["/", "概览", "01"], ["/recommendations", "岗位推荐", "02"], ["/applications", "投递看板", "03"],
  ["/setup", "简历导入", "04"], ["/profile", "画像与事实", "05"], ["/resumes", "修改建议", "06"],
];

const systemLinks = [["/sources", "数据来源", "07"], ["/settings", "设置与备份", "08"]];

export function Layout() {
  return <div className="app-shell">
    <TaskCompletionWatcher />
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">秋</span><span><strong>秋招助手</strong><small>2027 求职工作台</small></span></div>
      <nav aria-label="主导航"><p className="nav-label">工作台</p>{links.map(([to, label, index]) => <NavLink key={to} to={to} end={to === "/"}><span>{index}</span>{label}</NavLink>)}<p className="nav-label">系统</p>{systemLinks.map(([to, label, index]) => <NavLink key={to} to={to}><span>{index}</span>{label}</NavLink>)}</nav>
      <div className="local-mode"><i aria-hidden="true" /><span><strong>本地模式</strong><small>数据保存在当前设备</small></span></div>
    </aside>
    <main className="content"><Outlet /></main>
  </div>;
}
