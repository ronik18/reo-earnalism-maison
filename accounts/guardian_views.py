"""Policy-gated India account permission and separately authorized rights."""
from core.api import json_endpoint,json_body,api_response,operation_key,DomainError
from . import guardian
from .views import require_fresh


@json_endpoint(('GET',))
def policies(request):
    return api_response({'items':guardian.policies()})


@json_endpoint(('GET','POST'))
def authorizations(request):
    guardian.enabled()
    if request.method=='GET':return api_response(guardian.list_authorizations(request))
    from .enrollment import PARENT_FIELDS
    d=json_body(request,{'jurisdiction','purpose','notice_version','method','source_authorization_id'}|PARENT_FIELDS,['jurisdiction','purpose','notice_version','method'])
    status,body=guardian.request_authorization(request,**d,operation_id=operation_key(request))
    return api_response(body,status,version=body['version'])


@json_endpoint(('GET',))
def detail(request,authorization_id):
    return api_response(guardian.authorization_detail(request,authorization_id))


@json_endpoint(('POST',))
def withdraw(request,authorization_id):
    guardian.enabled();require_fresh(request)
    d=json_body(request,{'expected_version'},['expected_version'])
    if type(d['expected_version']) is not int:raise DomainError('validation_error','A current integer version is required.',422)
    status,body=guardian.withdraw(request,authorization_id,**d,operation_id=operation_key(request))
    return api_response(body,status,version=body['version'])


@json_endpoint(('POST',))
def review(request,authorization_id):
    guardian.enabled();require_fresh(request)
    d=json_body(request,{'approve','evidence_sha256','expected_version'},['approve','evidence_sha256','expected_version'])
    if type(d['expected_version']) is not int:raise DomainError('validation_error','A current integer version is required.',422)
    status,body=guardian.review(request,authorization_id,**d,operation_id=operation_key(request))
    return api_response(body,status,version=body['version'])


@json_endpoint(('POST',))
def claim_capability(request,authorization_id):
    guardian.enabled();json_body(request,set())
    return api_response(guardian.issue_claim(request,authorization_id))


@json_endpoint(('POST',))
def claim(request,authorization_id):
    return api_response(guardian.claim_account(request,authorization_id),202)


@json_endpoint(('POST',))
def privacy_requests(request,authorization_id):
    guardian.enabled();d=json_body(request,{'kind','confirm'},['kind','confirm'])
    status,body=guardian.request_privacy(request,authorization_id,**d,operation_id=operation_key(request))
    return api_response(body,status)


@json_endpoint(('GET',))
def privacy_request(request,authorization_id,privacy_request_id):
    from .views import privacy_data
    return api_response(privacy_data(guardian.privacy_job(request,authorization_id,privacy_request_id)))


def _export(request,authorization_id,privacy_request_id):
    from datetime import datetime
    from django.utils import timezone
    require_fresh(request);job=guardian.privacy_job(request,authorization_id,privacy_request_id)
    if job.kind!='privacy_export' or job.status!='done':raise DomainError('not_found','A completed export was not found.',404)
    try:expiry=datetime.fromisoformat(job.result['expires_at'].replace('Z','+00:00'))
    except (KeyError,TypeError,ValueError):raise DomainError('export_unavailable','Request a new export.',410)
    if timezone.now()>=expiry:raise DomainError('export_expired','Request a new export.',410)
    return job,expiry


@json_endpoint(('POST',))
def privacy_download(request,authorization_id,privacy_request_id):
    from datetime import timedelta
    from django.utils import timezone
    from django.urls import reverse
    from library import storage
    guardian.enabled();json_body(request,set());job,artifact_expiry=_export(request,authorization_id,privacy_request_id)
    expiry=min(timezone.now()+timedelta(seconds=120),artifact_expiry)
    seconds=int((expiry-timezone.now()).total_seconds())
    if seconds<1:raise DomainError('export_expired','Request a new export.',410)
    if not job.result.get('storage_key'):raise DomainError('export_unavailable','Request a new export.',410)
    if storage.is_r2():url=storage.private_url(job.result['storage_key'],seconds,'application/json')
    else:
        job.result['delivery_until']=expiry.isoformat();job.save(update_fields=['result'])
        url=request.build_absolute_uri(f'/api/v1/me/guardian/authorizations/{authorization_id}/privacy-requests/{privacy_request_id}/file')
    return api_response({'url':url,'expires_at':expiry.isoformat(),'sha256':job.result['sha256'],'bytes':job.result['bytes'],'content_type':'application/json'})


@json_endpoint(('GET',))
def privacy_file(request,authorization_id,privacy_request_id):
    from datetime import datetime
    from django.conf import settings
    from django.utils import timezone
    from django.http import FileResponse
    from library import storage
    guardian.enabled()
    if not settings.LOCAL:raise DomainError('export_unavailable','Request a private download grant.',410)
    job,_=_export(request,authorization_id,privacy_request_id)
    try:delivery=datetime.fromisoformat(job.result['delivery_until'].replace('Z','+00:00'))
    except (KeyError,TypeError,ValueError):raise DomainError('export_expired','Request a download grant.',410)
    if timezone.now()>=delivery:raise DomainError('export_expired','Request a download grant.',410)
    storage.verify_private(job.result['storage_key'],job.result['bytes'],job.result['sha256'],'application/json')
    path=storage._local_path(job.result['storage_key'])
    response=FileResponse(path.open('rb'),as_attachment=True,filename='earnalism-authorized-personal-data.json',content_type='application/json')
    response['Cache-Control']='private, no-store';return response
