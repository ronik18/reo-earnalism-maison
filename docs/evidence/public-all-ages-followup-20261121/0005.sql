BEGIN;
--
-- Add field guardian_managed to user
--
ALTER TABLE "auth_user" ADD COLUMN "guardian_managed" boolean DEFAULT false NOT NULL;
ALTER TABLE "auth_user" ALTER COLUMN "guardian_managed" DROP DEFAULT;
--
-- Add field retain_until to guardianauthorization
--
ALTER TABLE "maison_guardian_authorization" ADD COLUMN "retain_until" timestamp with time zone NULL;
--
-- Add field claim_expires_at to guardianauthorization
--
ALTER TABLE "maison_guardian_authorization" ADD COLUMN "claim_expires_at" timestamp with time zone NULL;
--
-- Add field claim_sha256 to guardianauthorization
--
ALTER TABLE "maison_guardian_authorization" ADD COLUMN "claim_sha256" varchar(64) DEFAULT '' NOT NULL;
ALTER TABLE "maison_guardian_authorization" ALTER COLUMN "claim_sha256" DROP DEFAULT;
--
-- Add field claimed_at to guardianauthorization
--
ALTER TABLE "maison_guardian_authorization" ADD COLUMN "claimed_at" timestamp with time zone NULL;
--
-- Add field prospective_subject_id to guardianauthorization
--
ALTER TABLE "maison_guardian_authorization" ADD COLUMN "prospective_subject_id" uuid NULL;
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Alter field prospective_subject_id on guardianauthorization
--
ALTER TABLE "maison_guardian_authorization" ALTER COLUMN "prospective_subject_id" SET DEFAULT '79aebc263f7b409dbd6fddf6c30ee8b3'::uuid;
UPDATE "maison_guardian_authorization" SET "prospective_subject_id" = '5bdf287bea4146ba97f5e8e695034bb0'::uuid WHERE "prospective_subject_id" IS NULL; SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE "maison_guardian_authorization" ALTER COLUMN "prospective_subject_id" SET NOT NULL;
ALTER TABLE "maison_guardian_authorization" ADD CONSTRAINT "maison_guardian_authoriz_prospective_subject_id_06cfc1a9_uniq" UNIQUE ("prospective_subject_id");
ALTER TABLE "maison_guardian_authorization" ALTER COLUMN "prospective_subject_id" DROP DEFAULT;
--
-- Alter field child on guardianauthorization
--
SET CONSTRAINTS "maison_guardian_authorization_child_id_7bfa865b_fk_auth_user_id" IMMEDIATE; ALTER TABLE "maison_guardian_authorization" DROP CONSTRAINT "maison_guardian_authorization_child_id_7bfa865b_fk_auth_user_id";
ALTER TABLE "maison_guardian_authorization" ALTER COLUMN "child_id" DROP NOT NULL;
ALTER TABLE "maison_guardian_authorization" ADD CONSTRAINT "maison_guardian_authorization_child_id_7bfa865b_fk_auth_user_id" FOREIGN KEY ("child_id") REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED;
COMMIT;
