BEGIN;
--
-- Create model GuardianAuthorization
--
CREATE TABLE "maison_guardian_authorization" ("id" uuid NOT NULL PRIMARY KEY, "jurisdiction" varchar(2) NOT NULL, "purpose" varchar(24) NOT NULL, "notice_version" varchar(64) NOT NULL, "method" varchar(64) NOT NULL, "policy_sha256" varchar(64) NOT NULL, "evidence_sha256" varchar(64) NOT NULL, "status" varchar(12) NOT NULL, "created_at" timestamp with time zone NOT NULL, "reviewed_at" timestamp with time zone NULL, "expires_at" timestamp with time zone NOT NULL, "withdrawn_at" timestamp with time zone NULL, "version" bigint NOT NULL CHECK ("version" >= 0), "child_id" bigint NOT NULL, "guardian_id" bigint NOT NULL, "reviewer_id" bigint NULL, CONSTRAINT "maison_guardian_distinct_subjects" CHECK (NOT ("child_id" = ("guardian_id"))), CONSTRAINT "maison_guardian_independent_review" CHECK ((NOT ("reviewer_id" = ("guardian_id") AND "reviewer_id" IS NOT NULL) AND NOT ("reviewer_id" = ("child_id") AND "reviewer_id" IS NOT NULL))), CONSTRAINT "maison_guardian_status" CHECK ("status" IN ('pending', 'authorized', 'rejected', 'withdrawn')), CONSTRAINT "maison_guardian_version" CHECK ("version" >= 1), CONSTRAINT "maison_guardian_review_evidence" CHECK ((NOT ("status" = 'authorized') OR ("reviewed_at" IS NOT NULL AND NOT ("evidence_sha256" = '')))));
ALTER TABLE "maison_guardian_authorization" ADD CONSTRAINT "maison_guardian_authorization_child_id_7bfa865b_fk_auth_user_id" FOREIGN KEY ("child_id") REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "maison_guardian_authorization" ADD CONSTRAINT "maison_guardian_auth_guardian_id_ce49e27a_fk_auth_user" FOREIGN KEY ("guardian_id") REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "maison_guardian_authorization" ADD CONSTRAINT "maison_guardian_auth_reviewer_id_03e05320_fk_auth_user" FOREIGN KEY ("reviewer_id") REFERENCES "auth_user" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "maison_guardian_authorization_child_id_7bfa865b" ON "maison_guardian_authorization" ("child_id");
CREATE INDEX "maison_guardian_authorization_guardian_id_ce49e27a" ON "maison_guardian_authorization" ("guardian_id");
CREATE INDEX "maison_guardian_authorization_reviewer_id_03e05320" ON "maison_guardian_authorization" ("reviewer_id");
COMMIT;
