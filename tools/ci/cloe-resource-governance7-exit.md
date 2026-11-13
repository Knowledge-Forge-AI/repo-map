# REPOMAP-CLOE-RESOURCE-GOVERNANCE7 Preparation Work Exit

Status: bounded source accepted after independently audited review and parent
wording corrections. Hosted qualification remains pending.

## Scope and behavior

ADR 0190 adds call-owned admission for the portable worker's prepared spools,
derived only from its selected bundle byte and record limits. One shared
spooled-record total and aggregate family payload admit equality, refuse before
the proving write, and retain their state on refusal. The encoder still owns
final bundle, line and framing validation. Earlier refusal of inevitably invalid
data is intentional; default storage callers retain their existing path.

The owned worker now cooperates with cancellation during actual row acquisition,
buffer replay and spool admission. Controlled preparation closes acquired
iterators and every directly created family source, attempts all owned releases,
preserves the actual active primary and surfaces the first normal close error.
Completed spools are reclaimed if a later owned iterator close fails. There is
no retry of an uncertain release and no native preemption claim.

The spool-to-bundle bound applies to ordinary owned JSON-shaped worker rows,
whose recursive checksum validation excludes non-string payload keys before
spool serialization. It does not cover adversarial key subclasses or concurrent
mutation. Memory families remain bounded by the existing row threshold, not
Python byte size. The conservative temporary payload calculation is 4B plus
materialized source, metadata, buffers, allocation and existing objects; this is
not a whole-worker disk, RSS or operating-system quota.

## Executed proof

All commands use the canonical tools/run_tests.py runner, --jobs 1 and
--no-coverage. Integration executes in the existing disposable container sandbox
with its existing PostgreSQL harness; no SDK or application image was built.

Unit: 151 passed in 64.93s (0:01:04)

```text
src/test/unit/python/repomap_kg/storage/preparation_work.unit.test.py
src/test/unit/python/repomap_kg/storage/preparation_iterator_custody.unit.test.py
src/test/unit/python/repomap_kg/storage/staged_spool_custody.unit.test.py
src/test/unit/python/repomap_kg/storage/row_spool_custody.unit.test.py
src/test/unit/python/repomap_kg/storage/row_spool.unit.test.py
src/test/unit/python/repomap_kg/architecture/arch1d_dependency_dag.unit.test.py
src/test/unit/python/tools/ci/retained_python_projection.unit.test.py
src/test/unit/python/tools/ci/retained_python_ratchets_scope.unit.test.py
src/test/unit/python/tools/ci/python_retention_inventory.unit.test.py
src/test/unit/python/repomap_kg/storage/arch6c_pipeline_lifetime_measurement.unit.test.py
src/test/unit/python/repomap_kg/artifacts/bundle_sort_resources.unit.test.py
```

Integration: 22 passed in 79.69s (0:01:19)

```text
src/test/int/python/repomap_kg/coordinator/portable_spool_custody.int.test.py
src/test/int/python/repomap_kg/coordinator/portable_worker_discovery_elision.int.test.py
src/test/int/python/repomap_kg/coordinator/preparation_publication.int.test.py
src/test/int/python/repomap_kg/ops/first_use_local.int.test.py
src/test/int/python/repomap_kg/ops/first_use_server.int.test.py
src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py
```

Actual large sealed inputs exercise record/byte refusal. The buffered file-size
observations alone do not prove that no prohibited write occurred; that guarantee
is established by the unchanged RowSpool observer-before-handle.write order,
combined with the admission refusal tests and independent source review. Real spawned Local and PostgreSQL refreshes preserve the accepted
publication pin through early preparation refusal, then recover after restoring
the normal capability. Progress reaches canonicalization and not storage_prepare.
These are distinct from in-process cancellation and injected data-error ordering;
the worker's existing terminal-event precedence is unchanged. Existing Local,
Server, mixed-source, discovery, spool, measurement and sorter owners also pass.

The initial unit RED failed at the absent optional API; it does not alone prove
mid-row cancellation timing. Two actual integration RED cases demonstrate the
old excess byte/record spooling. Full selected preimages and original immutable
failure receipts are retained privately. Later static setup failures exposed an
inapplicable product cohort, missing retained enrollment and an unused import;
those were corrected without rewriting their historical outcomes.

All retained/type/cohort profiles pass. Three clean retained product owners,
three clean test owners and one test cohort are additive. Existing ownership,
profile ordering and every numerical debt ceiling remain unchanged. The exact
forward-admission lineage witness includes this phase. New helpers avoid Red
complexity. The existing build_staged_rows routine retains 14 branches and 12
locals; three necessary check calls raise statements 39 to 42 and the optional
argument raises parameters 7 to 8. The parent accepts that bounded legacy
change rather than broadening this slice into a facade rewrite.

Topology, export, file-length, suppression, compile, whitespace and privacy
checks pass for the frozen review bytes. The independent resulting-source
review includes the recursive checksum, row-adapter and measurement owners
omitted from the earlier design grants. The parent reconciled all 27 reviewer
grants, exact hashes and every granted stage's bounded reads. The zero-grant
primary has no capture; this does not prove tool absence. The closer read only
scope/evidence and deferred the two wording corrections to the parent.

## Boundaries and continuation

No complete local unit, integration, smoke, staging, system or combined suite
was selected; no current complete-suite override exists. Local Python coverage
was not measured. No dependency, package/lock, image, runner-policy/native class,
schema, CLI/MCP/report contract, model/held-out study, live runtime or release
change is selected. Static extraction and read-only MCP remain intact.

CI142 passed only its exact published source. Its cumulative application 51,
qualifier-command 22 and wheel-transfer 46 slots remain spent; actual Rust
component invocations are 21. Unit and integration coverage cushions remain
5 and 498 branch arcs short at that source. This slice makes no coverage claim.

Hosted state: operator AVAILABLE; no remote write or campaign is selected for
this local checkpoint, so no automatic hosted lane is expected. Current-source
hosted qualification remains pending. New APGR dispatches use dynamic_default.
This slice stays local within the larger connected milestone, pursuing useful
10k–100k changed lines without padding. W5/W6/W7/W8 completion remains open.


## Review disposition

The independent checkpoint found no code defect. Both low findings are corrected:
the roadmap now records completed source/scoped proof, and this exit separates
buffered file-size observations from the source-order guarantee. The parent also
inspected canonical_rows: each directly created _iter_* source is a fresh
generator. That owner was not read by the reviewer. RED test preimages differ
from final owners; no identical-assertion provenance is claimed. The structure
fallback ambiguously pairs two unchanged test constructors, without affecting
production metrics or debt. Original receipts remain immutable.

No executable or quality metadata changed after review. Fresh document checks
precede commitment; no product test repetition or second independent checkpoint
is needed for these wording-only corrections. The unused conditional checkpoint
closes with this phase. Future phases return to dynamic_default. Source is
accepted only within this bounded claim, not hosted or whole-roadmap qualified.
