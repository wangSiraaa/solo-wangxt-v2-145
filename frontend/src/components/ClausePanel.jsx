const TYPE_ORDER = {
  LAYTIME_ALLOWED: 1,
  TURNTIME: 2,
  EXCLUSION: 3,
  DEMURRAGE_RATE: 4,
  DESPATCH_RATE: 5,
  ONCE_ON_DEMURRAGE: 6,
};

/** 租约条款面板：计算所采用的每一条都可在此对照原文（虚构条款）。 */
export default function ClausePanel({ clauses }) {
  const sorted = [...clauses].sort(
    (a, b) => (TYPE_ORDER[a.clause_type] || 9) - (TYPE_ORDER[b.clause_type] || 9)
  );
  return (
    <section className="card">
      <h3>租约条款（虚构）</h3>
      <ul className="clause-list">
        {sorted.map((c) => (
          <li key={c.id} className="clause-item">
            <div className="clause-head">
              <span className="chip">{c.code}</span>
              <span className="clause-title">{c.title}</span>
              <span className="dim">{c.clause_type_display}</span>
            </div>
            <p className="clause-text">{c.text}</p>
            <p className="clause-params mono">{JSON.stringify(c.params)}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
