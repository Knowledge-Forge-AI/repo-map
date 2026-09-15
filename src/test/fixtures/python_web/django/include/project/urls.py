from django.urls import include, path

urlpatterns = [
    path("nested/", include("nested.urls")),
]
