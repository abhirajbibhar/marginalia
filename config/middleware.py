"""
Project middleware.

SecurityHeadersMiddleware
    Emits a strict Content-Security-Policy and a small set of hardening headers.
    ``wasm-unsafe-eval`` is required by the EmbedPDF PDF engine (WebAssembly);
    it is the only relaxation beyond 'self' for scripts.

RateLimitMiddleware
    Thin dispatch layer for the runtime rate limiter; the per-view limits live
    in settings.RATE_LIMITS and are enforced by decorator in runtime.ratelimit
    (this middleware only handles the login form path, which is not a CBV).
"""
from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin

from runtime.ratelimit import RateLimiter, RateLimitExceeded

_rate_limiter = RateLimiter()


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Attach CSP and friends to every HTML/JSON response."""

    def process_response(self, request, response):
        directives = getattr(settings, "CSP_DIRECTIVES", None)
        if directives:
            csp = "; ".join(
                f"{key} {' '.join(values)}" for key, values in directives.items()
            )
            response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


class RateLimitMiddleware(MiddlewareMixin):
    """Rate limit a few sensitive endpoints before they reach the view."""

    def process_request(self, request):
        # /accounts/login/ POST is throttled per-IP+username; the JSON sync API
        # is throttled per-user inside annotations.views (it needs the user).
        if request.method == "POST" and request.path == "/accounts/login/":
            key = f"login:{request.META.get('REMOTE_ADDR', '?')}:{request.POST.get('username', '')}"
            try:
                _rate_limiter.check(key, *settings.RATE_LIMITS["login"])
            except RateLimitExceeded:
                return HttpResponse("Too many login attempts. Try again later.", status=429)
        return None
