"""
领域模型

事实（抵港、NOR 送达/被接受、停工）与合同条款、费率分开建模；
结算结果一旦定稿即不可覆盖，只能产生新版本。
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class EvidenceStatus(models.TextChoices):
    VERIFIED = "VERIFIED", "已核实"
    PENDING = "PENDING", "待核对"
    DISPUTED = "DISPUTED", "有争议"


class CharterParty(models.Model):
    """租约（本系统使用虚构租约规则，不构成法律解释）"""

    code = models.CharField("租约代码", max_length=50, unique=True)
    name = models.CharField("租约名称", max_length=200)
    fictional_notice = models.TextField(
        "虚构规则声明",
        default="本租约条款为演示用虚构规则，不替代任何真实合同文本或法律解释。",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Clause(models.Model):
    """租约条款：起算、允许时间、排除、费率等，params 存结构化参数"""

    class ClauseType(models.TextChoices):
        LAYTIME_ALLOWED = "LAYTIME_ALLOWED", "允许装卸时间"
        TURNTIME = "TURNTIME", "起算准备时间"
        EXCLUSION = "EXCLUSION", "时间排除"
        DEMURRAGE_RATE = "DEMURRAGE_RATE", "滞期费率"
        DESPATCH_RATE = "DESPATCH_RATE", "速遣费率"
        ONCE_ON_DEMURRAGE = "ONCE_ON_DEMURRAGE", "一旦滞期持续滞期"

    charter_party = models.ForeignKey(
        CharterParty, on_delete=models.CASCADE, related_name="clauses"
    )
    code = models.CharField("条款编号", max_length=20)  # 如 FIC-03
    clause_type = models.CharField(
        "条款类型", max_length=30, choices=ClauseType.choices
    )
    title = models.CharField("标题", max_length=200)
    text = models.TextField("条款原文（虚构）")
    params = models.JSONField("结构化参数", default=dict)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["charter_party", "code"], name="uniq_clause_code_per_cp"
            )
        ]

    def __str__(self):
        return f"{self.code} {self.title}"


class Voyage(models.Model):
    class Operation(models.TextChoices):
        LOAD = "LOAD", "装货"
        DISCHARGE = "DISCHARGE", "卸货"

    reference = models.CharField("航次编号", max_length=50, unique=True)
    charter_party = models.ForeignKey(
        CharterParty, on_delete=models.PROTECT, related_name="voyages"
    )
    vessel_name = models.CharField("船名", max_length=100)
    port_name = models.CharField("港口", max_length=100)
    cargo_description = models.CharField("货物", max_length=200, blank=True)
    operation = models.CharField(
        "作业", max_length=10, choices=Operation.choices, default=Operation.DISCHARGE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["reference"]

    def __str__(self):
        return f"{self.reference} {self.vessel_name}@{self.port_name}"


class Event(models.Model):
    """事实时间表中的事件点。NOR 送达与被接受是两种不同事实。"""

    class EventType(models.TextChoices):
        ARRIVAL = "ARRIVAL", "抵港"
        NOR_TENDERED = "NOR_TENDERED", "准备就绪通知送达"
        NOR_ACCEPTED = "NOR_ACCEPTED", "准备就绪通知被接受"
        BERTHED = "BERTHED", "靠泊"
        COMMENCED = "COMMENCED", "开始作业"
        COMPLETED = "COMPLETED", "完工"
        DEPARTED = "DEPARTED", "离港"

    voyage = models.ForeignKey(Voyage, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField("事件", max_length=20, choices=EventType.choices)
    occurred_at = models.DateTimeField("发生时间(UTC)")
    evidence_status = models.CharField(
        "证据状态",
        max_length=10,
        choices=EvidenceStatus.choices,
        default=EvidenceStatus.PENDING,
    )
    source = models.CharField("证据来源", max_length=200, blank=True)
    note = models.TextField("备注", blank=True)

    class Meta:
        ordering = ["occurred_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["voyage", "event_type"], name="uniq_event_type_per_voyage"
            )
        ]

    def __str__(self):
        return f"{self.voyage.reference} {self.get_event_type_display()} {self.occurred_at:%Y-%m-%d %H:%M}Z"


class Stoppage(models.Model):
    """停工片段：原因 + 起止时间。重叠片段在计算时取并集，不重复扣减。"""

    class Reason(models.TextChoices):
        WEATHER = "WEATHER", "恶劣天气"
        WEEKEND_HOLIDAY = "WEEKEND_HOLIDAY", "周末/节假日"
        WAITING_BERTH = "WAITING_BERTH", "等待泊位"
        EQUIPMENT = "EQUIPMENT", "船舶设备故障"
        STRIKE = "STRIKE", "罢工"
        OTHER = "OTHER", "其他"

    voyage = models.ForeignKey(
        Voyage, on_delete=models.CASCADE, related_name="stoppages"
    )
    reason = models.CharField("停工原因", max_length=20, choices=Reason.choices)
    started_at = models.DateTimeField("开始(UTC)")
    ended_at = models.DateTimeField("结束(UTC)")
    evidence_status = models.CharField(
        "证据状态",
        max_length=10,
        choices=EvidenceStatus.choices,
        default=EvidenceStatus.PENDING,
    )
    source = models.CharField("证据来源", max_length=200, blank=True)
    note = models.TextField("备注", blank=True)

    class Meta:
        ordering = ["started_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ended_at__gt=models.F("started_at")),
                name="stoppage_end_after_start",
            )
        ]

    def __str__(self):
        return f"{self.voyage.reference} {self.get_reason_display()} {self.started_at:%m-%d %H:%M}→{self.ended_at:%m-%d %H:%M}Z"


class Settlement(models.Model):
    """
    结算单：保存计算引擎的完整快照（report），金额用 Decimal。
    定稿(FINAL)后不可修改、不可删除；历史版本只能被新版本取代(SUPERSEDED)，不能被覆盖。
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        FINAL = "FINAL", "已定稿"
        SUPERSEDED = "SUPERSEDED", "已被取代"

    # 允许的状态流转；其余一律拒绝
    _ALLOWED_TRANSITIONS = {
        Status.DRAFT: {Status.DRAFT, Status.FINAL},
        Status.FINAL: {Status.SUPERSEDED},
        Status.SUPERSEDED: set(),
    }

    voyage = models.ForeignKey(
        Voyage, on_delete=models.CASCADE, related_name="settlements"
    )
    version = models.PositiveIntegerField("版本")
    status = models.CharField(
        "状态", max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    report = models.JSONField("计算快照")
    total_amount = models.DecimalField(
        "结算总额", max_digits=14, decimal_places=2, default=0
    )
    currency = models.CharField("币种", max_length=3, default="USD")
    note = models.TextField("备注", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField("定稿时间", null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["voyage", "version"], name="uniq_settlement_version"
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Settlement.objects.get(pk=self.pk)
            allowed = self._ALLOWED_TRANSITIONS[old.status]
            if self.status not in allowed:
                raise ValidationError(
                    f"结算单状态不允许从 {old.get_status_display()} 变更为 "
                    f"{self.get_status_display()}；历史结算不能覆盖，请创建新版本。"
                )
            if old.status != self.Status.DRAFT:
                # 非草稿：除状态/定稿时间外任何字段都不得变化
                for f in ("report", "total_amount", "currency", "note", "voyage_id", "version"):
                    new_val = getattr(self, f)
                    old_val = getattr(old, f)
                    if f == "total_amount":
                        # 统一成 Decimal 再比较（赋值时可能是字符串）
                        from decimal import Decimal as _D

                        new_val, old_val = _D(str(new_val)), _D(str(old_val))
                    if old_val != new_val:
                        raise ValidationError(
                            f"已定稿/历史结算的 {f} 不可修改；请创建新版本。"
                        )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("仅草稿状态的结算可以删除；历史结算不能覆盖或删除。")
        return super().delete(*args, **kwargs)

    def finalize(self):
        if self.status != self.Status.DRAFT:
            raise ValidationError("仅草稿可以定稿。")
        self.status = self.Status.FINAL
        self.finalized_at = timezone.now()
        self.save()

    def __str__(self):
        return f"{self.voyage.reference} v{self.version} {self.get_status_display()} {self.total_amount}{self.currency}"
