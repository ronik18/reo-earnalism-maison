"""Minimal origin security metadata. Never inspect request bodies or raw URLs."""
import ipaddress
import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger('earnalism.security')


def request_event(request, response, duration_ms):
    """Pure projection: cached identity only, no authentication/database lookup."""
    actor = getattr(request, '_cached_user', None)
    actor_id = str(getattr(actor, 'public_id', '')) if getattr(actor, 'is_authenticated', False) else None
    if actor_id and not re.fullmatch(r'[a-f0-9-]{36}', actor_id):actor_id = None
    try:source_ip = str(ipaddress.ip_address(getattr(request, 'trusted_client_ip', None)))
    except (ValueError, TypeError):source_ip = None
    match = getattr(request, 'resolver_match', None)
    route = getattr(match, 'route', '') if match else ''
    route = re.sub(r'[^A-Za-z0-9/_<>:.-]', '?', str(route))[:256] or 'unmatched'
    method = request.method if re.fullmatch(r'[A-Z]{1,12}', request.method) else 'OTHER'
    territory = getattr(request, 'territory', '')
    if not re.fullmatch('[A-Z]{2}', territory):territory = 'ZZ'
    return {'event':'earnalism.security.request','schema_version':1,
            'at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
            'component':'web','request_id':str(getattr(request,'request_id',''))[:36],
            'method':method,'route':route,'status':int(response.status_code),
            'duration_ms':max(0,min(86400000,int(duration_ms))),
            'territory':territory,'actor_id':actor_id,'source_ip':source_ip}


def emit_request_event(request, response, duration_ms):
    try:logger.info(json.dumps(request_event(request,response,duration_ms),separators=(',',':'),ensure_ascii=True))
    except Exception:
        # Logging transport cannot change an already-computed user response.
        # Archive/source failures are reported by the separate bounded job.
        pass
