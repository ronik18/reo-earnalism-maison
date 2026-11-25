import uuid
from django.db import models
from django.contrib.postgres.indexes import GinIndex


class PublicCacheReference(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    url=models.CharField(max_length=2048)
    url_sha256=models.CharField(max_length=64,unique=True)
    dependencies=models.JSONField(default=list)
    expires_at=models.DateTimeField(db_index=True)
    emitted_at=models.DateTimeField(auto_now=True)
    class Meta:
        db_table='maison_public_cache_reference'
        indexes=[GinIndex(fields=['dependencies'],name='maison_cache_deps_idx')]


class PublicCacheGeneration(models.Model):
    id=models.PositiveSmallIntegerField(primary_key=True,default=1,editable=False)
    epoch=models.PositiveBigIntegerField(default=1)
    class Meta:
        db_table='maison_public_cache_generation'
        constraints=[models.CheckConstraint(condition=models.Q(id=1),name='maison_cache_singleton')]


class ReviewItem(models.Model):
    """One thing the owner approves in the Monday batch (revenue plan Task 5)."""
    KINDS = [('clearance', 'clearance'), ('cover', 'cover'), ('edition', 'edition'), ('post', 'post')]
    STATUSES = [('pending', 'pending'), ('approved', 'approved'), ('rejected', 'rejected')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=KINDS)
    ref = models.CharField(max_length=240)
    sha256 = models.CharField(max_length=64)
    summary = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUSES, default='pending')
    decided_by = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    standing = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'maison_review_item'
        permissions = [('decide_review', 'Can approve or reject Monday review items')]
        constraints = [
            models.UniqueConstraint(fields=['kind', 'ref', 'sha256'], name='maison_review_item_uq'),
            models.CheckConstraint(condition=models.Q(kind__in=['clearance', 'cover', 'edition', 'post']), name='maison_review_kind_ck'),
            models.CheckConstraint(condition=models.Q(status__in=['pending', 'approved', 'rejected']), name='maison_review_status_ck'),
            models.CheckConstraint(condition=models.Q(standing=False) | models.Q(kind='post', status='approved'), name='maison_review_standing_post_ck'),
        ]
        indexes = [models.Index(fields=['status', 'kind'], name='maison_review_status_idx')]
