import { SEGMENT_STYLE, fmtShort } from "../utils.js";

/**
 * 计算分段时间轴：把 [起算, 完工] 的自然时间按比例画成
 * 计入(绿) / 排除(橙) / 滞期(红) 三段式色带，并标注关键里程碑。
 */
export default function SegmentBar({ report }) {
  const segments = report.segments || [];
  const t0 = new Date(report.commencement.at).getTime();
  const t1 = new Date(report.completion_at).getTime();
  const span = t1 - t0;
  if (span <= 0) return null;

  const pct = (iso) => ((new Date(iso).getTime() - t0) / span) * 100;

  const milestones = [
    { at: report.commencement.at, label: "起算" },
    report.exhaustion_at && { at: report.exhaustion_at, label: "允许时间用尽" },
    { at: report.completion_at, label: "完工" },
  ].filter(Boolean);

  return (
    <div className="segment-bar-wrap">
      <div className="segment-bar">
        {segments.map((s, i) => {
          const style = SEGMENT_STYLE[s.kind] || {};
          const left = pct(s.start);
          const width = Math.max(pct(s.end) - left, 0.4);
          return (
            <div
              key={i}
              className="segment"
              style={{ left: `${left}%`, width: `${width}%`, background: style.color }}
              title={`${style.label} ${fmtShort(s.start)} → ${fmtShort(s.end)} (${s.hours}h)${
                s.reasons ? " · " + s.reasons.join("/") : ""
              }${s.note ? " · " + s.note : ""}`}
            >
              {width > 7 && <span>{Number(s.hours).toFixed(1)}h</span>}
            </div>
          );
        })}
      </div>
      <div className="milestone-row">
        {milestones.map((m, i) => (
          <div
            key={i}
            className="milestone"
            style={{ left: `${Math.min(Math.max(pct(m.at), 0), 100)}%` }}
          >
            <span className="milestone-tick" />
            <span className="milestone-label">
              {m.label} {fmtShort(m.at)}
            </span>
          </div>
        ))}
      </div>
      <div className="legend">
        {Object.entries(SEGMENT_STYLE).map(([k, v]) => (
          <span key={k} className="legend-item">
            <i style={{ background: v.color }} /> {v.label}
          </span>
        ))}
      </div>
    </div>
  );
}
