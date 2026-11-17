import hmac
import uuid
from django.conf import settings
from django.http import JsonResponse

class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            value = uuid.UUID(request.headers.get('X-Request-ID', ''))
            if value.version != 4:
                raise ValueError
        except (ValueError, AttributeError):
            value = uuid.uuid4()
        request.request_id = str(value)
        # Production country needs the separately qualified edge adapter; query input never authorizes.
        request.territory = 'IN' if settings.LOCAL else 'ZZ'
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        response.setdefault('Cache-Control', 'private, no-store')
        response['X-Content-Type-Options'] = 'nosniff'
        response.setdefault('Referrer-Policy', settings.SECURE_REFERRER_POLICY)
        response['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        return response

class OriginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.LOCAL and request.path != '/api/v1/health/live':
            received = request.headers.get('X-Maison-Origin', '')
            if not hmac.compare_digest(received, settings.ORIGIN_SHARED_SECRET):
                return JsonResponse({'type': 'about:blank', 'title': 'Forbidden', 'status': 403,
                                     'code': 'origin_forbidden', 'detail': 'Use the configured application origin.',
                                     'request_id': request.request_id, 'retryable': False}, status=403,
                                    content_type='application/problem+json')
        return self.get_response(request)
