export type Notice = { kind: "success" | "warning" | "error"; message: string } | null;

export function TaskNotice({ notice, onClose }: { notice: Notice; onClose: () => void }) {
  if (!notice) return null;
  return <div className={`task-notice ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
    <span>{notice.kind === "success" ? "✓" : notice.kind === "warning" ? "!" : "×"}</span>
    <p>{notice.message}</p>
    <button type="button" aria-label="关闭提示" onClick={onClose}>×</button>
  </div>;
}
