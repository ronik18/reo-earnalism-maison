# Neon setup and audit — 18 November 2026

The owner approved retaining PostgreSQL 18 in the existing Singapore project and updating the LLD baseline. This is a version baseline approval, not a claim that compatibility and launch acceptance have completed.

## Installed configuration

- Installed global Neon CLI 9.6.0 using `npm i -g neon@latest`.
- Ran the requested `neon init -y --org-id org-misty-dew-00335964 --project-id quiet-cloud-63128335 --branch production --services postgres` in this dedicated repository.
- Init created `neon.ts` (Postgres only, Auth disabled), an ignored `.neon` project link, and added `@neon/config` and `@neon/env` package dependencies. Existing frontend scripts and concurrent work are preserved; a private pre-init snapshot is retained under ignored `.local/neon-init-preimage/`.
- Init installed user-level neon-postgres plugin 3.0.9 for Codex, Claude Code, Claude Desktop, Cursor and VS Code, plus Neon skills/MCP configuration for GitHub Copilot CLI. Existing configuration was retained. No duplicate project MCP server was added.
- Fetched the requested skill from [Neon](https://neon.com/.well-known/agent-skills/neon/SKILL.md). Its SHA-256 is `e8309b1ae5166a702c2b23dd5e05d25410f13d8c1475d8971762ee22e7a1f2e3`, byte-identical to the installed plugin skill.
- The installed plugin configures OAuth MCP at `https://mcp.neon.tech/mcp`, with no embedded API key. MCP tools are not exposed in this already-running session, so installation/configuration is verified but an MCP tool call is not claimed. Authenticated CLI access works.
- Completed browser-backed `neon login`. `neon config plan` and `neon deploy` report no infrastructure changes and only Postgres utilized. Deploy pulled five variables into ignored `.env.local`, permission 0600. The Functions hostname variable does not enable Functions.
- Added ignored env-file patterns, optional explicit dotenv loading, pooled/direct connection selection and full TLS verification in Django. Env values and credentials remain untracked.

## Verification

The original certificate lookup and unsupported pooled startup-timeout failures are resolved. The app uses a trusted platform CA bundle and full certificate/hostname verification. A direct-only setup command provisions current-role/database timeout defaults; fresh pooled connections report5s/2s/10s, and a six-second query was cancelled after5.08seconds.

All37 migrations are applied to PostgreSQL18.7 with zero pending. The actual draft book browser journey passes against Neon using the local private-media adapter. Full evidence, exact IDs, parallel-lane status and remaining public-launch qualifications are in [NEON_VALIDATION_HANDOFF.md](NEON_VALIDATION_HANDOFF.md).

No new paid infrastructure, public publication, cutover or legacy changes occurred. Django/psycopg remain the runtime; Node is build/config tooling only. No Neon Functions, Auth, object storage, AI gateway or realtime service was added. MCP installation/configuration was checked, but an MCP tool call is not claimed in this existing session.
