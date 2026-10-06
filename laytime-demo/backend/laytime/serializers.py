from rest_framework import serializers

from .models import (
    CharterParty,
    Clause,
    EventFragment,
    Settlement,
    SettlementLine,
    Voyage,
)


class ClauseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clause
        fields = ["id", "code", "title", "text", "rule_type", "parameters"]


class CharterPartySerializer(serializers.ModelSerializer):
    clauses = ClauseSerializer(many=True, read_only=True)

    class Meta:
        model = CharterParty
        fields = [
            "id", "code", "name", "laytime_allowed_hours",
            "demurrage_rate_per_day", "despatch_rate_per_day",
            "disclaimer", "clauses",
        ]


class EventFragmentSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    reason_display = serializers.CharField(
        source="get_reason_display", read_only=True
    )
    evidence_display = serializers.CharField(
        source="get_evidence_status_display", read_only=True
    )

    class Meta:
        model = EventFragment
        fields = [
            "id", "kind", "kind_display", "occurred_at", "reason",
            "reason_display", "evidence_status", "evidence_display", "note",
        ]


class VoyageSerializer(serializers.ModelSerializer):
    charter_party = CharterPartySerializer(read_only=True)

    class Meta:
        model = Voyage
        fields = ["id", "label", "vessel_name", "port", "charter_party"]


class SettlementLineSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = SettlementLine
        fields = [
            "id", "kind", "kind_display", "label", "amount", "basis_hours",
            "rate_per_day", "clause_codes", "intervals",
        ]


class SettlementSerializer(serializers.ModelSerializer):
    lines = SettlementLineSerializer(many=True, read_only=True)
    voyage_label = serializers.CharField(source="voyage.label", read_only=True)

    class Meta:
        model = Settlement
        fields = [
            "id", "voyage", "voyage_label", "version", "created_at", "status",
            "natural_hours", "laytime_used_hours", "actual_working_hours",
            "allowed_hours", "demurrage_amount", "despatch_amount",
            "segments", "pending_fragment_ids", "blocked_reason",
            "disclaimer", "lines",
        ]
        read_only_fields = fields  # settlements are immutable via the API
