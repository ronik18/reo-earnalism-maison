# Legal follow-up — bounded US pre-consent contact route

21 November 2026; source main `93b9730`. This read-only lane advances the completed [field/source/recipient map](../neon-cap-followup-20261121/legal.md) into one concrete precollection decision. No flow, age rule, national method, notice, account, provider, spending, DNS or title state changed. All47regions remain in scope; public qualification stays OPEN.

## New source question resolved

**A narrow contact-before-consent route exists; it does not authorize ordinary account creation.** Current [16CFR312.5(c)(1)](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-312/section-312.5) permits limited collection of parent/child name or online contact information solely to deliver notice and obtain parental consent; unsuccessful collection must be deleted after a reasonable time. The rule does not prescribe a universal numerical deadline. Separately, paragraph(b)(2)(viii) allows the no-disclosure email method only with additional assurance, such as a confirmatory message after receiving consent, and revocation notice. The broader parent-verification standard still applies. A first verification email is not both notice and completed consent. These findings do not select that route or establish its applicability to Earnalism.

[16CFR312.4(c)(1)](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-312/section-312.4) supplies the direct-notice content: explain the initial contact collection where applicable; proposed child information, uses and relevant recipients; affirmative permission requirements and available separate disclosure choice; privacy-policy link; consent mechanism; and deletion if permission is not obtained in a reasonable time. The message must accurately describe the actual planned processing. A generic account-verification template cannot be assumed to contain that notice.

[16CFR312.2](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-312/section-312.2) distinguishes mixed-audience precollection/neutral age determination and includes passive tracking within collection. Its internal-operations definition restricts permitted purposes. Consequently, a parent-email exception cannot be used as a blanket approval for existing browser, account or Google processing. These eCFR pages were retrieved today and displayed title16 current through19November2026; the site identifies eCFR as authoritative but unofficial.

## Engineering inference from current source

The inspected `accounts/guardian_views.py` and `accounts/guardian.py` request path belongs to an authenticated requesting account. It does not implement an anonymous contact-only bootstrap. Its request creates prospective authority metadata, not the required purpose-specific direct parental notice. The existing claim stage collects account fields only after its technical capability checks, but those checks do not establish the national method, parent relationship or real subject identity. Ordinary signup/Google remain separate intake paths identified by the preceding source map. Guardian activation stays OFF with an empty policy map.

The smallest **design candidate for review**, not an authorized implementation, is:

| Phase | Candidate boundary / acceptance evidence |
|---|---|
| Entry decision | Establish the actual audience/ground and all intake paths first. Do not add an unapproved universal age gate, child ban or silent Google bypass. |
| Pending contact | If this US exception applies, collect only the contact actually needed to seek permission, with a short-lived opaque transaction reference. No child account/email/password/display-name/progress/profile is created under that exception. References and security metadata still require their own purpose/retention analysis. |
| Direct notice | Provide the exact information above, tied to the reviewed notice version and actual intended recipient/use map. No marketing, reading notifications or unrelated reuse of pending contact. |
| Consent and assurance | Obtain the affirmative permission and a distinct additional-assurance event required by the selected qualified method; preserve revocation. Do not infer permission from delivery, opening, mailbox login, a staff digest or an adult-verification result. |
| Claim | Bind the reviewed parent/subject/purpose to the exact account creation. Prevent normal signup/Google from becoming an alternative unreviewed child-intake path. Existing random slot/capability semantics alone do not prove the real relationship. |
| Abandonment | Propose and justify a concrete pending-contact deadline; account for mail/outbox, logs, provider copies and restore reconciliation. The rule's reasonable-time language is not a ready-made7/30day retention setting. No new cleanup window is implemented here. |

This resolves a bootstrap design option without inventing an obligation to buy a vendor or collect an ID document. It does not resolve actual audience classification, no-disclosure eligibility, provider secondary uses, parent/subject assurance or another46countries' requirements. Do not build this and a provider alternative in parallel merely to claim progress.

## Next integration decision

Review **one** named method package against the existing actual-field map: determine whether the direct no-disclosure route can satisfy the real audience, recipient and binding facts; otherwise use the already prepared provider test-onboarding route. The existence of the contact-only exception narrows the proposed intake boundary, but is not authority to alter current public registration or enable a synthetic policy. Where those factual/legal conclusions remain unsupported, retain the explicit gap and seek the exact qualified interpretation rather than fabricate a PASS. No inquiry or contract was sent/accepted by this lane. The Selfish Giant remains draft and legacy remains unchanged.
