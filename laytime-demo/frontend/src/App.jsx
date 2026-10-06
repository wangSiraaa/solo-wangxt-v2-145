import React, { useEffect, useState } from "react";
import { api } from "./api";
import VoyageDetail from "./components/VoyageDetail";

export default function App() {
  const [voyages, setVoyages] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listVoyages().then(setVoyages).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>装卸时间与滞期速遣核算</h1>
        <p className="disclaimer">
          本系统使用虚构租约条款进行演示性核算，不构成法律解释或建议。
        </p>
      </header>
      {error && <p className="error">后端连接失败：{error}</p>}
      <div className="layout">
        <aside>
          <h2>航次</h2>
          <ul className="voyage-list">
            {voyages.map((v) => (
              <li
                key={v.id}
                className={selected === v.id ? "active" : ""}
                onClick={() => setSelected(v.id)}
              >
                <strong>{v.label}</strong>
                <span>
                  {v.vessel_name} · {v.port}
                </span>
              </li>
            ))}
          </ul>
        </aside>
        <main>
          {selected ? (
            <VoyageDetail voyageId={selected} key={selected} />
          ) : (
            <p className="hint">请选择左侧航次查看事件片段、条款与结算。</p>
          )}
        </main>
      </div>
    </div>
  );
}
