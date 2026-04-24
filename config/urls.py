from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import RedirectView
from apps.dart_analysis.views import DartReportPageView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dart-ui", permanent=False)),
    path("favicon.ico", lambda request: HttpResponse(status=204)),
    path("admin/", admin.site.urls),
    path("dart/", DartReportPageView.as_view(), name="dart-ui"),
    path("api/v1/", include("apps.dart_analysis.urls")),
]
