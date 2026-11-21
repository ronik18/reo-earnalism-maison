# Provider-independent child authorization —21November2026

## Scope decision

No Epic organization, KWS setup, private inquiry, keys, paid method or new agreement is required for this review. The owner explicitly asks to skip unnecessary provider setup. Earlier organization/setup approval candidates are superseded as next actions, not executed. The exact private inquiry was approved but could not be submitted without organization membership; it remains unsent and is now deferred. Do not ask for that organization again as a general release prerequisite.

An Epic developer organization is an administrative workspace, not incorporation of a company. It became relevant solely because EOS private support denied access without membership and KWS provisioning uses that workspace. Neither requirement is an Earnalism legal obligation or an accepted dependency of its current free-access operation.

## Public technical questions resolved

[PV flow](https://dev.epicgames.com/docs/kids-web-services/parent-verification-service/pv-service-flow): provider verification concerns adult status; consent management and required direct notices remain the developer’s responsibility. A new vendor therefore would not by itself fix collection sequencing or account authorization. Conversely, do not impose an invented universal biological-parent proof beyond the applicable law/method’s actual assurance requirement. The separate question is whether the chosen lawful process authorizes this child, purpose and account.

[Integration](https://dev.epicgames.com/docs/kids-web-services/parent-verification-service/pv-service-integration) and [webhook](https://dev.epicgames.com/docs/kids-web-services/parent-verification-service/set-up/pv-service-configure-webhook) specify API credentials, distinct TEST/production secrets and raw-body HMAC-SHA256 verification over timestamp/body; key rotation can yield multiple signatures. This resolves the earlier public-specification unknown, but is not a reason to build an unused adapter. No provider call or secret is required to understand the specification.

[Verification response](https://dev.epicgames.com/docs/kids-web-services/parent-verification-service/set-up/pv-service-configure-verification-response): signed status/external-payload and transaction/time information permit application binding and authenticity checks if KWS is ever chosen. A browser redirect or Boolean is insufficient by itself. No deployed callback or real-provider acceptance is claimed. Existing47-code technical availability is retained separately from national legality.

## Smallest implementation plan to qualify

1. Identify the country/purpose’s actual need for consent or representative authority; distinguish it from contractual capacity and content suitability. Use a supported direct, proportionate process before assuming a card/ID/face vendor is necessary. No single worldwide age or identity-document rule is established.
2. Reuse the existing request/review/claim/withdraw/rights foundation. Add the selected method’s exact notice/permission record and bind the eventual child account to the same permitted prospective subject and guardian operation. A digest is integrity evidence, not a substitute for the underlying permission. Avoid collecting a child email/password first just to choose the route.
3. Cover ordinary registration and Google consistently; shared API enforcement must match the single reader journey. Collect only the minimum age/capacity facts justified for the applicable process. Do not add a DOB database, age ban or different language-specific reader journey to simplify the checklist.
4. For a direct-consent method, use the regulator-supported sequence and assurance level. Examples are in the regional followups; a signed form or email response is not a universal47-country method. Record notice version, purpose, exact account/subject binding, method-specific assurance, decision, expiry/withdrawal and minimum evidence custody. Reuse existing staff MFA/ownership controls, not a new provider dashboard.
5. Prepare one worked synthetic acceptance case for that selected lawful method: notice before covered collection; correct claimant/child/purpose; wrong-subject, replay and withdrawal rejection; expiry/recovery; rights scope and transition to independent capacity. Reuse unchanged tests. Do not label an arbitrary manual fixture a legally accepted method or production verification.

## Limits requiring actual completion

Technical subject binding, all-enrollment routing, applicable translated notices/parental controls and independent-capacity transition remain implementation work after the exact national design is resolved. Public documentation cannot create a guardian’s authorization, sign a recipient instrument, appoint a representative, file an actual notice, prove domestic storage or exercise a provider. Those facts remain distinct from research; source references and owner approval cannot replace them.

No runtime guardrail, migration, country removal or new provider setup is added here. Existing production guardian policy stays unchanged; this document is not public activation. Physical Android/iOS/OS-specific UAT remains deferred, untested and non-blocking. Book draft, legacy source/data/DNS and current isolated runtime are unchanged.
