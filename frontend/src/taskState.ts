import { useIsMutating, type MutationKey } from "@tanstack/react-query";

export const taskKeys = {
  recommendationRecompute: ["task", "recommendation-recompute"] as const,
  sourceRun: ["task", "source-run"] as const,
  customSourceParse: ["task", "custom-source-parse"] as const,
  resumeParse: ["task", "resume-parse"] as const,
  backupCreate: ["task", "backup-create"] as const,
  backupRestore: ["task", "backup-restore"] as const,
  tailorAdvice: (jobId: number) => ["task", "tailor-advice", jobId] as const,
};

export function useTaskPending(mutationKey: MutationKey): boolean {
  return useIsMutating({ mutationKey, exact: true }) > 0;
}
