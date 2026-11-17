import hmac
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.views.decorators.http import require_GET

def problem(request, code, status=403):
    return JsonResponse({'type': 'about:blank', 'title': code.replace('_', ' ').capitalize(),
                         'status': status, 'code': code, 'detail': 'The request could not be completed.',
                         'request_id': request.request_id, 'retryable': status >= 500},
                        status=status, content_type='application/problem+json')

def csrf_failure(request, reason=''):
    return problem(request, 'csrf_failed')

@require_GET
def live(request):
    return JsonResponse({'status': 'ok', 'request_id': request.request_id})

@require_GET
def ready(request):
    received = request.headers.get('X-Health-Probe', '')
    if not hmac.compare_digest(received, settings.HEALTH_PROBE_SECRET):
        return problem(request, 'probe_forbidden')
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            return problem(request, 'schema_not_ready', 503)
    except Exception:
        return problem(request, 'dependency_unavailable', 503)
    return JsonResponse({'status': 'ok', 'request_id': request.request_id})
