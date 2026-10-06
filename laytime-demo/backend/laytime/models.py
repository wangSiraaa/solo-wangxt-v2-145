"""
Domain model for laytime / demurrage / despatch.

Design notes
------------
* All durations and money are Decimal — never float.
* NOR *tendered* and NOR *accepted* are separate event kinds: they are
  different facts and only acceptance starts laytime (per fictional clause).
* EventFragment carries an evidence status; fragments without verified
  evidence stay PENDING and are excluded from calculation but reported.
* Settlement is append-only: recalculation inserts a new version row.
  Historical settlements are never overwritten (enforced at the API layer
  and by a uniqueness constraint on (voyage, version)).
* Every charge line stores the exact intervals and clause codes it was
  derived from, so finance can trace any amount back to time and text.
"""
from django.db import models


class CharterParty(models.Model):
    """A fictional fixture of charter-party terms. Not legal advice."""

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)
    laytime_allowed_hours = models.DecimalField(max_digits=8, decimal_places=2)
    demurrage_rate_per_day = models.DecimalField(max_digits=12, decimal_places=2)
    despatch_rate_per_day = models.DecimalField(max_digits=12, decimal_places=2)
    disclaimer = models.TextField(
        default="虚构租约条款，仅用于演示计时与费用核算，不构成法律解释或建议。"
    )

    def __str__(self):
        return f"{self.code} {self.name}"


class Clause(models.Model):
    """A single fictional clause. rule_type drives the calculation engine."""

    RULE_WEEKEND_EXCLUSION = "WEEKEND_EXCLUSION"
    RULE_WEATHER_EXCLUSION = "WEATHER_EXCLUSION"
    RULE_BERTH_WAIT_EXCLUSION = "BERTH_WAIT_EXCLUSION"
    RULE_NOR_ACCEPTANCE = "NOR_ACCEPTANCE"
    RULE_NO_DOUBLE_COUNT = "NO_DOUBLE_COUNT"
    RULE_EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    RULE_TYPES = [
        (RULE_WEEKEND_EXCLUSION, "周末不计入"),
        (RULE_WEATHER_EXCLUSION, "天气停工不计入"),
        (RULE_BERTH_WAIT_EXCLUSION, "等泊时间不计入"),
        (RULE_NOR_ACCEPTANCE, "NOR 被接受方起算"),
        (RULE_NO_DOUBLE_COUNT, "重叠原因不重复扣减"),
        (RULE_EVIDENCE_REQUIRED, "缺证据片段待核对"),
    ]

    charter_party = models.ForeignKey(
        CharterParty, related_name="clauses", on_delete=models.CASCADE
    )
    code = models.CharField(max_length=20)
    title = models.CharField(max_length=120)
    text = models.TextField()
    rule_type = models.CharField(max_length=40, choices=RULE_TYPES)
    parameters = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("charter_party", "code")
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.title}"


class Voyage(models.Model):
    label = models.CharField(max_length=120)
    vessel_name = models.CharField(max_length=120)
    port = models.CharField(max_length=120)
    charter_party = models.ForeignKey(CharterParty, on_delete=models.PROTECT)

    def __str__(self):
        return self.label


class EventFragment(models.Model):
    """One observed fact on the timeline, as reported by an agent/terminal."""

    KIND_ARRIVAL = "ARRIVAL"
    KIND_NOR_TENDERED = "NOR_TENDERED"
    KIND_NOR_ACCEPTED = "NOR_ACCEPTED"
    KIND_STOPPAGE_START = "STOPPAGE_START"
    KIND_STOPPAGE_END = "STOPPAGE_END"
    KIND_COMPLETION = "COMPLETION"
    KINDS = [
        (KIND_ARRIVAL, "抵港"),
        (KIND_NOR_TENDERED, "NOR 送达"),
        (KIND_NOR_ACCEPTED, "NOR 被接受"),
        (KIND_STOPPAGE_START, "停工开始"),
        (KIND_STOPPAGE_END, "复工"),
        (KIND_COMPLETION, "装卸完毕"),
    ]

    REASON_NONE = ""
    REASON_WEATHER = "WEATHER"
    REASON_BERTH_WAIT = "BERTH_WAIT"
    REASON_OTHER = "OTHER"
    REASONS = [
        (REASON_NONE, "—"),
        (REASON_WEATHER, "天气"),
        (REASON_BERTH_WAIT, "等待泊位"),
        (REASON_OTHER, "其他"),
    ]

    EVIDENCE_VERIFIED = "VERIFIED"
    EVIDENCE_PENDING = "PENDING"
    EVIDENCE_STATUSES = [
        (EVIDENCE_VERIFIED, "已核实"),
        (EVIDENCE_PENDING, "待核对"),
    ]

    voyage = models.ForeignKey(
        Voyage, related_name="fragments", on_delete=models.CASCADE
    )
    kind = models.CharField(max_length=20, choices=KINDS)
    occurred_at = models.DateTimeField()
    reason = models.CharField(max_length=20, choices=REASONS, blank=True, default="")
    evidence_status = models.CharField(
        max_length=10, choices=EVIDENCE_STATUSES, default=EVIDENCE_VERIFIED
    )
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["occurred_at", "id"]

    def __str__(self):
        return f"{self.voyage_id} {self.kind} @ {self.occurred_at:%Y-%m-%d %H:%M}"


class Settlement(models.Model):
    """One immutable calculation result. Recalculation = new version."""

    STATUS_FINAL = "FINAL"
    STATUS_BLOCKED = "BLOCKED"  # e.g. NOR tendered but never accepted
    STATUSES = [(STATUS_FINAL, "已定稿"), (STATUS_BLOCKED, "无法起算")]

    voyage = models.ForeignKey(
        Voyage, related_name="settlements", on_delete=models.CASCADE
    )
    version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=STATUS_FINAL)

    natural_hours = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    laytime_used_hours = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    actual_working_hours = models.DecimalField(
        max_digits=10, decimal_places=4, default=0
    )
    allowed_hours = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    demurrage_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    despatch_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Full classified segment list + pending fragments, for audit replay.
    segments = models.JSONField(default=list)
    pending_fragment_ids = models.JSONField(default=list)
    blocked_reason = models.CharField(max_length=255, blank=True, default="")
    disclaimer = models.TextField(
        default="虚构租约条款下的演示性核算，不构成法律解释或建议。"
    )

    class Meta:
        unique_together = ("voyage", "version")
        ordering = ["-version"]


class SettlementLine(models.Model):
    """A single charge (or zero-charge note) with full traceability."""

    KIND_DEMURRAGE = "DEMURRAGE"
    KIND_DESPATCH = "DESPATCH"
    KIND_INFO = "INFO"
    KINDS = [
        (KIND_DEMURRAGE, "滞期费"),
        (KIND_DESPATCH, "速遣费"),
        (KIND_INFO, "说明"),
    ]

    settlement = models.ForeignKey(
        Settlement, related_name="lines", on_delete=models.CASCADE
    )
    kind = models.CharField(max_length=10, choices=KINDS)
    label = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    basis_hours = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    rate_per_day = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    clause_codes = models.JSONField(default=list)
    # The exact time intervals this line is derived from.
    intervals = models.JSONField(default=list)

    class Meta:
        ordering = ["id"]
