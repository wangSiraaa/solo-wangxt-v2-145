"""
装卸时间 / 滞期速遣计算引擎

设计要点
--------
* 全部金额用 Decimal 核算；时间内部以整数秒累计，仅在输出时换算小时。
* 三类时间分开：
    - 自然时间 natural      : 起算点 → 完工 的全部流逝时间
    - 实际作业时间 working  : 自然时间 − 全部停工（无论条款是否排除）
    - 允许计入时间 used     : 自然时间 − 条款排除的停工（即已用装卸时间）
* 重叠停工取并集，绝不重复扣减。
* 排除与否由租约条款决定（天气 / 周末节假日 / 等泊 / 设备故障…）。
* “一旦滞期，持续滞期”为可选条款：允许时间用尽后，排除不再适用。
* NOR 送达与被接受是不同事实；只认“被接受”作为起算依据。
* 缺证据（待核对/有争议）的片段不会阻止试算，但结果标记为 PROVISIONAL，
  且此类结算不允许定稿。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .models import Clause, Event, EvidenceStatus, Stoppage

SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
CENT = Decimal("0.01")
HOUR_Q = Decimal("0.0001")


def _hours(seconds: int | float) -> Decimal:
    """秒 → 小时（Decimal，4 位小数）"""
    return (Decimal(int(seconds)) / Decimal(SECONDS_PER_HOUR)).quantize(HOUR_Q)


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- 区间合并

@dataclass
class IntervalItem:
    start: datetime
    end: datetime
    payload: dict[str, Any]


def merge_intervals(items: list[IntervalItem]) -> list[dict[str, Any]]:
    """
    区间并集。重叠/相接的区间合并为一个，同时保留全部贡献者
    （停工记录 id、原因、条款号），保证重叠原因不被重复扣减且可追溯。
    """
    merged: list[dict[str, Any]] = []
    for it in sorted(items, key=lambda x: (x.start, x.end)):
        if merged and it.start <= merged[-1]["end"]:
            m = merged[-1]
            if it.end > m["end"]:
                m["end"] = it.end
            m["payloads"].append(it.payload)
        else:
            merged.append({"start": it.start, "end": it.end, "payloads": [it.payload]})
    return merged


# ---------------------------------------------------------------- 条款配置

@dataclass
class EngineConfig:
    allowed_hours: Decimal = Decimal("72")
    turntime_hours: Decimal = Decimal("6")
    excluded_reasons: dict[str, bool] = field(default_factory=dict)  # reason -> 是否排除
    demurrage_rate: Decimal | None = None      # 每天
    despatch_rate: Decimal | None = None       # 每天
    once_on_demurrage: bool = False
    currency: str = "USD"
    # 条款溯源: 配置项 -> 条款编号
    clause_refs: dict[str, str | None] = field(default_factory=dict)


def build_config(clauses: list[Clause]) -> tuple[EngineConfig, list[str]]:
    cfg = EngineConfig()
    warnings: list[str] = []
    refs: dict[str, str | None] = {
        "allowed": None, "turntime": None, "demurrage_rate": None,
        "despatch_rate": None, "once_on_demurrage": None,
    }
    exclusion_clause_by_reason: dict[str, str] = {}

    for c in clauses:
        p = c.params or {}
        if c.clause_type == Clause.ClauseType.LAYTIME_ALLOWED:
            cfg.allowed_hours = Decimal(str(p.get("hours", cfg.allowed_hours)))
            refs["allowed"] = c.code
        elif c.clause_type == Clause.ClauseType.TURNTIME:
            cfg.turntime_hours = Decimal(str(p.get("hours", cfg.turntime_hours)))
            refs["turntime"] = c.code
        elif c.clause_type == Clause.ClauseType.EXCLUSION:
            reason = p.get("reason")
            if reason:
                cfg.excluded_reasons[reason] = bool(p.get("excluded", False))
                exclusion_clause_by_reason[reason] = c.code
        elif c.clause_type == Clause.ClauseType.DEMURRAGE_RATE:
            cfg.demurrage_rate = Decimal(str(p["per_day"])) if "per_day" in p else None
            cfg.currency = p.get("currency", cfg.currency)
            refs["demurrage_rate"] = c.code
        elif c.clause_type == Clause.ClauseType.DESPATCH_RATE:
            cfg.despatch_rate = Decimal(str(p["per_day"])) if "per_day" in p else None
            refs["despatch_rate"] = c.code
        elif c.clause_type == Clause.ClauseType.ONCE_ON_DEMURRAGE:
            cfg.once_on_demurrage = bool(p.get("always", False))
            refs["once_on_demurrage"] = c.code

    if refs["allowed"] is None:
        warnings.append("租约缺少“允许装卸时间”条款，按默认 72 小时试算。")
    if refs["turntime"] is None:
        warnings.append("租约缺少“起算准备时间”条款，按默认 6 小时试算。")
    if cfg.demurrage_rate is None:
        warnings.append("租约缺少滞期费率条款，滞期费无法计价。")
    if cfg.despatch_rate is None:
        warnings.append("租约缺少速遣费率条款，速遣费无法计价。")

    cfg.clause_refs = refs
    cfg.exclusion_clause_by_reason = exclusion_clause_by_reason  # type: ignore[attr-defined]
    return cfg, warnings


# ---------------------------------------------------------------- 主计算

def calculate_laytime(voyage) -> dict[str, Any]:
    """对单个航次运行完整核算，返回可 JSON 序列化的报告。"""
    events = {e.event_type: e for e in voyage.events.all()}
    stoppages = list(voyage.stoppages.all())
    clauses = list(voyage.charter_party.clauses.all())
    cfg, warnings = build_config(clauses)

    unverified: list[dict[str, Any]] = []
    for e in voyage.events.all():
        if e.evidence_status != EvidenceStatus.VERIFIED:
            unverified.append({
                "kind": "event", "id": e.id,
                "label": e.get_event_type_display(),
                "status": e.get_evidence_status_display(),
            })
    for s in stoppages:
        if s.evidence_status != EvidenceStatus.VERIFIED:
            unverified.append({
                "kind": "stoppage", "id": s.id,
                "label": f"停工·{s.get_reason_display()}",
                "status": s.get_evidence_status_display(),
            })

    report: dict[str, Any] = {
        "engine": "laytime-engine/1.0",
        "voyage_id": voyage.id,
        "voyage_reference": voyage.reference,
        "charter_party": {
            "code": voyage.charter_party.code,
            "name": voyage.charter_party.name,
            "fictional_notice": voyage.charter_party.fictional_notice,
        },
        "currency": cfg.currency,
        "warnings": warnings,
        "unverified_inputs": unverified,
    }

    # ---- 事实核查：NOR 送达与被接受是不同事实，起算只认“被接受” ----
    nor_tendered = events.get(Event.EventType.NOR_TENDERED)
    nor_accepted = events.get(Event.EventType.NOR_ACCEPTED)
    completed = events.get(Event.EventType.COMPLETED)

    facts = []
    for et in Event.EventType:
        e = events.get(et)
        facts.append({
            "event_type": et.value,
            "label": Event.EventType(et).label,
            "occurred_at": _iso(e.occurred_at) if e else None,
            "evidence_status": e.evidence_status if e else None,
            "event_id": e.id if e else None,
        })
    report["facts"] = facts

    block_reasons: list[str] = []
    if nor_tendered and not nor_accepted:
        warnings.append(
            "准备就绪通知已送达但无“被接受”记录：送达与被接受是不同事实，"
            "起算点无法确定。"
        )
    if not nor_accepted:
        block_reasons.append("缺少“准备就绪通知被接受”记录，装卸时间起算点无法确定。")
    if not completed:
        block_reasons.append("缺少“完工”记录，装卸时间终点无法确定。")
    if block_reasons:
        report.update({"status": "BLOCKED", "block_reasons": block_reasons})
        return report

    turntime = timedelta(seconds=int(cfg.turntime_hours * SECONDS_PER_HOUR))
    commencement = nor_accepted.occurred_at + turntime
    end = completed.occurred_at
    if end <= commencement:
        report.update({
            "status": "BLOCKED",
            "block_reasons": ["完工时间早于或等于起算时间，请核对事实时间表。"],
        })
        return report

    report["commencement"] = {
        "at": _iso(commencement),
        "basis": "准备就绪通知被接受时间 + 起算准备时间",
        "nor_accepted_event_id": nor_accepted.id,
        "turntime_clause": cfg.clause_refs["turntime"],
        "turntime_hours": str(cfg.turntime_hours),
    }
    report["completion_at"] = _iso(end)

    # ---- 停工片段裁剪到 [起算, 完工] ----
    clipped: list[tuple[datetime, datetime, Stoppage]] = []
    for s in stoppages:
        a, b = max(s.started_at, commencement), min(s.ended_at, end)
        if a < b:
            clipped.append((a, b, s))

    # 实际作业时间：自然时间 − 全部停工并集（无论条款是否排除）
    merged_all = merge_intervals([
        IntervalItem(a, b, {"id": s.id, "reason": s.reason}) for a, b, s in clipped
    ])
    natural_seconds = int((end - commencement).total_seconds())
    stopped_seconds = sum(int((m["end"] - m["start"]).total_seconds()) for m in merged_all)
    working_seconds = natural_seconds - stopped_seconds

    # ---- 条款排除：只取条款声明为排除的原因 ----
    exclusion_clause_by_reason = cfg.exclusion_clause_by_reason  # type: ignore[attr-defined]
    excludable = [
        (a, b, s) for a, b, s in clipped
        if cfg.excluded_reasons.get(s.reason, False)
    ]
    merged_excl = merge_intervals([
        IntervalItem(a, b, {
            "id": s.id,
            "reason": s.reason,
            "reason_label": s.get_reason_display(),
            "clause_code": exclusion_clause_by_reason.get(s.reason),
        })
        for a, b, s in excludable
    ])

    # 条款未排除的停工：仍计入装卸时间（列出以便追溯）
    non_excludable_stoppages = []
    for a, b, s in clipped:
        if not cfg.excluded_reasons.get(s.reason, False):
            non_excludable_stoppages.append({
                "stoppage_id": s.id,
                "reason": s.reason,
                "reason_label": s.get_reason_display(),
                "start": _iso(a), "end": _iso(b),
                "hours": str(_hours((b - a).total_seconds())),
                "clause_code": exclusion_clause_by_reason.get(s.reason),
                "effect": "按条款不计入排除，仍占用装卸时间",
            })

    # ---- 时间轴推进：分段 + “一旦滞期持续滞期” ----
    allowed_seconds = int(cfg.allowed_hours * SECONDS_PER_HOUR)
    segments: list[dict[str, Any]] = []
    applied_exclusions: list[dict[str, Any]] = []
    exclusions_not_applied: list[dict[str, Any]] = []

    t = commencement
    used_seconds = 0
    exhaustion_at: datetime | None = None

    def emit(kind: str, a: datetime, b: datetime, **extra: Any) -> None:
        if b <= a:
            return
        segments.append({
            "kind": kind,
            "start": _iso(a), "end": _iso(b),
            "hours": str(_hours((b - a).total_seconds())),
            **extra,
        })

    for iv in merged_excl + [{"start": end, "end": end, "payloads": []}]:
        gap_end = min(iv["start"], end)
        # —— 排除区间之前的计数/滞期段 ——
        if gap_end > t:
            gap_seconds = int((gap_end - t).total_seconds())
            if exhaustion_at is None:
                if used_seconds + gap_seconds >= allowed_seconds:
                    exh = t + timedelta(seconds=allowed_seconds - used_seconds)
                    emit("COUNTING", t, exh)
                    used_seconds = allowed_seconds
                    exhaustion_at = exh
                    emit("DEMURRAGE", exh, gap_end, note="允许时间已用尽")
                else:
                    emit("COUNTING", t, gap_end)
                    used_seconds += gap_seconds
            else:
                emit("DEMURRAGE", t, gap_end)
            t = gap_end
        # —— 排除区间本身 ——
        iv_start, iv_end = max(iv["start"], t), min(iv["end"], end)
        if iv_end > iv_start and iv["payloads"]:
            reasons = sorted({p["reason_label"] for p in iv["payloads"]})
            clause_codes = sorted({p["clause_code"] for p in iv["payloads"] if p["clause_code"]})
            stoppage_ids = sorted({p["id"] for p in iv["payloads"]})
            secs = int((iv_end - iv_start).total_seconds())
            applies = (not cfg.once_on_demurrage) or (exhaustion_at is None)
            entry = {
                "start": _iso(iv_start), "end": _iso(iv_end),
                "hours": str(_hours(secs)),
                "reasons": reasons,
                "clause_codes": clause_codes,
                "stoppage_ids": stoppage_ids,
            }
            if applies:
                emit("EXCLUDED", iv_start, iv_end,
                     reasons=reasons, clause_codes=clause_codes,
                     stoppage_ids=stoppage_ids)
                applied_exclusions.append(entry)
            else:
                emit("DEMURRAGE", iv_start, iv_end,
                     reasons=reasons, clause_codes=clause_codes,
                     stoppage_ids=stoppage_ids,
                     note="一旦滞期，持续滞期：该排除不再适用")
                entry["not_applied_because"] = (
                    f"允许时间已于 {_iso(exhaustion_at)} 用尽，"
                    f"依据条款 {cfg.clause_refs['once_on_demurrage']} 排除不再适用"
                )
                exclusions_not_applied.append(entry)
            t = max(t, iv_end)

    demurrage_seconds = sum(
        int((datetime.fromisoformat(s["end"]) - datetime.fromisoformat(s["start"])).total_seconds())
        for s in segments if s["kind"] == "DEMURRAGE"
    )
    laytime_used_seconds = min(used_seconds, allowed_seconds)
    saved_seconds = max(0, allowed_seconds - used_seconds) if exhaustion_at is None else 0

    # ---- 费用（Decimal 核算） ----
    charges: list[dict[str, Any]] = []
    if demurrage_seconds > 0:
        if cfg.demurrage_rate is not None:
            amount = _money(
                Decimal(demurrage_seconds) * cfg.demurrage_rate / Decimal(SECONDS_PER_DAY)
            )
            charges.append({
                "type": "DEMURRAGE",
                "label": "滞期费",
                "period": {"from": _iso(exhaustion_at), "to": _iso(end)},
                "hours": str(_hours(demurrage_seconds)),
                "rate_per_day": str(cfg.demurrage_rate),
                "amount": str(amount),
                "trace": {
                    "rate_clause": cfg.clause_refs["demurrage_rate"],
                    "allowed_clause": cfg.clause_refs["allowed"],
                    "once_on_demurrage_clause": (
                        cfg.clause_refs["once_on_demurrage"] if cfg.once_on_demurrage else None
                    ),
                    "formula": f"{_hours(demurrage_seconds)}小时 ÷ 24 × {cfg.demurrage_rate}/天",
                },
            })
        else:
            warnings.append("存在滞期时间但缺少滞期费率条款，滞期费未计价。")
    elif saved_seconds > 0:
        if cfg.despatch_rate is not None:
            amount = _money(
                Decimal(saved_seconds) * cfg.despatch_rate / Decimal(SECONDS_PER_DAY)
            )
            charges.append({
                "type": "DESPATCH",
                "label": "速遣费",
                "period": {"from": _iso(commencement), "to": _iso(end)},
                "hours": str(_hours(saved_seconds)),
                "rate_per_day": str(cfg.despatch_rate),
                "amount": str(amount),
                "trace": {
                    "rate_clause": cfg.clause_refs["despatch_rate"],
                    "allowed_clause": cfg.clause_refs["allowed"],
                    "once_on_demurrage_clause": None,
                    "formula": f"节省{_hours(saved_seconds)}小时 ÷ 24 × {cfg.despatch_rate}/天",
                },
            })
        else:
            warnings.append("存在节省时间但缺少速遣费率条款，速遣费未计价。")

    total = sum((Decimal(c["amount"]) for c in charges), Decimal("0"))

    report.update({
        "status": "PROVISIONAL" if unverified else "OK",
        "allowed_hours": str(cfg.allowed_hours),
        "allowed_clause": cfg.clause_refs["allowed"],
        "exhaustion_at": _iso(exhaustion_at),
        "time_summary": {
            "natural_hours": str(_hours(natural_seconds)),          # 自然时间
            "all_stoppage_hours": str(_hours(stopped_seconds)),     # 全部停工
            "working_hours": str(_hours(working_seconds)),          # 实际作业时间
            "excluded_applied_hours": str(_hours(sum(
                int((datetime.fromisoformat(e["end"]) - datetime.fromisoformat(e["start"])).total_seconds())
                for e in applied_exclusions
            ))),
            "laytime_used_hours": str(_hours(laytime_used_seconds)),  # 允许计入时间（已用）
            "demurrage_hours": str(_hours(demurrage_seconds)),
            "despatch_hours": str(_hours(saved_seconds)),
        },
        "segments": segments,
        "exclusions_applied": applied_exclusions,
        "exclusions_not_applied": exclusions_not_applied,
        "non_excludable_stoppages": non_excludable_stoppages,
        "charges": charges,
        "total_amount": str(_money(total)),
        "boundary_note": (
            "允许时间刚好用尽：既无滞期也无速遣。"
            if exhaustion_at is not None and demurrage_seconds == 0 and saved_seconds == 0
            else None
        ),
    })
    return report
