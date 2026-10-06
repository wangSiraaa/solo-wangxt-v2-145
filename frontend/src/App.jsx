import { useEffect, useState } from "react";
import { api } from "./api.js";
import VoyageDetail from "./components/VoyageDetail.jsx";

export default function App() {
  const [voyages, setVoyages] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .listVoyages()
      .then((rows) => {
        setVoyages(rows);
        if (rows.length && !selectedId) setSelectedId(rows[0].id);
      })
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1>装卸时间与滞期速遣核算</h1>
          <p className="subtitle">
            事实时间表 → 条款判断 → Decimal 核算 → 可追溯结算
          </p>
        </div>
        <div className="fictional-notice">
          本系统使用虚构租约规则（FICTCON-2026），仅作演示，不替代法律解释
        </div>
      </header>
      {error && <div className="alert alert-bad">{error}</div>}
      <div className="app-body">
        <aside className="voyage-list">
          <h2>航次</h2>
          {voyages.map((v) => (
            <button
              key={v.id}
              className={`voyage-item ${v.id === selectedId ? "active" : ""}`}
              onClick={() => setSelectedId(v.id)}
            >
              <span className="voyage-ref">{v.reference}</span>
              <span className="voyage-meta">
                {v.vessel_name} · {v.port_name} · {v.operation_display}
              </span>
              <span className="voyage-meta dim">{v.charter_party_code}</span>
            </button>
          ))}
        </aside>
        <main className="voyage-main">
          {selectedId ? (
            <VoyageDetail key={selectedId} voyageId={selectedId} />
          ) : (
            <p className="dim">请选择航次</p>
          )}
        </main>
      </div>
    </div>
  );
}
