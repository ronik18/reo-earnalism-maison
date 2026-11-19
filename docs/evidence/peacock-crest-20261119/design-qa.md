# Peacock Crest — independent theme QA

**Final result: passed for the bounded theme scope below.** No remaining actionable P0/P1/P2 theme defect was observed after the implementer’s corrections and recapture. This is not an assertion that all 26 screens, all data states or provider-dependent features received full end-to-end acceptance.

Audit date: 19 November 2026. Implementation: current shared-source local preview `http://localhost:8045/en/`. Root owns integration/release. This lane changed no application source, provider state, Figma file, branch or commit. Reports/captures are under this temporary audit directory; the Integration Lane should copy selected evidence to durable storage before relying on it for release.

## Reference and comparison method

Selected style authority was the supplied 14-page Peacock Crest handoff PDF, token files and supplied SVG kit under `/tmp/maison-theme-review/peacock/`. The older Ford Gold v1.1 captures were used only for existing layout/history. Their concept copy, menu implementation and content availability do not override the current app’s real scope. No complete new Peacock app canvas screenshot was supplied, so no claim of pixel-identical recreation is made. Attachment example/prototype JavaScript was not executed.

Compared source and rendered implementation in the same visual input: [desktop comparison](comparison-desktop.jpg) and [phone comparison](comparison-phone.jpg). The desktop pair uses the same guest Home state and normalized1440×900 viewport; the phone reference includes a bezel/scaled viewport and is explicitly a hierarchy comparison. The original screenshots remain unchanged.

Checked five visual surfaces: typography, spacing/layout, colors, imagery and app copy. New styling uses the supplied motifs. Current test fixture copy and unavailable/provider-disabled states remain honest; no old prototype audio/checkout claims were imported.

## Actual browser conditions

Requested CSS viewports were confirmed using `innerWidth/innerHeight`: **1440×900**, **393×852**, **1024×768**. The available CUA surface had no IAB; the audit used a separate Chrome QA tab/session at localhost8045, leaving provider tabs untouched. Existing Chrome 90% host zoom was retained; viewport overrides were calibrated and reset at completion. Raw screenshot output includes extra density padding; `normalized/` crops preserve the actual CSS viewport and do not resize its content. These are desktop responsive emulations, not physical-device UAT. Safe-area arithmetic was source-reviewed; a physical inset was not emulated.

## Findings and closure

|Finding|Initial evidence|Small correction|Recapture|
|---|---|---|---|
|P2 missing crest in nested titles|S01 onboarding, S07 title and S12 video headings computed `::after` content/background none|Narrow `.onboarding-panel>h1`, `.title-layout>div>h1`, `.video-room>h1` crest selectors|PASS; all three render one crest. Reader/status/dialog exclusion retained.|
|P2 compact header width|Phone immersive Back33.8px and language 34.8px, despite 44px height|Minimum 44px width on browsing/immersive header links|PASS; actual CSS 44×44 subject to subpixel rounding, labels and title still fit.|
|P2 scroll box under navigation|Inherited old `min-height:calc(100vh -104px)` extended phone scroll box to y817 while bar began y770|Peacock `.web-stage{min-height:0}`|PASS; browsing stage y68.99–770.23 and bar y770.23–852.22. Immersive bottom0 retained.|

Additional preflight issues addressed by the implementer before/following initial rendering: official Phosphor icon+label tablet navigation; Settings reachability; legal/contact links inside member Settings; no leftover Ford Gold stage pseudos; Light icons/error contrast and Reader focus color.

## Rendered acceptance

