"""
Root URL configuration.

Page routes live in each app; the JSON annotation sync API is mounted under
/api/reading/ (the only non-HTMX XHR surface in the app — see
docs/COLLABORATION.md).
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Marginalia administration"
admin.site.site_title = "Marginalia"
admin.site.index_title = "Library administration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
    path("library/", include("apps.library.urls")),
    path("authors/", include("apps.authors.urls")),
    path("series/", include("apps.series.urls")),
    path("collections/", include("apps.collections.urls")),
    path("read/", include("apps.reading.urls")),
    path("rooms/", include("apps.rooms.urls")),
    path("annotations/", include("apps.annotations.urls")),
    path("manage/", include("apps.adminpanel.urls")),
    path("api/reading/", include("apps.annotations.api_urls")),
]

# Local development serves uploaded media from Django; production local
# deployments use nginx (docs/DEPLOY_LOCAL.md) and on Cloudflare media lives
# behind /read/<id>/file/ with permission checks + Range support.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
