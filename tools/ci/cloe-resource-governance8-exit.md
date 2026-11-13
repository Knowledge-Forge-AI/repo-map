# REPOMAP-CLOE-RESOURCE-GOVERNANCE8 Bounded Materialization Exit

Status: bounded source accepted after independently audited review and parent
advisory dispositions. Hosted qualification is
pending for this successor. ADR0191 records the design and accepted changes.

## Behavior and ownership

Materialization uses the existing open_stream interface and bounded source copy
and destination readback. It independently checks actual EOF, size and SHA-256,
handles partial writes, verifies destination identity, and retains exclusive
private creation, final permissions, exact view/byte totals and accepted output.
The existing capability/ref bounds remain; no new numeric input policy exists.
Existing per-artifact checkpoint callbacks retain their frequency; a separate
optional private IO callback checks actual chunk, partial-write and readback work.

Every directly acquired source context and destination descriptor has one
explicit release attempt. Source __exit__ receives the actual active exception;
an enter failure attempts close once. A truthy exit cannot suppress a failed
copy. All owned releases are attempted; the actual body primary survives later
copy-local cleanup failures, while normal release failure remains visible.
Uncertain releases are not explicitly retried.

Only individual source OSError is normalized to the existing corrupt artifact
category. Existing artifact bounds/stale/corrupt errors pass through unchanged;
destination and callback failures keep their own identity. Filesystem excess
is a bounds failure from the store; independent corrupt checks defend against
nonconforming custom readers. A private partial destination can precede source
EOF, and the first reached destination fault can preempt a later source fault.
Both changes are intentional and tested. Completed views remain all-or-nothing.

Legacy outer workspace cleanup/refusal precedence is unchanged: it can replace
an active body failure. The test characterizes that behavior and explicitly
reclaims its fixture-owned residual after observation. Likewise one uncertain
source close is deliberately held long enough to prove no subject retry, then
reclaimed by the fixture. These are not subject cleanup-PASS claims for refused
releases. Default real execution and all test-owned resources close normally.

## Executed proof

The baseline RED2 recorded whole source/readback buffers of 196609 bytes and
196609 bytes actually consumed/written after the cancellation hook fired. That
hook runs on both legacy read and new stream paths; the category alone is not
the witness. The first RED retained the failures without byte values; RED2 adds
only assertion diagnostics before source repair. Both full selected preimages
and original receipts are retained, without claiming final test hashes match
their earlier versions. The GREEN witness admits at most 65536 source bytes and
performs zero destination writes before cooperative cancellation.

Canonical commands use tools/run_tests.py, --jobs 1 and --no-coverage. Integration
runs in the existing authenticated disposable sandbox and PostgreSQL harness.

Unit: 193 passed in 57.84s

```text
src/test/unit/python/repomap_kg/coordinator/materialization_streaming.unit.test.py
src/test/unit/python/repomap_kg/coordinator/materialization_source_contract.unit.test.py
src/test/unit/python/repomap_kg/coordinator/materialization_custody.unit.test.py
src/test/unit/python/repomap_kg/coordinator/materialization_destination.unit.test.py
src/test/unit/python/repomap_kg/coordinator/portable_materialization.unit.test.py
src/test/unit/python/repomap_kg/artifacts/stores.unit.test.py
src/test/unit/python/repomap_kg/artifacts/store_verify_custody.unit.test.py
src/test/unit/python/tools/ci/retained_python_projection.unit.test.py
src/test/unit/python/tools/ci/retained_python_ratchets_scope.unit.test.py
src/test/unit/python/tools/ci/python_retention_inventory.unit.test.py
```

Integration: 45 passed in 122.85s (0:02:02)

```text
src/test/int/python/repomap_kg/coordinator/materialization_custody.int.test.py
src/test/int/python/repomap_kg/coordinator/materialization_publication.int.test.py
src/test/int/python/repomap_kg/coordinator/preparation_publication.int.test.py
src/test/int/python/repomap_kg/coordinator/portable_spool_custody.int.test.py
src/test/int/python/repomap_kg/coordinator/navigation33_worker_disposition.int.test.py::test_portable_and_refresh_worker_startup_refusals_and_materialization
src/test/int/python/repomap_kg/ops/first_use_local.int.test.py
src/test/int/python/repomap_kg/ops/first_use_server.int.test.py
src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py
```

Unit proof covers empty/one/exact-chunk/next-byte data, both supported stores and
reference-version forms, short/custom/malformed readers, independent source
digest/size/bounds guards, source acquisition/read/exit and destination acquisition/
partial write/readback failures, cancellation, all-owned release ordering,
truthy-exit refusal and legacy outer precedence. Faults use real owned files
and descriptors; injected failures are labelled, not OS-permission guarantees.

