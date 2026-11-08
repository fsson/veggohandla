from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve


def media(request, path):
    """Recipe images. Served by Django also in production: a personal app with a handful of
    images doesn't need a separate web server for them."""
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),  # set_language (the SV/EN switch)
    path("", include("core.urls")),
    re_path(r"^media/(?P<path>.*)$", media),
]
