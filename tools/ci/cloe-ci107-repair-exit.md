# REPOMAP-CLOE-CI107REPAIR1 Exit: Exact Trixie prerequisite refresh

Status: **NOT ACCEPTED for whole-candidate qualification**. CI107's executed
system preflight failed before any application build. This forward repair
prepares one separately bound CI108 attempt; its complete hosted gates remain
pending. Full W5 acceptance remains open.

## Cause and correction

The CI107 native observation differs from the frozen package manifest only in
`linux-libc-dev`: Debian Trixie security now provides `6.12.115-2/all`, replacing
`6.12.113-1`. The exact official archive download matches the native APT SHA-256.
Refresh that one build-header row and the derived candidate-manifest digest.
Keep strict package/hash matching, the empty runtime closure and dynamic
Psycopg/libpq assembly. Stale or tampered rows must still refuse before a build
intent. No source/package/lockfile dependency is added.

Fresh official metadata also advances the PostgreSQL 16.15 Trixie and Python
3.12 slim Trixie index pins. Both indexes retain byte-identical ARM64 and AMD64
child manifests, configs and rootfs identities. Current release, Python-payload,
hosted metadata and unit expectations are updated together under ADR0105.
The preflight config table, test-profile mirrors and dated metadata observation
follow those same exact indexes; test population and isolation policy do not change.
The SDK recipe and native child identities remain unchanged. ADR0139 retains
the exact old/new identities and the bounded compatibility assessment.

## Evidence and boundaries

The new exact-header unit regression failed before the correction. The
introducing commit and exact-commit report record final scoped unit and
containerized integration selectors/results, static enforcement, privacy and
diff checks, and independent `dynamic_default` resulting-state review.
Integration exercises the actual session preflight with injected public
observations; it proves current admission and stale/tampered refusal with no
application build. It does not establish a native assembled-image result.

CI107's eight other jobs passed. Its system report records zero application
builds and successful cleanup. Preserve that evidence and its published
reservation/nonce as immutable history. The successor ledger appends the
no-start observation, retaining cumulative actual starts at 23 and the existing
maximum of 24. Preserve the legacy build-profile hold separately.

CI108 attempt 1 uses a fresh authority, source/context binding, nonce,
reservation and grant. Old campaign identities are denied. One ordinary
fast-forward staging publication synchronizes existing draft PR23 and triggers
the normal public pipeline. Hosted capacity is AVAILABLE under the operator's
standing selection. No duplicate trigger, automatic retry or manual dispatch
is included.

Complete local Python unit, integration, smoke, staging, system and combined
suites and local Python coverage remain intentionally unselected. No local
application or SDK build, runtime promotion, tag, release, main update, live
deployment, production pgvector admission or unrelated roadmap work is part of
this repair. Hosted CI108 owns complete populations, coverage and native
assembled-product qualification for the final candidate.
