# ADR 0117: CI94 remediation and one replacement staging campaign

## Status and authority

Accepted before implementation, 2026-10-30, for REPOMAP-CLOE-CI94REPAIR1.
The maintainer reports CI failure and requests another attempt. Direct parent
work retains the native Claude/Muse CLI execution preference. This fresh request
authorizes the bounded corrections below and one normal replacement campaign;
it is not an automatic retry or a numerical operator answer.

CI94 attempt 1 executed and failed unit, pre-review and staging measurement
while the native preflight and main-system gate passed. Retained system intent,
image and cleanup evidence spends the eleventh native AMD start. Preserve all
eleven actual observations. Supersede ADR0116's no-twelfth clause only for one
twelfth native linux/amd64 start in CI95 attempt 1 through the existing sole
system builder. No thirteenth start, attempt 2 or automatic retry.

## Evidence and corrections

- Unit coverage already exceeds the requested two-point margin: 88.1% line
  and 87.6% branch against 85/85. Three behavior/assertion cases failed.
- The replacement fixture frees its original inode before creating identical
  bytes. Linux may reuse that inode, defeating the fixture's intended distinct
  identity. Create a distinct file while the original is still alive, prove
  distinct identity, then atomically replace. Preserve drift-refusal assertions;
  do not change journal schemas or promise hostile same-user writer detection.
- Defer the migration filesystem's `fcntl` capability probe until a migration
  operation asks for it. Local entry imports remain neutral; migration still
  refuses unsupported platforms before writes. Do not expand the canary allowlist.
- Update the missed runner assertion to ADR0115's typed diagnostics and prove
  matching first-cause evidence. Remove the newly added type suppression through
  explicit narrowing, without modifying suppression baselines.
- Staging's 1,862 measured cases passed, but strict combine refused an unregistered
  discovery-script shard, leaving abrupt A blocked. New diagnostic fixtures retain
  ambient coverage configuration in raw child launches. Reuse the qualified full
  coverage-environment scrubber for tool-only diagnostic children, including its
  bootstrap-path handling. Keep source selection, child registration/receipts,
  unknown-shard refusal and M/A acceptance strict. No new launch family, exclusion,
  denominator adjustment or exception for unregistered shards is permitted.

The association of the retained shard with the inherited-environment isolated
diagnostic launch is a source-backed inference. Focused synthetic-source child
custody tests must prove isolation and preservation of the parent's environment;
hosted CI remains responsible for complete measurement and coverage margins.
Unrelated discovery-path hardening and the prior low review observations remain
outside this correction unless fresh evidence makes them necessary.

## Verification and publication

Use exact canonical unit and containerized integration selectors with
`--no-coverage`. A synthetic-source component session may exercise coverage
bootstrap mechanics; it must not collect or report RepoMap project coverage.
Require independent native source/grant review, clean static/suppression/export/
privacy checks, an exact-author commit and exact-commit report before one ordinary
staging synchronize push through unchanged draft PR23.

Bind fresh authority, nonce/reservation, pre-append ledger and final runtime
context to CI95 attempt 1, before staging
`35d9235cefd740e13ae7228a791338d5a5fcf9ee`, against unchanged main
`5ad00d162ad8a04430874275246a53227578c533`. Refuse spent CI94 credentials and
all prior spent pairs. Preserve the application/SDK recipes, native host checks,
strict event/merge/source identity, secure I/O and every debt ceiling. At most one
necessary hosted materialization of the unchanged system SDK recipe is retained.

No complete local suite, local app/SDK build, dependency/pin/workflow policy,
coverage threshold, suppression baseline, broad namespace/default-home cutover,
main promotion, tag, deployment or history rewrite. Public author and committer
remain Samuel Leighton Lair <sam.lair@knowledge-forge.ai>. Preserve the protected
private checkout and every already reported phase commit.
