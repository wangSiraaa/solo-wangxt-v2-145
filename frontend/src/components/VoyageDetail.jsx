import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import Timeline from "./Timeline.jsx";
import ClausePanel from "./ClausePanel.jsx";
import CalcReport from "./CalcReport.jsx";
import SettlementPanel from "./SettlementPanel.jsx";

export default function VoyageDetail({ voyageId }) {
  const [voyage, setVoyage] = useState(null);
  const [report, setReport] = useState(null);       // 当前展示的报告
  const [reportSource, setReportSource] = useState("live"); // live | settlement id
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const v = await api.getVoyage(voyageId);
      setVoyage(v);
      return v;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }, [voyageId]);

  const runCalc = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await api.calculate(voyageId);
      setReport(r);
      setReportSource("live");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [voyageId]);

  useEffect(() => {
    reload().then((v) => {
      if (v) runCalc();
    });
  }, [reload, runCalc]);

  const patchEvidence = async (kind, id, status) => {
    try {
      if (kind === "event") await api.patchEvent(id, { evidence_status: status });
      else await api.patchStoppage(id, { evidence_status: status });
      await reload();
      await runCalc();
    } catch (e) {
      setError(e.message);
    }
  };

  const viewSettlement = (s) => {
    setReport(s.report);
    setReportSource(s.id);
  };

  if (!voyage) return <p className="dim">加载中…</p>;

  const viewingSettlement =
    reportSource !== "live"
      ? voyage.settlements.find((s) => s.id === reportSource)
      : null;

  return (
    <div className="voyage-detail">
      <section className="card voyage-head">
        <div>
          <h2>
            {voyage.reference} · {voyage.vessel_name}
          </h2>
          <p className="dim">
            {voyage.port_name} · {voyage.operation_display} · {voyage.cargo_description}
          </p>
        </div>
        <div className="voyage-head-right">
          <span className="chip">{voyage.charter_party.code}</span>
          <span className="dim">{voyage.charter_party.name}</span>
        </div>
      </section>

      {error && <div className="alert alert-bad">{error}</div>}

      <div className="columns">
        <div className="col-left">
          <Timeline
            events={voyage.events}
            stoppages={voyage.stoppages}
            onPatchEvidence={patchEvidence}
          />
          <ClausePanel clauses={voyage.charter_party.clauses} />
        </div>
        <div className="col-right">
          {viewingSettlement && (
            <div className="alert alert-lock">
              正在查看历史结算快照 v{viewingSettlement.version}（
              {viewingSettlement.status_display}）—— 快照不可修改、不可覆盖。
              <button className="btn btn-small" onClick={runCalc}>
                返回实时试算
              </button>
            </div>
          )}
          <CalcReport
            report={report}
            loading={loading}
            onRecalc={runCalc}
            readonly={reportSource !== "live"}
          />
          <SettlementPanel
            voyageId={voyageId}
            settlements={voyage.settlements}
            onChanged={reload}
            onView={viewSettlement}
          />
        </div>
      </div>
    </div>
  );
}
