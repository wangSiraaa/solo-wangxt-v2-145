"""
Laytime calculation engine.

Three clocks are kept strictly separate:

* natural time   — wall-clock time from laytime start to cargo completion
* laytime used   — natural time minus excludable intervals (weekend /
                   weather / berth-wait), with overlapping reasons merged
                   by interval UNION so nothing is deducted twice
* working time   — natural time minus ALL stoppage intervals

Everything is Decimal. Intervals are half-open [start, end).
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

# All calendar-based judgements (weekend windows, midnight boundaries) are
# made in the project's local timezone; the ORM returns UTC under USE_TZ.
LOCAL_TZ = timezone.get_current_timezone()

HOUR = Decimal(3600)
DAY_HOURS = Decimal(24)
CENT = Decimal("0.01")


@dataclass
class Stoppage:
    start: datetime
    end: datetime
    reason: str  # WEATHER | BERTH_WAIT | OTHER
    fragment_ids: list = field(default_factory=list)


@dataclass
class Segment:
    start: datetime
    end: datetime
    hours: Decimal
    reasons: list          # active stoppage reasons (may be several: overlap)
    weekend: bool          # inside a clause-defined weekend window
    counted: bool          # counts against laytime
    working: bool          # cargo actually being worked
    clause_codes: list     # clauses that exclude this segment (empty if counted)

    def as_json(self):
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "hours": str(self.hours.quantize(Decimal("0.0001"))),
            "reasons": self.reasons,
            "weekend": self.weekend,
            "counted": self.counted,
            "working": self.working,
            "clause_codes": self.clause_codes,
        }


def hours_between(a: datetime, b: datetime) -> Decimal:
    return Decimal((b - a).total_seconds()) / HOUR


def pair_stoppages(events):
    """Pair STOPPAGE_START/END fragments per reason, in time order.

    An unclosed stoppage runs to the last known event and is flagged by the
    caller via the returned warnings list.
    """
    open_by_reason = {}
    stoppages, warnings = [], []
    last_seen = None
    for ev in events:
        last_seen = ev.occurred_at
        if ev.kind == "STOPPAGE_START":
            open_by_reason.setdefault(ev.reason, []).append(ev)
        elif ev.kind == "STOPPAGE_END":
            starts = open_by_reason.get(ev.reason) or []
            if starts:
                st = starts.pop(0)
                if ev.occurred_at > st.occurred_at:
                    stoppages.append(
                        Stoppage(st.occurred_at, ev.occurred_at, ev.reason,
                                 [st.id, ev.id])
                    )
    for reason, starts in open_by_reason.items():
        for st in starts:
            if last_seen and last_seen > st.occurred_at:
                stoppages.append(
                    Stoppage(st.occurred_at, last_seen, reason, [st.id])
                )
                warnings.append(
                    f"停工片段 #{st.id}（{reason}）无对应复工记录，"
                    f"按最后已知事件时间封闭，需人工复核。"
                )
    return stoppages, warnings


def weekend_windows(start: datetime, end: datetime, parameters: dict):
    """Generate weekend exclusion windows across [start, end].

    Default (fictional clause CP-02): Saturday 00:00 to Monday 00:00.
    `parameters` may override with {"from_weekday": 5, "from_hour": 0,
    "to_weekday": 0, "to_hour": 0}.
    """
    from_wd = int(parameters.get("from_weekday", 5))   # Saturday
    from_h = int(parameters.get("from_hour", 0))
    to_wd = int(parameters.get("to_weekday", 0))       # Monday
    to_h = int(parameters.get("to_hour", 0))
    windows = []
    day = datetime.combine(start.date() - timedelta(days=1), time.min,
                           tzinfo=start.tzinfo)
    limit = end + timedelta(days=2)
    while day <= limit:
        if day.weekday() == from_wd:
            w_start = day + timedelta(hours=from_h)
            days_to_end = (to_wd - from_wd) % 7 or 7
            w_end = (day + timedelta(days=days_to_end)).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(hours=to_h)
            windows.append((w_start, w_end))
        day += timedelta(days=1)
    return windows


# reason -> clause code that excludes it from laytime
REASON_CLAUSE = {"WEATHER": "CP-03", "BERTH_WAIT": "CP-04"}
EXCLUDABLE_REASONS = set(REASON_CLAUSE)


def classify_segments(start, end, stoppages, weekends):
    """Split [start, end) at every boundary; classify each elementary segment."""
    points = {start, end}
    for s in stoppages:
        points.add(max(s.start, start))
        points.add(min(s.end, end))
    for w0, w1 in weekends:
        points.add(max(w0, start))
        points.add(min(w1, end))
    ordered = sorted(p for p in points if start <= p <= end)

    segments = []
    for a, b in zip(ordered, ordered[1:]):
        if a >= b:
            continue
        reasons = sorted({s.reason for s in stoppages if s.start < b and s.end > a})
        in_weekend = any(w0 < b and w1 > a for w0, w1 in weekends)
        clauses = []
        if in_weekend:
            clauses.append("CP-02")
        clauses += [REASON_CLAUSE[r] for r in reasons if r in REASON_CLAUSE]
        counted = not clauses
        segments.append(
            Segment(
                start=a,
                end=b,
                hours=hours_between(a, b),
                reasons=reasons,
                weekend=in_weekend,
                counted=counted,
                working=not reasons and not in_weekend,
                clause_codes=clauses,
            )
        )
    return segments


def money(hours: Decimal, rate_per_day: Decimal) -> Decimal:
    return (hours / DAY_HOURS * rate_per_day).quantize(CENT, rounding=ROUND_HALF_UP)


def calculate(voyage):
    """Run the full calculation for a voyage. Returns a plain dict result.

    Never writes to the database — the view layer persists the Settlement.
    """
    cp = voyage.charter_party
    clauses = {c.code: c for c in cp.clauses.all()}
    params = {}
    for c in clauses.values():
        if c.rule_type == "WEEKEND_EXCLUSION":
            params = c.parameters or {}

    verified = [
        f for f in voyage.fragments.all()
        if f.evidence_status == "VERIFIED"
    ]
    pending = [
        f for f in voyage.fragments.all()
        if f.evidence_status == "PENDING"
    ]

    def first(kind):
        return next((f for f in verified if f.kind == kind), None)

    nor_tendered = first("NOR_TENDERED")
    nor_accepted = first("NOR_ACCEPTED")
    completion = first("COMPLETION")

    result = {
        "status": "FINAL",
        "blocked_reason": "",
        "warnings": [],
        "pending_fragment_ids": [f.id for f in pending],
        "segments": [],
        "lines": [],
        "totals": {},
    }

    # NOR tendered and NOR accepted are different facts: only acceptance
    # starts laytime (fictional clause CP-01).
    if not nor_accepted or not completion:
        result["status"] = "BLOCKED"
        if nor_tendered and not nor_accepted:
            result["blocked_reason"] = (
                "NOR 已送达但未被接受（CP-01：送达与接受是不同事实），"
                "装卸时间无法起算。"
            )
        elif not completion:
            result["blocked_reason"] = "缺少已核实的装卸完毕记录，无法结算。"
        else:
            result["blocked_reason"] = "缺少已核实的 NOR 接受记录，无法起算。"
        return result

    start = nor_accepted.occurred_at.astimezone(LOCAL_TZ)
    end = completion.occurred_at.astimezone(LOCAL_TZ)
    if end <= start:
        result["status"] = "BLOCKED"
        result["blocked_reason"] = "装卸完毕时间早于起算时间，数据异常。"
        return result

    stoppages, warnings = pair_stoppages(verified)
    for s in stoppages:
        s.start = s.start.astimezone(LOCAL_TZ)
        s.end = s.end.astimezone(LOCAL_TZ)
    result["warnings"] += warnings
    weekends = weekend_windows(start, end, params)
    segments = classify_segments(start, end, stoppages, weekends)

    natural = hours_between(start, end)
    used = sum((s.hours for s in segments if s.counted), Decimal(0))
    working = sum((s.hours for s in segments if s.working), Decimal(0))
    allowed = cp.laytime_allowed_hours

    counted_intervals = [s.as_json() for s in segments if s.counted]
    excluded_intervals = [s.as_json() for s in segments if not s.counted]

    lines = []
    if used > allowed:
        excess = used - allowed
        amount = money(excess, cp.demurrage_rate_per_day)
        lines.append({
            "kind": "DEMURRAGE",
            "label": "滞期费",
            "amount": amount,
            "basis_hours": excess,
            "rate_per_day": cp.demurrage_rate_per_day,
            "clause_codes": ["CP-01", "CP-05"],
            "intervals": counted_intervals,
        })
    elif used < allowed:
        saved = allowed - used
        amount = money(saved, cp.despatch_rate_per_day)
        lines.append({
            "kind": "DESPATCH",
            "label": "速遣费",
            "amount": amount,
            "basis_hours": saved,
            "rate_per_day": cp.despatch_rate_per_day,
            "clause_codes": ["CP-01", "CP-05"],
            "intervals": counted_intervals,
        })
    else:
        lines.append({
            "kind": "INFO",
            "label": "允许装卸时间刚好用尽，无滞期费/速遣费",
            "amount": Decimal("0.00"),
            "basis_hours": Decimal(0),
            "rate_per_day": Decimal(0),
            "clause_codes": ["CP-01"],
            "intervals": counted_intervals,
        })
    if excluded_intervals:
        lines.append({
            "kind": "INFO",
            "label": "不计入装卸时间的区间（重叠原因仅扣减一次，CP-05）",
            "amount": Decimal("0.00"),
            "basis_hours": natural - used,
            "rate_per_day": Decimal(0),
            "clause_codes": sorted(
                {c for s in segments if not s.counted for c in s.clause_codes}
            ),
            "intervals": excluded_intervals,
        })

    result["segments"] = [s.as_json() for s in segments]
    result["lines"] = lines
    result["totals"] = {
        "natural_hours": natural,
        "laytime_used_hours": used,
        "actual_working_hours": working,
        "allowed_hours": allowed,
        "demurrage_amount": lines[0]["amount"] if lines[0]["kind"] == "DEMURRAGE" else Decimal("0.00"),
        "despatch_amount": lines[0]["amount"] if lines[0]["kind"] == "DESPATCH" else Decimal("0.00"),
    }
    return result
