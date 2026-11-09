# ADR 0176: One requested CI134 corrective qualification

Status: Accepted for bounded preparation and one newly requested campaign.
Date: 2026-11-08.
Phase: REPOMAP-CLOE-CI133REPAIR1.

## Context

The operator requested another attempt after CI133 failed. CI133 passed its
system, native D12/Rust, static, source/export and security jobs. Its one unit
failure is an obsolete rendered-recipe hash after the approved Debian header
pin refresh. All integration tests passed; measured branches were 20001/25030,
23 short of the 80% hard floor and 524 short of the desired 82% margin.
Unit branches were 21695/25030, above the 85% floor and 82 short of 87%.

CI133 consumed one application build, bringing actual cumulative starts to
43. Its native Rust qualification and two exact wheel transfers brought those
cumulative allocations to 13 and 30. Its owned resources were cleaned up.
No previous nonce, reservation or native qualification result may be reused.

## Decision

Interpret the current explicit retry request as authority for one fresh normal
CI134 attempt 1. ADR 0175's prohibition on an automatic successor remains:
this is a newly requested campaign, not an automatic retry or rearm.
The operator did not state numeric ceilings in this request. The following
are the minimum ledger increments for one existing pipeline invocation:

- application starts: 43 to 44, through the existing native AMD system builder;
- native Rust qualification commands: 13 to 14;
- transfers of the same two hash-bound parser wheels: 30 to 32.

Correct the stale recipe fixture and add meaningful tests of maintained
resource/sealing boundaries identified by the hosted coverage report. Preserve
the renderer, package pins, dependencies, lockfiles, runner policy, strict
receipts, debt ceilings and complete maintained-source denominator. New tests
must exercise observable contracts rather than merely execute missing lines.

Before publication, require exact scoped unit and containerized integration
proof with no coverage; strict static, privacy, topology, export, compilation
and whitespace checks; a freshly derived application context and native import
closure; acyclic approval/guard/manifest/reservation binding; explicit refusal
of spent CI133 tuples; and independent frozen-candidate dynamic_default review.
That review must challenge this interpretation of current retry authority.

Publish at most one ordinary staging push through the existing draft PR23 to
trigger CI134 attempt 1. Public main remains unchanged. Source parent is
8ddcdbe116f6e02435b1b0a5cc6621882a67efff; public base is
5ad00d162ad8a04430874275246a53227578c533. Public author and committer remain
Samuel Leighton Lair <sam.lair@knowledge-forge.ai>.

## Limits and evidence

No local complete suite, local Python coverage, local application/SDK build, new
dependency or test-runner policy class is authorized. No rerun, second push,
automatic CI135, additional build, main/tag/release or history rewrite follows.
Scoped passing tests establish source readiness only. Coverage improvements,
whole-population acceptance and fresh native qualification require CI134.
Hard unit 85/85 and integration 80/80 floors and desired 87/82 margins remain.
The previous system result supports diagnosis, not acceptance of this successor.

## Alternatives and rollback

Replaying CI133 would retain the obsolete fixture and would not test corrected
source. Relaxing thresholds, dropping source from measurement, relabeling M as
A or waiving incomplete receipts is rejected. Holding publication is required
if fresh authority binding or source proof cannot be established. A failed new
campaign requires another explicit operator request and corrective disposition.
