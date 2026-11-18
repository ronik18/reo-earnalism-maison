# Current account and operating-compliance qualification

18 November 2026. The account lane began with a read-only source/configuration audit; Integration Lane subsequently completed the explicitly authorized two-message HTTPS test on an owned synthetic account. No DNS modification or book publication occurred. This lane prepared additive bilingual notice views/templates and focused tests, alongside this document and its [sanitized evidence](evidence/account-compliance-current.json). Integration Lane owns shared route/footer wiring and deployment.

## Account email: production HTTPS qualification passed

The profile uses `PUBLIC_BASE_URL=https://maison.theearnalism.com`, SMTP `smtp.gmail.com:465` with SSL, and approved sender `sales@reoenterprise.org`. No credential values are retained here. The Integration Lane should verify the deployed encrypted environment agrees before sending. The only authorized test recipient remains `ronik18@gmail.com`.

`accounts/email_delivery.py` constructs links from the fixed configured base, not incoming Host: `/auth/verify/` and `/auth/reset/`, with bounded safe return paths. Verification expires after86400seconds and reset after1800seconds. Existing [SMTP journey evidence](evidence/smtp-account-journeys.json) already demonstrates inbox receipt, SPF/DKIM passes, nonconsuming landing GET, confirmation/replay rejection, old-session/device invalidation and new-password login. Those tests used an isolated local account and explicitly do not qualify production HTTPS links.

Actual production HTTPS qualification now passed:36 checks, exactly two SMTP submissions and both messages received in the approved inbox. Verification/reset landing, confirmation/replay, old-session/password rejection and new login passed; the owned synthetic member was deactivated and sessions revoked. SPF/DKIM passed; DMARC was not reported. See [production evidence](evidence/https-email-qualification.json). No further email sends are required to repeat unchanged evidence.

## Sender-domain policy

Read-only DNS shows `reoenterprise.org` SPF `v=spf1 include:_spf.google.com ~all` and MX `1 smtp.google.com`. `_dmarc.reoenterprise.org` returned no TXT answer in this bounded lookup. Prior actual received mail passed SPF and DKIM; DMARC was not reported. No selector was guessed and no DNS change is proposed as already approved.

