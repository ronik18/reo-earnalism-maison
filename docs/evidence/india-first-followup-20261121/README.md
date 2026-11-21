# India-first launch follow-up —21November2026

The owner requested any remaining India-first gaps to be closed and the isolated release tested/pushed/deployed/validated. Physical Android/iOS/OS-specific UAT remains deferred, untested and non-blocking. No provider setup, new agreement/spend, schema migration, book publication or legacy/DNS change is included.

## Confirmed defects and narrow corrections

1. **Independent reader session revoked by former guardian.** A real local PostgreSQL reproduction on165edc9 completed independent-capacity transition and a fresh sign-in, then submitted another withdrawal against the former parent's historical permission. The old implementation returned200 and revoked the now-independent reader's session. Withdrawal is now a no-op for an already-withdrawn permission, and an account-processing withdrawal can revoke only a currently managed child's sessions. Existing current-version checks and operation receipts remain. Parent deletion already filters currently managed children; no change is made to that path merely for completeness.
2. **Google recovery loses the reader destination.** The native error helper used saved-state locale but dropped its safe destination, query and fragment. The sign-in page's new-account recovery link also dropped it. Recovery now retains an encoded same-origin path through retry and signup, with external/invalid destinations safely falling back. OAuth tokens, private failure details and state are not included. No provider call is needed to reproduce or verify the helper.

3. **Renewal/independence PostgreSQL deadlock.** Event-coordinated real PostgreSQL execution reproduced a503 when independence held the child and commit needed a deferred foreign-key lock on the guardian, while renewal held the guardian and waited on the child. Independence now takes existing guardian/child account locks in ascending primary-key order before changing authority. Tests cover both operation orderings and current authority after they complete. No distributed lock, retry queue, new schema or provider is introduced.

The review was bounded to actual changed-flow correctness/security. No additional required UI redesign, verifier, stronger identity claim or new operating gate was inferred. Current direct electronic permission remains an authenticated declaration-based India method, not independent identity/custody or future DPDP certification.

## Acceptance and release handling

Use focused PostgreSQL tests for the reproduced regression, current managed withdrawal, independence and Google recovery; native rendered-link tests for encoded destinations and external rejection; then exact-head CI and deployed affected-browser/read-only invariant checks. Reuse the existing unchanged853actual-image/binary-tool,202immutable-asset and broader India acceptance within its recorded scope; do not rerun unrelated production/mail/title workflows or claim they newly executed. The static release should remaina9865d304bd665301cdf337e0e6a7f7de0e51f5731ac6afe604ace6b18c240f6 because only Python and rendered HTML links change.

Final results, exact source/commit/static binding and book/legacy preservation will be recorded after execution. Nothing pending is labeledPASS here.

## Completed predeployment acceptance

[Receipt](predeploy-validation.json):107targeted actual PostgreSQL checksPASS97.419seconds, including both coordinated renewal/independence orderings, historical guardian withdrawal, current managed withdrawal, former-parent deletion, Google/OIDC and guardian/retention/privacy regressions.16rendered web checksPASS. The final image matches285source/contract/static files exactly; system/schema checksPASS and its202-file static manifest equals the existing qualifieda9865d3release. No asset upload or environment change is required. Exact-head CI, deployment and affected live-browser checks remain pending until the final executed receipt.

## Executed isolated rollout

[Final receipt](release-receipt.json): PR41merged; runtime516179fLive on web/maintenance/archive. Exacthead/merge/mainCI PASS:861backend tests with22unchangedbinarytoolskips covered by retained actual-image acceptance,37client and12voiceplan PASS.107focusedPG and16web checksPASS. Actual18Chromium/Firefox/virtual-phone recovery checks plus3nativeSafari checksPASS; existing202-file staticrelease unchanged and live references match. Newbuildscheduledmaintenance/clearleasePASS. Publichealth/catalog200, draft404; signedoutprivateendpoints401/no-store. No newproductionlogin/childrecords were created; previousauthenticatedoperator evidence is reused only forunchangedpaths. Draft/version42/hash/32paragraphs, zero finance/enrollment, schema and legacyHTTPS200 remain unchanged. No migration, newprovider/agreement, paidresource, assetupload/environmentedit, extraexport or legacy/DNS write. PhysicalUAT stays deferred and non-blocking.
