from django.urls import path

from apps.dart_analysis.views import (
    DartDisclosureDetailView,
    DartInvestmentReportView,
    DartOriginalDocumentView,
    DartReportView,
    DartValidationView,
)

urlpatterns = [
    path("dart/validate", DartValidationView.as_view(), name="dart-validate"),
    path("dart/report", DartReportView.as_view(), name="dart-report"),
    path("dart/investment-report", DartInvestmentReportView.as_view(), name="dart-investment-report"),
    path("dart/document", DartOriginalDocumentView.as_view(), name="dart-document"),
    path("dart/disclosure-detail", DartDisclosureDetailView.as_view(), name="dart-disclosure-detail"),
]
