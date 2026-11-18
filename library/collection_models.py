"""Persistent editorial collections; publication never grants edition access."""
import uuid
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class CatalogCollection(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    slug=models.SlugField(max_length=160,unique=True,validators=[RegexValidator(r'^[a-z0-9]+(-[a-z0-9]+)*$')])
    title_en=models.CharField(max_length=200)
    title_bn=models.CharField(max_length=200)
    description_en=models.TextField(max_length=4000,blank=True)
    description_bn=models.TextField(max_length=4000,blank=True)
    house=models.CharField(max_length=20,choices=[(x,x) for x in ('classics','golpo','learn','interview','series','collections')],default='collections')
    kind=models.CharField(max_length=12,choices=[(x,x) for x in ('shelf','series','author','topic')],default='shelf')
    published=models.BooleanField(default=False)
    version=models.PositiveBigIntegerField(default=1,editable=False)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        app_label='library'
        db_table='maison_catalog_collection'
        ordering=['slug','id']
        constraints=[models.CheckConstraint(condition=Q(version__gte=1),name='maison_collection_version_positive'),models.CheckConstraint(condition=Q(kind__in=['shelf','series','author','topic']),name='maison_collection_kind'),models.CheckConstraint(condition=Q(house__in=['classics','golpo','learn','interview','series','collections']),name='maison_collection_house'),models.CheckConstraint(condition=Q(slug__regex=r'^[a-z0-9]+(-[a-z0-9]+)*$'),name='maison_collection_slug')]

    def save(self,*args,**kwargs):
        self.full_clean()
        super().save(*args,**kwargs)
        self.refresh_from_db(fields=['version','updated_at'])


class CatalogItem(models.Model):
    collection=models.ForeignKey(CatalogCollection,on_delete=models.CASCADE,related_name='items')
    edition=models.ForeignKey('library.Edition',on_delete=models.PROTECT,related_name='catalog_items')
    sort_order=models.PositiveIntegerField()
    class Meta:
        app_label='library'
        db_table='maison_catalog_item'
        ordering=['sort_order','id']
        constraints=[models.UniqueConstraint(fields=['collection','edition'],name='maison_catalog_item_edition_uq'),models.UniqueConstraint(fields=['collection','sort_order'],name='maison_catalog_item_order_uq',deferrable=models.Deferrable.DEFERRED),models.CheckConstraint(condition=Q(sort_order__gte=0),name='maison_catalog_item_order_positive')]
