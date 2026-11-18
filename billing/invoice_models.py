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
