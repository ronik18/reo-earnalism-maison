# Private Stream application acceptance

The final receipt qualifies one original silent three-minute technical fixture on the isolated Maison service in actual Chrome. It does not qualify book video rights, captions, physical devices, production HA or public publication. Both technical fixture and The Selfish Giant remain draft with null live pointers.

The historical renewal stall is preserved in `application-before-fix.json`. PR #4 fixes metadata/play startup ordering, retained progress during warmup and explicit pause during renewal. Actual replay crossed two grant renewals, paused Retry stayed paused, Play resumed at the retained position, and playback completed with a server-persisted 180000ms position. Final SQL used the existing SELECT-only backup role and confirms the five temporary content permissions are absent.

Runtime is main `664f750428b5edb7797a55db41c2608a25b8f5d3`; Render deploy `dep-dbvd6vf40ujc7395p9fg`. Exact-head CI [44507349183](https://github.com/ronik18/reo-earnalism-maison/actions/runs/44507349183) passed 480 backend and 32 client tests, build and migration checks. No schema, API, SDK dependency, architecture, DNS or additional paid plan changes were introduced by this fix.

The immutable asset release contains 71 files / 7372261 bytes. Recovery verified all 71 existing objects without rewriting them; public bundle checksum and HTTPS MISS to HIT passed. Secrets and signed playback URLs are excluded. During operator recovery, shell-quoted dotenv values required proper decoding before Docker env-file use; durable configuration was preserved. Verify persisted masked provider fields by private readback and the actual loaded release.
