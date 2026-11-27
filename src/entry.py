"""
Cloudflare Worker entrypoint (Python Workers + django-cf).

Deployment (docs/DEPLOY_CLOUDFLARE.md):

    uv run pywrangler dev      # local Worker runtime with wrangler dev --local
    npx wrangler deploy        # after pywrangler build

The class below wires the Django WSGI application into the Worker fetch
handler. django-cf's DjangoCF mixin serves the WSGI app through the Workers
WSGI adaptor and exposes bindings (D1 "DB", R2 "BUCKET") through
``workers.env``. Static assets (Bootstrap 6, HTMX, the EmbedPDF bundle and
pdfium.wasm) are served by Workers static assets (wrangler.jsonc), not Django.
"""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")

from workers import WorkerEntrypoint  # noqa: E402
from django_cf import DjangoCF  # noqa: E402

application = get_wsgi_application()


class Default(DjangoCF, WorkerEntrypoint):
    """Serve Django; route non-Django paths to static assets automatically."""

    async def get_app(self):
        return application
