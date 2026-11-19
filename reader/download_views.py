from core.api import json_endpoint,json_body,api_response,operation_key,DomainError
from . import download_services as services
from .views import territory


def _device(request):
    if not getattr(request,'device',None):raise DomainError('device_required','An active session device is required.',403)
    return request.device.id


@json_endpoint(('GET','POST'))
def downloads(request):
    if request.method=='GET':return api_response(services.list_licenses(request.user,_device(request),request.GET))
    data=json_body(request,{'edition_revision_id','format','unit_ids','device_id'},['edition_revision_id','format','unit_ids','device_id'])
    status,result=services.create_license(request.user,_device(request),data,operation_key(request),territory(request))
    return api_response(result,status)


@json_endpoint(('GET','DELETE'))
def download(request,license_id):
    if request.method=='GET':return api_response(services.get_license(request.user,_device(request),license_id))
    status,result=services.revoke_license(request.user,_device(request),license_id,operation_key(request));return api_response(result,status)


@json_endpoint(('POST',))
def refresh(request,license_id):return api_response(services.refresh_license(request.user,_device(request),license_id))


@json_endpoint(('POST',))
def renew(request,license_id):
    status,result=services.renew_license(request.user,_device(request),license_id,operation_key(request),territory(request));return api_response(result,status)


@json_endpoint(('GET',))
def pieces(request,license_id,asset_id):
    from django.http import HttpResponse
    raw=services.local_piece_manifest(request.user,_device(request),license_id,asset_id,request.GET.get('token',''),territory(request))
    response=HttpResponse(raw,content_type='application/json');response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff';return response