Review Authentication-Results on the next actual messages for SPF/DKIM domain alignment. Google recommends SPF, DKIM and DMARC; additional bulk-sender obligations depend on actual traffic. A monitoring DMARC proposal may be useful after identifying the authorized sender inventory/report mailbox, but absent DMARC is not being invented into a blanket low-volume transactional-mail legal blocker. Never add `p=reject` blindly or alter the unrelated preserved `theearnalism.com` mail records. [Google sender guidelines](https://support.google.com/mail/answer/81126)

## Operating compliance: concrete implementation gaps

No dedicated public privacy-notice or terms routes/templates were found in the initial audited source. Additive qualification drafts are now prepared in web/legal.py and templates/web/privacy.html, terms.html and contact.html; they are not final accepted disclosures. Backend contact, preferences/consent, export and deletion APIs exist; these do not supply the missing public disclosures. The runtime contract historically left retention approval pending; the owner explicitly approved the proposed cleanup windows on 19 November 2026. Approval is not proof of actual cleanup execution. Export artifacts have a seven-day default expiry and cleanup logic, but expiry alone does not prove physical cleanup or complete enforcement across account records, email/outbox, audit/rate data, support, backups or retained financial obligations.

Prepare simple public EN/BN privacy/terms pages and discoverable contact using the existing template approach. Before final copy, obtain or verify actual controller details for Reo Enterprise, India; valid correspondence/grievance contact, purpose/legal bases, necessary versus optional processing, provider recipients/regions, transfer arrangements, retention/deletion criteria, account rights/request route, age/children scope and effective/version dates. Do not invent an address, claim an executed provider DPA/SCC or promise immediate erasure from immutable backups. GDPR Article13 is a concrete disclosure reference for applicable European activity, and ChapterV governs applicable international transfers; this audit does not assert the law is identical across all regions. [Official GDPR text](https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng/)

The simplest completion is one accurate disclosure/data map/retention schedule using existing Render/Neon/R2/Google configurations, plus the existing rights-request workflow—no new compliance service or architecture is required. Production export/deletion processing and scheduled cleanup need actual execution evidence before public claims of completed erasure or response service levels.

## Region policy and launch scope

`contracts/publication-policy.json` is the authority:47 active regions; AE/Mainland CN and pending jurisdictions excluded. Every offered exact edition/format/action must pass the complete active whitelist. Original-text public-domain analysis alone does not clear cover artwork, edition materials or distribution obligations, and copyright clearance does not establish platform privacy/consumer compliance. The Selfish Giant remains draft; this audit grants no publication clearance.

Reader-only qualification does not amend approved P0. Payments, audio and offline remaining disabled prevents unsupported claims while their approved acceptance work remains open. A smaller launch scope requires owner approval under `docs/APPROVED_BASELINE.md`; it is not automatically waived by this audit.

## Integration priorities

1. Reuse the completed production HTTPS verification/reset receipt and explicit action evidence; do not send repeat tests unnecessarily.
2. Keep accurate public privacy/terms/contact disclosure and implement the now owner-approved cleanup windows; the prepared additive pages explicitly identify remaining facts rather than invent them.
3. Verify processor/transfer arrangements and applicable operating requirements against actual enabled collection and the47-region target. Keep exact-title publication evidence as a separate gate.
4. Retain remaining approved P0/operational/device work in the consolidated checklist. DMARC enforcement escalation, marketing/bulk-mail tooling and optional third-party compliance products are not prerequisites invented by this review.

## Local notice validation

Four focused tests passed in the existing Docker/PostgreSQL18 harness (`web.test_legal`,4tests,0.101s,system checks clean). Rendered EN/BN copy, all six integrated routes/footer links, private/no-store, invalid locale404 and POST405 passed. The original cloud-backed virtualenv import stalled and was gracefully cancelled; it is not a passing test result. Public deployment, production operating acceptance and owner-fact completion remain separate.

## Integration follow-up

Production HTTPS verification/reset now passed actual action/replay/session tests, with exactly two messages received in the approved inbox and SPF/DKIM pass; see `evidence/https-email-qualification.json`. DMARC was not reported; no DNS change was made. The dedicated synthetic account was deactivated and its sessions revoked.

The optional support outbox destination was not exposed through Django settings. Added an explicit SUPPORT_EMAIL setting; the new Contact notice uses its mailto fallback and does not display a nonfunctional embedded form when this destination is unset. No support test message was sent, and configuration/maintenance delivery remains an operator prerequisite.

## Support configuration follow-up

Five focused local notice tests pass (0.101s, clean system checks), including the form absent when SUPPORT_EMAIL is unset and present when configured, while the approved mailbox mailto remains available. No support test email was sent. Runtime support destination/configuration and any actual support-submission acceptance remain pending; the qualification contact page does not pretend that an unconfigured form works. This does not reopen the completed account-email gate.


## Owner retention/account decision, 19 November 2026

The owner approved the cleanup windows in [the schedule](RETENTION_AND_AGE_POLICY_REVIEW.md) and declined the proposed guardian/independent-child-account additions (“Not needed at all”). No new child-account flow or age restriction is authorized. This is not a waiver of applicable obligations or a global child-data compliance claim, and the declined feature choice is not an isolated-rollout blocker.

Use existing bounded maintenance for eligible account/action/session/replay cleanup, with PostgreSQL tests and separate actual execution/scheduling evidence. Do not describe token expiry as physical erasure. Preserve pending/uncertain submissions, used accounts, active sessions, valid35-day receipts, financial/legal obligations and the approved backup design.

The 30-day ordinary-log,90-day security/audit and90-day-after-resolution support windows are approved policy but not automatically implemented by their approval. App logs are provider stdout; provider retention requires readback. The contact outbox has no case-resolution lifecycle, and SMTP `done` is not resolution. AuditEvent combines routine security outcomes with publication, rights, commerce, consent and privacy evidence and has no incident/hold lifecycle; no blanket audit-table deletion is qualified. Avoid a new support/logging service merely to represent these remaining operator/provider facts. Keep their actual acceptance in the consolidated checklist without claiming it is complete.

This documentation update performs no live deletion, email send, provider/DNS change, paid provisioning, book publication or legacy-platform modification.

## Retention implementation acceptance,19November2026

The subsequent [bounded cleanup](RETENTION_IMPLEMENTATION.md) is now deployed on isolated Maison and manually qualified against its existing Neon database:12 expired devices/5 expired sessions removed, repeat0, active accounts/sessions/preferences/audit/billing and draft-book/assets preserved.256 backend/28 frontend exact-source CI checks passed. This supersedes the earlier implementation-in-progress status only for the tested database categories. Recurring execution, provider-log retention, actual support-resolution retention and eligible audit/incident handling remain explicit acceptance items; no blanket policy-completion or global legal-clearance claim.
