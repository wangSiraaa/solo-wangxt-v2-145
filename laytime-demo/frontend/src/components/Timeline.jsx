import React from "react";

const KIND_LABEL = {
  ARRIVAL: "抵港",
  NOR_TENDERED: "NOR 送达",
  NOR_ACCEPTED: "NOR 被接受",
  STOPPAGE_START: "停工开始",
  STOPPAGE_END: "复工",
  COMPLETION: "装卸完毕",
};

export default function Timeline({ fragments }) {
  return (
    <section>
      <h3>事件片段（事实时间线）</h3>
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>事件</th>
            <th>原因</th>
            <th>证据</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          {fragments.map((f) => (
            <tr
              key={f.id}
              className={f.evidence_status === "PENDING" ? "pending" : ""}
            >
              <td>{new Date(f.occurred_at).toLocaleString("zh-CN")}</td>
              <td>{KIND_LABEL[f.kind] || f.kind_display}</td>
              <td>{f.reason ? f.reason_display : "—"}</td>
              <td>
                <span className={`badge ${f.evidence_status.toLowerCase()}`}>
                  {f.evidence_display}
                </span>
              </td>
              <td>{f.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        「NOR 送达」与「NOR 被接受」是不同事实，仅接受起算（CP-01）；
        待核对片段不参与核算。
      </p>
    </section>
  );
}
