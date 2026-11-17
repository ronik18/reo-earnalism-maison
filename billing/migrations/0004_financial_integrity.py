from django.db import migrations

SQL=r'''
CREATE FUNCTION maison_refund_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE captured bigint; payment_currency text; reserved bigint;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'refund financial history cannot be deleted' USING ERRCODE='23514'; END IF;
  SELECT amount_minor,currency INTO captured,payment_currency FROM maison_payment WHERE id=NEW.payment_id FOR UPDATE;
  IF NEW.currency IS DISTINCT FROM payment_currency OR NEW.proposed_amount_minor<=0 OR NEW.proposed_amount_minor>captured THEN
    RAISE EXCEPTION 'refund proposal exceeds captured funds or currency differs' USING ERRCODE='23514';
  END IF;
  IF TG_OP='UPDATE' THEN
    IF (NEW.payment_id,NEW.proposed_amount_minor,NEW.currency) IS DISTINCT FROM (OLD.payment_id,OLD.proposed_amount_minor,OLD.currency) THEN
      RAISE EXCEPTION 'refund proposal identity is immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.amount_minor IS DISTINCT FROM OLD.amount_minor AND NOT(OLD.status='requested' AND NEW.status='approved') THEN
      RAISE EXCEPTION 'refund amount changes only on first approval' USING ERRCODE='23514';
    END IF;
    IF OLD.status='processed' AND NEW IS DISTINCT FROM OLD THEN
      RAISE EXCEPTION 'processed refund is immutable' USING ERRCODE='23514';
    END IF;
    IF NEW.version<=OLD.version THEN NEW.version:=OLD.version+1; END IF;
  END IF;
  IF NEW.status IN('approved','submitted','pending','processed') THEN
    IF NEW.amount_minor IS NULL OR NEW.amount_minor<=0 OR NEW.amount_minor>NEW.proposed_amount_minor OR NEW.approved_by_id IS NULL THEN
      RAISE EXCEPTION 'approved refund requires one bounded amount and approver' USING ERRCODE='23514';
    END IF;
    SELECT COALESCE(SUM(amount_minor),0) INTO reserved FROM maison_refund
      WHERE payment_id=NEW.payment_id AND id<>NEW.id AND status IN('approved','submitted','pending','processed');
    IF reserved+NEW.amount_minor>captured THEN
      RAISE EXCEPTION 'refund reservations exceed captured payment' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER maison_refund_guard BEFORE INSERT OR UPDATE OR DELETE ON maison_refund FOR EACH ROW EXECUTE FUNCTION maison_refund_guard();

CREATE FUNCTION maison_payment_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'payment financial history cannot be deleted' USING ERRCODE='23514'; END IF;
  IF (NEW.order_id,NEW.provider,NEW.provider_payment_id,NEW.amount_minor,NEW.currency,NEW.captured_at,NEW.verification_source,NEW.evidence_sha256)
     IS DISTINCT FROM (OLD.order_id,OLD.provider,OLD.provider_payment_id,OLD.amount_minor,OLD.currency,OLD.captured_at,OLD.verification_source,OLD.evidence_sha256) THEN
    RAISE EXCEPTION 'captured payment identity is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.version<=OLD.version THEN NEW.version:=OLD.version+1; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER maison_payment_identity_guard BEFORE UPDATE OR DELETE ON maison_payment FOR EACH ROW EXECUTE FUNCTION maison_payment_identity_guard();

CREATE FUNCTION maison_order_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'order financial history cannot be deleted' USING ERRCODE='23514'; END IF;
  IF (NEW.user_id,NEW.offer_id,NEW.operation_id,NEW.request_sha256,NEW.total_minor,NEW.currency,NEW.offer_snapshot,NEW.test_only)
     IS DISTINCT FROM (OLD.user_id,OLD.offer_id,OLD.operation_id,OLD.request_sha256,OLD.total_minor,OLD.currency,OLD.offer_snapshot,OLD.test_only) THEN
    RAISE EXCEPTION 'ordered money, actor and terms are immutable' USING ERRCODE='23514';
  END IF;
  IF OLD.provider_order_id IS NOT NULL AND NEW.provider_order_id IS DISTINCT FROM OLD.provider_order_id THEN
    RAISE EXCEPTION 'provider order reference is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.version<=OLD.version THEN NEW.version:=OLD.version+1; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER maison_order_snapshot_guard BEFORE UPDATE OR DELETE ON maison_order FOR EACH ROW EXECUTE FUNCTION maison_order_snapshot_guard();

CREATE FUNCTION maison_invoice_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'issued invoice snapshot is immutable' USING ERRCODE='23514'; END $$;
CREATE TRIGGER maison_invoice_immutable_guard BEFORE UPDATE OR DELETE ON maison_invoice FOR EACH ROW EXECUTE FUNCTION maison_invoice_immutable_guard();
'''
REVERSE='''
DROP TRIGGER maison_invoice_immutable_guard ON maison_invoice;
DROP FUNCTION maison_invoice_immutable_guard();
DROP TRIGGER maison_order_snapshot_guard ON maison_order;
DROP FUNCTION maison_order_snapshot_guard();
DROP TRIGGER maison_payment_identity_guard ON maison_payment;
DROP FUNCTION maison_payment_identity_guard();
DROP TRIGGER maison_refund_guard ON maison_refund;
DROP FUNCTION maison_refund_guard();
'''
class Migration(migrations.Migration):
    dependencies=[('billing','0003_refund_description_alter_legacyliability_user')]
    operations=[migrations.RunSQL(SQL,REVERSE)]
