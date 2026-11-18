from django.db import migrations,models
class Migration(migrations.Migration):
    dependencies=[('reader','0003_download_license')]
    operations=[migrations.AddIndex(model_name=model,index=models.Index(fields=fields,name=name)) for model,fields,name in [
      ('progress',['user','-updated_at','-id'],'maison_progress_keyset_idx'),
      ('completion',['user','-updated_at','-id'],'maison_completion_keyset_idx'),
      ('saveditem',['user','-created_at','-id'],'maison_saved_keyset_idx'),
      ('personallist',['user','name','id'],'maison_list_keyset_idx'),
      ('annotation',['user','-created_at','-id'],'maison_annotation_keyset_idx')]]
