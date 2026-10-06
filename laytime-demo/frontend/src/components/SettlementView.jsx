import React from "react";

function fmt(dt) {
  return new Date(dt).toLocaleString("zh-CN", { hour12: false });
}

function IntervalTable({ intervals }) {
  return (
    <table className="intervals">
      <thead>
        <tr>
          <th>起</th>
          <th>止</th>
          <th>小时</th>
          <th>状态</th>
          <th>原因</th>
          <th>采用条款</th>
        </tr>
      </thead>
      <tbody>
        {intervals.map((s, i) => (
          <tr key={i} className={s.counted ? "counted" : "excluded"}>
            <td>{fmt(s.start)}</td>
            <td>{fmt(s.end)}</td>
            <td>{s.hours}</td>
            <td>{s.counted ? "计入" : "不计入"}</td>
            <td>
              {s.reasons.join(" + ")}
              {s.weekend ? "周末" : ""}
              {!s.reasons.length && !s.weekend ? "—" : ""}
            </td>
            <td>{s.clause_codes.join(", ") || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SettlementView({ settlement, onRecalculate }) {
  if (!settlement) return null;
  if (settlement.status === "BLOCKED") {
    return (
      <section className="blocked">
        <h3>结算 v{settlement.version}：无法起算</h3>
        <p>{settlement.blocked_reason}</p>
      </section>
    );
  }
  return (
    <section>
      <h3>
        结算 v{settlement.version}
        <small>（历史版本只读，重新核算将生成新版本，不覆盖）</small>
      </h3>
      <div className="totals">
        <div>
          <label>自然时间</label>
          <b>{settlement.natural_hours} h</b>
        </div>
        <div>
          <label>允许计入（已用）</label>
          <b>{settlement.laytime_used_hours} h</b>
        </div>
        <div>
          <label>实际作业</label>
          <b>{settlement.actual_working_hours} h</b>
        </div>
        <div>
          <label>允许时间</label>
          <b>{settlement.allowed_hours} h</b>
        </div>
        <div className="money">
          <label>滞期费</label>
          <b>USD {settlement.demurrage_amount}</b>
        </div>
        <div className="money">
          <label>速遣费</label>
          <b>USD {settlement.despatch_amount}</b>
        </div>
      </div>

      <h4>费用明细与追溯</h4>
      {settlement.lines.map((line) => (
        <details key={line.id} className={`line ${line.kind.toLowerCase()}`}>
          <summary>
            <span className="tag">{line.kind_display}</span>
            {line.label} — 金额 USD {line.amount}（基数 {line.basis_hours} h ×
            费率 {line.rate_per_day}/天）· 条款：
            {line.clause_codes.join(", ") || "—"}
          </summary>
          <IntervalTable intervals={line.intervals} />
        </details>
      ))}

      <h4>全部计时区间</h4>
      <IntervalTable intervals={settlement.segments} />

      {settlement.pending_fragment_ids.length > 0 && (
        <p className="warning">
          有 {settlement.pending_fragment_ids.length}
          条事件片段证据待核对，未参与本次核算；补齐证据后请重新核算（生成新版本）。
        </p>
      )}
      <button onClick={onRecalculate}>重新核算（生成新版本）</button>
    </section>
  );
}
