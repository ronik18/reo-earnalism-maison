import hashlib
import json
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from .api import DomainError, public_uuid
from .models import OperationReceipt, AuditEvent


class OperationResult(tuple):
    def __new__(cls,status,body,replayed=False):
        result=super().__new__(cls,(status,body));result.replayed=replayed;return result


def payload_hash(kind, payload):
    raw = json.dumps({'kind':kind,'input':payload},sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def apply_operation(user, operation_id, kind, payload, callback):
    """Serialize a member's short local mutation and receipt in one transaction.

    callback returns (http_status, JSON response, resulting_version). No external IO.
    Actor serialization also handles two simultaneous absent-progress v0 writes.
    """
    operation_id = public_uuid(operation_id, 'operation_id')
    digest = payload_hash(kind,payload)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        old = OperationReceipt.objects.filter(actor=user,operation_id=operation_id).first()
        if old:
            if old.kind != kind or old.request_sha256 != digest:
                raise DomainError('idempotency_key_reused','This operation ID was already used for different input.',409)
            return OperationResult(old.http_status,old.response,True)
        status, body, version = callback()
        OperationReceipt.objects.create(actor=user,operation_id=operation_id,kind=kind,request_sha256=digest,
            http_status=status,response=body,resulting_version=version,expires_at=timezone.now()+timedelta(days=35))
        return OperationResult(status,body,False)


def audit(actor, action, entity, detail=None):
    return AuditEvent.objects.create(actor=actor,action=action,entity_kind=entity.__class__.__name__,entity_id=str(entity.pk),detail=detail or {})
