# ADR 0172: Bounded CI131 coverage remediation attempt

## Status

Accepted for one manually requested staging retry after scoped proof and
independent review. Complete hosted qualification remains pending.

## Date

2026-11-08

## Context

CI130 executed the complete unit and integration populations successfully:
17,243 unit cases and 2,300 measured integration cases passed. Its integration
branch coverage was 19,623/24,570 (79.8657%), 33 branches below the 80% hard
floor. Unit branch coverage passed 85% at 86.3289%. Eight of nine jobs passed;
the staging manager report names only `M: coverage floors not met`.

The system lane passed five scenarios and consumed application start 41.
The native AMD and Rust component evidence passed, with cumulative counters
10 commands and 24 wheel transfers. These positive component results do not
qualify the failed overall campaign, and its reservation remains spent.

The current manual retry request selects one next staging attempt. The source
parent is `b7b4514fb29d81f8717badbbe86e3c075af07077`, and public main remains
`5ad00d162ad8a04430874275246a53227578c533`.

## Decision

Add source-backed tests for filesystem delivery, source-sealing fallback,
retained-object/record custody, publication correspondence and bounded
PostgreSQL readbacks. Preserve every coverage floor, denominator, exclusion,
measurement boundary, quality profile and debt ceiling. Local tests use exact
selectors with `--no-coverage`; hosted CI owns complete-population measurement.

After scoped proof and independent `dynamic_default` review, publish one
ordinary staging update through existing draft PR23, selecting CI131 attempt 1.
The new cumulative ceilings are application starts 42, native AMD commands 11
and wheel transfers 26, adding exactly one start, one command and two transfers.
No automatic retry, CI132, second push, main/tag promotion, history rewrite or
release acceptance is authorized.

The 87% unit and 82% integration branch margins remain desired targets. Source
arc mapping is a forecast, not measured local coverage or a guaranteed hosted
percentage. Missing evidence must not be replaced with a threshold exception.

## Binding and historical custody

Append the authenticated failed-CI130 consumption observation before deriving
a fresh nonce, approval, observed-ledger digest and reservation. Preserve every
inherited ledger root value, list prefix, spent constant and superseded value.
Add the CI130 spent tuple to both grant and proof denial paths. Tests retain
predecessor scalar refusals as well as future ordinal/cap refusals.

Bind the existing six governance owners:

1. `tools/ci/d12_system_build_grant.json`
2. `tools/ci/d12_hosted_candidate.json`
3. `tools/ci/d12_system_grant.py`
4. `src/test/unit/python/tools/ci/d12_system_grant.unit.test.py`
5. `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py`
6. `tools/ci/rust_pilot_qualification_manifest.json`

Derive the application context from final source, including eligible untracked
source. The application payload is unchanged in this test-only repair, but its
identity must still be recomputed. The Rust closure remains 264 paths; only the
current grant-guard digest changes. No historical native result is repinned.
The current preimages match the adopted CI130 receipt directly; no historical
test-framing amendment enters this attempt.

Construct approval first, then guard bytes, manifest bytes and reservation,
and finally the grant. Approval excludes its own digest, reservation, current
guard and post-render manifest fields. Reservation excludes its own digest.
Parse and serialize candidate JSON normally; bind all resulting raw bytes.

## Verification and limits

Require the exact scoped feature cohort, five grant unit cases, the host-proof
unit owner and three selected admission integration cases. Exclude the separate
materialization test. Final static, privacy, suppression, topology, export,
file-length, compilation, whitespace and historical-custody checks must pass.
The required independent review precedes the exact source commit and local
commit report. Public author and committer remain Samuel Leighton Lair
<sam.lair@knowledge-forge.ai>.

No runtime dependency, package metadata, lockfile, product behavior, database
schema, workflow trigger, test-runner policy, production admission or Local/MCP
authority changes. Complete local unit, integration, smoke, staging, system and
combined suites, local coverage, new local application/SDK builds, native
qualification and acquisitions remain unselected.

## Alternatives and rollback

Reusing CI130 is rejected because it was consumed. Weakening coverage or
measurement is rejected because it conceals the deficiency. Copying a prior
context count or native result is rejected because identity must bind the
current source. Before publication, a failed proof leaves the candidate local
for correction. After the single publication, further remote attempts require
another operator request.
