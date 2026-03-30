from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("jury/", views.jury_discussion, name="jury_discussion"),
    path("jury/clear/", views.jury_clear, name="jury_clear"),
    path("history/", views.history, name="history"),
    path("about/", views.about, name="about"),
    path("feedback/", views.jury_feedback, name="jury_feedback"),
    path("gdocs/share/", views.gdocs_share, name="gdocs_share"),
    path("gdocs/callback/", views.gdocs_callback, name="gdocs_callback"),
]
