# CLOE resource governance5 source Exit

Phase: `REPOMAP-CLOE-RESOURCE-GOVERNANCE5`. Date: 2026-11-12.
Disposition: bounded source accepted; hosted qualification remains pending.

## Changed boundary

ADR0186 derives per-family admission from the encoder's existing remaining byte
and record limits, before buffering/spilling. One overflow row may be acquired
and encoded but is not buffered/written. Output and trailer checks remain.
Earlier invalid-input refusal can preempt later faults; accepted bytes and all
existing category vocabulary remain. Adapter and worker-terminal precedence
are distinct. Direct sorter callers without budgets retain aggregate behavior.

Owned incremental merge levels cap fan-in at32 inputs plus one output. Partial
outputs are registered before writing, old inputs are removed only after a
successful output close, and normal cleanup failure aborts progress. Actual
primary failures survive all-owned cleanup. The counters retain ingress meaning,
not total rewrite IO. Prepared-row and store-temporary costs remain separate;
there is no whole-worker hard quota or measured speed claim.

Verification now keeps descriptor/raw custody through fstat, identity, reference,
fdopen and verifier construction. Existing safe error conversion, expected
version, factory seams and verification-context failure precedence remain.
There is no new asynchronous/hostile-path or reused-fd guarantee.

## Exact scoped proof

Eight initial RED cases reproduced both late-consumption defects, unbounded
fan-in and five descriptor-acquisition leaks. Repairs plus partial write/flush/
close/read, cancellation, unlink, source-failure and consumer-close cases pass.
Canonical floats remain refused; valid Unicode/integer/duplicate lines and all
seven-family reference bytes/checksums remain exact.

Initial checkpoint1 unit:81 passed, --no-coverage, --jobs1. Exact selectors:

```text
src/test/unit/python/repomap_kg/artifacts/bundle_sort_resources.unit.test.py
src/test/unit/python/repomap_kg/artifacts/store_verify_custody.unit.test.py
src/test/unit/python/repomap_kg/artifacts/bundle_cancellation.unit.test.py
src/test/unit/python/repomap_kg/artifacts/bundle_stream.unit.test.py
src/test/unit/python/repomap_kg/artifacts/bundle_stream_contract.unit.test.py
src/test/unit/python/repomap_kg/artifacts/store_producer_custody.unit.test.py
src/test/unit/python/repomap_kg/artifacts/bundle_sort_failures.unit.test.py
src/test/unit/python/repomap_kg/artifacts/filesystem_faults.unit.test.py
src/test/unit/python/repomap_kg/artifacts/stores.unit.test.py::test_filesystem_and_memory_store_read_get_stream_verify_parity
src/test/unit/python/repomap_kg/artifacts/stores.unit.test.py::test_filesystem_store_locator_mismatch_and_stale_version
src/test/unit/python/repomap_kg/artifacts/stores.unit.test.py::test_filesystem_store_idempotent_put_and_collision_detection
```

Containerized integration:29 passed on the same current production bytes.
After extracting the actual IO observer, the changed worker owner was rerun:
8 passed, with all other original owner function bodies and selected files
unchanged. These are scoped diagnostics, not hosted qualification or Python
coverage. The in-process adapter witness forces multi-level IO inside its attempt, preserves
exact bundle bytes and proves the test fan-in3 bound of four sorter handles.
Overflow consumes only one proving extra row and leaves the sealed store objects
unchanged. The PostgreSQL corpus includes16 maintained publications and
accepted-marker/family preservation after refusal, plus post-finalize rollback.
Exact initial containerized selectors (--suite int --no-coverage,
--pg-container-port55433, --jobs1):

