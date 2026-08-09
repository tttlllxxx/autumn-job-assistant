import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { type Notice, TaskNotice } from "./TaskNotice";

type TaskRun = {
  id: number;
  task_type: string;
  status: "running" | "completed" | "failed" | "interrupted";
  error_message: string | null;
};

const taskLabels: Record<string, string> = {
  recommendation_recompute: "推荐更新",
  source_run: "来源采集",
  custom_source_parse: "公司岗位解析",
  source_entry_update: "官方入口更新",
  resume_parse: "简历解析",
  tailor_advice: "修改方案生成",
  backup_create: "备份创建",
  backup_restore: "备份恢复",
  daily_pipeline: "每日岗位流水线",
};

export function TaskCompletionWatcher() {
  const client = useQueryClient();
  const [notice, setNotice] = useState<Notice>(null);
  const known = useRef<Map<number, TaskRun["status"]>>(new Map());
  const initialized = useRef(false);
  const query = useQuery<TaskRun[]>({
    queryKey: ["task-history"],
    queryFn: () => api("/api/tasks?active_only=false&limit=50"),
    refetchInterval: 2_000,
  });
  const tasks = Array.isArray(query.data) ? query.data : [];

  useEffect(() => {
    if (!query.isSuccess) return;
    if (!initialized.current) {
      tasks.forEach((task) => known.current.set(task.id, task.status));
      initialized.current = true;
      return;
    }
    for (const task of [...tasks].reverse()) {
      const previous = known.current.get(task.id);
      known.current.set(task.id, task.status);
      if (task.status === "running" || (previous !== undefined && previous !== "running")) continue;
      const label = taskLabels[task.task_type] ?? "后台任务";
      if (["source_run", "custom_source_parse", "source_entry_update"].includes(task.task_type)) {
        void client.invalidateQueries({ queryKey: ["sources"] });
        void client.invalidateQueries({ queryKey: ["jobs"] });
      } else if (task.task_type === "recommendation_recompute") {
        void client.invalidateQueries({ queryKey: ["recommendations"] });
      } else if (task.task_type === "resume_parse") {
        void client.invalidateQueries({ queryKey: ["resumes"] });
        void client.invalidateQueries({ queryKey: ["profile"] });
      } else if (task.task_type === "tailor_advice") {
        void client.invalidateQueries({ queryKey: ["tailor-advice-list"] });
        void client.invalidateQueries({ queryKey: ["tailor-advice"] });
      }
      setNotice(
        task.status === "completed"
          ? { kind: "success", message: `${label}已完成。` }
          : { kind: "error", message: `${label}未完成：${task.error_message ?? "请重试"}` },
      );
    }
  }, [client, query.isSuccess, tasks]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 8_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  return <TaskNotice notice={notice} onClose={() => setNotice(null)} />;
}
