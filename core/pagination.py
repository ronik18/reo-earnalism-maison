"""Bounded signed keyset pagination for private/member list APIs."""
import hashlib
import json
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import Q
from .api import DomainError


def _context(request,scope,maximum):
    try:
        limit=int(request.GET.get('limit',20))
        if not 1<=limit<=maximum:raise ValueError
    except (TypeError,ValueError):raise DomainError('invalid_limit',f'Use 1–{maximum} records per page.',422)
    query=[(k,request.GET.getlist(k)) for k in sorted(request.GET) if k!='cursor']
    actor=str(request.user.pk) if getattr(request.user,'is_authenticated',False) else 'anonymous'
    binding=hashlib.sha256(json.dumps([scope,actor,getattr(request,'territory','ZZ'),query],separators=(',',':')).encode()).hexdigest()
    data=None
    token=request.GET.get('cursor')
    if token:
        try:
            if len(token)>1024:raise ValueError
            data=signing.loads(token,salt='maison-keyset-v1',max_age=3600)
            if not isinstance(data,dict) or data.get('binding')!=binding:raise ValueError
        except (signing.BadSignature,ValueError,TypeError):raise DomainError('invalid_cursor','This cursor is invalid for the current list.',422)
    return limit,binding,data


def _result(rows,limit,binding,position):
    more=len(rows)>limit;selected=rows[:limit]
    cursor=signing.dumps({'binding':binding,'after':position(selected[-1])},salt='maison-keyset-v1',compress=True) if more and selected else None
    return {'items':selected,'next_cursor':cursor,'has_more':more}


def paginate_queryset(request,queryset,scope,ordering='-created_at',maximum=100,serialize=None,scan_limit=500):
    limit,binding,data=_context(request,scope+':'+ordering,maximum)
    field=ordering.lstrip('-');descending=ordering.startswith('-');pk=queryset.model._meta.pk
    qs=queryset.order_by(ordering,('-' if descending else '')+pk.name) if field!=pk.name else queryset.order_by(ordering)
    if data is not None:
        try:
            after=data['after']
            if not isinstance(after,list) or len(after)!=2:raise ValueError
            value=queryset.model._meta.get_field(field).to_python(after[0]);identity=pk.to_python(after[1])
            lookup='lt' if descending else 'gt'
            qs=qs.filter(Q(**{field+'__'+lookup:value}) | Q(**{field:value,pk.name+'__'+lookup:identity}))
        except (KeyError,ValueError,TypeError,ValidationError):raise DomainError('invalid_cursor','Invalid list position.',422)
    position=lambda row:[str(getattr(row,field)),str(row.pk)]
    if serialize is None:return _result(list(qs[:limit+1]),limit,binding,position)
    batch=list(qs[:scan_limit+1]);selected=[];examined=None;count=0
    for row in batch[:scan_limit]:
        count+=1;examined=row
        value=serialize(row)
        if value is not None:selected.append(value)
        if len(selected)>=limit:break
    more=len(batch)>count
    cursor=signing.dumps({'binding':binding,'after':position(examined)},salt='maison-keyset-v1',compress=True) if more and examined else None
    return {'items':selected,'next_cursor':cursor,'has_more':more}



# Retain the existing download-license cursor contract.
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from .api import public_uuid

def keyset_page(rows,params,scope,time_field,serialize):
    try:limit=int(params.get('limit','20'))
    except (ValueError,TypeError):raise DomainError('validation_error','limit must be1–100.',422)
    if not 1<=limit<=100:raise DomainError('validation_error','limit must be1–100.',422)
    cursor=params.get('cursor');query={str(k):str(v) for k,v in params.items() if k!='cursor'}
    if cursor:
        try:
            if len(cursor)>1024:raise ValueError()
            position=signing.loads(cursor,salt='maison-private-keyset',max_age=3600)
            if position['scope']!=scope or position['query']!=query:raise ValueError()
            stamp=parse_datetime(position['at'])
            if not stamp or timezone.is_naive(stamp):raise ValueError()
            identifier=public_uuid(position['id'])
        except (signing.BadSignature,ValueError,TypeError,KeyError,DomainError):
            raise DomainError('invalid_cursor','Invalid or expired page cursor.',400)
        rows=rows.filter(Q(**{time_field+'__lt':stamp})|Q(**{time_field:stamp,'pk__lt':identifier}))
    selected=list(rows.order_by('-'+time_field,'-pk')[:limit+1]);more=len(selected)>limit;selected=selected[:limit]
    next_cursor=None
    if more:
        last=selected[-1]
        next_cursor=signing.dumps({'scope':scope,'query':query,'at':getattr(last,time_field).isoformat(),'id':str(last.pk)},salt='maison-private-keyset',compress=True)
    return {'items':[serialize(row) for row in selected],'next_cursor':next_cursor,'has_more':more}
