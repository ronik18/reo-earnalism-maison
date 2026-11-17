import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


class OperationReceipt(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    operation_id = models.UUIDField()
    kind = models.CharField(max_length=64)
    request_sha256 = models.CharField(max_length=64)
    http_status = models.PositiveSmallIntegerField()
    response = models.JSONField()
    resulting_version = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = 'maison_operation_receipt'
        constraints = [
            models.UniqueConstraint(fields=['actor', 'operation_id'], name='maison_receipt_actor_operation_uq'),
            models.CheckConstraint(condition=Q(http_status__gte=200, http_status__lt=300), name='maison_receipt_success_status'),
        ]
        indexes = [models.Index(fields=['expires_at'], name='maison_receipt_expiry_idx')]


class OutboxJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=64)
    dedupe_key = models.CharField(max_length=200, unique=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=12, default='pending', choices=[(v,v) for v in ['pending','claimed','done','blocked','dead','cancelled']])
    attempts = models.PositiveSmallIntegerField(default=0)
    not_before = models.DateTimeField()
    lease_owner = models.CharField(max_length=100, blank=True)
    locked_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'maison_outbox'
        indexes = [models.Index(fields=['status','not_before'], name='maison_outbox_due_idx')]
        constraints = [models.CheckConstraint(condition=Q(attempts__lte=7), name='maison_outbox_attempt_bound')]


class AuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64)
    entity_kind = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=100)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'maison_audit'
        indexes = [models.Index(fields=['entity_kind','entity_id','created_at'], name='maison_audit_entity_idx')]
