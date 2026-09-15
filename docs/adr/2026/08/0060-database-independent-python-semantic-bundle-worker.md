# ADR 0060: Database-Independent Python Semantic Bundle Worker

## Status

Accepted architecture with the STR-WORK4-FIX3 local implementation complete.
ADR 0061 selects the worker for the STR-PUB5 local production route. Hosted complete
integration and assembled-product qualification remain pending.

## Date

2026-08-31

## Context

ADR 0059 established sealed snapshot, receipt, bundle, store, and publisher-validation
contracts but did not provide a real semantic worker. The production refresh worker
still carries PostgreSQL and source-root authority. RepoMap needs one process that can
reuse the current Python semantic engine while holding neither authority.

The STR-WORK4 opening audit also found tightly coupled seam defects: four portable
terminal categories were absent from the protocol vocabulary, failure outcome was not
bound to `error_category`, nested manifest objects accepted unknown fields and coerced
revisions, and pipeline integration owners were placeholders.

## Decision

Implement `repomap_kg.coordinator.portable_worker` as the sole portable worker
entrypoint. Its parent creates one owner-private `PortableExecutionCapability` version
1, launches it through the existing managed-process boundary, supplies a closed
environment and private working directory, and removes the capability. The capability
contains only the exact job/attempt, semantic generations, filesystem artifact-store
root, attempt workspace root, immutable manifest reference/version, and byte bounds.

The worker negotiates ASYNC1 `portable_snapshot_v1` contract `1.0`, verifies the exact
request and capability identity, consumes canonical manifest bytes from
`FileSystemArtifactStore`, and materializes only verified regular files into one
private attempt directory. The manifest additively carries locator-free semantic
binding fields needed to reproduce the incumbent path; legacy STR-SEAM3 manifests
without those optional fields retain identical canonical bytes and decode behavior but
are refused by this worker as `unsupported_contract`.

`graph.multi_source_pipeline.capture_sealed_multi_source_candidate` is the supported
adapter seam. It constructs the same `OpsGraphConfig` semantics over command-owned
materialized roots and calls `capture_multi_source_candidate`; coordinator code does
not import `_CapturedSource`, `_module_exports`, or `_binding_view`. The worker then
uses `build_staged_rows` for all seven families. The successful path emits deterministic
`bundle1:` and `receipt1:` artifacts. The receipt is untrusted producer evidence.
Publication remains `not_started` and no accepted-publication identity is emitted.

## Authority Boundary

The worker receives no PostgreSQL, control-store, registry, target source-checkout, Git,
provider, network, lifecycle, arbitrary-command, or publication authority. It does not
invoke the staged publisher. The process boundary is an allowlisted authority boundary,
not a hostile-code sandbox. A runtime audit guard additionally rejects database and
publisher imports, network/socket operations, subprocess/exec operations, and filesystem
access outside the store, command workspace, and trusted interpreter, standard-library,
installed-dependency, and RepoMap package roots. Reads never grant writes. Fork,
forkpty, spawn, exec, shell/system, network/DNS, database, registry, lifecycle, and
publisher authority are denied. Static extraction remains non-executing.

## Compatibility And Activation

Legacy protocol messages remain decodable. STR-WORK4 supplies the launch adapter and
offline parity harness; ADR 0061 owns production bundle consumption, receipt
reconciliation, route selection, cutover, and rollback.

## Verification And Consequences

Focused owners compare the real managed worker's decoded seven-family bundle with
incumbent pre-publication rows for public one-source and multi-source Nix fixtures after
temporary harness-owned source copies removed. Caller-owned source roots remain in place
and byte/mode/identity stable throughout. They prove relocation-invariant bundle
and receipt bytes for one exact attempt, validator idempotency, deterministic worker
replay, conflicting-attempt and failed/cancelled-to-completed rejection, the complete
typed failure vocabulary, deterministic internal and parent-wait cancellation, exact
workspace/capability/process settlement, primary-failure precedence, and behavioral
runtime-authority denial through the installed worker guard.

Current portable bundles declare `stage-unassigned-v1` and every row carries only the
fixed non-authoritative placeholder. The explicit `legacy-absent-v1` decoder accepts
only older headers without the contract field and rows without `stage_id`; mixed and
physical-stage shapes fail. The attempt remains part of the
bundle header and identity. Only semantic family rows are independent of a future
publisher-owned PostgreSQL stage identifier.

Pipeline integration owners drive the real managed process for negotiation, typed
failures, cancellation, authority denial, crash, parity, replay/conflict, cleanup, and
publisher validation without publication. They are executable but intentionally
unselected locally under TEST-ISO2. PostgreSQL bundle ingestion and assembled-product
route owners do not exist until STR-PUB5 implements that route.

After negotiation, failure-receipt denial cannot erase the primary terminal: current
failed/cancelled extensions allow `receipt: null` only with a closed bounded
receipt-write diagnostic. Completed output always requires both receipt and bundle.
All terminal classes remain `publication_state: not_started` and cannot create
`commit_unknown`.

PostgreSQL remains canonical graph authority and the current staged publisher remains
the only production mutator. Hosted integration and assembled-product evidence remain
pending.
## STR-WORK4-FIX3 Authority And Cleanup Corrections

The parent creates one private attempt root before launch, derives the child
capability workspace from that root, places the process CWD and all
materialization below it, records the root device/inode/owner identity, and
reclaims that exact root after process-tree settlement. Cleanup is recursive,
no-follow, and refuses identity substitution or unexpected nodes; a bounded
cleanup diagnostic does not rewrite the primary terminal outcome.

The installed Python audit hook performs real-operation denial for network,
process, prohibited import, filesystem enumeration, and filesystem mutation
events. Reads are limited to exact runtime/package, store, and attempt roots;
writes are limited to the attempt root and store object/temporary roots.
Relative paths are normalized, `dir_fd` mutation forms are refused, and both
paths of rename/link operations are checked. Events outside standard CPython
filesystem audit coverage (such as direct `os.truncate`, `os.chown`, `os.utime`,
or `os.setxattr`) are not separate audit events and descriptor paths bypass
symlink component checks. This remains a Python audit-hook capability boundary,
not an OS-grade hostile-code sandbox.

Focused evidence is labeled as natural production conditions,
test-authorized conformance injection, or protocol validation only. These
labels describe what the owner proves; they do not promote candidate evidence
into publication authority.
