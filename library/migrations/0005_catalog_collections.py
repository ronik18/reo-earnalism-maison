import django.core.validators
import django.db.models.deletion
import uuid
from django.db import migrations,models


class Migration(migrations.Migration):
    dependencies=[('library','0004_alter_work_house')]
    operations=[
        migrations.CreateModel(name='CatalogCollection',fields=[('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),('slug',models.SlugField(max_length=160,unique=True,validators=[django.core.validators.RegexValidator('^[a-z0-9]+(-[a-z0-9]+)*$')])),('title_en',models.CharField(max_length=200)),('title_bn',models.CharField(max_length=200)),('description_en',models.TextField(blank=True,max_length=4000)),('description_bn',models.TextField(blank=True,max_length=4000)),('house',models.CharField(choices=[(x,x) for x in ('classics','golpo','learn','interview','series','collections')],default='collections',max_length=20)),('kind',models.CharField(choices=[(x,x) for x in ('shelf','series','author','topic')],default='shelf',max_length=12)),('published',models.BooleanField(default=False)),('version',models.PositiveBigIntegerField(default=1,editable=False)),('updated_at',models.DateTimeField(auto_now=True))],options={'db_table':'maison_catalog_collection','ordering':['slug','id'],'constraints':[models.CheckConstraint(condition=models.Q(version__gte=1),name='maison_collection_version_positive'),models.CheckConstraint(condition=models.Q(kind__in=['shelf','series','author','topic']),name='maison_collection_kind'),models.CheckConstraint(condition=models.Q(house__in=['classics','golpo','learn','interview','series','collections']),name='maison_collection_house'),models.CheckConstraint(condition=models.Q(slug__regex='^[a-z0-9]+(-[a-z0-9]+)*$'),name='maison_collection_slug')]}),
        migrations.CreateModel(name='CatalogItem',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('sort_order',models.PositiveIntegerField()),('collection',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='items',to='library.catalogcollection')),('edition',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='catalog_items',to='library.edition'))],options={'db_table':'maison_catalog_item','ordering':['sort_order','id'],'constraints':[models.UniqueConstraint(fields=('collection','edition'),name='maison_catalog_item_edition_uq'),models.UniqueConstraint(deferrable=models.Deferrable.DEFERRED,fields=('collection','sort_order'),name='maison_catalog_item_order_uq'),models.CheckConstraint(condition=models.Q(sort_order__gte=0),name='maison_catalog_item_order_positive')]}),
        migrations.RunSQL('''
CREATE FUNCTION maison_collection_version() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  NEW.version=OLD.version+1; NEW.updated_at=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER maison_collection_version BEFORE UPDATE ON maison_catalog_collection FOR EACH ROW EXECUTE FUNCTION maison_collection_version();
CREATE FUNCTION maison_catalog_item_version() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
  IF TG_OP='DELETE' THEN
    UPDATE maison_catalog_collection SET version=version+1 WHERE id=OLD.collection_id;
    RETURN OLD;
  END IF;
  UPDATE maison_catalog_collection SET version=version+1 WHERE id=NEW.collection_id;
  IF TG_OP='UPDATE' AND OLD.collection_id<>NEW.collection_id THEN
    UPDATE maison_catalog_collection SET version=version+1 WHERE id=OLD.collection_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER maison_catalog_item_version AFTER INSERT OR UPDATE OR DELETE ON maison_catalog_item FOR EACH ROW EXECUTE FUNCTION maison_catalog_item_version();
''','''DROP TRIGGER maison_catalog_item_version ON maison_catalog_item; DROP FUNCTION maison_catalog_item_version(); DROP TRIGGER maison_collection_version ON maison_catalog_collection; DROP FUNCTION maison_collection_version();'''),
    ]
