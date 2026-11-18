"""Persisted existing recurring agreements; creating/charging remains provider-gated."""
import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q,F
from django.core.exceptions import ValidationError

class BillingPlan(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    offer=models.OneToOneField('billing.Offer',on_delete=models.PROTECT)
    interval_unit=models.CharField(max_length=8,choices=[('month','month'),('year','year')])
    interval_count=models.PositiveSmallIntegerField(default=1)
    max_cycles=models.PositiveIntegerField(null=True,blank=True)
    provider=models.CharField(max_length=16,default='razorpay')
    provider_plan_id=models.CharField(max_length=128,null=True,unique=True)
    merchant_approved_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_billing_plan'
        constraints=[models.CheckConstraint(condition=Q(interval_unit__in=['month','year']),name='maison_plan_interval'),models.CheckConstraint(condition=Q(interval_count__gte=1,interval_count__lte=12),name='maison_plan_interval_count'),models.CheckConstraint(condition=Q(max_cycles__isnull=True)|Q(max_cycles__gt=0),name='maison_plan_cycles')]

class Mandate(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    provider=models.CharField(max_length=16,default='razorpay')
    provider_mandate_id=models.CharField(max_length=128,null=True,blank=True)
    provider_status=models.CharField(max_length=64,blank=True)
    status=models.CharField(max_length=16,default='pending')
    method=models.CharField(max_length=12,default='other')
    currency=models.CharField(max_length=3,default='INR')
    max_amount_minor=models.PositiveBigIntegerField()
    authorized_at=models.DateTimeField(null=True,blank=True)
    expires_at=models.DateTimeField(null=True,blank=True)
    revoked_at=models.DateTimeField(null=True,blank=True)
    revocation_pending=models.BooleanField(default=False)
    version=models.PositiveBigIntegerField(default=1)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_mandate'
        indexes=[models.Index(fields=['user','-created_at','-id'],name='maison_mandate_keyset_idx')]
        constraints=[models.UniqueConstraint(fields=['provider','provider_mandate_id'],name='maison_mandate_provider_uq'),models.CheckConstraint(condition=Q(status__in=['pending','authorized','paused','cancelled','failed','expired']),name='maison_mandate_state'),models.CheckConstraint(condition=Q(method__in=['card','upi','emandate','other']),name='maison_mandate_method'),models.CheckConstraint(condition=Q(max_amount_minor__gt=0),name='maison_mandate_amount'),models.CheckConstraint(condition=~Q(status='authorized')|Q(authorized_at__isnull=False,provider_mandate_id__isnull=False),name='maison_mandate_authority'),models.CheckConstraint(condition=Q(version__gt=0),name='maison_mandate_version')]

class Subscription(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    plan=models.ForeignKey(BillingPlan,on_delete=models.PROTECT)
    mandate=models.OneToOneField(Mandate,null=True,blank=True,on_delete=models.PROTECT,related_name='subscription')
    provider=models.CharField(max_length=16,default='razorpay')
    provider_subscription_id=models.CharField(max_length=128,null=True,blank=True)
    provider_status=models.CharField(max_length=16,default='created')
    status=models.CharField(max_length=16,default='pending')
    cancel_at_period_end=models.BooleanField(default=False)
    cancellation_requested_at=models.DateTimeField(null=True,blank=True)
    current_period_start=models.DateTimeField(null=True,blank=True)
    current_period_end=models.DateTimeField(null=True,blank=True)
    paid_through=models.DateTimeField(null=True,blank=True)
    next_charge_at=models.DateTimeField(null=True,blank=True)
    version=models.PositiveBigIntegerField(default=1)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_subscription'
        indexes=[models.Index(fields=['user','-created_at','-id'],name='maison_sub_keyset_idx')]
        constraints=[models.UniqueConstraint(fields=['provider','provider_subscription_id'],name='maison_subscription_provider_uq'),models.CheckConstraint(condition=Q(status__in=['pending','active','past_due','paused','cancelled','completed','expired']),name='maison_subscription_state'),models.CheckConstraint(condition=Q(provider_status__in=['created','authenticated','active','pending','halted','paused','cancelled','completed','expired']),name='maison_subscription_provider_state'),models.CheckConstraint(condition=Q(current_period_start__isnull=True,current_period_end__isnull=True)|Q(current_period_start__isnull=False,current_period_end__isnull=False,current_period_end__gt=F('current_period_start')),name='maison_subscription_period'),models.CheckConstraint(condition=Q(cancel_at_period_end=False)|Q(cancellation_requested_at__isnull=False),name='maison_subscription_cancel_time'),models.CheckConstraint(condition=~Q(status='active')|Q(mandate__isnull=False,current_period_end__isnull=False),name='maison_subscription_active_period'),models.CheckConstraint(condition=Q(version__gt=0),name='maison_subscription_version')]
    def clean(self):
        if self.mandate_id and self.mandate.user_id!=self.user_id:
            raise ValidationError('Mandate and subscription must have the same owner.')
