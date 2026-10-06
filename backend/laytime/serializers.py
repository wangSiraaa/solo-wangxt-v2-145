from rest_framework import serializers

from .models import CharterParty, Clause, Event, Settlement, Stoppage, Voyage


class ClauseSerializer(serializers.ModelSerializer):
    clause_type_display = serializers.CharField(
        source="get_clause_type_display", read_only=True
    )

    class Meta:
        model = Clause
        fields = [
            "id", "code", "clause_type", "clause_type_display",
            "title", "text", "params",
        ]


class CharterPartySerializer(serializers.ModelSerializer):
    clauses = ClauseSerializer(many=True, read_only=True)

    class Meta:
        model = CharterParty
        fields = ["id", "code", "name", "fictional_notice", "clauses"]


class EventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(
        source="get_event_type_display", read_only=True
    )
    evidence_status_display = serializers.CharField(
        source="get_evidence_status_display", read_only=True
    )

    class Meta:
        model = Event
        fields = [
            "id", "voyage", "event_type", "event_type_display", "occurred_at",
            "evidence_status", "evidence_status_display", "source", "note",
        ]


class StoppageSerializer(serializers.ModelSerializer):
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    evidence_status_display = serializers.CharField(
        source="get_evidence_status_display", read_only=True
    )

    class Meta:
        model = Stoppage
        fields = [
            "id", "voyage", "reason", "reason_display", "started_at", "ended_at",
            "evidence_status", "evidence_status_display", "source", "note",
        ]

    def validate(self, attrs):
        start = attrs.get("started_at", getattr(self.instance, "started_at", None))
        end = attrs.get("ended_at", getattr(self.instance, "ended_at", None))
        if start and end and end <= start:
            raise serializers.ValidationError("停工结束时间必须晚于开始时间。")
        return attrs


class VoyageListSerializer(serializers.ModelSerializer):
    charter_party_code = serializers.CharField(
        source="charter_party.code", read_only=True
    )
    operation_display = serializers.CharField(
        source="get_operation_display", read_only=True
    )

    class Meta:
        model = Voyage
        fields = [
            "id", "reference", "vessel_name", "port_name", "operation",
            "operation_display", "cargo_description", "charter_party_code",
        ]


class SettlementSummarySerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Settlement
        fields = [
            "id", "version", "status", "status_display",
            "total_amount", "currency", "created_at", "finalized_at", "note",
        ]


class VoyageDetailSerializer(serializers.ModelSerializer):
    charter_party = CharterPartySerializer(read_only=True)
    events = EventSerializer(many=True, read_only=True)
    stoppages = StoppageSerializer(many=True, read_only=True)
    settlements = SettlementSummarySerializer(many=True, read_only=True)
    operation_display = serializers.CharField(
        source="get_operation_display", read_only=True
    )

    class Meta:
        model = Voyage
        fields = [
            "id", "reference", "vessel_name", "port_name", "operation",
            "operation_display", "cargo_description", "charter_party",
            "events", "stoppages", "settlements",
        ]


class SettlementSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    voyage_reference = serializers.CharField(
        source="voyage.reference", read_only=True
    )

    class Meta:
        model = Settlement
        fields = [
            "id", "voyage", "voyage_reference", "version", "status",
            "status_display", "report", "total_amount", "currency",
            "note", "created_at", "finalized_at",
        ]
        read_only_fields = ["report", "total_amount", "currency", "version"]