Integration proves exact reference bundle bytes and semantic authority over a
real 4201-function multi-chunk source. Twenty-one adapter/IO fault cases preserve
categories, store objects and owned-workspace cleanup; deliberately nonconforming
source wrappers exercise the boundary without claiming a conforming backend.
Actual spawned Local/PostgreSQL workers preserve accepted publication pins after
per-artifact bound refusal, then recover. Existing preparation/spool, startup,
Local/Server/mixed first-use owners also pass. Adapter injections do not claim
native signal or terminal-order qualification; worker terminal precedence stays.

Existing real setup and accepted-pin fixtures are shared with the preparation
owners, retaining their test node names. The two proof owners with new Red-local
growth were given cohesive operation/observation helpers; no new Red growth
remains. Five initial test typing findings were corrected without suppressions
or debt relaxation. All product, test/support, fixture, tools and clean cohort
profiles pass. Two product modules, six test owners and three support owners are
additive, with exact forward-only lineage and unchanged inherited numerical
debt/profile ceilings. Topology/export/length/compile/privacy/suppression and
whitespace checks accompany the frozen review and final commit.

## Resource limits and continuation

Copy-owned transient payload is conservatively <= two 65536-byte chunks plus the
store reader, hashes and Python overhead. At most two directly owned file
descriptors overlap; readback follows source/writer release. Destination payload
cannot exceed the existing declared bounds. Memory/custom stores and callbacks
retain independent allocation, and individual IO/hash/stat/cleanup calls remain
non-preemptible. No RSS, physical-disk, CPU/OS quota or timing/speedup claim.

CI142 qualified only its exact published source. Its measured integration
had seven branch arcs above the hard 80 floor and 498 short of the desired 82
cushion; successor fault proof addresses real affected contracts, not a measured
coverage claim. All floors, denominators, exclusions and desired 87/82 targets
remain unchanged. Hosted measurement of this successor is still pending.

No complete local unit/integration/smoke/staging/system/combined suite was
selected: no current full-suite override exists. Local Python coverage was not
measured. No dependency, package/lock, image/SDK, runner/native class, model or
held-out study, schema/CLI/MCP/report vocabulary, live/installed runtime, main,
tag or release change occurred. Extraction stays static and MCP read-only.

Hosted state is operator AVAILABLE. No remote action or campaign is selected
for this local source checkpoint; no automatic lane is expected yet. It joins
governance7 in one connected roadmap milestone before a fresh exact staging
binding. All prior application 51/qualifier-entry22/wheels46 slots stay spent.
New dispatches use dynamic_default. Scoped source proof and pending independent
review do not establish whole-candidate, full W5-W8, image/platform or release
acceptance. Batch useful work toward the 10k–100k line aim without padding.


## Independent review and parent disposition

One dynamic_default checkpoint reconciles all 29 reviewer grants and all granted
primary/reviewer/closer bounded native reads. The primary inspected scope and
evidence only; the closer did likewise. No blocking defect was found. Three
low advisories are dispositioned without executable changes: clarify that chunk
checks follow acquisition, require the existing conforming BinaryIO.close
contract, and correct the lineage-only scope description in an appended parent
addendum. Original proof and frozen review artifacts remain immutable.

The ADR and exit were hash-bound through grant manifests and the frozen source;
the primary's evidence did not repeat those fields. Parent checks bind both
RED2 product files to the source parent and verify all actual selected 193/45
canonical executions. The reviewer mapped 49 unit and 24 integration cases to
read code and disclosed the remaining bounded scopes; whole-file or whole-suite
independent inspection is not claimed. Source/fixture extraction bodies and the
lineage consumer remain explicitly scoped. Embedded preimage hashes were checked
by the parent before assembly; the reviewer attested the composite grant only.

Iteration history is retained: RED1/RED2 reproduce two failures; RED2 adds byte
telemetry. Unit feedback 6/84/189 culminates in 193, integration 23 in 45. Five test
typing findings and the separate new-local complexity signal were corrected;
every final quality profile passes with no numerical debt change. Earlier passes
are not summed into final counts. Local/Server native bound refusal proves the
existing up-front store guard and recovery; custom-stream tests prove the new
copy-level fallback. Short/digest failures can follow admitted earlier writes;
there is no promise that all source validation precedes every write.

Only documentation/evidence corrections follow review. Fresh document checks
precede commitment; product-test repetition and a second source checkpoint are
unnecessary for these advisory clarifications. The accepted source stays local
in the connected batch. Hosted coverage and full roadmap gates remain pending.
