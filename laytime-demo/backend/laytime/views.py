from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .engine import calculate
from .models import (
    CharterParty,
    EventFragment,
    Settlement,
    SettlementLine,
    Voyage,
)
from .serializers import (
    CharterPartySerializer,
    EventFragmentSerializer,
    SettlementSerializer,
    VoyageSerializer,
)


class CharterPartyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CharterParty.objects.prefetch_related("clauses")
    serializer_class = CharterPartySerializer


class EventFragmentViewSet(viewsets.ModelViewSet):
    """Operations records facts; evidence status can be updated when the
    missing paperwork arrives. Fragments are never deleted, only corrected
    by superseding entries."""

    queryset = EventFragment.objects.all()
    serializer_class = EventFragmentSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        voyage = self.request.query_params.get("voyage")
        return qs.filter(voyage_id=voyage) if voyage else qs


class VoyageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Voyage.objects.select_related("charter_party").prefetch_related(
        "charter_party__clauses", "fragments"
    )
    serializer_class = VoyageSerializer

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Event fragments plus the latest settlement, for the React timeline."""
        voyage = self.get_object()
        fragments = EventFragmentSerializer(voyage.fragments.all(), many=True).data
        latest = voyage.settlements.first()
        return Response({
            "voyage": VoyageSerializer(voyage).data,
            "fragments": fragments,
            "latest_settlement": (
                SettlementSerializer(latest).data if latest else None
            ),
        })

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def calculate(self, request, pk=None):
        """Run the engine and persist a NEW settlement version.

        Historical settlements are never overwritten: each call inserts
        version = max(version) + 1.
        """
        voyage = self.get_object()
        result = calculate(voyage)
        last = voyage.settlements.order_by("-version").first()
        version = (last.version + 1) if last else 1

        totals = result["totals"]
        settlement = Settlement.objects.create(
            voyage=voyage,
            version=version,
            status=result["status"],
            natural_hours=totals.get("natural_hours", 0),
            laytime_used_hours=totals.get("laytime_used_hours", 0),
            actual_working_hours=totals.get("actual_working_hours", 0),
            allowed_hours=totals.get("allowed_hours", 0),
            demurrage_amount=totals.get("demurrage_amount", 0),
            despatch_amount=totals.get("despatch_amount", 0),
            segments=result["segments"],
            pending_fragment_ids=result["pending_fragment_ids"],
            blocked_reason=result["blocked_reason"],
        )
        for line in result["lines"]:
            SettlementLine.objects.create(settlement=settlement, **line)

        payload = SettlementSerializer(settlement).data
        payload["warnings"] = result["warnings"]
        return Response(payload, status=status.HTTP_201_CREATED)


class SettlementViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Read-only by design: no update/partial_update/destroy — a historical
    settlement cannot be overwritten. Corrections happen by posting a new
    calculation version on the voyage."""

    queryset = Settlement.objects.select_related("voyage").prefetch_related("lines")
    serializer_class = SettlementSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        voyage = self.request.query_params.get("voyage")
        return qs.filter(voyage_id=voyage) if voyage else qs
