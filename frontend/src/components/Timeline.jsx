import { EVIDENCE_BADGE, REASON_LABEL, fmtDT } from "../utils.js";

function EvidenceSelect({ kind, id, value, onPatch }) {
  const badge = EVIDENCE_BADGE[value] || {};
  return (
    <span className={`badge ${badge.cls} evidence-select`}>
      <select
        value={value}
        onChange={(e) => onPatch(kind, id, e.target.value)}
        title="修改证据状态"
      >
        <option value="VERIFIED">已核实</option>
        <option value="PENDING">待核对</option>
        <option value="DISPUTED">有争议</option>
      </select>
    </span>
  );
}

/**
 * 事实时间表：事件点 + 停工片段。
 * NOR「送达」与「被接受」是两个独立事实，分别成行；
 * 缺证据的片段标记为待核对（斜纹底），可直接在此更新证据状态。
 */
export default function Timeline({ events, stoppages, onPatchEvidence }) {
  return (
    <section className="card">
      <h3>事实时间表（UTC）</h3>
      <table className="table">
        <thead>
          <tr>
            <th>事实</th>
            <th>时间</th>
            <th>证据状态</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr
              key={e.id}
              className={e.evidence_status !== "VERIFIED" ? "row-pending" : ""}
            >
              <td>
                {e.event_type_display}
                {e.event_type === "NOR_TENDERED" && (
                  <span className="fact-hint">送达 ≠ 被接受</span>
                )}
                {e.event_type === "NOR_ACCEPTED" && (
                  <span className="fact-hint">起算依据</span>
                )}
              </td>
              <td className="mono">{fmtDT(e.occurred_at)}</td>
              <td>
                <EvidenceSelect
                  kind="event"
                  id={e.id}
                  value={e.evidence_status}
                  onPatch={onPatchEvidence}
                />
              </td>
              <td className="dim">{e.source || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>停工片段</h4>
      {stoppages.length === 0 && <p className="dim">无停工记录</p>}
      {stoppages.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>原因</th>
              <th>开始</th>
              <th>结束</th>
              <th>证据状态</th>
            </tr>
          </thead>
          <tbody>
            {stoppages.map((s) => (
              <tr
                key={s.id}
                className={s.evidence_status !== "VERIFIED" ? "row-pending" : ""}
              >
                <td>
                  <span className={`reason-dot reason-${s.reason}`} />
                  {REASON_LABEL[s.reason] || s.reason_display}
                  {s.note && <span className="fact-hint">{s.note}</span>}
                </td>
                <td className="mono">{fmtDT(s.started_at)}</td>
                <td className="mono">{fmtDT(s.ended_at)}</td>
                <td>
                  <EvidenceSelect
                    kind="stoppage"
                    id={s.id}
                    value={s.evidence_status}
                    onPatch={onPatchEvidence}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
