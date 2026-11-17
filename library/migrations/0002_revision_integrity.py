from django.db import migrations

SQL=r'''
CREATE FUNCTION maison_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.edition_id IS DISTINCT FROM NEW.edition_id THEN
    RAISE EXCEPTION 'revision edition is immutable' USING ERRCODE='23514';
  END IF;
  IF OLD.state <> 'draft' AND NEW.state='draft' THEN
    RAISE EXCEPTION 'frozen revisions cannot return to draft' USING ERRCODE='23514';
  END IF;
  IF OLD.state <> 'draft' AND
    (NEW.title,NEW.description,NEW.content_sha256,NEW.anchor_revision,NEW.access_policy,NEW.download_policy,NEW.preview)
    IS DISTINCT FROM
    (OLD.title,OLD.description,OLD.content_sha256,OLD.anchor_revision,OLD.access_policy,OLD.download_policy,OLD.preview) THEN
    RAISE EXCEPTION 'frozen revision content requires a new revision' USING ERRCODE='23514';
  END IF;
  IF NEW.version <= OLD.version THEN NEW.version := OLD.version+1; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER maison_revision_guard BEFORE UPDATE ON maison_edition_revision
FOR EACH ROW EXECUTE FUNCTION maison_revision_guard();

CREATE FUNCTION maison_content_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_revision uuid; new_revision uuid; candidate record; unit_revision uuid;
BEGIN
  IF TG_TABLE_NAME='maison_paragraph_anchor' THEN
    IF TG_OP <> 'INSERT' THEN SELECT revision_id INTO old_revision FROM maison_unit WHERE id=OLD.unit_id; END IF;
    IF TG_OP <> 'DELETE' THEN SELECT revision_id INTO new_revision FROM maison_unit WHERE id=NEW.unit_id; END IF;
  ELSE
    IF TG_OP <> 'INSERT' THEN old_revision := OLD.revision_id; END IF;
    IF TG_OP <> 'DELETE' THEN new_revision := NEW.revision_id; END IF;
  END IF;
  FOR candidate IN SELECT id,state FROM maison_edition_revision
    WHERE id IN (old_revision,new_revision) ORDER BY id FOR UPDATE LOOP
    IF candidate.state <> 'draft' THEN
      RAISE EXCEPTION 'frozen revision child cannot change' USING ERRCODE='23514';
    END IF;
  END LOOP;
  IF TG_TABLE_NAME='maison_asset' AND TG_OP <> 'DELETE' THEN
    IF NEW.unit_id IS NOT NULL THEN
      SELECT revision_id INTO unit_revision FROM maison_unit WHERE id=NEW.unit_id;
      IF unit_revision IS DISTINCT FROM NEW.revision_id THEN
        RAISE EXCEPTION 'asset unit belongs to another revision' USING ERRCODE='23514';
      END IF;
    END IF;
    IF NEW.storage_key NOT LIKE 'revisions/' || NEW.revision_id::text || '/%' THEN
      RAISE EXCEPTION 'asset locator is not revision scoped' USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE' AND NEW.version <= OLD.version THEN NEW.version := OLD.version+1; END IF;
  END IF;
  UPDATE maison_edition_revision SET version=version+1 WHERE id IN(old_revision,new_revision);
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER maison_unit_guard BEFORE INSERT OR UPDATE OR DELETE ON maison_unit FOR EACH ROW EXECUTE FUNCTION maison_content_guard();
CREATE TRIGGER maison_paragraph_guard BEFORE INSERT OR UPDATE OR DELETE ON maison_paragraph_anchor FOR EACH ROW EXECUTE FUNCTION maison_content_guard();
CREATE TRIGGER maison_asset_guard BEFORE INSERT OR UPDATE OR DELETE ON maison_asset FOR EACH ROW EXECUTE FUNCTION maison_content_guard();
CREATE TRIGGER maison_timing_guard BEFORE INSERT OR UPDATE OR DELETE ON maison_timing_map FOR EACH ROW EXECUTE FUNCTION maison_content_guard();

CREATE FUNCTION maison_edition_live_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_id uuid; revision_state text;
BEGIN
  IF NEW.live_revision_id IS NOT NULL THEN
    SELECT edition_id,state INTO owner_id,revision_state FROM maison_edition_revision WHERE id=NEW.live_revision_id;
    IF owner_id IS DISTINCT FROM NEW.id OR revision_state IS DISTINCT FROM 'live' THEN
      RAISE EXCEPTION 'live revision must belong to edition and be live' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP='UPDATE' AND NEW.version <= OLD.version THEN NEW.version := OLD.version+1; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER maison_edition_live_guard BEFORE INSERT OR UPDATE ON maison_edition FOR EACH ROW EXECUTE FUNCTION maison_edition_live_guard();
'''

REVERSE='''
DROP TRIGGER maison_edition_live_guard ON maison_edition;
DROP FUNCTION maison_edition_live_guard();
DROP TRIGGER maison_timing_guard ON maison_timing_map;
DROP TRIGGER maison_asset_guard ON maison_asset;
DROP TRIGGER maison_paragraph_guard ON maison_paragraph_anchor;
DROP TRIGGER maison_unit_guard ON maison_unit;
DROP FUNCTION maison_content_guard();
DROP TRIGGER maison_revision_guard ON maison_edition_revision;
DROP FUNCTION maison_revision_guard();
'''

class Migration(migrations.Migration):
    dependencies=[('library','0001_initial')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
