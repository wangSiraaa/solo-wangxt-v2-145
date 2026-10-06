"""
引擎与结算不变性的测试。

覆盖需求点：跨午夜、重叠停工不重复扣减、刚好用尽允许时间、
一旦滞期持续滞期、NOR 送达≠被接受、缺证据保持待核对、
历史结算不可覆盖、金额 Decimal 精确核算。
"""
from datetime import datetime, timezone
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from .engine import IntervalItem, calculate_laytime, merge_intervals
from .models import (
    CharterParty,
    Clause,
    Event,
    EvidenceStatus,
    Settlement,
    Stoppage,
    Voyage,
)

UTC = timezone.utc


def dt(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def make_cp(code="TEST-CP", **overrides):
    """构造测试用虚构租约；可通过 overrides 调整条款参数。"""
    cp = CharterParty.objects.create(code=code, name="测试虚构租约")
    spec = [
        ("C-01", Clause.ClauseType.LAYTIME_ALLOWED, {"hours": overrides.get("allowed", "72")}),
        ("C-02", Clause.ClauseType.TURNTIME, {"hours": overrides.get("turntime", "6")}),
        ("C-03", Clause.ClauseType.EXCLUSION, {"reason": "WEATHER", "excluded": True}),
        ("C-04", Clause.ClauseType.EXCLUSION, {"reason": "WEEKEND_HOLIDAY", "excluded": True}),
        ("C-05", Clause.ClauseType.EXCLUSION, {"reason": "WAITING_BERTH", "excluded": False}),
        ("C-06", Clause.ClauseType.EXCLUSION, {"reason": "EQUIPMENT", "excluded": False}),
        ("C-07", Clause.ClauseType.DEMURRAGE_RATE, {"per_day": "12000", "currency": "USD"}),
        ("C-08", Clause.ClauseType.DESPATCH_RATE, {"per_day": "6000", "currency": "USD"}),
        ("C-09", Clause.ClauseType.ONCE_ON_DEMURRAGE,
         {"always": overrides.get("once_on_demurrage", True)}),
    ]
    for code, ctype, params in spec:
        Clause.objects.create(
            charter_party=cp, code=code, clause_type=ctype,
            title=code, text="虚构条款", params=params,
        )
    return cp


def make_voyage(cp, ref, nor_accepted, completed, stoppages=(), evidence=EvidenceStatus.VERIFIED):
    v = Voyage.objects.create(
        reference=ref, charter_party=cp, vessel_name="测试轮", port_name="测试港"
    )
    Event.objects.create(
        voyage=v, event_type=Event.EventType.NOR_TENDERED,
        occurred_at=nor_accepted, evidence_status=EvidenceStatus.VERIFIED,
    )
    if nor_accepted is not None:
        Event.objects.create(
            voyage=v, event_type=Event.EventType.NOR_ACCEPTED,
            occurred_at=nor_accepted, evidence_status=evidence,
        )
    if completed is not None:
        Event.objects.create(
            voyage=v, event_type=Event.EventType.COMPLETED,
            occurred_at=completed, evidence_status=EvidenceStatus.VERIFIED,
        )
    for reason, a, b, ev in stoppages:
        Stoppage.objects.create(
            voyage=v, reason=reason, started_at=a, ended_at=b, evidence_status=ev,
        )
    return v


class MergeIntervalsTests(TestCase):
    def test_overlapping_intervals_union_not_sum(self):
        base = dt(2026, 1, 1, 0)
        items = [
            IntervalItem(dt(2026, 1, 1, 10), dt(2026, 1, 1, 14), {"id": 1}),
            IntervalItem(dt(2026, 1, 1, 12), dt(2026, 1, 1, 16), {"id": 2}),
            IntervalItem(dt(2026, 1, 2, 1), dt(2026, 1, 2, 2), {"id": 3}),
        ]
        merged = merge_intervals(items)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["start"], dt(2026, 1, 1, 10))
        self.assertEqual(merged[0]["end"], dt(2026, 1, 1, 16))  # 6h 而非 4+4=8h
        self.assertEqual({p["id"] for p in merged[0]["payloads"]}, {1, 2})
        self.assertEqual(base < merged[0]["start"], True)