```text
src/test/int/python/repomap_kg/coordinator/portable_spool_custody.int.test.py
src/test/int/python/repomap_kg/coordinator/portable_worker_discovery_elision.int.test.py
src/test/int/python/repomap_kg/storage/str_pub5_portable_publication.int.test.py::test_direct_one_source_portable_refresh_into_disposable_postgres
src/test/int/python/repomap_kg/ops/first_use_workload_local.int.test.py
src/test/int/python/repomap_kg/coordinator/portable_durable_readback.int.test.py::test_worker_produced_portable_bundle_durable_publication_readback_and_reconciliation
src/test/int/python/repomap_kg/storage/str_pub5_portable_publication.int.test.py::test_seven_family_post_finalize_fault_preserves_graph_receipt_and_authority
```

The final corrective integration selection is the first file listed above,
portable_spool_custody.int.test.py. All test executions preserve source/HEAD/
index and prove cleanup; host Docker resource sets are unchanged. The existing
unit runner's Go-helper bootstrap is not a Python coverage claim.

Every static quality profile passes: full source census, ownership, retained
Ruff/mypy/import/length ratchets, clean tests/support/tools/fixtures/conftest,
and cohort closure. Five additive owners comprise one retained product module with zero new
findings and four clean test/support owners. Two new cohorts preserve every
inherited row/order/rule and numerical debt. All edited
Python owners remain at most400 lines. Topology, public export, suppression,
compilation, file-length and diff checks pass; final documentation check follows.

Complete local unit, integration, smoke, staging, system and combined populations
remain intentionally unselected under the scoped-testing policy. No local
Python coverage, dependency, package/lock, runner-policy/native class, new image,
SDK/application build, model study, public campaign, main/tag/release or full
W5-W8 acceptance is claimed. CI140 qualifies only its earlier source; desired
87/82 branch margins stay pending. Spent application/Rust/wheel counters50/20/44
and the prior two-checkpoint claude_only exception are not rearmed. New APGR
dispatches use dynamic_default; this local checkpoint joins a larger milestone.


## Corrective source proof

The first source review found no blocking code defect but identified gaps in
failure cleanup, boundary evidence and documentation. Its read audit left
store-common lines101-161 unread, so that checkpoint is not final conforming
acceptance. The parent preserves its technical findings without accepting the
all-input claim.

Corrections check run cleanup before the real owned-directory fallback, both
in unit failures and the in-process adapter integration. The deliberate secondary
unlink refusal leaves exactly that refused file until fallback; the source
primary remains primary. Exact equality and later-family byte-boundary tests
observe normal input exhaustion, distinguishing admission from trailer refusal.
Three additional RED cases show invalid fan-in was accepted; it now refuses
before IO. The default private fan-in32 and accepted bundle bytes are unchanged.

Current proof:86 scoped unit cases and29 containerized integration cases pass,
then8 cases in the updated worker owner pass after unused fixture bindings are
simplified. All current production bytes match every proof; final unit owners
and helpers match unit proof, and the current integration owner matches its
recheck. The exact selectors above are unchanged; complete local populations
and Python coverage remain unselected. Every strict static profile passes with
unchanged inherited debt. Corrective independent review remains pending.


## Parent source acceptance

The second approved independent checkpoint closes the reviewed corrections and
the earlier store-common read gap. Parent audits verify every granted stage's
actual bounded reads and returned bytes, all26 reviewer copies and exact hash
attestations. The complete quality/roadmap diffs and actual RED excerpts were
available to this review. All source/test bytes and quality metadata remain
equal to the reviewed copies; only parent adoption wording follows the review.
Final documentation/topology/export checks are required before the local commit.

The RED runs describe their historical test bodies; canonical receipts also pin
those test-owner hashes. The strengthened assertions are source-reviewed and
GREEN, without claiming a fresh RED run for every final assertion. The IO
observer counts process-wide temporary-file allocations conservatively. Internal
test names are not a native worker qualification or support claim.

The two-checkpoint exception is spent. Future dispatches use dynamic_default;
no third review, automatic retry, new build/model allocation or public CI is
implied. Source acceptance remains separate from hosted and whole-roadmap gates.
