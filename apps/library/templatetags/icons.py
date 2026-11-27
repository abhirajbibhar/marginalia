"""
{% icon name size %} — the Cadence template's inline SVG icons.

The template contract is explicit: icons are the template's inline SVGs and no
icon font or library (e.g. Bootstrap Icons) may be added. This tag embeds the
same 16×16 stroke-style glyphs so pages can reuse them server-side.

Usage: {% icon "book" %} or {% icon "search" 18 %}
"""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# Stroke-based 16×16 glyphs in the template's visual language. Inner markup
# only; <svg> wrapper is added by _wrap().
ICONS = {
    # navigation
    "dashboard": '<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>',
    "book": '<path d="M2 3a1 1 0 0 1 1-1h4.5a2.5 2.5 0 0 1 2.5 2.5V14a2 2 0 0 0-2-2H3a1 1 0 0 1-1-1z"/><path d="M14 3a1 1 0 0 0-1-1h-4.5A2.5 2.5 0 0 0 6 4.5V14a2 2 0 0 1 2-2h6a1 1 0 0 0 1-1z"/>',
    "authors": '<circle cx="6" cy="5.5" r="2.5"/><path d="M1.5 14a4.5 4.5 0 0 1 9 0"/><path d="M11 3.2a2.5 2.5 0 0 1 0 4.6M12 14a4.5 4.5 0 0 0-1.6-3.4"/>',
    "series": '<path d="M3 2.5h10v11H3z"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3"/>',
    "collections": '<path d="M3 3h4.5v4.5H3zM8.5 3H13v4.5H8.5zM3 8.5h4.5V13H3zM8.5 8.5H13V13H8.5z"/>',
    "rooms": '<path d="M14 4a3 3 0 0 1-3 3H6l-3 2.5V4a3 3 0 0 1 3-3h5a3 3 0 0 1 3 3z"/><path d="M3 8.5V12a3 3 0 0 0 3 3h4l3.5 2.5"/>',
    "highlight": '<path d="M4 6h8a1.5 1.5 0 0 1 1.5 1.5V13h-11V7.5A1.5 1.5 0 0 1 4 6z"/><path d="M3 13h10"/>',
    "history": '<circle cx="8" cy="8" r="6"/><path d="M8 4.5V8l2.5 1.5"/>',
    "settings": '<circle cx="8" cy="8" r="2.25"/><path d="M8 1.5v1.6M8 12.9v1.6M14.5 8h-1.6M3.1 8H1.5m10.1-4.6-1.1 1.1M5.5 10.5l-1.1 1.1m0-8.2 1.1 1.1m5 5 1.1 1.1"/>',
    # actions & misc
    "search": '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14" stroke-linecap="round"/>',
    "plus": '<path d="M8 3.5v9M3.5 8h9" stroke-linecap="round"/>',
    "upload": '<path d="M8 10.5v-7M5 6l3-3 3 3"/><path d="M2.5 10v2.5a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V10"/>',
    "back": '<path d="M9.5 3.5 5 8l4.5 4.5"/>',
    "bookmark": '<path d="M4 2.5h8v11l-4-2.5-4 2.5z"/>',
    "star": '<path d="m8 2 1.8 3.8 4.2.5-3 3 .8 4.2L8 11.5 4.2 13.5l.8-4.2-3-3 4.2-.5z"/>',
    "trash": '<path d="M3 4.5h10M6 4.5v-2h4v2M4.5 4.5l.5 8.5h6l.5-8.5"/>',
    "edit": '<path d="m10.5 2.5 3 3-7 7H3.5v-3z"/>',
    "users": '<circle cx="6" cy="5.5" r="2.5"/><path d="M1.5 14a4.5 4.5 0 0 1 9 0"/><path d="M11 3.2a2.5 2.5 0 0 1 0 4.6M12 14a4.5 4.5 0 0 0-1.6-3.4"/>',
    "link": '<path d="M6.5 9.5 9.5 6.5"/><path d="M7 4.5 8.5 3a3 3 0 0 1 4.2 4.2L11.2 8.7"/><path d="M9 11.5 7.5 13A3 3 0 0 1 3.3 8.8L4.8 7.3"/>',
    "clock": '<circle cx="8" cy="8" r="6"/><path d="M8 4.5V8l2.5 1.5"/>',
    "check": '<path d="m3.5 8.5 3 3 6-6" stroke-linecap="round"/>',
    "x": '<path d="m4 4 8 8M12 4l-8 8" stroke-linecap="round"/>',
    "chevron-right": '<path d="m6 3.5 4.5 4.5L6 12.5"/>',
    "filter": '<path d="M2 3.5h12L9.5 8.5v4l-3 1.5v-5.5z"/>',
    "download": '<path d="M8 2.5v7M5 7l3 3 3-3"/><path d="M2.5 11v2a.5.5 0 0 0 .5.5h10a.5.5 0 0 0 .5-.5v-2"/>',
    "eye": '<path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="1.75"/>',
    "info": '<circle cx="8" cy="8" r="6"/><path d="M8 7v4M8 5h.01"/>',
    "alert": '<path d="M8 2.5 14 13H2z"/><path d="M8 6.5v3M8 11h.01"/>',
    "menu": '<path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11"/>',
    "sun": '<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M14.5 8H13M3 8H1.5m10.1-4.6-1 1M5.4 10.6l-1 1m0-7.2 1 1m5.2 5.2 1 1"/>',
    "moon": '<path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5"/>',
    "logout": '<path d="M6 3H3.5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1H6"/><path d="M10 5l3 3-3 3M13 8H6"/>',
    "room-add": '<path d="M14 4a3 3 0 0 1-3 3H6l-3 2.5V4a3 3 0 0 1 3-3h5a3 3 0 0 1 3 3z"/><path d="M8 7v4M6 9h4" stroke-linecap="round"/>',
    "refresh": '<path d="M13 8a5 5 0 1 1-1.5-3.5"/><path d="M13 2v3h-3"/>',
}


@register.simple_tag
def icon(name: str, size: int = 17) -> str:
    """Render one template icon as inline SVG (decorative: aria-hidden)."""
    body = ICONS.get(name, ICONS["info"])
    return mark_safe(
        f'<svg width="{size}" height="{size}" viewBox="0 0 16 16" fill="none" '
        f'stroke="currentColor" stroke-width="1.6" aria-hidden="true">{body}</svg>'
    )


@register.simple_tag
def icon_fill(name: str, size: int = 17) -> str:
    """Filled variant for glyphs that read better filled (moon)."""
    body = ICONS.get(name, ICONS["info"])
    return mark_safe(
        f'<svg width="{size}" height="{size}" viewBox="0 0 16 16" fill="currentColor" '
        f'stroke="none" aria-hidden="true">{body}</svg>'
    )
