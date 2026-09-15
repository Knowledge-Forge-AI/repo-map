from django.urls import include, path, re_path

from app import views

urlpatterns = [
    path("users/", views.user_list, name="users"),
    re_path(r"^items/(?P<slug>[-\w]+)/$", views.ItemView.as_view()),
    path("api/", include("app.api.urls")),
]
