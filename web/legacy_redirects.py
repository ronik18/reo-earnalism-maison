"""Old theearnalism.com URLs after the apex cutover (LLD 4: retired slugs answer 410).

Static pages move permanently to their Maison equivalents. A legacy book slug
redirects only once that title is republished on Maison; until then it is Gone.
"""
from django.http import HttpResponsePermanentRedirect

LEGACY_PAGES = {
    'privacy': '/en/privacy/', 'terms': '/en/terms/', 'contact': '/en/contact/', 'copyright': '/en/terms/',
    'library': '/en/explore/', 'pricing': '/en/pass/', 'about': '/en/', 'journal': '/en/', 'micro-story': '/en/',
}
# Legacy slug -> Maison edition id, added when the title is republished.
LEGACY_TITLES: dict[str, str] = {}


def legacy_page(request, name, rest=''):
    return HttpResponsePermanentRedirect(LEGACY_PAGES[name])


def legacy_title(request, slug):
    edition_id = LEGACY_TITLES.get(slug)
    if edition_id:
        return HttpResponsePermanentRedirect(f'/en/titles/{edition_id}/')
    from .views import page
    # 410 tells search engines the old page is gone; the branded page still leads into the library.
    return page(request, 'en', 'web/status.html', status=410, error_key='not_found')
