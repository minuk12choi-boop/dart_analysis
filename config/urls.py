from django.contrib import admin
from django.urls import include, path
from apps.dart_analysis.views import DartReportPageView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dart/", DartReportPageView.as_view(), name="dart-ui"),
    path("api/v1/", include("apps.dart_analysis.urls")),
]
