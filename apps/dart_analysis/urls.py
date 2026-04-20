from django.urls import path

from apps.dart_analysis.views import DartOriginalDocumentView, DartValidationView

urlpatterns = [
    path("dart/validate", DartValidationView.as_view(), name="dart-validate"),
    path("dart/document", DartOriginalDocumentView.as_view(), name="dart-document"),
]
