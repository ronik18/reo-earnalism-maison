# Privacy reconciliation before reopening restored Maison

The qualified path uses the existing privacy workers and recorded holds. An older database/private-media snapshot can reintroduce personal records and exports removed after that snapshot. It cannot independently identify later deletions or holds. Keep the restored target isolated and writes closed until current, authenticated instructions have been reconciled.

Before a planned restore, the operator retains a narrowly scoped private instruction set from current confirmed privacy deletion requests and applicable holds: exact member public IDs, request IDs/status, relevant times and reviewed hold instructions. Protect it with the established owner-controlled encrypted custody path; do not put personal manifests,dumps or export URLs in Git/chat. A disaster that loses the current instructions remains an explicit recovery gap, not a passed automatic journal/PITR claim.

After restoring into a distinct target:

1. Check its identity and the snapshot/schema/content manifest; do not reconnect traffic yet.
2. Reapply current holds first, through the existing recorded-hold semantics. Never infer a hold is released merely from age.
3. Reapply confirmed eligible deletions through the existing authenticated worker/service path for those exact members. Preserve pending/uncertain finance and protected artifacts; inspect blocked results rather than bypassing them.
4. Verify erased personal rows and exact private exports, revoked sessions/licenses, retained minimal tombstones/obligations,held content and unrelated manuscript hashes. A deleted DB row does not prove a copied export is gone.
5. Repeat the exact reapplication to prove idempotency, review remaining pending work, then authorize reopening writes through the authoritative release lane.

## Actual local qualification,20November2026

An actual PostgreSQL18 dump was restored into a distinct disposable local database with its original-fixture private-media snapshot. The restore reintroduced8 personal rows and2 exports. Replaying a confirmed deletion erased4 rows/1export again; reapplying a post-snapshot hold preserved the other4rows/1export and blocked deletion with privacy_hold. One tombstone,repeat idempotent,original English/Bengali manuscript hashes unchanged. No production data dump,provider call,live restore,financial mutation or book/legacy change. [Redacted receipt](evidence/operating-release-20261120/restore-privacy-drill.json).

This qualifies operator-assisted reapplication of supported instructions. It does not claim an automatic off-database erasure journal,providerPITR,HA,disaster-loss recovery,mailbox erasure or physical-device UAT. Existing logical archive/restore acceptance remains separately preserved.
