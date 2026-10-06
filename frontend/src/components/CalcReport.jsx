import SegmentBar from "./SegmentBar.jsx";
import { fmtDT, fmtHours, fmtMoney } from "../utils.js";

const STATUS_BADGE = {
  OK: { text: "可结算", cls: "badge-ok" },
  PROVISIONAL: { text: "暂估 · 含待核对事实", cls: "badge-warn" },
  BLOCKED: { text: "事实不全 · 无法计算", cls: "badge-bad" },
};

function ClauseChip({ code }) {
  if (!code) return <span className="dim">—</span>;
  return <span className="chip chip-clause">{code}</span>;
}

/**
 * 核算报告：概要 → 分段时间轴 → 费用（含溯源）→ 排除明细 → 警告/待核对。
 * 每笔费用都能追到计时区间与采用条款。
 */
export default function CalcReport({ report, loading, onRecalc, readonly }) {
  if (!report) return null;

  if (report.status === "BLOCKED") {
    return (
      <section className="card">
        <div className="card-head">
          <h3>核算报告</h3>
          <span className="badge badge-bad">事实不全 · 无法计算</span>
        </div>
        <ul className="warn-list">
          {(report.block_reasons || []).map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
        {(report.warnings || []).length > 0 && (
          <ul className="warn-list dim">
            {report.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
        <p className="dim">
          提示：准备就绪通知「送达」与「被接受」是不同事实，起算只以被接受为准。
        </p>
      </section>
    );
  }

  const ts = report.time_summary;
  const badge = STATUS_BADGE[report.status] || {};

  return (
    <section className="card">
      <div className="card-head">
        <h3>核算报告</h3>
        <div className="card-head-actions">
          <span className={`badge ${badge.cls}`}>{badge.text}</span>
          {!readonly && (
            <button className="btn" onClick={onRecalc} disabled={loading}>
              {loading ? "计算中…" : "重新试算"}
            </button>
          )}
        </div>
      </div>

      {report.boundary_note && (
        <div className="alert alert-info">{report.boundary_note}</div>
      )}

      <div className="summary-grid">
        <div className="summary-item">
          <span className="summary-label">
            允许装卸时间 <ClauseChip code={report.allowed_clause} />
          </span>
          <strong>{fmtHours(report.allowed_hours)}</strong>
        </div>
        <div className="summary-item">
          <span className="summary-label">允许计入时间（已用）</span>
          <strong>{fmtHours(ts.laytime_used_hours)}</strong>
        </div>
        <div className="summary-item">
          <span className="summary-label">自然时间</span>
          <strong>{fmtHours(ts.natural_hours)}</strong>
        </div>
        <div className="summary-item">
          <span className="summary-label">实际作业时间</span>
          <strong>{fmtHours(ts.working_hours)}</strong>
        </div>
        <div className="summary-item">
          <span className="summary-label">条款排除时间</span>
          <strong>{fmtHours(ts.excluded_applied_hours)}</strong>
        </div>
        <div className="summary-item">
          <span className="summary-label">全部停工时间</span>
          <strong>{fmtHours(ts.all_stoppage_hours)}</strong>
        </div>
        <div className="summary-item highlight-red">
          <span className="summary-label">滞期时间</span>
          <strong>{fmtHours(ts.demurrage_hours)}</strong>
        </div>
        <div className="summary-item highlight-green">
          <span className="summary-label">节省时间</span>
          <strong>{fmtHours(ts.despatch_hours)}</strong>
        </div>
      </div>

      <SegmentBar report={report} />

      <h4>费用明细（可追溯）</h4>
      {report.charges.length === 0 && (
        <p className="dim">无滞期/速遣费用。</p>
      )}
      {report.charges.map((c, i) => (
        <div key={i} className={`charge charge-${c.type.toLowerCase()}`}>
          <div className="charge-main">
            <span className="charge-label">{c.label}</span>
            <span className="charge-amount">{fmtMoney(c.amount, report.currency)}</span>
          </div>
          <div className="charge-trace">
            <div>
              计时区间：<span className="mono">{fmtDT(c.period.from)} → {fmtDT(c.period.to)}</span>
              （{fmtHours(c.hours)}）
            </div>
            <div>
              采用条款：费率 <ClauseChip code={c.trace.rate_clause} /> 允许时间{" "}
              <ClauseChip code={c.trace.allowed_clause} />
              {c.trace.once_on_demurrage_clause && (
                <> 滞期规则 <ClauseChip code={c.trace.once_on_demurrage_clause} /></>
              )}
            </div>
            <div className="mono dim">计算式：{c.trace.formula}</div>
          </div>
        </div>
      ))}
      <div className="total-row">
        合计：<strong>{fmtMoney(report.total_amount, report.currency)}</strong>
      </div>

      <h4>条款排除明细（重叠已合并，不重复扣减）</h4>
      {report.exclusions_applied.length === 0 && (
        <p className="dim">无适用的排除。</p>
      )}
      {report.exclusions_applied.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>区间</th>
              <th>时长</th>
              <th>原因</th>
              <th>依据条款</th>
              <th>停工记录</th>
            </tr>
          </thead>
          <tbody>
            {report.exclusions_applied.map((e, i) => (
              <tr key={i}>
                <td className="mono">
                  {fmtDT(e.start)} → {fmtDT(e.end)}
                </td>
                <td>{fmtHours(e.hours)}</td>
                <td>{e.reasons.join("、")}</td>
                <td>
                  {e.clause_codes.map((c) => (
                    <ClauseChip key={c} code={c} />
                  ))}
                </td>
                <td className="mono dim">#{e.stoppage_ids.join(" #")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {report.exclusions_not_applied.length > 0 && (
        <>
          <h4>未适用的排除（一旦滞期，持续滞期）</h4>
          <table className="table">
            <tbody>
              {report.exclusions_not_applied.map((e, i) => (
                <tr key={i}>
                  <td className="mono">
                    {fmtDT(e.start)} → {fmtDT(e.end)}
                  </td>
                  <td>{e.reasons.join("、")}</td>
                  <td className="dim">{e.not_applied_because}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {report.non_excludable_stoppages.length > 0 && (
        <>
          <h4>按条款仍计入的停工</h4>
          <table className="table">
            <tbody>
              {report.non_excludable_stoppages.map((s, i) => (
                <tr key={i}>
                  <td className="mono">
                    {fmtDT(s.start)} → {fmtDT(s.end)}
                  </td>
                  <td>{s.reason_label}</td>
                  <td>{fmtHours(s.hours)}</td>
                  <td>
                    <ClauseChip code={s.clause_code} />{" "}
                    <span className="dim">{s.effect}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {report.warnings.length > 0 && (
        <>
          <h4>警告</h4>
          <ul className="warn-list">
            {report.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </>
      )}

      {report.unverified_inputs.length > 0 && (
        <>
          <h4>待核对事实（{report.unverified_inputs.length}）</h4>
          <ul className="warn-list">
            {report.unverified_inputs.map((u, i) => (
              <li key={i}>
                [{u.kind === "event" ? "事件" : "停工"} #{u.id}] {u.label} —— {u.status}
              </li>
            ))}
          </ul>
          <p className="dim">含待核对事实的结算不能定稿。</p>
        </>
      )}
    </section>
  );
}
