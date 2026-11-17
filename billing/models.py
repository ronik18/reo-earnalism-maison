"""Reconciled Lane A state-machine schema, extended with explicit free grant scope."""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q,F

class Offer(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    code=models.CharField(max_length=64)
    name=models.CharField(max_length=160)
    kind=models.CharField(max_length=24,default='edition_purchase',choices=[(x,x) for x in ['one_time_pass','edition_purchase','track_purchase']])
    edition=models.ForeignKey('library.Edition',null=True,blank=True,on_delete=models.PROTECT)
    track=models.ForeignKey('learning.Track',null=True,blank=True,on_delete=models.PROTECT)
    formats=models.JSONField(default=list)
    price_minor=models.PositiveBigIntegerField()
    currency=models.CharField(max_length=3,default='INR')
    duration_seconds=models.PositiveBigIntegerField()
    terms_version=models.CharField(max_length=64)
    terms_summary=models.TextField(blank=True)
    approved=models.BooleanField(default=False)
    active=models.BooleanField(default=False)
    test_only=models.BooleanField(default=True)
    expires_at=models.DateTimeField(null=True,blank=True)
    version=models.PositiveIntegerField(default=1)
    class Meta:
        db_table='maison_offer'
        constraints=[models.UniqueConstraint(fields=['code','version'],name='maison_offer_version_uq'),
                     models.CheckConstraint(condition=Q(price_minor__gt=0,duration_seconds__gt=0),name='maison_offer_positive')]
    def save(self,*args,**kwargs):
        old=type(self).objects.filter(pk=self.pk).first()
        frozen=('code','version','currency','price_minor','duration_seconds','edition_id','track_id','formats','terms_version','kind')
        if old and Order.objects.filter(offer=self).exists() and any(getattr(old,k)!=getattr(self,k) for k in frozen):
            raise ValidationError('Ordered offer terms are immutable; create a new offer version.')
        super().save(*args,**kwargs)

class Order(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    offer=models.ForeignKey(Offer,on_delete=models.PROTECT)
    total_minor=models.PositiveBigIntegerField()
    currency=models.CharField(max_length=3)
    offer_snapshot=models.JSONField()
    operation_id=models.UUIDField()
    request_sha256=models.CharField(max_length=64)
    provider_order_id=models.CharField(max_length=128,null=True,unique=True)
    provider=models.CharField(max_length=20,default='unconfigured')
    test_only=models.BooleanField(default=True)
    status=models.CharField(max_length=12,default='creating',choices=[(x,x) for x in ['creating','created','pending','paid','failed','cancelled','expired']])
    fulfillment_status=models.CharField(max_length=16,default='pending',choices=[(x,x) for x in ['pending','granted','refund_pending','refunded','review']])
    return_path=models.CharField(max_length=1024,default='/vault/')
    created_at=models.DateTimeField(auto_now_add=True)
    expires_at=models.DateTimeField()
    paid_at=models.DateTimeField(null=True)
    version=models.PositiveBigIntegerField(default=1)
    class Meta:
        db_table='maison_order'
        constraints=[models.UniqueConstraint(fields=['user','operation_id'],name='maison_order_operation_uq'),
                     models.CheckConstraint(condition=Q(total_minor__gt=0),name='maison_order_positive'),
                     models.CheckConstraint(condition=Q(status__in=['creating','created','pending','paid','failed','expired','cancelled']),name='maison_order_state')]

class Payment(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    order=models.ForeignKey(Order,on_delete=models.PROTECT,related_name='payments')
    provider=models.CharField(max_length=20)
    provider_payment_id=models.CharField(max_length=128)
    amount_minor=models.PositiveBigIntegerField()
    currency=models.CharField(max_length=3)
    status=models.CharField(max_length=24,default='captured',choices=[(x,x) for x in ['authorized','captured','failed','partially_refunded','refunded']])
    captured_at=models.DateTimeField()
    verification_source=models.CharField(max_length=24)
    evidence_sha256=models.CharField(max_length=64)
    version=models.PositiveBigIntegerField(default=1)
    class Meta:
        db_table='maison_payment'
        constraints=[models.UniqueConstraint(fields=['provider','provider_payment_id'],name='maison_provider_payment_uq'),
                     models.CheckConstraint(condition=Q(amount_minor__gt=0),name='maison_payment_positive')]

class PaymentEvent(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    provider=models.CharField(max_length=20)
    provider_event_id=models.CharField(max_length=160)
    body_sha256=models.CharField(max_length=64)
    payment=models.ForeignKey(Payment,null=True,on_delete=models.PROTECT)
    status=models.CharField(max_length=12,default='received')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_payment_event'
        constraints=[models.UniqueConstraint(fields=['provider','provider_event_id'],name='maison_provider_event_uq')]

class Entitlement(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    grant_key=models.CharField(max_length=200,unique=True)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    source=models.CharField(max_length=24,default='one_time_order',choices=[(x,x) for x in ['free','one_time_order','subscription_invoice','legacy_resolution']])
    scope=models.CharField(max_length=12,default='edition',choices=[(x,x) for x in ['platform','edition','track']])
    edition=models.ForeignKey('library.Edition',null=True,on_delete=models.PROTECT)
    revision=models.ForeignKey('library.Revision',null=True,on_delete=models.PROTECT)
    track=models.ForeignKey('learning.Track',null=True,on_delete=models.PROTECT)
    order=models.ForeignKey(Order,null=True,on_delete=models.PROTECT,related_name='entitlements')
    formats=models.JSONField(default=list)
    valid_from=models.DateTimeField()
    valid_until=models.DateTimeField(null=True)
    status=models.CharField(max_length=12,default='active',choices=[('active','active'),('revoked','revoked')])
    revoked_at=models.DateTimeField(null=True)
    version=models.PositiveBigIntegerField(default=1)
    class Meta:
        db_table='maison_entitlement'
        constraints=[models.UniqueConstraint(fields=['order'],condition=Q(order__isnull=False),name='maison_order_entitlement_once'),
                     models.UniqueConstraint(fields=['user','revision'],condition=Q(source='free'),name='maison_free_revision_entitlement'),
                     models.CheckConstraint(condition=Q(valid_until__isnull=True)|Q(valid_until__gt=F('valid_from')),name='maison_entitlement_window'),
                     models.CheckConstraint(condition=Q(scope='platform',edition__isnull=True,track__isnull=True)|Q(scope='edition',edition__isnull=False,track__isnull=True)|Q(scope='track',edition__isnull=True,track__isnull=False),name='maison_entitlement_scope')]
        indexes=[models.Index(fields=['user','revoked_at','valid_until'],name='maison_entitlement_access_idx')]

class Refund(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name='refunds')
    operation_id=models.UUIDField(unique=True)
    proposed_amount_minor=models.PositiveBigIntegerField()
    amount_minor=models.PositiveBigIntegerField(null=True)
    currency=models.CharField(max_length=3)
    reason=models.TextField()
    description=models.TextField(blank=True)
    status=models.CharField(max_length=12,default='requested',choices=[(x,x) for x in ['requested','approved','submitted','pending','processed','failed','rejected']])
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.PROTECT,related_name='+')
    created_at=models.DateTimeField(auto_now_add=True)
    approved_at=models.DateTimeField(null=True)
    processed_at=models.DateTimeField(null=True)
    provider_refund_id=models.CharField(max_length=128,null=True,unique=True)
    version=models.PositiveBigIntegerField(default=1)
    class Meta:
        db_table='maison_refund'
        permissions=[('approve_refund','Can approve one bounded refund proposal')]
        constraints=[models.CheckConstraint(condition=Q(amount_minor__isnull=True)|Q(amount_minor__gt=0,amount_minor__lte=F('proposed_amount_minor')),name='maison_refund_proposal_bound')]
    def save(self,*args,**kwargs):
        old=type(self).objects.filter(pk=self.pk).first()
        if old:
            if any(getattr(old,k)!=getattr(self,k) for k in ('payment_id','proposed_amount_minor','currency')):
                raise ValidationError('Refund proposal identity and ceiling are immutable.')
            if old.amount_minor!=self.amount_minor and not (old.status=='requested' and self.status=='approved'):
                raise ValidationError('A refund amount can change once, on requested to approved.')
            if old.status=='processed' and self.status!='processed': raise ValidationError('A processed refund is final.')
        super().save(*args,**kwargs)

class LegacyLiability(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.PROTECT)
    legacy_ref=models.CharField(max_length=160,unique=True)
    kind=models.CharField(max_length=20,default='reading_seconds',choices=[(x,x) for x in ['reading_seconds','entitlement','pending_payment','refund']])
    status=models.CharField(max_length=20,default='unresolved')
    seconds_balance=models.PositiveBigIntegerField(default=0)
    evidence_sha256=models.CharField(max_length=64)
    resolution=models.CharField(max_length=24,null=True)
    class Meta:
        db_table='maison_legacy_liability'

class Invoice(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    order=models.OneToOneField(Order,on_delete=models.PROTECT)
    number=models.CharField(max_length=100,unique=True)
    amount_minor=models.PositiveBigIntegerField()
    currency=models.CharField(max_length=3)
    document_sha256=models.CharField(max_length=64)
    line_snapshot=models.JSONField()
    issued_at=models.DateTimeField()
    class Meta:
        db_table='maison_invoice'
    def save(self,*args,**kwargs):
        if type(self).objects.filter(pk=self.pk).exists(): raise ValidationError('Issued financial snapshots are immutable.')
        super().save(*args,**kwargs)

class PaymentAllocation(models.Model):
    payment=models.ForeignKey(Payment,on_delete=models.PROTECT)
    invoice=models.ForeignKey(Invoice,on_delete=models.PROTECT)
    amount_minor=models.PositiveBigIntegerField()
    class Meta:
        db_table='maison_payment_allocation'
        constraints=[models.UniqueConstraint(fields=['payment','invoice'],name='maison_payment_invoice_uq')]
