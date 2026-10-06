/** 时间/格式工具：系统内部一律 UTC，展示时标注。 */

export function fmtDT(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
  );
}

export function fmtShort(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

export function fmtHours(h) {
  if (h === undefined || h === null) return "—";
  const n = Number(h);
  return `${n.toFixed(2)} 小时`;
}

export function fmtMoney(amount, currency = "USD") {
  if (amount === undefined || amount === null) return "—";
  return `${Number(amount).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ${currency}`;
}

export const EVIDENCE_BADGE = {
  VERIFIED: { text: "已核实", cls: "badge-ok" },
  PENDING: { text: "待核对", cls: "badge-warn" },
  DISPUTED: { text: "有争议", cls: "badge-bad" },
};

export const REASON_LABEL = {
  WEATHER: "恶劣天气",
  WEEKEND_HOLIDAY: "周末/节假日",
  WAITING_BERTH: "等待泊位",
  EQUIPMENT: "船舶设备故障",
  STRIKE: "罢工",
  OTHER: "其他",
};

export const SEGMENT_STYLE = {
  COUNTING: { label: "计入装卸时间", color: "#2f9e44" },
  EXCLUDED: { label: "条款排除", color: "#f08c00" },
  DEMURRAGE: { label: "滞期时间", color: "#e03131" },
};
