from datetime import datetime
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import EventFragment, Settlement, Voyage

TZ = timezone.get_current_timezone()


def ts(s):
    return timezone.make_aware(datetime.strptime(s, "%Y-%m-%d %H:%M"), TZ)


class EngineCaseTests(TestCase):
    """The three required scenarios, seeded by seed_demo."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def calc(self, label):
        voyage = Voyage.objects.get(label=label)
        client = APIClient()
        resp = client.post(f"/api/voyages/{voyage.pk}/calculate/")
        assert resp.status_code == 201, resp.content
        return resp.json()

    def test_case_a_cross_midnight_and_pending_evidence(self):
        data = self.calc("案例A：跨午夜天气停工")
        # natural 28h, cross-midnight weather 22:00->02:00 excluded 4h
        self.assertEqual(Decimal(data["natural_hours"]), Decimal("28.0000"))
        self.assertEqual(Decimal(data["laytime_used_hours"]), Decimal("24.0000"))
        self.assertEqual(Decimal(data["actual_working_hours"]), Decimal("24.0000"))
        # allowed 20h -> 4h demurrage at 12000/day
        self.assertEqual(Decimal(data["demurrage_amount"]), Decimal("2000.00"))
        self.assertEqual(Decimal(data["despatch_amount"]), Decimal("0.00"))
        # the unverified 14:00-15:00 weather claim stays pending, not deducted
        self.assertEqual(len(data["pending_fragment_ids"]), 2)
        excluded = [s for s in data["segments"] if not s["counted"]]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["hours"], "4.0000")
        self.assertEqual(excluded[0]["clause_codes"], ["CP-03"])
        # demurrage line traces back to the counted intervals
        dem = next(l for l in data["lines"] if l["kind"] == "DEMURRAGE")
        self.assertEqual(Decimal(dem["basis_hours"]), Decimal("4.0000"))
        self.assertTrue(dem["intervals"])

    def test_case_b_overlapping_reasons_deducted_once(self):
        data = self.calc("案例B：天气与等泊交叠")
        # natural 36h; weather 10-14 + berth 12-16 -> union 10-16 = 6h only
        self.assertEqual(Decimal(data["natural_hours"]), Decimal("36.0000"))
        self.assertEqual(Decimal(data["laytime_used_hours"]), Decimal("30.0000"))
        # allowed 28h -> 2h demurrage = 1000.00
        self.assertEqual(Decimal(data["demurrage_amount"]), Decimal("1000.00"))
        excluded = [s for s in data["segments"] if not s["counted"]]
        self.assertEqual(sum(Decimal(s["hours"]) for s in excluded),
                         Decimal("6.0000"))
        # the 12:00-14:00 overlap carries BOTH reasons and both clauses
        overlap = [s for s in excluded if len(s["reasons"]) == 2]
        self.assertEqual(len(overlap), 1)
        self.assertEqual(overlap[0]["hours"], "2.0000")
        self.assertEqual(sorted(overlap[0]["clause_codes"]), ["CP-03", "CP-04"])

    def test_case_c_weekend_exclusion_exactly_exhausted(self):
        data = self.calc("案例C：跨周末且刚好用尽")
        # natural 72h; weekend Sat 00:00 - Mon 00:00 excluded 48h; used 24h
        self.assertEqual(Decimal(data["natural_hours"]), Decimal("72.0000"))
        self.assertEqual(Decimal(data["laytime_used_hours"]), Decimal("24.0000"))
        self.assertEqual(Decimal(data["demurrage_amount"]), Decimal("0.00"))
        self.assertEqual(Decimal(data["despatch_amount"]), Decimal("0.00"))
        info = next(l for l in data["lines"] if l["kind"] == "INFO")
        self.assertIn("刚好用尽", info["label"])
        weekend = [s for s in data["segments"] if s["weekend"]]
        self.assertEqual(sum(Decimal(s["hours"]) for s in weekend),
                         Decimal("48.0000"))
        self.assertTrue(all(s["clause_codes"] == ["CP-02"] for s in weekend))

    def test_case_d_nor_tendered_not_accepted_is_blocked(self):
        data = self.calc("案例D：NOR 送达未被接受")
        self.assertEqual(data["status"], "BLOCKED")
        self.assertIn("送达", data["blocked_reason"])
        self.assertEqual(data["lines"], [])


class SettlementImmutabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        self.client = APIClient()
        self.voyage = Voyage.objects.get(label="案例C：跨周末且刚好用尽")

    def test_recalculation_creates_new_version_not_overwrite(self):
        r1 = self.client.post(f"/api/voyages/{self.voyage.pk}/calculate/")
        r2 = self.client.post(f"/api/voyages/{self.voyage.pk}/calculate/")
        self.assertEqual(r1.json()["version"], 1)
        self.assertEqual(r2.json()["version"], 2)
        self.assertEqual(
            Settlement.objects.filter(voyage=self.voyage).count(), 2
        )
        # the historical settlement is untouched
        first = Settlement.objects.get(voyage=self.voyage, version=1)
        self.assertEqual(first.laytime_used_hours, Decimal("24.0000"))

    def test_settlement_endpoint_is_read_only(self):
        self.client.post(f"/api/voyages/{self.voyage.pk}/calculate/")
        s = Settlement.objects.get(voyage=self.voyage, version=1)
        for method in ("put", "patch", "delete"):
            resp = getattr(self.client, method)(
                f"/api/settlements/{s.pk}/",
                {"demurrage_amount": "999999.00"},
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 405, method)
        s.refresh_from_db()
        self.assertEqual(s.demurrage_amount, Decimal("0.00"))

    def test_pending_fragment_excluded_until_verified_then_counts(self):
        voyage = Voyage.objects.get(label="案例A：跨午夜天气停工")
        r1 = self.client.post(f"/api/voyages/{voyage.pk}/calculate/")
        self.assertEqual(Decimal(r1.json()["laytime_used_hours"]),
                         Decimal("24.0000"))
        # evidence arrives for the claimed 14:00-15:00 weather stoppage
        EventFragment.objects.filter(
            voyage=voyage, evidence_status="PENDING"
        ).update(evidence_status="VERIFIED")
        r2 = self.client.post(f"/api/voyages/{voyage.pk}/calculate/")
        # now the extra 1h is excluded too: used 23h, demurrage 3h = 1500
        self.assertEqual(Decimal(r2.json()["laytime_used_hours"]),
                         Decimal("23.0000"))
        self.assertEqual(Decimal(r2.json()["demurrage_amount"]),
                         Decimal("1500.00"))
        self.assertEqual(r2.json()["pending_fragment_ids"], [])
        # version 1 remains as it was
        v1 = Settlement.objects.get(voyage=voyage, version=1)
        self.assertEqual(v1.laytime_used_hours, Decimal("24.0000"))
