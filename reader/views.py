import uuid
from django.conf import settings
from core.api import json_endpoint,json_body,api_response,DomainError,expected_version,operation_key,problem_data
from core.pagination import paginate_queryset
from library.validation import validate_schema
from . import services
from .models import Progress,Completion,Annotation,SavedItem,PersonalList


def territory(request):return getattr(request,'territory','IN' if getattr(settings,'LOCAL',False) else 'ZZ')
def key(request):return operation_key(request)
def page(items):return {'items':items,'next_cursor':None,'has_more':False}


@json_endpoint(('GET','PUT'))
def progress(request,edition_id,format):
    if request.method=='GET':
        result=services.get_progress(request.user,edition_id,format,territory(request));return api_response(result,version=result['version'])
    d=json_body(request,{'operation_id','edition_revision_id','location','occurred_at'},['operation_id','edition_revision_id','location','occurred_at'])
    validate_schema(d,'ProgressInput')
    status,result=services.set_progress(request.user,edition_id,format,d,expected_version(request),territory(request));return api_response(result,status,version=result['version'])


@json_endpoint(('GET',))
def list_progress(request):
    rows=Progress.objects.filter(user=request.user)
    if request.GET.get('edition_id'):
        from core.api import public_uuid
        rows=rows.filter(edition_id=public_uuid(request.GET['edition_id'],'edition_id'))
    if request.GET.get('format'):
        if request.GET['format'] not in ('reader','audio','video'):raise DomainError('validation_error','Invalid format.',422)
        rows=rows.filter(format=request.GET['format'])
    result=paginate_queryset(request,rows,'progress',ordering='-updated_at')
    result['items']=[services.progress_data(x) for x in result['items']]
    return api_response(result)


@json_endpoint(('GET','PUT'))
def completion(request,edition_id,format):
    if request.method=='GET':
        result=services.get_completion(request.user,edition_id,format,territory(request));return api_response(result,version=result['version'])
    d=json_body(request,{'operation_id','is_complete'},['operation_id','is_complete'])
    status,result=services.set_completion(request.user,edition_id,format,d,expected_version(request),territory(request));return api_response(result,status,version=result['version'])


@json_endpoint(('GET','POST'))
def annotations(request):
    if request.method=='GET':
        rows=Annotation.objects.filter(user=request.user,deleted_at=None).select_related('revision__edition')
        if request.GET.get('edition_revision_id'):
            from core.api import public_uuid
            rows=rows.filter(revision_id=public_uuid(request.GET['edition_revision_id'],'edition_revision_id'))
        result=paginate_queryset(request,rows,'annotations')
        result['items']=[services.annotation_data(x,request.user) for x in result['items']]
        return api_response(result)
    d=json_body(request,{'annotation_id','edition_revision_id','kind','range','color','note_text'},['annotation_id','edition_revision_id','kind','range','color','note_text'])
    status,result=services.create_annotation(request.user,d,operation_key(request),territory(request));return api_response(result,status,version=result['version'])


@json_endpoint(('GET','PATCH','DELETE'))
def annotation(request,annotation_id):
    if request.method=='GET':
        row=Annotation.objects.filter(pk=annotation_id,user=request.user,deleted_at=None).select_related('revision__edition').first()
        if not row:raise DomainError('not_found','Annotation not found.',404)
        return api_response(services.annotation_data(row,request.user),version=row.version)
    if request.method=='DELETE':status,result=services.delete_annotation(request.user,annotation_id,key(request),expected_version(request))
    else:status,result=services.patch_annotation(request.user,annotation_id,json_body(request,{'note_text','color'}),key(request),expected_version(request))
    return api_response(result,status,version=result.get('version'))


@json_endpoint(('GET',))
def saved_items(request):
    result=paginate_queryset(request,SavedItem.objects.filter(user=request.user).select_related('edition'),'saved-items')
    shelf=services.Shelf(territory(request),request.user);shelf.prepare(result['items'])
    result['items']=[{'edition_id':str(row.edition_id),'saved_at':services.iso(row.created_at),'available':shelf.cards.get(row.edition_id) is not None}
                     for row in result['items']]
    return api_response(result)


@json_endpoint(('PUT','DELETE'))
def saved_item(request,edition_id):
    status,result=services.saved_set(request.user,edition_id,request.method=='PUT',key(request));return api_response(result,status)


