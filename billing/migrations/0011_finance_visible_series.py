from django.db import migrations,models


class Migration(migrations.Migration):
    dependencies=[('billing','0010_mandate_identity')]
    operations=[
        migrations.AddField(model_name='financenumbersequence',name='series_prefix',field=models.CharField(max_length=12,null=True)),
        migrations.RemoveConstraint(model_name='financenumbersequence',name='maison_finance_sequence_identity'),
        migrations.AddConstraint(model_name='financenumbersequence',constraint=models.UniqueConstraint(fields=('issuer_key','policy_version','kind','fiscal_year'),condition=models.Q(series_prefix__isnull=True),name='maison_finance_sequence_identity')),
        migrations.AddConstraint(model_name='financenumbersequence',constraint=models.UniqueConstraint(fields=('issuer_key','series_prefix','kind','fiscal_year'),condition=models.Q(series_prefix__isnull=False),name='maison_finance_visible_series')),
    ]
