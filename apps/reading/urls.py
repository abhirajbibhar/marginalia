"""Reading URLs: reader, file serving, bookmarks, reviews, history."""
from django.urls import path

from apps.reading import views

app_name = "reading"

urlpatterns = [
    path("<int:pk>/", views.reader, name="reader"),
    path("<int:pk>/file/", views.serve_book_file, name="file"),
    path("<int:pk>/cover/", views.serve_cover, name="cover"),
    path("<int:pk>/bookmark/", views.toggle_bookmark, name="bookmark"),
    path("<int:pk>/progress/", views.save_progress, name="progress"),
    path("<int:pk>/review/", views.review, name="review"),
    path("history/", views.history, name="history"),
]
