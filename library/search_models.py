"""Derived public metadata indexes and explicitly reviewed spelling aliases."""
import unicodedata
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField


class SearchDocument(models.Model):
    revision=models.OneToOneField('library.Revision',on_delete=models.CASCADE,primary_key=True,related_name='search_index')
    title_normalized=models.TextField(default='')
    text_normalized=models.TextField(default='')
    document=SearchVectorField(null=True)
    locale=models.CharField(max_length=2,choices=[('en','English'),('bn','Bengali')])
    class Meta:
        app_label='library'
        db_table='maison_search_document'
        indexes=[GinIndex(fields=['document'],name='maison_search_document_gin'),
            GinIndex(fields=['title_normalized'],opclasses=['gin_trgm_ops'],name='maison_search_title_trgm'),
            models.Index(fields=['title_normalized'],opclasses=['text_pattern_ops'],name='maison_search_title_prefix')]
        constraints=[models.CheckConstraint(condition=Q(locale__in=['en','bn']),name='maison_search_document_locale')]


class SearchAlias(models.Model):
    locale=models.CharField(max_length=2,choices=[('en','English'),('bn','Bengali')])
    alias_normalized=models.CharField(max_length=100)
    target_normalized=models.CharField(max_length=100)
    reviewed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    reviewed_at=models.DateTimeField()
    active=models.BooleanField(default=True)
    class Meta:
        app_label='library'
        db_table='maison_search_alias'
        constraints=[models.UniqueConstraint(fields=['locale','alias_normalized'],name='maison_search_alias_uq'),
            models.CheckConstraint(condition=Q(locale__in=['en','bn']),name='maison_search_alias_locale')]
    def save(self,*args,**kwargs):
        for name in ('alias_normalized','target_normalized'):
            raw=getattr(self,name)
            if not isinstance(raw,str):raise ValidationError('Search aliases require text.')
            setattr(self,name,unicodedata.normalize('NFC',' '.join(raw.split())).casefold())
        self.full_clean()
        return super().save(*args,**kwargs)
