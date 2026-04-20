from django.urls import path

from apps.dart_analysis.views import DartValidationView

urlpatterns = [
    path("dart/validate", DartValidationView.as_view(), name="dart-validate"),
]
