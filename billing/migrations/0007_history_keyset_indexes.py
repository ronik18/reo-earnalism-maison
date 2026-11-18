from django.db import migrations,models
class Migration(migrations.Migration):
    dependencies=[('billing','0006_invoice_artifact')]
    operations=[migrations.AddIndex(model_name='subscription',index=models.Index(fields=['user','-created_at','-id'],name='maison_sub_keyset_idx')),migrations.AddIndex(model_name='mandate',index=models.Index(fields=['user','-created_at','-id'],name='maison_mandate_keyset_idx')),migrations.AddIndex(model_name='order',index=models.Index(fields=['user','-created_at','-id'],name='maison_order_keyset_idx')),migrations.AddIndex(model_name='invoice',index=models.Index(fields=['-issued_at','-id'],name='maison_invoice_keyset_idx'))]
