import { useState } from "react";
import { api } from "../api.js";
import { fmtDT, fmtMoney } from "../utils.js";

const STATUS_CLS = {
  DRAFT: "badge-warn",
  FINAL: "badge-ok",
  SUPERSEDED: "badge-dim",
};

/**
 * 结算面板：
 * - 「生成结算草稿」把当前试算快照存为新版本（版本号递增，不覆盖历史）
 * - 草稿可定稿；定稿后锁定，旧定稿自动转为「已被取代」
 * - 已定稿/历史版本不可修改、不可删除
 */
export default function SettlementPanel({ voyageId, settlements, onChanged, onView }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const act = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await onChanged();
    } catch (e) {
      setError(e.payload?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="card-head">
        <h3>结算版本</h3>
        <button
          className="btn"
          disabled={busy}
          onClick={() => act(() => api.settle(voyageId))}
        >
          生成结算草稿（新版本）
        </button>
      </div>
      {error && <div className="alert alert-bad">{error}</div>}
      {settlements.length === 0 && (
        <p className="dim">尚无结算。点击右上角按钮，以当前试算生成草稿快照。</p>
      )}
      {settlements.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>版本</th>
              <th>状态</th>
              <th>金额</th>
              <th>创建时间</th>
              <th>定稿时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {settlements.map((s) => (
              <tr key={s.id}>
                <td className="mono">v{s.version}</td>
                <td>
                  <span className={`badge ${STATUS_CLS[s.status]}`}>
                    {s.status === "FINAL" && "🔒 "}
                    {s.status_display}
                  </span>
                </td>
                <td className="mono">{fmtMoney(s.total_amount, s.currency)}</td>
                <td className="mono">{fmtDT(s.created_at)}</td>
                <td className="mono">{s.finalized_at ? fmtDT(s.finalized_at) : "—"}</td>
                <td className="actions">
                  <button className="btn btn-small" onClick={() => onView(s)}>
                    查看快照
                  </button>
                  {s.status === "DRAFT" && (
                    <>
                      <button
                        className="btn btn-small btn-primary"
                        disabled={busy}
                        onClick={() => act(() => api.finalizeSettlement(s.id))}
                      >
                        定稿
                      </button>
                      <button
                        className="btn btn-small btn-danger"
                        disabled={busy}
                        onClick={() => act(() => api.deleteSettlement(s.id))}
                      >
                        删除
                      </button>
                    </>
                  )}
                  {s.status !== "DRAFT" && (
                    <span className="dim">不可修改</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="dim note">
        历史结算不能直接覆盖：每次结算生成新版本快照；定稿后内容、金额锁定，
        旧定稿仅被标记为「已被取代」，始终可回查。
      </p>
    </section>
  );
}
