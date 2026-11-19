# Isolated Maison free-access rollout — 19 November 2026

The owner instructed that Maison be free for every user in the approved territories, with planned Earnalism Pass values struck through. This changes the current isolated commercial rollout; it does not publish a title, alter the active publication whitelist, or qualify future paid billing.

## Customer behavior

`MAISON_FREE_ACCESS=true` enables free access for verified members to eligible current released editions and learning. Existing territory, publication, rights, format, account and device controls remain authoritative. Draft staff review remains private and MFA-protected; free access cannot reveal draft editions or override denied rights. Offline licenses still use the existing bounded rights/device policy.

The Pass page shows **Free** as the actual price. INR99/month and INR999/year are clearly labelled planned reference amounts and struck through. They are not prior selling prices, discounts, approved financial offers, or automatic future subscriptions. A future paid plan requires a separate explicit choice. New monetary-order creation and untouched provider-create jobs are blocked before merchant calls. Existing historical status/reconciliation, invoices/credit notes and cancellation/revocation controls remain intact. No zero-price financial records are manufactured.

## Pricing analysis and limits

The current official Storytel India page advertises entry pricing from INR149/month and400,000+stories: https://www.storytel.com/in . INR99 is approximately34%below that entry reference, chosen as a conceptual lower position for Maison's small pre-release catalog. INR999/year is INR83.25/month in arithmetic terms. No customer conversion, willingness-to-pay or revenue dataset was available; these are planning estimates, not statistically validated commercial prices.

Everand's official help page, updated17August2026, lists USD11.99/month for its Standard plan, one monthly unlock, and1.5M+titles: https://support.scribd.com/hc/en-us/articles/40678839226644-Everand-plans-Standard-Plus-and-Deluxe . Its market/currency/catalog differ, so it is contextual evidence only, not a like-for-like price comparison. Both references were checked19November2026.

## Financial integrity

A local PostgreSQL regression reproduced an approval-version rotation repeating the same visible fiscal invoice number. Migration0011 adds explicit prefix-based counter identity; new sequences continue across approval-version changes. Legacy counters remain unchanged and provide a conservative high-water floor. No legacy prefix is invented and no financial history is removed. Invalid numbering versions now fail before reservation. All financial writers must use the new schema/code before paid activity is ever re-enabled; reverse migration must not delete history to force compatibility.

Production SELECT-only preflight found zero live active offers, pending live orders, nonterminal live subscriptions, authorized/pending live mandates, financial sequence rows, invoices or credit notes. No existing financial cohort needs cancellation or data migration. No live charge, refund, mandate authorization/revocation or commercial document issuance is required for this free path. Future merchant activation retains its separate real-provider and exact finance-policy acceptance requirements.

## Preserved scope

The Selfish Giant remains draft with null live pointer,32paragraphs,version42 and the original manuscript hash. Legacy application/data/DNS and infrastructure plans are unchanged. Physical Android/iOS UAT remains owner-deferred and non-blocking. The free flag has a false default for compatibility; the isolated deployment explicitly enables it.
