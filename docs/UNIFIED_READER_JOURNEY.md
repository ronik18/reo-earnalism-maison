# Owner amendment — single reader journey,20November2026

The owner removed separate interface-language journeys: one English interface for every reader, with all eligible published book languages visible by default. Book language is an optional list/search filter, not an account access restriction. Bengali editions retain their actual Bengali titles/text, fonts and language metadata. Territory, rights, publication state and access boundaries remain unchanged; “entire library” does not publish drafts or bypass those boundaries.

Existing Bengali interface URLs redirect to their matching English destinations, preserving query/token paths and POST semantics. Existing profile language values are retained for compatibility but no longer choose interface text or implicitly filter catalogs. No database migration or bulk preference rewrite is needed. Signup/onboarding/Settings/header/immersive/offline controls use the same English journey; direct edition links and saved progress retain edition identity.

Home,Explore,search,collections,Series and learning discovery default to all languages. Explicit content filters remain separate and bind pagination cursors. Mixed-language search applies the appropriate per-edition search configuration. Language choices are derived from published content with current English/Bengali options. Additional publication-language validation/index/model changes remain necessary when introducing a new language; this amendment does not itself publish another language.

Legacy locale API fields and dormant translation resources remain compatibility data, not active alternate screens. Existing security/financial/retention/publication policies and the protected draft are unchanged. Physical Android/iOS UAT remains deferred and non-blocking.

## Deployed acceptance

PR#10/main284ae36 is Live on all three existing isolated services. Exact-mainCI passed548backend/37client tests;66mixed-language localbrowser,3cachedfallback and93livebrowserchecks passed. [Receipt and previews](evidence/unified-reader-20261120/README.md). Protected draft and legacy unchanged.
