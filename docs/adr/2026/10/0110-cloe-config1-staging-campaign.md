# ADR 0110: CLOE configuration milestone staging campaign

## Status and authority

Accepted before admission implementation, 2026-10-29, for
REPOMAP-CLOE-CONFIG1. The maintainer instructed: "proceed until the next
milestone warranting public ci then publish to public staging. you know, the
usual."

This instruction authorizes one normal release-qualification campaign for the
implemented ADR0109 milestone. The parent interprets its necessary native AMD
application build as a new milestone allocation after the completed D12/CI87
campaign. This is not a claim that the maintainer supplied a numerical build
reply. Preserve all seven spent starts and all earlier records. Instantiate
one additional start, cumulative maximum eight, without resetting history or
granting a retry. ADR0108's closed campaign cannot qualify this changed tree.

## Decision

Permit one ordinary public staging publication descending from preview main
5ad00d162ad8a04430874275246a53227578c533, and one fresh draft staging-to-main
PR opening event. The old staging branch was removed after PR13 merged.
Read-only repository inspection currently identifies the next PR as 23 and the
next qualification ordinal as 91. Bind exactly PR23 / CI91 attempt 1; recheck
before publication and refuse unexpected identity drift. No generic PR-number
wildcard, synchronize event, reopening or manual dispatch is admitted.

For this opening event, bind the pre-publication baseline (`before`) to the
exact current main (`base`). Neither field claims to have come from a GitHub
synchronize payload. Require the opening payload to omit `before`/`after`,
derive the successor from its same-repository staging head, and prove both
parents of the live GitHub test merge. Reject supplied synchronize fields,
wrong actions, base/head/repository/draft/platform/run/attempt mismatches and
spent grants. Keep strict schemas, frozen runtime bytes, SDK identity,
duplicate-key/file authority, secure proof writing and child revalidation.

Allocate at most one native linux/amd64 application start through the existing
sole main-system builder, with at most one necessary hosted materialization
of the unchanged SDK recipe. Use a fresh nonce, reservation, approval record,
pre-append ledger hash and final runtime source identity. Deny CI87's spent
nonce/reservation alongside every earlier spent pair. Retain the prior seven
consumption observations unchanged; append the new milestone reservation.

Scoped unit and containerized integration checks without coverage, independent
native source review, static/export/privacy checks and an exact-commit local
report precede publication. The hosted pipeline owns complete populations,
coverage and system qualification; earlier green evidence is not transferable.
Use Samuel Leighton Lair <sam.lair@knowledge-forge.ai> for public metadata.

## Boundaries

No ninth start, retry, attempt 2, local application or SDK build, complete local
suite, project coverage, new dependency, supplier-pin or runner-policy change,
weakened gate, main promotion, release tag, repository rename or deployment.
Debian stable slim and dynamically linked Psycopg remain unchanged. Actual or
uncertain starts spend the allocation; later failure requires a forward
remediation and separately authorized campaign.