class EngineTests(TestCase):
    def setUp(self):
        self.cp = make_cp()

    def test_cross_midnight_stoppage_and_midnight_commencement(self):
        """跨午夜：NOR 18:00 被接受 + 6h → 00:00 起算；22:00→次日02:00 天气排除 4h。"""
        v = make_voyage(
            self.cp, "T-XMID",
            nor_accepted=dt(2026, 3, 10, 18), completed=dt(2026, 3, 13, 12),
            stoppages=[(Stoppage.Reason.WEATHER, dt(2026, 3, 11, 22), dt(2026, 3, 12, 2),
                        EvidenceStatus.VERIFIED)],
        )
        r = calculate_laytime(v)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["commencement"]["at"], "2026-03-11T00:00:00+00:00")
        self.assertEqual(r["time_summary"]["natural_hours"], "60.0000")
        self.assertEqual(r["time_summary"]["laytime_used_hours"], "56.0000")
        self.assertEqual(r["time_summary"]["despatch_hours"], "16.0000")
        charge = r["charges"][0]
        self.assertEqual(charge["type"], "DESPATCH")
        self.assertEqual(Decimal(charge["amount"]), Decimal("4000.00"))
        self.assertEqual(charge["trace"]["rate_clause"], "C-08")

    def test_overlapping_stoppages_not_double_deducted(self):
        """天气(排除)与设备故障(照计)重叠 2h：并集 6h 只扣天气 4h，不重复扣减。"""
        v = make_voyage(
            self.cp, "T-OVL",
            nor_accepted=dt(2026, 4, 1, 8), completed=dt(2026, 4, 5, 14),
            stoppages=[
                (Stoppage.Reason.WEATHER, dt(2026, 4, 2, 10), dt(2026, 4, 2, 14),
                 EvidenceStatus.VERIFIED),
                (Stoppage.Reason.EQUIPMENT, dt(2026, 4, 2, 12), dt(2026, 4, 2, 16),
                 EvidenceStatus.VERIFIED),
            ],
        )
        r = calculate_laytime(v)
        ts = r["time_summary"]
        self.assertEqual(ts["natural_hours"], "96.0000")
        self.assertEqual(ts["all_stoppage_hours"], "6.0000")   # 并集 10:00→16:00
        self.assertEqual(ts["working_hours"], "90.0000")
        self.assertEqual(ts["excluded_applied_hours"], "4.0000")  # 仅天气
        self.assertEqual(ts["laytime_used_hours"], "72.0000")
        self.assertEqual(ts["demurrage_hours"], "20.0000")
        self.assertEqual(Decimal(r["total_amount"]), Decimal("10000.00"))
        # 设备故障按条款照计，出现在“未排除停工”清单中
        self.assertEqual(len(r["non_excludable_stoppages"]), 1)
        self.assertEqual(r["non_excludable_stoppages"][0]["clause_code"], "C-06")

    def test_exact_exhaustion_no_demurrage_no_despatch(self):
        """刚好用尽 72.0000 小时：无滞期无速遣，给出边界说明。"""
        v = make_voyage(
            self.cp, "T-EXACT",
            nor_accepted=dt(2026, 5, 1, 0), completed=dt(2026, 5, 4, 12),
            stoppages=[(Stoppage.Reason.WEATHER, dt(2026, 5, 2, 6), dt(2026, 5, 2, 12),
                        EvidenceStatus.VERIFIED)],
        )
        r = calculate_laytime(v)
        self.assertEqual(r["time_summary"]["laytime_used_hours"], "72.0000")
        self.assertEqual(r["time_summary"]["demurrage_hours"], "0.0000")
        self.assertEqual(r["time_summary"]["despatch_hours"], "0.0000")
        self.assertEqual(r["charges"], [])
        self.assertEqual(Decimal(r["total_amount"]), Decimal("0.00"))
        self.assertIsNotNone(r["boundary_note"])
        self.assertEqual(r["exhaustion_at"], r["completion_at"])

    def test_once_on_demurrage_exclusion_stops_applying(self):
        """一旦滞期持续滞期：用尽点之后的天气停工不再排除。"""
        v = make_voyage(
            self.cp, "T-OOD",
            nor_accepted=dt(2026, 1, 1, 0), completed=dt(2026, 1, 6, 6),
            # 用尽点 = 01-01 06:00 + 72h = 01-04 06:00；天气 01-04 12:00→18:00 在用尽点之后
            stoppages=[(Stoppage.Reason.WEATHER, dt(2026, 1, 4, 12), dt(2026, 1, 4, 18),
                        EvidenceStatus.VERIFIED)],
        )
        r = calculate_laytime(v)
        self.assertEqual(r["exhaustion_at"], "2026-01-04T06:00:00+00:00")
        self.assertEqual(r["exclusions_applied"], [])
        self.assertEqual(len(r["exclusions_not_applied"]), 1)
        # 滞期 = 01-04 06:00 → 01-06 06:00 = 48h（天气 6h 不再扣除）
        self.assertEqual(r["time_summary"]["demurrage_hours"], "48.0000")
        self.assertEqual(Decimal(r["total_amount"]), Decimal("24000.00"))

    def test_without_once_on_demurrage_clause_exclusion_still_applies(self):
        cp = make_cp(code="TEST-CP-NOOD")
        # 去掉“一旦滞期”条款
        Clause.objects.filter(
            charter_party=cp, clause_type=Clause.ClauseType.ONCE_ON_DEMURRAGE
        ).delete()
        v = make_voyage(
            cp, "T-NOOD",
            nor_accepted=dt(2026, 1, 1, 0), completed=dt(2026, 1, 6, 6),
            stoppages=[(Stoppage.Reason.WEATHER, dt(2026, 1, 4, 12), dt(2026, 1, 4, 18),
                        EvidenceStatus.VERIFIED)],
        )
        r = calculate_laytime(v)
        self.assertEqual(len(r["exclusions_applied"]), 1)
        self.assertEqual(r["time_summary"]["demurrage_hours"], "42.0000")  # 48-6
        self.assertEqual(Decimal(r["total_amount"]), Decimal("21000.00"))

    def test_nor_tendered_but_not_accepted_blocks_calculation(self):
        """送达≠被接受：只有送达记录时计算被阻断。"""
        v = Voyage.objects.create(
            reference="T-NOR", charter_party=self.cp,
            vessel_name="测试轮", port_name="测试港",
        )
        Event.objects.create(
            voyage=v, event_type=Event.EventType.NOR_TENDERED,
            occurred_at=dt(2026, 1, 1, 8), evidence_status=EvidenceStatus.VERIFIED,
        )
        Event.objects.create(
            voyage=v, event_type=Event.EventType.COMPLETED,
            occurred_at=dt(2026, 1, 3, 8), evidence_status=EvidenceStatus.VERIFIED,
        )
        r = calculate_laytime(v)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertTrue(any("被接受" in b for b in r["block_reasons"]))
        self.assertTrue(any("送达与被接受是不同事实" in w for w in r["warnings"]))

    def test_unverified_fragments_make_provisional(self):
        """缺证据片段保持待核对：结果 PROVISIONAL 且列出待核对项。"""
        v = make_voyage(
            self.cp, "T-PEND",
            nor_accepted=dt(2026, 6, 1, 10), completed=dt(2026, 6, 3, 22),
            stoppages=[(Stoppage.Reason.WEATHER, dt(2026, 6, 2, 8), dt(2026, 6, 2, 14),
                        EvidenceStatus.PENDING)],
            evidence=EvidenceStatus.PENDING,
        )
        r = calculate_laytime(v)
        self.assertEqual(r["status"], "PROVISIONAL")
        kinds = {(u["kind"], u["label"]) for u in r["unverified_inputs"]}
        self.assertIn(("event", "准备就绪通知被接受"), kinds)
        self.assertIn(("stoppage", "停工·恶劣天气"), kinds)

    def test_decimal_money_rounding(self):
        """金额用 Decimal：1 小时滞期 = 12000/24 = 500.00，不允许浮点误差。"""
        v = make_voyage(
            self.cp, "T-MONEY",
            nor_accepted=dt(2026, 1, 1, 0), completed=dt(2026, 1, 4, 7),  # 73h 自然时间
        )
        r = calculate_laytime(v)
        self.assertEqual(r["time_summary"]["demurrage_hours"], "1.0000")
        self.assertEqual(Decimal(r["charges"][0]["amount"]), Decimal("500.00"))


