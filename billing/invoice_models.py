"""Finance-approved retained invoice artifacts; no document generation or tax inference."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class InvoiceArtifact(models.Model):
    invoice=models.OneToOneField('billing.Invoice',on_delete=models.PROTECT,primary_key=True,related_name='artifact')
    storage_key=models.CharField(max_length=512,unique=True)
    sha256=models.CharField(max_length=64)
    bytes=models.PositiveBigIntegerField()
    snapshot_sha256=models.CharField(max_length=64)
    issuer_version=models.CharField(max_length=120)
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='+')
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table='maison_invoice_artifact'
        permissions=[('attach_invoice_artifact','Can bind a verified finance-approved invoice PDF')]
        constraints=[models.CheckConstraint(condition=Q(bytes__gt=0),name='maison_invoice_artifact_bytes')]

    def save(self,*args,**kwargs):
        if type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Approved invoice artifacts are immutable.')
        super().save(*args,**kwargs)


class InvoiceRevision(models.Model):
    """Append-only payable revisions and separate refund-linked credit documents."""
    import uuid
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    invoice=models.ForeignKey('billing.Invoice',on_delete=models.PROTECT,related_name='documents')
    kind=models.CharField(max_length=12,choices=[('invoice','Invoice'),('credit_note','Credit note')])
    sequence=models.PositiveIntegerField()
    refund=models.OneToOneField('billing.Refund',null=True,on_delete=models.PROTECT,related_name='credit_document')
    number=models.CharField(max_length=100)
    amount_minor=models.PositiveBigIntegerField()
    currency=models.CharField(max_length=3)
    snapshot=models.JSONField()
    snapshot_sha256=models.CharField(max_length=64)
    storage_key=models.CharField(max_length=512,null=True,unique=True)
    document_sha256=models.CharField(max_length=64,null=True)
    bytes=models.PositiveBigIntegerField(null=True)
    issuer_version=models.CharField(max_length=120)
    approved_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.PROTECT,related_name='+')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_invoice_revision'
        permissions=[('issue_financial_document','Can issue exact finance-approved invoice and credit-note documents')]
        constraints=[models.UniqueConstraint(fields=['invoice','sequence'],name='maison_financial_doc_sequence'),models.UniqueConstraint(fields=['number'],condition=Q(kind='credit_note'),name='maison_credit_note_number_unique'),
            models.CheckConstraint(condition=Q(kind='invoice',refund__isnull=True)|Q(kind='credit_note',refund__isnull=False),name='maison_financial_doc_kind'),
            models.CheckConstraint(condition=Q(amount_minor__gt=0,sequence__gt=0),name='maison_financial_doc_positive'),
            models.CheckConstraint(condition=Q(storage_key__isnull=True,document_sha256__isnull=True,bytes__isnull=True)|Q(storage_key__isnull=False,document_sha256__isnull=False,bytes__gt=0),name='maison_financial_doc_artifact')]
    def save(self,*args,**kwargs):
        if type(self).objects.filter(pk=self.pk).exists():raise ValidationError('Issued financial document revisions are immutable.')
        super().save(*args,**kwargs)


class FinanceNumberSequence(models.Model):
    issuer_key=models.CharField(max_length=64)
    policy_version=models.CharField(max_length=120)
    kind=models.CharField(max_length=12)
    fiscal_year=models.CharField(max_length=16)
    next_number=models.PositiveBigIntegerField(default=1)
    class Meta:
        db_table='maison_finance_number_sequence'
        constraints=[models.UniqueConstraint(fields=['issuer_key','policy_version','kind','fiscal_year'],name='maison_finance_sequence_identity'),models.CheckConstraint(condition=Q(next_number__gt=0),name='maison_finance_sequence_positive')]
