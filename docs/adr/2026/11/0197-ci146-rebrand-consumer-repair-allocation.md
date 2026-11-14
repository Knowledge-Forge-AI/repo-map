# ADR 0197: Allocate one CI146 rebrand-consumer repair campaign

## Status and authority

The operator selected route A in the CI146 decision packet on 2026-11-13
(local date), after the prepared ADR 0196 source passed scoped proof and
independent review. This supersedes only CI145's next-campaign exclusion and
the three spent ceilings below. It grants no automatic retry or CI147 campaign.

## Observed predecessor

CI145 attempt 1, run 43544294343, tested merge
013fe7eed63be8527d4b09ace7dbd933f88f2d48 from main
5ad00d162ad8a04430874275246a53227578c533 and staging
4bad748452454e46148af6742fcb070168d4d45a. Its tree was
9f6a1f015b9230f4673ba4e8ee0b8b0d86a4af8b. The system artifact records one
successful application build, four passed scenarios, then refusal of the real
canonical MCP name by a stale consumer. Cleanup and terminal absence passed.
Eight unit failures concerned rebrand expectations. A scoped PostgreSQL case
also reproduced a separate catalog pin mismatch; ADR 0196 owns those repairs.
The completed same-attempt integration report is EXECUTED_FAIL: measured M
completed all 2,572 planned cases (2,546 passed, 14 failed, 12 skipped), while
all five declared abrupt A cases passed. Both legs passed cleanup and report
validation. M coverage was 89.19% lines and 80.11% branches, above the hard
80/80 floor; the requested 82% branch margin remains pending hosted measurement.
The fourteen failures comprise two catalog consumers, ten installed setup
failures, one CLI version expectation and one cancellation-control race.
ADR 0196 records their repairs, including the separately frozen incumbent's
version and the deterministic interrupt-masking regression. None is waived.

Native Rust qualification passed and transferred its two exact pinned wheels.
Cumulative observed consumption is 53 application starts, 25 charged qualifier
entries and 52 wheel transfers. Actual component-runtime entries are 24, a
different counter from charged entries. Every previous nonce remains spent.

## Decision

Permit exactly one additional native linux/amd64 application start, increasing
the cumulative cap 53 to 54. Permit one existing native qualifier entry 25 to 26
and its two pinned wheel transfers 52 to 54. Preserve the existing workflow,
system builder, platform, dependency classes and qualification requirements.
Append the observed predecessor and this allocation to the complete retained
ledger without changing any published prefix. Bind a fresh nonce, approval,
context and manifest; no old image or native result is rebound as current proof.

The source must pass its required scoped tests, static/privacy checks and
independent review. Final grant/ledger/manifest and release-document integration
must also pass scoped proof and independent review before exactly one normal
staging push triggering CI146 attempt 1. First complete CI145 analysis and
repair its remaining deficiencies. Unexpected dependency or runner-policy class
changes require separate authority. No gate or evidence obligation is reduced.

Use the prepared publication-neutral v0.0.4 notes in the final frozen candidate,
so later successful promotion does not require editing its qualified source.
The already selected v0.0.4 exception in ADR 0195 and CHANGELOG remains: only
after exact current hosted PASS and M/A/system audits, advance main ordinarily
to the qualified staging commit and create the annotated v0.0.4 tag and GitHub
source prerelease at that same commit. Do not squash, create a new merge commit,
force push or rewrite published history. Public author, committer and tagger
remain Samuel Leighton Lair <sam.lair@knowledge-forge.ai>.

## Limits

No second push, automatic retry, CI147 allocation, extra native command, wheel
transfer or application start. No local application/SDK build, complete local
suite, local coverage, model/study, new dependency or runner-policy class,
production/image/platform admission, registry publication or live activation.
Hard coverage floors and the requested two-point margin remain unchanged and
must be measured in hosted CI. The completed repository/checkout renames and
three historical RepoMap tag/releases are not repeated by this allocation.
