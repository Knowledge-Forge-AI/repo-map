# ADR 0132: CI103 measured-child repair and one successor qualification

## Status and authority

Accepted by the parent under the current explicit operator request, conditional
on corrected source, scoped proof and independent final review before staging
publication. Phase: REPOMAP-CLOE-CI103REPAIR1. Date: 2026-11-01.

The operator requested: "CI: failed. Try again: you must." The parent interprets
this as authority to repair the executed CI103 deficiency and publish one
corrected successor through the existing public staging/PR23 pipeline. It
includes one twenty-first native linux/amd64 application start for CI104
attempt1. This records the parent's interpretation, not a numerical human
reply. It supersedes ADR0131's prohibition on a twenty-first start only for
this exact corrected attempt; all twenty observed starts remain spent.

## Context

CI103 attempt1, run41275226551, tested staging
593495896d05037129f7cf1ce7b08831c6779444 through merge
bf5fbf76c149b4f59c2ec906bf46ba7ac88900b7 and tree
3834336c094c353046fac096a402ca562ec81e02. Eight jobs passed, including unit,
pre-review static, security and native system qualification. Measured integration
reported1956passed,12skipped and24deselected, but coverage assembly rejected a
valid SQLite shard without invocation registration. The overall candidate is
EXECUTED_FAIL and NOT ACCEPTED. System success is exact-candidate evidence;
its twentieth native start and verified cleanup remain recorded as spent.

Unit lines57531/65359 and branches18596/21338 exceed the requested87% margins.
Integration measurement is unavailable, not zero and not a valid82% claim.
Hard85/85 unit and80/80 integration gates remain unchanged. Hosted CI owns
complete-population measurement for the corrected successor.

## Decision and repair boundary

Repair the test-owned D12 round-trip child launch and terminal lifetime using
the existing measured-process contract. Preserve the runner bootstrap when
extending PYTHONPATH and allow Python descendants to finalize normal terminal
receipts instead of bypassing atexit through exec. Retain strict rejection of
unregistered/fabricated/stale shards, source identity, custom-archive/hash/data
and exact btree+gin checks, and all restoration assertions.

Use small fixture-only nested coverage to prove registration, terminal and
combination behavior. This is an instrumentation regression test, not local
project coverage or whole-suite qualification. Preserve the local SQL replay
shim's documented PG17-client/PG16-server portability limitation; direct native
pg_restore qualification remains hosted.

Permit one ordinary staging push after completed repair and review, producing
one automatic PR23 synchronize campaign, CI104 attempt1. Reserve exactly one
twenty-first native linux/amd64 application start with total/per-platform cap21.
Preserve all historical consumption observations and reservations, and reject
CI103's spent nonce/reservation in both validators alongside every earlier
spent or superseded identifier. Bind the fresh grant to current frozen runtime
context, repository/workflow/event/PR, staging-before5934958, unchanged main
base5ad00d1, exact merge parents and tree. Unchanged runtime context does not
make a spent grant reusable. Exclusive consumption and cleanup remain required.

Supplier pins, Debian stable-slim/Trixie responsibility, dynamic Psycopg linking,
dependencies, application/SDK recipes, runner and coverage policy, debt ceilings
and all existing security dispositions remain unchanged. Hosted setup may
materialize its unchanged SDK at most once. Scoped container integration uses
the existing cached SDK and five frozen setup prerequisites.

## Verification, publication and stop boundary

Require exact scoped unit and containerized integration selectors with
--no-coverage, real child/receipt and restore regressions, retained static with
zero debt regression, compilation/topology/length/export/privacy checks, fresh
independent final source/grant/evidence review and protected-checkout custody.
No complete local Python population, local project coverage, local application
or SDK build, new image or infrastructure is authorized. Local results do not
qualify the complete candidate.

Commit once with Samuel Leighton Lair <sam.lair@knowledge-forge.ai> as author
and committer, generate the exact-commit report, and verify public refs, current
PR23 and latest completed campaign before the fast-forward staging push. Stop
after verifying automatic CI104 attempt1 begins, with qualification pending.

No twenty-second start, automatic retry, rerun, duplicate dispatch, PR-state
change, main promotion, tag, package release, rename, live deployment,
extension admission, calibration rerun or held-out query is included. Later
failure requires separate next-attempt authority. Historical evidence and
lineage stay immutable; rollback is a reviewed forward correction.
