# Peacock Crest acceptance matrix — final independent audit

Scope: current existing app only. All26 IDs have a source mapping; representative rendered states are identified individually. A source-only or unavailable state is not a full feature/browser acceptance. No supplied prototype JS was executed.

Target CSS viewports: desktop1440×900, phone393×852, tablet1024×768, confirmed by innerWidth/innerHeight. Chrome existing90% zoom was retained and viewport overrides calibrated; temporary overrides reset. Raw screenshot backend adds density padding; normalized QA crops retain the actual CSS viewport without resizing content.

|ID|Screen|Desktop|Phone|Tablet|
|---|---|---|---|---|
|S01|Welcome and onboarding|Source-reviewed; this viewport/state was not rendered in this audit|PASS initial onboarding view; final crest recaptured. Steps2–3 source-reviewed, not exercised.|Source-reviewed; this viewport/state was not rendered in this audit|
|S02|Sign in and sign up|Source-reviewed; this viewport/state was not rendered in this audit|PASS Bengali password form + real local test-account sign-in; provider paths gated/not exercised.|Source-reviewed; this viewport/state was not rendered in this audit|
|S03|Home guest|PASS final guest Home|PASS final guest Home|PASS final guest Home|
|S04|Home member|Source-reviewed; this viewport/state was not rendered in this audit|PASS member Home with Light theme and Bengali content|PASS member Home with Light theme; no overflow|
|S05|Explore|Source-reviewed; this viewport/state was not rendered in this audit|Source-reviewed; this viewport/state was not rendered in this audit|PASS Explore in True Black; filters/catalog rendered|
|S06|Search|Source-reviewed; this viewport/state was not rendered in this audit|Source-reviewed; this viewport/state was not rendered in this audit|PASS Dark search form, river query submitted and result navigation|
|S07|Title page|Observed rectangular full cover/title/actions; crest fix source-reviewed, final crest recaptured on phone|PASS final EN/BN title layout and crest; no crop or overflow|Source-reviewed; this viewport/state was not rendered in this audit|
|S08|Reader|PASS member Reader; plain text surface|PASS EN/BN previews, immersive header, local comfort dialog. EN20px/33px and BN20px/36px|Source-reviewed; this viewport/state was not rendered in this audit|
|S09|Reader end of preview|Source-reviewed; this viewport/state was not rendered in this audit|PASS preview-end sheet; all actions fit; Close restores trigger focus|Source-reviewed; this viewport/state was not rendered in this audit|
|S10|Audio mini and full player|Source-reviewed; this viewport/state was not rendered in this audit|PASS gated unavailable layout and immersive shell only. Full/mini playback not available in local fixture.|Source-reviewed; this viewport/state was not rendered in this audit|
|S11|Audio preview end sheet|Source-reviewed; this viewport/state was not rendered in this audit|PASS unavailable/error layout only. Actual audio preview sheet remains source-only.|Source-reviewed; this viewport/state was not rendered in this audit|
|S12|Video player|Source-reviewed; this viewport/state was not rendered in this audit|PASS no-approved-video layout, crest and immersive shell. Actual provider player not exercised.|Source-reviewed; this viewport/state was not rendered in this audit|
|S13|Series page|Source-reviewed; this viewport/state was not rendered in this audit|PASS empty released-Series layout. Populated episodes not exercised.|Source-reviewed; this viewport/state was not rendered in this audit|
|S14|Clips feed|Source-reviewed; this viewport/state was not rendered in this audit|PASS existing P1 unavailable state only; no feed claim|Source-reviewed; this viewport/state was not rendered in this audit|
|S15|Switch format sheet|Source-reviewed; this viewport/state was not rendered in this audit|Source-reviewed; this viewport/state was not rendered in this audit|Source-reviewed; this viewport/state was not rendered in this audit|
|S16|Learn home and Track page|PASS Learn catalog layout; Track route/lesson entry AX inspected. Full populated track visual states not exhaustive.|Source-reviewed; this viewport/state was not rendered in this audit|Source-reviewed; this viewport/state was not rendered in this audit|
|S17|Lesson quiz and result|Source-reviewed; this viewport/state was not rendered in this audit|PASS quiz selection/server result score100/correct feedback and visible next action|Source-reviewed; this viewport/state was not rendered in this audit|
|S18|Interview Studio home and role track|Source-reviewed; this viewport/state was not rendered in this audit|PASS SDE home layout; question/rubric states source-reviewed only|Source-reviewed; this viewport/state was not rendered in this audit|
|S19|Practice and readiness|Source-reviewed; this viewport/state was not rendered in this audit|PASS existing P1 unavailable state only|Source-reviewed; this viewport/state was not rendered in this audit|
|S20|Pass page|Source-reviewed; this viewport/state was not rendered in this audit|PASS no-approved-offer layout and retained gate copy|Source-reviewed; this viewport/state was not rendered in this audit|
|S21|Checkout and success|Source-reviewed; this viewport/state was not rendered in this audit|Source-reviewed; this viewport/state was not rendered in this audit|Source-reviewed; this viewport/state was not rendered in this audit|
|S22|Vault home|Source-reviewed; this viewport/state was not rendered in this audit|PASS empty Vault navigation/layout; list-edit variants source-only|Source-reviewed; this viewport/state was not rendered in this audit|
|S23|Highlights Notes Downloads|Source-reviewed; this viewport/state was not rendered in this audit|PASS local empty/error Downloads layout; complete offline package not qualified|Source-reviewed; this viewport/state was not rendered in this audit|
|S24|Settings billing and cancel|Source-reviewed; this viewport/state was not rendered in this audit|PASS member settings appearance save; guest Settings→SignIn→Privacy access|PASS Light/TrueBlack appearance and icons; sensitive/financial actions not submitted|
|S25|Gift flow|Source-reviewed; this viewport/state was not rendered in this audit|PASS existing P1 unavailable state only|Source-reviewed; this viewport/state was not rendered in this audit|
|S26|System states|Source-reviewed; this viewport/state was not rendered in this audit|PASS404/plain status card, halo off; gated media/system states also inspected|Source-reviewed; this viewport/state was not rendered in this audit|