class SettlementImmutabilityTests(TestCase):
    def setUp(self):
        self.cp = make_cp()
        self.voyage = make_voyage(
            self.cp, "T-SETTLE",
            nor_accepted=dt(2026, 3, 10, 18), completed=dt(2026, 3, 13, 12),
        )

    def _draft(self, version=1):
        report = calculate_laytime(self.voyage)
        return Settlement.objects.create(
            voyage=self.voyage, version=version, report=report,
            total_amount=report["total_amount"], currency="USD",
        )

    def test_finalized_settlement_cannot_be_modified_or_deleted(self):
        s = self._draft()
        s.finalize()
        s.total_amount = Decimal("999.00")
        with self.assertRaises(DjangoValidationError):
            s.save()
        with self.assertRaises(DjangoValidationError):
            s.delete()

    def test_new_version_supersedes_but_does_not_overwrite(self):
        s1 = self._draft(version=1)
        s1.finalize()
        s2 = self._draft(version=2)
        s2.finalize()  # 通过 API 流程才会取代；这里手动模拟
        # 手动走 API 的取代逻辑：
        s1.status = Settlement.Status.SUPERSEDED
        s1.save()
        s1.refresh_from_db()
        self.assertEqual(s1.status, Settlement.Status.SUPERSEDED)
        self.assertEqual(Settlement.objects.filter(voyage=self.voyage).count(), 2)
        # 历史版本仍可读、金额未被覆盖
        self.assertEqual(s1.total_amount, Decimal(str(s2.total_amount)))
        with self.assertRaises(DjangoValidationError):
            s1.delete()

    def test_superseded_is_frozen(self):
        s1 = self._draft(version=1)
        s1.finalize()
        s1.status = Settlement.Status.SUPERSEDED
        s1.save()
        s1.status = Settlement.Status.DRAFT
        with self.assertRaises(DjangoValidationError):
            s1.save()


