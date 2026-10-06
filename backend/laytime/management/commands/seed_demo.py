"""
载入演示数据：虚构租约 FICTCON-2026 + 四个典型航次案例。

案例覆盖：
  VOY-DEMO-001  跨午夜停工（起算点恰在午夜，天气停工 22:00→次日02:00）→ 速遣
  VOY-DEMO-002  多个停工原因交叠（天气与设备故障重叠，不重复扣减）→ 滞期
  VOY-DEMO-003  刚好用尽允许时间（72.0000 小时整）→ 无滞期无速遣
  VOY-DEMO-004  缺证据片段（NOR 被接受、天气停工均待核对）→ PROVISIONAL，不可定稿

再次执行会删除旧演示数据并重建（仅 VOY-DEMO-* 与 FICTCON-2026）。
"""
from datetime import datetime, timezone
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from laytime.engine import calculate_laytime
from laytime.models import (
    CharterParty,
    Clause,
    Event,
    EvidenceStatus,
    Settlement,
    Stoppage,
    Voyage,
)

UTC = timezone.utc
V = EvidenceStatus.VERIFIED
P = EvidenceStatus.PENDING


def dt(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


CLAUSES = [
    ("FIC-01", Clause.ClauseType.LAYTIME_ALLOWED, "允许装卸时间",
     "装卸两港合计允许使用连续 72 小时作为装卸时间。",
     {"hours": "72"}),
    ("FIC-02", Clause.ClauseType.TURNTIME, "起算准备时间",
     "装卸时间自准备就绪通知书被接受后 6 小时起算。",
     {"hours": "6"}),
    ("FIC-03", Clause.ClauseType.EXCLUSION, "恶劣天气排除",
     "因恶劣天气实际造成停工的时间，不计入装卸时间。",
     {"reason": "WEATHER", "excluded": True}),
    ("FIC-04", Clause.ClauseType.EXCLUSION, "周末及节假日排除",
     "周六、周日及当地节假日期间的停工时间，不计入装卸时间。",
     {"reason": "WEEKEND_HOLIDAY", "excluded": True}),
    ("FIC-05", Clause.ClauseType.EXCLUSION, "等泊照计",
     "等待泊位所耗时间计入装卸时间，不予排除。",
     {"reason": "WAITING_BERTH", "excluded": False}),
    ("FIC-06", Clause.ClauseType.EXCLUSION, "船舶设备故障照计",
     "因船舶自身设备故障造成的停工时间计入装卸时间，不予排除。",
     {"reason": "EQUIPMENT", "excluded": False}),
    ("FIC-07", Clause.ClauseType.DEMURRAGE_RATE, "滞期费率",
     "滞期费率为每日 12,000 美元，不足一日按比例计算。",
     {"per_day": "12000", "currency": "USD"}),
    ("FIC-08", Clause.ClauseType.DESPATCH_RATE, "速遣费率",
     "速遣费率为每日 6,000 美元（滞期费率之半），不足一日按比例计算。",
     {"per_day": "6000", "currency": "USD"}),
    ("FIC-09", Clause.ClauseType.ONCE_ON_DEMURRAGE, "一旦滞期持续滞期",
     "允许装卸时间一经用尽，船舶即处于滞期状态，此后各项时间排除均不再适用。",
     {"always": True}),
]


class Command(BaseCommand):
    help = "载入虚构租约与演示航次（跨午夜/重叠停工/刚好用尽/待核对）"

    @transaction.atomic
    def handle(self, *args, **options):
        Voyage.objects.filter(reference__startswith="VOY-DEMO-").delete()
        CharterParty.objects.filter(code="FICTCON-2026").delete()

        cp = CharterParty.objects.create(
            code="FICTCON-2026",
            name="虚构件杂货租约（演示版）",
        )
        for code, ctype, title, text, params in CLAUSES:
            Clause.objects.create(
                charter_party=cp, code=code, clause_type=ctype,
                title=title, text=text, params=params,
            )

        # ---------- 案例 1：跨午夜 ----------
        v1 = Voyage.objects.create(
            reference="VOY-DEMO-001", charter_party=cp,
            vessel_name="远洋之星", port_name="东海港",
            cargo_description="钢材 12,000 吨", operation=Voyage.Operation.DISCHARGE,
        )
        self._events(v1, [
            (Event.EventType.ARRIVAL, dt(2026, 3, 10, 15), V, "代理抵港报告"),
            (Event.EventType.NOR_TENDERED, dt(2026, 3, 10, 16), V, "船长电文"),
            (Event.EventType.NOR_ACCEPTED, dt(2026, 3, 10, 18), V, "租家确认回执"),
            (Event.EventType.BERTHED, dt(2026, 3, 10, 20), V, "代理靠泊报告"),
            (Event.EventType.COMMENCED, dt(2026, 3, 11, 0, 30), V, "理货记录"),
            (Event.EventType.COMPLETED, dt(2026, 3, 13, 12), V, "完工证书"),
        ])
        Stoppage.objects.create(
            voyage=v1, reason=Stoppage.Reason.WEATHER,
            started_at=dt(2026, 3, 11, 22), ended_at=dt(2026, 3, 12, 2),
            evidence_status=V, source="气象记录+甲板日志",
            note="大风封舱，停工跨午夜",
        )

        # ---------- 案例 2：重叠停工 ----------
        v2 = Voyage.objects.create(
            reference="VOY-DEMO-002", charter_party=cp,
            vessel_name="恒远轮", port_name="南湾港",
            cargo_description="化肥 20,000 吨", operation=Voyage.Operation.LOAD,
        )
        self._events(v2, [
            (Event.EventType.ARRIVAL, dt(2026, 4, 1, 2), V, "代理抵港报告"),
            (Event.EventType.NOR_TENDERED, dt(2026, 4, 1, 6), V, "船长电文"),
            (Event.EventType.NOR_ACCEPTED, dt(2026, 4, 1, 8), V, "租家确认回执"),
            (Event.EventType.BERTHED, dt(2026, 4, 1, 10), V, "代理靠泊报告"),
            (Event.EventType.COMMENCED, dt(2026, 4, 1, 15), V, "理货记录"),
            (Event.EventType.COMPLETED, dt(2026, 4, 5, 14), V, "完工证书"),
        ])
        Stoppage.objects.create(
            voyage=v2, reason=Stoppage.Reason.WEATHER,
            started_at=dt(2026, 4, 2, 10), ended_at=dt(2026, 4, 2, 14),
            evidence_status=V, source="气象记录",
            note="暴雨停工（条款排除）",
        )
        Stoppage.objects.create(
            voyage=v2, reason=Stoppage.Reason.EQUIPMENT,
            started_at=dt(2026, 4, 2, 12), ended_at=dt(2026, 4, 2, 16),
            evidence_status=V, source="轮机日志",
            note="克令吊故障，与暴雨时段重叠 2 小时（条款照计）",
        )

        # ---------- 案例 3：刚好用尽 ----------
        v3 = Voyage.objects.create(
            reference="VOY-DEMO-003", charter_party=cp,
            vessel_name="启航号", port_name="北仑港",
            cargo_description="卷钢 9,500 吨", operation=Voyage.Operation.DISCHARGE,
        )
        self._events(v3, [
            (Event.EventType.ARRIVAL, dt(2026, 4, 30, 20), V, "代理抵港报告"),
            (Event.EventType.NOR_TENDERED, dt(2026, 4, 30, 22), V, "船长电文"),
            (Event.EventType.NOR_ACCEPTED, dt(2026, 5, 1, 0), V, "租家确认回执"),
            (Event.EventType.BERTHED, dt(2026, 5, 1, 2), V, "代理靠泊报告"),
            (Event.EventType.COMMENCED, dt(2026, 5, 1, 7), V, "理货记录"),
            (Event.EventType.COMPLETED, dt(2026, 5, 4, 12), V, "完工证书"),
        ])
        Stoppage.objects.create(
            voyage=v3, reason=Stoppage.Reason.WEATHER,
            started_at=dt(2026, 5, 2, 6), ended_at=dt(2026, 5, 2, 12),
            evidence_status=V, source="气象记录",
            note="雷暴停工 6 小时（条款排除）",
        )

        # ---------- 案例 4：待核对 ----------
        v4 = Voyage.objects.create(
            reference="VOY-DEMO-004", charter_party=cp,
            vessel_name="云帆轮", port_name="西沙港",
            cargo_description="袋装水泥 8,000 吨", operation=Voyage.Operation.DISCHARGE,
        )
        self._events(v4, [
            (Event.EventType.ARRIVAL, dt(2026, 6, 1, 6), V, "代理抵港报告"),
            (Event.EventType.NOR_TENDERED, dt(2026, 6, 1, 8), V, "船长电文"),
            (Event.EventType.NOR_ACCEPTED, dt(2026, 6, 1, 10), P,
             "租家口头确认，书面回执未到"),
            (Event.EventType.BERTHED, dt(2026, 6, 1, 12), V, "代理靠泊报告"),
            (Event.EventType.COMMENCED, dt(2026, 6, 1, 17), V, "理货记录"),
            (Event.EventType.COMPLETED, dt(2026, 6, 3, 22), V, "完工证书"),
        ])
        Stoppage.objects.create(
            voyage=v4, reason=Stoppage.Reason.WEATHER,
            started_at=dt(2026, 6, 2, 8), ended_at=dt(2026, 6, 2, 14),
            evidence_status=P, source="仅甲板日志，缺气象证明",
            note="据称大雨停工，证据待补",
        )

        # ---------- 案例 1 的历史结算（已定稿，演示不可覆盖） ----------
        report = calculate_laytime(v1)
        Settlement.objects.create(
            voyage=v1, version=1, status=Settlement.Status.FINAL,
            report=report, total_amount=Decimal(report["total_amount"]),
            currency=report["currency"],
            note="首期结算（演示历史数据）",
            finalized_at=dt(2026, 3, 20, 9),
        )

        self.stdout.write(self.style.SUCCESS(
            "演示数据已载入：FICTCON-2026 租约 9 条条款，4 个航次，"
            "VOY-DEMO-001 含已定稿历史结算 v1。"
        ))

    @staticmethod
    def _events(voyage, rows):
        for etype, when, status, source in rows:
            Event.objects.create(
                voyage=voyage, event_type=etype, occurred_at=when,
                evidence_status=status, source=source,
            )
