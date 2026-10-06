"""
Seed a fictional charter party and four demo voyages:

  A  跨午夜天气停工（另含一条待核对片段）
  B  天气与等泊两个停工原因交叠 —— 并集扣减，不重复
  C  横跨周末且允许时间刚好用尽 —— 滞期/速遣均为零
  D  NOR 已送达但未被接受 —— 无法起算，保持阻塞

All clauses are fictional and for demonstration only.
"""
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from laytime.models import CharterParty, Clause, EventFragment, Voyage

TZ = timezone.get_current_timezone()


def ts(s):
    return timezone.make_aware(datetime.strptime(s, "%Y-%m-%d %H:%M"), TZ)


CLAUSES = [
    ("CP-01", "NOR 被接受方起算", "NOR_ACCEPTANCE",
     "装卸时间自准备就绪通知（NOR）被租家接受之时起算；NOR 仅送达而未被接受的，"
     "不起算。送达与接受是两个不同的事实。", {}),
    ("CP-02", "周末不计入", "WEEKEND_EXCLUSION",
     "星期六 00:00 至星期一 00:00 的时间不计入装卸时间。",
     {"from_weekday": 5, "from_hour": 0, "to_weekday": 0, "to_hour": 0}),
    ("CP-03", "天气停工不计入", "WEATHER_EXCLUSION",
     "因天气原因无法作业的时间不计入装卸时间。", {}),
    ("CP-04", "等泊时间不计入", "BERTH_WAIT_EXCLUSION",
     "船舶到达后等待泊位的时间不计入装卸时间。", {}),
    ("CP-05", "重叠原因不重复扣减", "NO_DOUBLE_COUNT",
     "同一时段存在多个不计入原因的，按时间区间的并集仅扣减一次。", {}),
    ("CP-06", "缺证据片段待核对", "EVIDENCE_REQUIRED",
     "缺乏核实证据的事件片段不参与核算，保持待核对状态直至补齐证据。", {}),
]


