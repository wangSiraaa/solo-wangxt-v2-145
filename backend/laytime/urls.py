from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CharterPartyViewSet,
    EventViewSet,
    SettlementViewSet,
    StoppageViewSet,
    VoyageViewSet,
)

router = DefaultRouter()
router.register("charter-parties", CharterPartyViewSet, basename="charterparty")
router.register("voyages", VoyageViewSet, basename="voyage")
router.register("events", EventViewSet, basename="event")
router.register("stoppages", StoppageViewSet, basename="stoppage")
router.register("settlements", SettlementViewSet, basename="settlement")

urlpatterns = [path("", include(router.urls))]
