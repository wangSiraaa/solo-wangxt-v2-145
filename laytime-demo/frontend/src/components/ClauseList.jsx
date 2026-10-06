import React from "react";

export default function ClauseList({ clauses, disclaimer }) {
  return (
    <section>
      <h3>合同条款（虚构，仅演示用）</h3>
      <ul className="clauses">
        {clauses.map((c) => (
          <li key={c.code}>
            <strong>{c.code}</strong> {c.title}：{c.text}
          </li>
        ))}
      </ul>
      <p className="disclaimer">{disclaimer}</p>
    </section>
  );
}
