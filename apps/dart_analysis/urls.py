from django.urls import path

from apps.dart_analysis.views import DartOriginalDocumentView, DartReportView, DartValidationView

urlpatterns = [
    path("dart/validate", DartValidationView.as_view(), name="dart-validate"),
    path("dart/report", DartReportView.as_view(), name="dart-report"),
    path("dart/document", DartOriginalDocumentView.as_view(), name="dart-document"),
]
