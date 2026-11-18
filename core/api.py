"""Small same-origin JSON boundary. CSRF remains Django middleware's responsibility."""
import json
import logging
import re
import uuid
from functools import wraps
from django.http import JsonResponse
from django.db import DatabaseError

logger = logging.getLogger(__name__)


class DomainError(Exception):
    def __init__(self, code, message, status=403, details=None, retry_after=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details
        self.retry_after = retry_after


def public_uuid(value, field='id'):
    try:
        result = uuid.UUID(str(value))
        if result.version != 4:
            raise ValueError
        return result
    except (ValueError, TypeError, AttributeError):
        raise DomainError('validation_error', f'{field} must be a UUID4.', 422)


def json_body(request, allowed=None, required=()):
    if len(request.body) > 262144:
        raise DomainError('payload_too_large', 'The request exceeds 256 KiB.', 413)
    if request.content_type != 'application/json':
        raise DomainError('unsupported_media_type', 'Use application/json.', 415)
    try:
        data = json.loads(request.body or b'{}',parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))
    except (ValueError, UnicodeDecodeError):
        raise DomainError('invalid_json', 'Invalid JSON.', 400)
    if not isinstance(data, dict):
        raise DomainError('validation_error', 'Expected a JSON object.', 422)
    if allowed is not None and set(data) - set(allowed):
        raise DomainError('validation_error', 'Unknown input field.', 422)
    if set(required) - set(data):
        raise DomainError('validation_error', 'A required field is missing.', 422)
    return data


def expected_version(request):
    value = request.headers.get('If-Match')
    if value is None:
        raise DomainError('precondition_required', 'Send the current ETag as If-Match.', 428)
    match = re.fullmatch(r'"v(\d+)"', value)
    if not match:
        raise DomainError('invalid_precondition', 'Expected a strong ETag such as "v3".', 400)
    return int(match.group(1))


def operation_key(request):
    value = request.headers.get('Idempotency-Key')
    if not value:
        raise DomainError('idempotency_key_required', 'Send an Idempotency-Key.', 400)
    return public_uuid(value, 'Idempotency-Key')


def api_response(body, status=200, version=None):
    response = JsonResponse(body, status=status, safe=isinstance(body, dict)) if status != 204 else JsonResponse({}, status=204)
    response['Cache-Control'] = 'private, no-store'
    response['X-Request-ID'] = str(uuid.uuid4())
    if version is not None:
        response['ETag'] = f'"v{version}"'
    return response


def problem_data(error,request=None):
    data = {'type': f'urn:maison:problem:{error.code}', 'title': error.code.replace('_',' ').capitalize(),
            'status': error.status, 'code': error.code, 'detail': error.message,
            'request_id': str(getattr(request,'request_id',uuid.uuid4())), 'retryable': error.status in (429,503)}
    if error.details is not None:
        data['current_resource'] = error.details
        if isinstance(error.details,dict) and isinstance(error.details.get('version'),int):data['current_version']=error.details['version']
    return data


def problem(error,request=None):
    data=problem_data(error,request)
    response = api_response(data, error.status)
    response['Content-Type'] = 'application/problem+json'
    if error.status in (429,503): response['Retry-After'] = str(error.retry_after if error.retry_after is not None else 2)
    return response


def json_endpoint(methods=('GET',), auth=True, verified=True):
    def decorate(fn):
        @wraps(fn)
        def view(request, *args, **kwargs):
            try:
                if request.method not in methods:
                    return problem(DomainError('method_not_allowed', 'Method not allowed.', 405),request)
                if auth and not request.user.is_authenticated:
                    raise DomainError('authentication_required', 'Sign in to continue.', 401)
                if auth and verified and not request.user.is_verified:
                    raise DomainError('email_verification_required', 'Verify your email before continuing.', 403)
                return fn(request, *args, **kwargs)
            except DomainError as exc:
                return problem(exc,request)
            except DatabaseError:
                logger.warning('Database operation unavailable', extra={'path':request.path})
                return problem(DomainError('temporarily_unavailable', 'Please retry this operation.', 503),request)
        return view
    return decorate
