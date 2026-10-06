import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import Timeline from "./Timeline";
import ClauseList from "./ClauseList";
import SettlementView from "./SettlementView";

export default function VoyageDetail({ voyageId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api
      .getTimeline(voyageId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [voyageId]);

  useEffect(load, [load]);

  const recalculate = () =>
    api.calculate(voyageId).then(load).catch((e) => setError(e.message));

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p>加载中…</p>;

  const { voyage, fragments, latest_settlement } = data;
  return (
    <div>
      <h2>
        {voyage.label}
        <small>
          {voyage.vessel_name} · {voyage.port} · 允许{" "}
          {voyage.charter_party.laytime_allowed_hours}h · 滞期{" "}
          {voyage.charter_party.demurrage_rate_per_day}/天 · 速遣{" "}
          {voyage.charter_party.despatch_rate_per_day}/天
        </small>
      </h2>
      <Timeline fragments={fragments} />
      <ClauseList
        clauses={voyage.charter_party.clauses}
        disclaimer={voyage.charter_party.disclaimer}
      />
      {latest_settlement ? (
        <SettlementView
          settlement={latest_settlement}
          onRecalculate={recalculate}
        />
      ) : (
        <button onClick={recalculate}>开始核算</button>
      )}
    </div>
  );
}
