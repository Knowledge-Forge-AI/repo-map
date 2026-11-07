# ADR 0111: CI91 compatibility repair and one staging retry

## Status and authority

Accepted before repair/admission implementation, 2026-10-29, for
REPOMAP-CLOE-CI91REPAIR1. After CI91 failed, the maintainer instructed:
"CI failed. Try again."

The parent interprets this fresh request as authority to repair the identified
failures and publish one corrected staging candidate through the normal hosted
pipeline. Its necessary native AMD application build is one new allocation,
cumulative maximum nine. This explicitly supersedes ADR0110's no-ninth clause
for this corrected campaign only. It is not an automatic retry or a claim that
the maintainer supplied a numerical build reply. All eight prior starts stay
spent; no ledger history, evidence or coverage threshold is reset.

## Context

CI91 attempt 1 executed on staging 4c913634eb1aca6f7de1941f0ec56ae7d3748924
and test merge 4043ff84d06f0635a741498a831c6996732eee28, against main
5ad00d162ad8a04430874275246a53227578c533. Seven of nine jobs passed,
including static, source/export, native system, native component and security
lanes. Unit had one namespace assertion failure and one fixture teardown
error. Integration had one legacy diagnostic assertion failure. Unit coverage
was 88.0% lines / 87.6% branches; integration was 90.2% / 82.4%. All exceeded
their hard floors by at least two percentage points; failures were behavioral.
Those measurements qualify neither a corrected successor nor its populations.

The loader's new discovery import accidentally joined its eager public facade.
The new autouse CLOE fixture depended on the shared monkeypatch fixture,
moving its teardown behind resource-state restoration; an intentionally
refusing environment was therefore still installed during restoration. The
empty-home message lost the legacy filename substring while adding CLOE.
Scoped canonical unit and containerized integration runs reproduce all three.

## Decision

Keep the discovery helper private, preserve the existing eager facade names
and identities, and retain the legacy empty-home wording while also naming
CLOE files. Give CLOE isolation its own MonkeyPatch context with fixture-owned
cleanup, preserving early collection isolation and explicit test overrides.
Do not weaken the injected environment failure or resource rollback assertions.

Publish one reviewed forward commit by ordinary push to the existing draft
PR23 staging-to-main pair. Bind exactly the resulting synchronize event,
CI92 attempt 1, previous staging 4c913634eb1aca6f7de1941f0ec56ae7d3748924
and unchanged main 5ad00d162ad8a04430874275246a53227578c533. Recheck remote
and ordinal drift before publication. Restore strict synchronize before/after
validation; opening events and their derived baseline are not admitted here.
Require the live two-parent GitHub test merge, exact platform, SDK recipe and
final frozen source bytes. Preserve secure IO, closed schemas, host/child
revalidation, all spent pairs and no-reuse behavior. Add CI91's spent pair.

Allocate at most one further native linux/amd64 application start through the
existing sole main-system builder, and at most one necessary hosted SDK
materialization using the unchanged recipe. Retain the exact current request,
pre-append ledger bytes, fresh approval/nonce/reservation and eight historical
consumption observations. Actual or uncertain starts spend the new slot.

Scoped unit and containerized integration proof without coverage, native
independent source review, static/export/privacy checks, a professional phase
commit and exact-commit local report precede the one publication. Public author
and committer remain Samuel Leighton Lair <sam.lair@knowledge-forge.ai>.
Hosted complete populations, coverage and assembled-product qualification
remain pending for the successor.

## Boundaries

No tenth start, automatic retry, attempt 2, local application/SDK build,
complete local suite, project coverage, new dependency, supplier-pin change,
runner-policy change, debt increase, weaker gate, main promotion, tag,
repository rename or deployment. Preserve the protected private checkout.
Debian stable slim and dynamically linked Psycopg remain unchanged.
