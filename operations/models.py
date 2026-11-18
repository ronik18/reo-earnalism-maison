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
