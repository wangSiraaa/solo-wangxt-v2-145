from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CharterPartyViewSet,
    EventFragmentViewSet,
    SettlementViewSet,
    VoyageViewSet,
)

router = DefaultRouter()
router.register("charter-parties", CharterPartyViewSet, basename="charterparty")
router.register("voyages", VoyageViewSet, basename="voyage")
router.register("fragments", EventFragmentViewSet, basename="fragment")
router.register("settlements", SettlementViewSet, basename="settlement")

urlpatterns = [path("", include(router.urls))]
