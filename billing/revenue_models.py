"""Owner revenue ledger and reinvestment record (approved spend only from earned revenue)."""
from django.conf import settings
from django.db import models
from django.db.models import Q

SOURCES=['pass','play_books','youtube','podcast','schools','licensing','sponsorship','other']

class RevenueEntry(models.Model):
    month=models.DateField()
    source=models.CharField(max_length=16,choices=[(x,x) for x in SOURCES])
    amount_minor=models.PositiveBigIntegerField()
    currency=models.CharField(max_length=3,default='INR')
    reference=models.CharField(max_length=160)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_revenue_entry'
        constraints=[models.CheckConstraint(condition=Q(month__day=1),name='maison_revenue_month_first'),
                     models.CheckConstraint(condition=Q(source__in=SOURCES),name='maison_revenue_source')]

class ReinvestmentEntry(models.Model):
    month=models.DateField()
    kind=models.CharField(max_length=10,choices=[('set_aside','set_aside'),('spend','spend')])
    amount_minor=models.PositiveBigIntegerField()
    purpose=models.CharField(max_length=200,blank=True,default='')
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.PROTECT,related_name='+')
    payback_due=models.DateField(null=True,blank=True)
    paid_back=models.BooleanField(null=True,blank=True)
    class Meta:
        db_table='maison_reinvestment_entry'
        constraints=[models.CheckConstraint(condition=Q(month__day=1),name='maison_reinvest_month_first'),
                     models.CheckConstraint(condition=Q(kind__in=['set_aside','spend']),name='maison_reinvest_kind'),
                     models.CheckConstraint(condition=~Q(kind='spend')|Q(approved_by__isnull=False,payback_due__isnull=False),name='maison_reinvest_spend_approved'),
                     models.UniqueConstraint(fields=['month'],condition=Q(kind='set_aside'),name='maison_reinvest_set_aside_once')]
