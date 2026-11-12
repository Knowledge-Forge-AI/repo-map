# ADR 0184: Elide discarded sealed-worker discovery hashes

## Status

Accepted by the parent for scoped source implementation under
`REPOMAP-CLOE-RESOURCE-GOVERNANCE4`, after the independent source-backed design
checkpoint and its F1–F10 amendments. Bounded implementation and resulting-source
review are accepted; hosted qualification remains pending. Date: 2026-11-12.

## Context

ADR0177 X4 deferred worker-side discarded discovery hashing. The portable
worker materializes verified inputs, then captures a staged semantic copy and
rechecks the complete snapshot vector. Each capture pass first computes a
discovery digest that `_capture_files` unconditionally replaces with its own
stable-read digest. Classification results remain necessary; those two
discovery digest computations have no consumer.

The existing `_sealing_scan` avoids classification altogether and constructs
snapshots directly. It has no placeholder convention and depends on sealing
meters. Its semantics and imports are unsuitable for worker classification.
The existing discovery-reader protocol supports a smaller, graph-local hook.

## Decision

Add a closed graph-local discovery hook that keeps traversal and classification
readers and replaces only the discarded hash read with an open-time probe.
The probe opens with the incumbent follow-symlink semantics and available
`O_NONBLOCK`/`O_CLOEXEC` flags, checks directory failure and closes its exact
descriptor. It returns a deliberately non-hex provisional value. Stable
capture replaces that value before a snapshot or observation is constructed;
`SnapshotManifestEntry` rejects it if it leaks to that boundary.

An explicit keyword-only `elide_discovery_hash=False` on the capture facade
selects the hook for both inventory passes. Sealed capture selects it;
ordinary capture and discovery retain their defaults. The inventory helper
rejects a non-boolean flag or combined elision/metering before exception
mapping. There is no branch on whether a function was patched for a test.

Classification delegates to the incumbent module globals at call time,
including `is_zsh_completion_candidate`. Traversal uses ordinary `os.walk`;
patching the discovery facade's `os` binding is not a new supported seam.
No artifacts, ops or coordinator dependency enters the discovery import closure.

Both stable reads, the staged extraction copy, source-vector checks,
classification results, semantic/candidate identities, family checksums and
publication encoding remain. The expected reduction is two discarded full
hash calls per selected file. This is a source-backed operation-count forecast,
not measured latency, physical-I/O, memory or whole-worker savings.

## Failure and cancellation boundaries

The probe preserves initial missing-file, directory and permission failures.
A mid-body read failure is observed by the authoritative stable reader rather
than the discarded discovery reader. This changes the observation stage while
remaining a capture refusal. Mutation and final-vector checks remain.

Only extension-classified paths that reach the hash probe gain its nonblocking
FIFO/device behavior. Go-generated, shebang and completion classification may
read earlier and remain subject to their incumbent native-I/O limitations.
This decision does not qualify general FIFO/device preemption or a hard deadline.
Available flags do not establish Windows support. Existing cancellation and
cleanup ownership remain; new OS-signal scenarios are not selected.

## Row encoding and follow-up work

Raw `RowSpool` JSON is not a canonical publication record: Unicode encoding,
the integer-only canonical domain and the record envelope differ. Keep the
current encoder. No `trust_encoded` option, byte transcoder or duplicate
canonicalizer is admitted. The source review also identified spool lifetime
and worker failure-state observations. They require their own concrete design
and acceptance before implementation; they are not silently bundled into a
serialization optimization.

## Proof and scope

Scoped unit owners must witness real hash and stable-read calls, preserve
ordinary discovery, test open/probe/delegation failures and reject a leaked
provisional digest. Compare complete candidate, observations, resolutions,
generation identities, family rows/checksums and bundle bytes on multiple
bindings, aliases, Unicode, executable/empty files and classification readers.
The witness window excludes materialization and staged-copy extraction.

Real containerized Local and PostgreSQL integration must validate worker
receipts, publication readback, accepted-marker preservation on refusal and
owned cleanup. The existing durable-publication readback owner supplies the
Server baseline; a named new parity owner must cover the changed boundary.
Required integration gaps block source acceptance. Exact selectors and results
belong in the phase exit and commit. Use canonical scoped `--no-coverage` runs.

Preserve quality roots, debt ceilings, file-length rules, measured/abrupt
roles and coverage denominators/floors. No dependency, image, runner-policy
class, schema/role, installed CLI/MCP/config/report/protocol or live target is
changed. No model, held-out, complete local suite, local coverage, application
or SDK build, or remote mutation follows from this decision. Batch useful
source work before a separately bound public campaign.

## Alternatives and rollback

Reusing the sealing scan would remove required classification. Reusing its
meter would introduce the wrong dependencies and accounting. Bypassing the
facade would lose established patch seams. Removing stable reads or the staged
copy would weaken source authority. Keeping all current reads remains a safe
rollback: revert the hook selection, with no stored-data migration.
