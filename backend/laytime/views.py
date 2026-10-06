from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.serializers import ValidationError as DRFValidationError

from .engine import calculate_laytime
from .models import CharterParty, Event, Settlement, Stoppage, Voyage
from .serializers import (
    CharterPartySerializer,
    EventSerializer,
    SettlementSerializer,
    StoppageSerializer,
    VoyageDetailSerializer,
    VoyageListSerializer,
)


def _guard_django_validation(fn):
    """把模型层 ValidationError 转成 DRF 400，而不是 500。"""
    try:
        return fn()
    except DjangoValidationError as exc:
        raise DRFValidationError(exc.messages)


class CharterPartyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CharterParty.objects.prefetch_related("clauses")
    serializer_class = CharterPartySerializer


class VoyageViewSet(viewsets.ModelViewSet):
    queryset = Voyage.objects.select_related("charter_party")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return VoyageDetailSerializer
        return VoyageListSerializer

    def retrieve(self, request, *args, **kwargs):
        voyage = get_object_or_404(
            Voyage.objects.select_related("charter_party")
            .prefetch_related(
                "charter_party__clauses", "events", "stoppages", "settlements"
            ),
            pk=kwargs["pk"],
        )
        return Response(VoyageDetailSerializer(voyage).data)

    @action(detail=True, methods=["post"])
    def calculate(self, request, pk=None):
        """试算：运行引擎并返回报告，不落库。"""
        voyage = self.get_object()
        report = calculate_laytime(voyage)
        return Response(report)

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        """
        生成结算草稿：运行引擎并把完整报告作为快照保存为新版本。
        永远不覆盖历史版本；BLOCKED 的报告不允许生成结算。
        """
        voyage = self.get_object()
        report = calculate_laytime(voyage)
        if report.get("status") == "BLOCKED":
            return Response(
                {"detail": "事实不完整，无法生成结算。", "report": report},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            next_version = (
                voyage.settlements.aggregate(m=Max("version"))["m"] or 0
            ) + 1
            settlement = Settlement.objects.create(
                voyage=voyage,
                version=next_version,
                report=report,
                total_amount=Decimal(report["total_amount"]),
                currency=report["currency"],
                note=request.data.get("note", ""),
            )
        return Response(
            SettlementSerializer(settlement).data, status=status.HTTP_201_CREATED
        )


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = Event.objects.all()
        voyage = self.request.query_params.get("voyage")
        return qs.filter(voyage_id=voyage) if voyage else qs


class StoppageViewSet(viewsets.ModelViewSet):
    serializer_class = StoppageSerializer

    def get_queryset(self):
        qs = Stoppage.objects.all()
        voyage = self.request.query_params.get("voyage")
        return qs.filter(voyage_id=voyage) if voyage else qs


class SettlementViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """结算单：不提供 update（快照不可改）；删除仅限草稿。"""

    serializer_class = SettlementSerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = Settlement.objects.select_related("voyage")
        voyage = self.request.query_params.get("voyage")
        return qs.filter(voyage_id=voyage) if voyage else qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        _guard_django_validation(instance.delete)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        """
        定稿：草稿 → 已定稿；同航次原已定稿版本转为“已被取代”（不覆盖、不删除）。
        含待核对/有争议片段（PROVISIONAL）的结算不允许定稿。
        """
        settlement = self.get_object()
        if settlement.report.get("unverified_inputs"):
            return Response(
                {
                    "detail": "存在待核对或有争议的事实片段，结算不能定稿；"
                              "请先补全证据或修正事实。",
                    "unverified_inputs": settlement.report["unverified_inputs"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            for old in Settlement.objects.filter(
                voyage=settlement.voyage, status=Settlement.Status.FINAL
            ):
                old.status = Settlement.Status.SUPERSEDED
                old.save()
            _guard_django_validation(settlement.finalize)
        return Response(SettlementSerializer(settlement).data)
