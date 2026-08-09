import { useIsMutating, useQuery, type MutationKey } from "@tanstack/react-query";
import { api } from "./api";

export const taskKeys = {
  recommendationRecompute: ["task", "recommendation-recompute"] as const,
  sourceRun: ["task", "source-run"] as const,
  customSourceParse: ["task", "custom-source-parse"] as const,
  sourceEntryUpdate: ["task", "source-entry-update"] as const,
  resumeParse: ["task", "resume-parse"] as const,
  backupCreate: ["task", "backup-create"] as const,
  backupRestore: ["task", "backup-restore"] as const,
  tailorAdvice: (jobId: number) => ["task", "tailor-advice", jobId] as const,
};

export function useTaskPending(mutationKey: MutationKey): boolean {
  const localPending = useIsMutating({ mutationKey, exact: true }) > 0;
  const taskType = typeof mutationKey[1] === "string" ? mutationKey[1].replaceAll("-", "_") : "";
  const scopeKey = mutationKey.length > 2 ? String(mutationKey[2]) : null;
  const query = useQuery<Array<{ id: number; status: string }>>({
    queryKey: ["persistent-tasks", taskType, scopeKey],
    queryFn: () => {
      const params = new URLSearchParams({ task_type: taskType, active_only: "true" });
      if (scopeKey !== null) params.set("scope_key", scopeKey);
      return api(`/api/tasks?${params.toString()}`);
    },
    enabled: Boolean(taskType),
    refetchInterval: 2_000,
  });
  return localPending || Boolean(query.data?.length);
}