class ApiTests(TestCase):
    def setUp(self):
        self.cp = make_cp()
        self.client = APIClient()
        self.voyage = make_voyage(
            self.cp, "T-API",
            nor_accepted=dt(2026, 3, 10, 18), completed=dt(2026, 3, 13, 12),
        )

    def test_calculate_endpoint_returns_traceable_report(self):
        resp = self.client.post(f"/api/voyages/{self.voyage.id}/calculate/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "OK")
        self.assertEqual(data["charges"][0]["trace"]["rate_clause"], "C-08")
        self.assertEqual(data["commencement"]["turntime_clause"], "C-02")

    def test_settle_finalize_and_history_not_overwritten(self):
        r1 = self.client.post(f"/api/voyages/{self.voyage.id}/settle/")
        self.assertEqual(r1.status_code, 201)
        s1 = r1.json()
        r2 = self.client.post(f"/api/settlements/{s1['id']}/finalize/")
        self.assertEqual(r2.status_code, 200)
        # 第二版
        r3 = self.client.post(f"/api/voyages/{self.voyage.id}/settle/")
        s2 = r3.json()
        self.assertEqual(s2["version"], 2)
        r4 = self.client.post(f"/api/settlements/{s2['id']}/finalize/")
        self.assertEqual(r4.status_code, 200)
        # 历史仍在，状态为已被取代
        hist = self.client.get(f"/api/settlements/{s1['id']}/").json()
        self.assertEqual(hist["status"], "SUPERSEDED")
        # 不允许更新（PUT/PATCH 不可用）
        self.assertIn(
            self.client.patch(f"/api/settlements/{s1['id']}/", {}, format="json").status_code,
            (405, 403),
        )
        # 已定稿不可删除
        self.assertEqual(
            self.client.delete(f"/api/settlements/{s2['id']}/").status_code, 400
        )

    def test_provisional_settlement_cannot_be_finalized(self):
        v = make_voyage(
            self.cp, "T-API-PEND",
            nor_accepted=dt(2026, 6, 1, 10), completed=dt(2026, 6, 3, 22),
            evidence=EvidenceStatus.PENDING,
        )
        r = self.client.post(f"/api/voyages/{v.id}/settle/")
        self.assertEqual(r.status_code, 201)
        sid = r.json()["id"]
        fin = self.client.post(f"/api/settlements/{sid}/finalize/")
        self.assertEqual(fin.status_code, 400)
        self.assertIn("待核对", fin.json()["detail"])

    def test_blocked_voyage_cannot_settle(self):
        v = Voyage.objects.create(
            reference="T-API-BLOCK", charter_party=self.cp,
            vessel_name="测试轮", port_name="测试港",
        )
        Event.objects.create(
            voyage=v, event_type=Event.EventType.NOR_TENDERED,
            occurred_at=dt(2026, 1, 1, 8), evidence_status=EvidenceStatus.VERIFIED,
        )
        r = self.client.post(f"/api/voyages/{v.id}/settle/")
        self.assertEqual(r.status_code, 400)