@json_endpoint(('GET','POST'))
def lists(request):
    if request.method=='GET':
        result=paginate_queryset(request,PersonalList.objects.filter(user=request.user),'personal-lists',ordering='name')
        result['items']=[services.list_data(x) for x in result['items']]
        return api_response(result)
    d=json_body(request,{'name'},['name']);status,result=services.create_list(request.user,d['name'],operation_key(request));return api_response(result,status,version=result['version'])


@json_endpoint(('GET','PATCH','DELETE'))
def personal_list(request,list_id):
    if request.method=='GET':
        row=PersonalList.objects.filter(pk=list_id,user=request.user).first()
        if not row:raise DomainError('not_found','List not found.',404)
        result=services.list_data(row,True);return api_response(result,version=result['version'])
    action='delete' if request.method=='DELETE' else 'rename';d={} if action=='delete' else json_body(request,{'name'},['name'])
    status,result=services.mutate_list(request.user,list_id,key(request),expected_version(request),action,d);return api_response(result,status,version=result.get('version'))


@json_endpoint(('PUT','DELETE'))
def list_edition(request,list_id,edition_id):
    status,result=services.mutate_list(request.user,list_id,key(request),expected_version(request),'add' if request.method=='PUT' else 'remove',{'edition_id':str(edition_id)})
    return api_response(result,status,version=result['version'])


@json_endpoint(('PUT',))
def list_order(request,list_id):
    d=json_body(request,{'edition_ids'},['edition_ids'])
    if not isinstance(d['edition_ids'],list) or len(d['edition_ids'])>500:raise DomainError('validation_error','Invalid list order.',422)
    status,result=services.mutate_list(request.user,list_id,key(request),expected_version(request),'reorder',d);return api_response(result,status,version=result['version'])


@json_endpoint(('GET',))
def vault(request):return api_response(services.vault_data(request.user,territory=territory(request),request=request))


@json_endpoint(('POST',))
def sync(request):
    d=json_body(request,{'device_id','operations'},['device_id','operations'])
    if not getattr(request,'device',None) or str(request.device.id)!=str(d['device_id']):raise DomainError('device_mismatch','Use this session device.',403)
    if not isinstance(d['operations'],list) or not 1<=len(d['operations'])<=100:raise DomainError('validation_error','Use 1–100 operations.',422)
    from core.api import public_uuid
    for item in d['operations']:
        if not isinstance(item,dict):raise DomainError('validation_error','Invalid operation.',422)
        public_uuid(item.get('operation_id'),'operation_id')
    results=[]
    # DB errors deliberately escape to one batch503. Committed earlier receipts remain
    # durable: client retries the unchanged entire batch, never fresh operation IDs.
    for op in d['operations']:
        try:
            if not isinstance(op,dict):raise DomainError('validation_error','Invalid operation.',422)
            validate_schema(op,'SyncOperation')
            kind=op.get('kind');oid=op.get('operation_id')
            if kind=='progress.set':
                data={k:op[k] for k in ['operation_id','edition_revision_id','location','occurred_at']}
                operation_result=services.set_progress(request.user,op['edition_id'],op['format'] if 'format' in op else op['location']['format'],data,op['base_version'],territory(request))
            elif kind=='annotation.create':operation_result=services.create_annotation(request.user,op['annotation'],oid,territory(request))
            elif kind=='annotation.patch':operation_result=services.patch_annotation(request.user,op['annotation_id'],op['patch'],oid,op['base_version'])
            elif kind=='annotation.delete':operation_result=services.delete_annotation(request.user,op['annotation_id'],oid,op['base_version'])
            elif kind=='saved.set':operation_result=services.saved_set(request.user,op['edition_id'],op['saved'],oid)
            else:raise DomainError('unsupported_operation','This operation cannot be queued offline.',422)
            status,result=operation_result
            results.append({'operation_id':str(oid),'outcome':'replayed' if getattr(operation_result,'replayed',False) else 'applied','http_status':status,'resource_id':result.get('annotation_id') or result.get('edition_id'),'version':result.get('version'),'problem':None})
        except (KeyError,TypeError):results.append({'operation_id':str(op.get('operation_id','')) if isinstance(op,dict) else '', 'outcome':'rejected','http_status':422,'resource_id':None,'version':None,'problem':problem_data(DomainError('validation_error','Invalid operation fields.',422),request)})
        except DomainError as e:results.append({'operation_id':str(op.get('operation_id','')),'outcome':'conflict' if e.status in [409,412] else 'rejected','http_status':e.status,'resource_id':None,'version':None,'problem':problem_data(e,request)})
    return api_response({'results':results,'server_time':services.iso(__import__('django.utils.timezone',fromlist=['now']).now())})
