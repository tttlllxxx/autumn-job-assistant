export function formatShanghaiTime(value: string | null | undefined, empty = "尚未运行") {
  if (!value) return empty;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const instant = new Date(hasZone ? value : `${value}Z`);
  return instant.toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" });
}
