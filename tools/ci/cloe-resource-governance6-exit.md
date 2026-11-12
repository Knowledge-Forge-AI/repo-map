# REPOMAP-CLOE-RESOURCE-GOVERNANCE6 Source Exit

Date: 2026-11-12. Disposition: bounded source accepted after independent review and parent
accuracy corrections; hosted qualification remains pending.

ADR0187 repairs metered temporary acquisition and the lifetime of raw and
buffered store resources. Every registered raw descriptor is attempted once
on cleanup OSError. A normal close failure remains visible; an active producer,
integrity, budget or control-flow primary survives secondary cleanup OSError.
Unlink is operation-local, including calls made inside an unrelated except.
The existing setup helper's wider BaseException suppression is explicitly
retained; later non-OSError cleanup can interrupt release and replace a primary.
No absolute asynchronous, hostile-path, reused-fd or OS-close-retry guarantee.

Accepted bytes, references/digests/versions, read headroom and EOF probes,
meter admission and successful operation counts stay unchanged. Normal puts
retain3 opens/2 fsyncs; collision puts retain3 opens/1 fsync. Cleanup does not
call the meter. Post-install refusal leaves the object under store custody
without claiming persistence or returning a successful reference.

## Exact scoped proof

Corrected baseline RED on the original production owner:25 failed,5 passed.
The first RED run included12 fixture-permission refusals before the intended
collision fault; those12 are not defect proof. Corrected private-file fixtures
reached actual close faults. Canonical receipts pin production, test and fixture
owners; the parent addendum explicitly extracts the helper pin omitted from
the reviewed RED projection, without rewriting historical receipts. The witnesses retain real fd identities and explicit proxy streams;
test teardown reclaims deliberately refused closes, without relying on GC.

Current unit:92 passed. Canonical --suite unit --no-coverage --jobs1 selectors:

```text
src/test/unit/python/repomap_kg/artifacts/metered_store_custody.unit.test.py
src/test/unit/python/repomap_kg/artifacts/store_metered_put.unit.test.py
src/test/unit/python/repomap_kg/artifacts/governance3_collision.unit.test.py
src/test/unit/python/repomap_kg/artifacts/store_producer_custody.unit.test.py
src/test/unit/python/repomap_kg/artifacts/sealing_refusal_contracts.unit.test.py
src/test/unit/python/repomap_kg/artifacts/metered_io.unit.test.py
```

Current containerized integration:31 passed. Canonical --suite int
--no-coverage --pg-container-port55433 --jobs1 selectors:

```text
src/test/int/python/repomap_kg/artifacts/metered_store_custody.int.test.py
src/test/int/python/repomap_kg/artifacts/sealing_refusal_contracts.int.test.py
src/test/int/python/repomap_kg/artifacts/source_fallback_custody.int.test.py
```

The new in-process sealer/store witnesses prove setup-fault descriptor
closure, prior-manifest preservation, and an actual manifest-write refusal
after the changed body is installed. The installed body stays in custody and
the budget refusal remains primary through unlink failure. Successful new and
collision paths retain exact bytes/reference/counters at admitted budgets.
Existing post-install and source-fallback owners are regression proof. No native
unmodified signal/worker claim follows from injected Python faults.

The initial integration witness refused at planned_write_bytes before store
entry. It was corrected to admit the body and reach actual write_bytes refusal;
the final31-case run passes. Unit and integration preserve source/HEAD/index and
prove exact cleanup; Docker image, volume, network and container sets match.
Managed/unmanaged build and pull counts are zero. No Python coverage claim.

All required Python quality profiles pass with complete census/enforcement,
zero cohort regressions and empty eligible-minus-enforced sets. Three clean
test/support owners and two cohorts are additive. All inherited inventory rows,
relative order, profiles, ownership/retention rules and numerical debt remain.
No new product owner, suppression or threshold relaxation. Every edited Python
owner is at most400 lines. Final topology/export/suppression, length, compilation
and diff checks are required before commitment.

## Structure, rollback and remaining gates

Python profile: bounded legacy repair with an explicit Orange ownership-boundary
decision. APG fallback statement/branch/argument/local counts are not Ruff/mypy
metrics. Three existing Red routines remain: collision statements62→59 and
branches23→20; verification branches14→13; put statements62→62 and branches18→16.
Collision locals13→14 includes its owned descriptor list; put locals20→21
includes its operation-local failure marker. The parent explicitly accepts both
bounded increases: statements do not grow, branches fall and no independent
responsibility or new Red crossing is introduced. This remains the smallest
repair, with broader legacy decomposition separate. Newly added callables/tests have
no measured Red signal. Full readability decomposition remains separate.
Source/test reversion needs no data migration.

Complete local unit, integration, smoke, staging, system and combined populations
remain intentionally unselected: hosted CI owns exhaustive qualification, and no
current complete-suite override exists. Local Python coverage, dependency/
package/lock/runner-policy/native-class changes, builds, model studies, live
targets, public push/CI, main/tag/release and full W5-W8 acceptance are unselected.

Hosted CI state for a new campaign: UNKNOWN; no capacity is inferred. Remote
write/trigger: none. Expected automatic lanes: none. Execution classification:
not applicable to this local checkpoint. Current-source hosted gates and desired
87/82 branch cushions remain pending; CI140 qualifies only its earlier source.
Spent application50/Rust20/wheels44 are not rearmed. New dispatches use
dynamic_default. This source joins the larger useful milestone batch.


## Independent review and parent disposition

One approved read-only claude_only checkpoint found no code correctness defect.
The parent reconciled all19 reviewer copies, exact hashes and every granted
stage's bounded native reads. The primary had zero grants; absent capture does
not prove tool absence. The closer read only scope/evidence and deferred writing
the two low-severity accuracy corrections to the parent.

The parent corrects both details: collision locals13→14 and put locals20→21 are
explicitly covered by the bounded legacy exception, and the RED helper SHA-256
is extracted from its original full canonical receipt. The curated projection
had omitted that value; the immutable canonical receipt already contained it.
Only documentation/evidence changes follow review. All executable and quality
metadata bytes remain identical to the reviewed copies and applicable proof.
Fresh document checks are required before commitment. No product tests need
repetition for these accuracy-only corrections, and the conditional second
checkpoint is unnecessary. The phase-specific exception closes after this
checkpoint; future dispatches return to dynamic_default. No new build or public
campaign is implied. Hosted and whole-roadmap gates remain pending.