- **Desktop:** final guest Home, typography, rectangular hero frame,72px ivory header,200px sidebar and main scrolling area passed. Member Reader and Learn catalog passed. Title full technical cover/actions were inspected before crest correction; the final crest was recaptured on phone.
- **Tablet:** final Home has 72px icon rail with named labels/Settings, no jali, no horizontal overflow. Search submitted `river`, result title navigation worked. Light member Home and True Black Explore were rendered; themes saved through the actual local account form. Keyboard Tab placed a visible rose focus outline on ivory-header Search.
- **Phone:** guest/member Home, Bengali sign-in and real local test-account login, title, EN/BN Reader, comfort dialog, preview boundary, onboarding first view, empty Series, SDE home, Pass with no approved offer, empty Vault, local Downloads empty/error,404 and existing P1 unavailable states rendered without horizontal overflow. Quiz answer submission returned 100/correct feedback with visible next action.
- **Reader and sheets:** plain opaque text surface and plain dialogs. Default saved 20px uses Source Serif 4 / 33px leading in EN and Noto Serif Bengali / 36px in BN. Five size presets 16/20/23/26/30 remained in the actual comfort dialog. Closing the preview boundary restored focus to its trigger. No ornament was inserted into Reader text, dialogs, media sheets or the S26 status card.
- **Navigation:** final phone bottom bar is 82px with 48px row and localized labels. Bengali Settings wraps within the bar; no page overflow. Guest legal access was verified by Settings→SignIn→scrollable footer→Privacy; member Settings also exposes legal/contact links. Pass remains reachable through Settings on phone. Immersive Reader/media routes hide normal header/bottom navigation and use 56px task header.

Full per-screen source/runtime coverage is explicit in [ACCEPTANCE.md](ACCEPTANCE.md) and [acceptance-matrix.json](acceptance-matrix.json), with all 26 IDs mapped. A viewport not rendered is labeled source-reviewed, not PASS.

## Colors, assets and fonts

Original PNG logo remains unchanged and unfiltered. Its SHA256 is `a9513b9c17a4e9e303ea5b9483546366f9648a9dfb11bb8691d1fbb297d48da8`. Nine self-hosted font assets matched the existing manifest: Cormorant Garamond, DM Sans, Source Serif 4, Noto Serif Bengali and Noto Sans Bengali. No new remote font service was introduced. Computed desktop heading was48px Cormorant; UI was DM Sans; Bengali Reader was Noto Serif Bengali.

All supplied ornament files were byte-identical during preflight; the root subsequently kept four loaded motifs in public static and moved unused supplied references to `docs/design/peacock-crest/reference`, preserving their content. Official Phosphor assets are separate, licensed icon additions. Runtime images use rectangular0px radius and `object-fit:contain`; the full technical fixture cover was visible. This does not establish artistic/typographic quality of a real book cover that was not in the fixture.

Halo observed opacity was .12 on desktop hero, .10 on phone hero / .10 on general desktop/tablet and .08 on general phone; decorative nodes are aria-hidden/pointer-events none. Light and True Black suppress canvas halo; True Black computed body background image none. Exact foreground/background WCAG calculations are in [contrast.json](contrast.json): ivory/plum 16.575:1, secondary/plum 10.664:1, brass/plum 9.86:1, ivory/rose 6.313:1, worst supplied hover top 4.534:1, ink/parchment 13.527:1. Brass on ivory would be 1.681:1; the rendered ivory header instead used dark text and rose keyboard focus, and Light side icons used the dark adaptation. These calculations and representative visual checks are not a complete automated accessibility conformance audit.

## Explicit limits and console truth

Actual audio/full mini player, audio preview-end sheet and format switch were unavailable in seeded 8045 content. Their source selectors were reviewed; only the honest gated/unavailable layouts were rendered. S12 had no approved provider video, so actual iframe playback was not tested here. Checkout/pending/success had no approved offer/order fixture on 8045 and remain source-only in this independent theme audit; the separate finance lane owns those flows. No provider activation, billing transaction, book publication or P1 Clips/Practice/Gift implementation was inferred. Physical UAT, Figma application and full new-canvas parity are not claimed.

`browser-console.json` contains **nine repeated asynchronous-listener/message-channel error records** across Home/watch, with no application stack or theme source reference. This is not a zero-console-error claim. No application exception or visible theme malfunction was observed during the checked flows; the messages remain recorded as browser/integration noise of unconfirmed origin.

Final source hashes are recorded in [source-hashes.json](source-hashes.json). No unresolved theme issue requires another source edit from this review. Next Integration Lane action: include the bounded matrix and selected final captures with exact-head checks, then perform the already-authorized integration/release steps.