class Command(BaseCommand):
    help = "Seed fictional charter party, clauses and demo voyages."

    def handle(self, *args, **options):
        cp, _ = CharterParty.objects.update_or_create(
            code="FICT-2026",
            defaults={
                "name": "虚构航次租约（演示用）",
                "laytime_allowed_hours": Decimal("24.00"),
                "demurrage_rate_per_day": Decimal("12000.00"),
                "despatch_rate_per_day": Decimal("6000.00"),
            },
        )
        for code, title, rule, text, params in CLAUSES:
            Clause.objects.update_or_create(
                charter_party=cp, code=code,
                defaults={"title": title, "rule_type": rule,
                          "text": text, "parameters": params},
            )

        Voyage.objects.all().delete()  # idempotent reseed of demo voyages

        def voyage(label, vessel, port, allowed):
            v = Voyage.objects.create(
                label=label, vessel_name=vessel, port=port, charter_party=cp
            )
            if allowed is not None:
                # per-voyage override is modelled by a dedicated charter party
                # copy so the shared fixture stays intact
                own = CharterParty.objects.create(
                    code=f"FICT-2026-{v.pk}", name=f"{cp.name}（{label}）",
                    laytime_allowed_hours=allowed,
                    demurrage_rate_per_day=cp.demurrage_rate_per_day,
                    despatch_rate_per_day=cp.despatch_rate_per_day,
                )
                for code, title, rule, text, params in CLAUSES:
                    Clause.objects.create(
                        charter_party=own, code=code, title=title,
                        rule_type=rule, text=text, parameters=params,
                    )
                v.charter_party = own
                v.save()
            return v

        def frag(v, kind, when, reason="", status="VERIFIED", note=""):
            return EventFragment.objects.create(
                voyage=v, kind=kind, occurred_at=ts(when), reason=reason,
                evidence_status=status, note=note,
            )

        # --- Case A: cross-midnight weather stoppage ---------------------
        # NOR accepted Mon 2026-10-12 08:00, completed Tue 2026-10-13 12:00
        # natural 28h; weather 22:00 -> 02:00 (+1d) excluded 4h; used 24h
        # allowed 20h -> demurrage 4h -> 4/24 * 12000 = 2000.00
        a = voyage("案例A：跨午夜天气停工", "远洋号", "虚构港 3 号泊位",
                   Decimal("20.00"))
        frag(a, "ARRIVAL", "2026-10-12 06:30")
        frag(a, "NOR_TENDERED", "2026-10-12 07:00", note="代理电邮送达")
        frag(a, "NOR_ACCEPTED", "2026-10-12 08:00", note="租家书面确认接受")
        frag(a, "STOPPAGE_START", "2026-10-12 22:00", reason="WEATHER",
             note="暴雨，港口通告暂停作业")
        frag(a, "STOPPAGE_END", "2026-10-13 02:00", reason="WEATHER",
             note="跨午夜复工")
        frag(a, "STOPPAGE_START", "2026-10-12 14:00", reason="WEATHER",
             status="PENDING", note="船方声称降雨停工，缺港口记录佐证")
        frag(a, "STOPPAGE_END", "2026-10-12 15:00", reason="WEATHER",
             status="PENDING", note="同上，待核对")
        frag(a, "COMPLETION", "2026-10-13 12:00")

        # --- Case B: overlapping stoppage reasons ------------------------
        # NOR accepted Mon 06:00, completed Tue 18:00 -> natural 36h
        # weather 10:00-14:00, berth wait 12:00-16:00 -> union 10:00-16:00
        # excluded 6h (NOT 8h); used 30h; allowed 28h -> demurrage 2h = 1000
        b = voyage("案例B：天气与等泊交叠", "长风号", "虚构港 7 号泊位",
                   Decimal("28.00"))
        frag(b, "ARRIVAL", "2026-10-12 05:00")
        frag(b, "NOR_TENDERED", "2026-10-12 05:30")
        frag(b, "NOR_ACCEPTED", "2026-10-12 06:00")
        frag(b, "STOPPAGE_START", "2026-10-12 10:00", reason="WEATHER",
             note="雷雨")
        frag(b, "STOPPAGE_END", "2026-10-12 14:00", reason="WEATHER")
        frag(b, "STOPPAGE_START", "2026-10-12 12:00", reason="BERTH_WAIT",
             note="泊位被占用，等待移泊")
        frag(b, "STOPPAGE_END", "2026-10-12 16:00", reason="BERTH_WAIT")
        frag(b, "COMPLETION", "2026-10-13 18:00")

        # --- Case C: weekend exclusion, laytime exactly exhausted --------
        # NOR accepted Fri 2026-10-02 08:00, completed Mon 2026-10-05 08:00
        # natural 72h; weekend Sat 00:00 - Mon 00:00 excluded 48h; used 24h
        # allowed 24h -> exactly exhausted -> demurrage = despatch = 0
        c = voyage("案例C：跨周末且刚好用尽", "海平号", "虚构港 1 号泊位",
                   Decimal("24.00"))
        frag(c, "ARRIVAL", "2026-10-02 06:00")
        frag(c, "NOR_TENDERED", "2026-10-02 07:00")
        frag(c, "NOR_ACCEPTED", "2026-10-02 08:00")
        frag(c, "COMPLETION", "2026-10-05 08:00")

        # --- Case D: NOR tendered but never accepted ---------------------
        d = voyage("案例D：NOR 送达未被接受", "远帆号", "虚构港锚地", None)
        frag(d, "ARRIVAL", "2026-10-06 09:00")
        frag(d, "NOR_TENDERED", "2026-10-06 09:30",
             note="已送达，租家尚未书面接受")

        self.stdout.write(self.style.SUCCESS(
            f"Seeded charter party {cp.code} with {len(CLAUSES)} fictional "
            f"clauses and 4 demo voyages (A/B/C/D)."
        ))
