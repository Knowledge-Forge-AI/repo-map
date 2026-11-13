# ADR 0191: Stream bounded materialization with cooperative copy cancellation

## Status

Parent-selected ordinary W7 implementation after an independently audited
18-copy design checkpoint and five required/advisory corrections. Source and exact scoped proof pass. Independently audited resulting-source
review and parent advisory dispositions accept this bounded source; hosted
qualification remains pending.
Phase: REPOMAP-CLOE-RESOURCE-GOVERNANCE8.

## Date

2026-11-13.

## Context

MaterializedWorkspace currently calls store.read for each entire artifact,
retains it through writing and reads the entire destination again. Cancellation
checks occur only before each artifact. ArtifactStore already requires
open_stream; both supported stores implement it. Filesystem streams validate
actual EOF, digest, size, identity and store version. Memory streams return an
unchecked BytesIO around already validated store data. This change bounds the
materializer's copy buffers; it is not a whole-store or worker memory limit.

The worker's existing per-artifact callback also invokes the private
during_materialization checkpoint. Calling that callback per chunk would alter
diagnostic hook frequency. The old read API normalizes source OSError into
ArtifactIntegrityError; the stream API exposes some raw OSError. Copying must
preserve the existing source/destination category distinction explicitly.

## Decision and private interfaces

Use private coordinator helpers for source-stream/descriptor custody and
bounded copying/readback. Keep each included owner <=400 physical lines and
new owners clean under the unchanged retained/type/cohort profiles. A small
ownership helper separate from the copy loop is selected to avoid new Red
complexity. No store or worker protocol changes.

MaterializedWorkspace gains only optional io_cancel_check=None. Its existing
cancel_check remains once before each artifact. The portable adapter passes
its existing _cancelled(cancel_event) to the new callback without creating a
new checkpoint name or event. None retains existing default caller behavior.

The private materialize_artifact(store, reference, destination, *, bound,
io_cancel_check=None) returns the verified byte count. Use a local implementation
chunk constant C=65536, following the existing store convention; it is a buffer
size, not a new input quota. Keep existing order, path construction, per-artifact
bound min(capability, reference size), exclusive/no-follow creation at0600,
final0400/0500 chmod, binding roots, view and materialized_bytes contracts.

Acquire and enter the source before creating the destination. Retain both its
original context manager and the returned reader. If __enter__ fails after
open_stream returns, attempt close exactly once while preserving that failure.
Register each destination descriptor immediately after acquisition. Record its
device/inode for readback comparison; this only governs the new private copy's
regular file, not outer workspace ownership or hostile-path admission.

Read min(C, reference.size_bytes - consumed + 1) until an actual empty read.
Do not stop at exactly size or rely on successful __exit__ to establish EOF.
Count and hash source chunks independently, reject non-bytes or a nonconforming
reader returning more than requested, and refuse excess before writing it.
Existing store-raised ArtifactIntegrityError, including bounds and staleness,
passes through unchanged. The fallback corrupt size/digest guard applies to
nonconforming custom streams. Filesystem excess raises artifact_bounds from
the store, before that fallback sees the excess byte. No error is relabelled.

Write each admitted chunk with memoryview partial-write handling and a check
before every actual write. Zero/negative writes retain OSError. Check before
each actual source read and output readback read. The chunk callback first runs
after source/writer acquisition; a direct caller with an already-set IO callback
can therefore create an empty private destination before refusal. The adapter
still runs its existing per-artifact checkpoint before these acquisitions. Callback failures keep
their actual identity and are not interpreted by their message text.

After source EOF and independent size/digest validation, release the source
context and the destination writer, attempting both once even if the first
release fails. On a normal path source __exit__ receives (None,None,None); on a
failed body it receives the actual type, object and traceback. A truthy return
never suppresses a copy failure. Clear ownership before release; never retry an
uncertain descriptor or close. With an active primary, attempt remaining owned
releases and preserve that exception object. Otherwise surface the first release
failure. Secondary notes, if any, contain types only, never private IO values.

Convert OSError from each individual source operation (open, enter, read,
exit/close) into the existing corrupt ArtifactIntegrityError category, retaining
the cause. Never wrap the yielded copy body or destination operations. Existing
ArtifactIntegrityError and callback exceptions propagate unchanged. Destination
OSError remains raw; actual worker mapping is source_capture, with the existing
PermissionError exception mapped to unsupported_capability. In-process adapter
ordering remains distinct from the unchanged worker cancellation-event terminal
precedence.

Open a fresh read-only/no-follow destination descriptor, compare device/inode,
and perform bounded actual size/SHA-256 readback including an EOF/trailing probe.
Mismatch retains OSError("artifact verification failed"). Close readback once,
preserving its active body primary. Only then apply existing permissions and
return a completed view after every entry succeeds.

## Accepted changes and preserved boundaries

A private partial destination now exists before source EOF validation. It is
never exposed in a completed view or published. Exact owned-root cleanup remains.
A destination EEXIST/ENOSPC reached before a late stale/digest/short-source error
now wins, whereas full source validation previously won first. This explicit
first-reached-fault change requires a regression. Each single source/destination
fault retains its category; exact private message text is not a new protocol.

The existing outer __enter__/__exit__ cleanup can replace a primary if root
cleanup itself refuses or fails. Leave that independent precedence unchanged,
characterize it and retain it as a separate failure-custody question. Do not
suppress an identity refusal or claim proven cleanup when it refuses. No shared
temporary helper, hostile-path, link, platform or asynchronous cleanup expansion.

Source manifest path validation already rejects casefold-ambiguous destinations.
Parent inspection confirms that owner and the actual worker mapping; neither
was in the design grants. Final source review must include both full owners.
All discovered constructor callers use the supported filesystem store, and the
store protocol already includes open_stream. No read-only partial store double
was found at that seam. Custom stores still own their implementation/resources and must return a
conforming BinaryIO with read, context management and close. An arbitrary
context manager lacking close is outside that protocol and has no release
guarantee. The copy independently verifies content, not backend internals.

## Resource derivation

For conforming readers, copy/readback requests never exceed C; partial writes
retain only views of the admitted chunk. Use a conservative two-chunk transient
payload bound plus the reader's own buffering, hashing and Python overhead.
At most two directly owned file descriptors overlap during copying; readback
starts after source/writer release. Destination payload never exceeds the
declared reference size. Memory stores may retain the complete object, and
callbacks/custom backends can allocate independently. No whole-worker RSS,
CPU/OS quota, physical filesystem bound or timing/speedup guarantee follows.
Single read/write/hash/stat/cleanup operations remain non-preemptible. Additional
source/destination hashing is an accepted cost of bounded materialization.

## Required proof

Before source repair, use a real artifact larger than3C to reproduce the whole
store read and whole destination readback. For mid-copy cancellation RED, the
hook must fire on both legacy read and stream paths. Observe actual bytes
consumed/written, not merely the eventual cancelled category: old whole content
is consumed/written; new prefix is <=C consumed and zero written. Label any
separate missing-keyword API failure honestly, not as a timing reproduction.

Use exact canonical scoped unit and containerized integration --no-coverage.
Cover empty/one/exact-C/C+1 content, short reads, executable modes, multiple
bindings/nested paths, reference versions, source short/excess/digest/stale,
source open/read/enter/exit failures, no output on early refusal, destination
short/zero/failed writes, partial-write/readback cancellation, corruption and
identity replacement, all-owned releases/no retries/actual primary identity,
legacy root-cleanup replacement, and source-versus-destination fault precedence.
Permission-denial injection must be labelled as such; mode000 is not a portable
denial under a privileged process. No skips or runner-policy changes.

Exercise real spawned Local/PostgreSQL success over multi-chunk source, exact
accepted-pin preservation after actual per-artifact bound refusal and recovery.
Preserve byte-equivalent reference bundles and default discovery/first-use/
mixed-source behavior. Adapter injections are not native signal qualification.
Final resulting-source review includes exact RED preimages/deltas, all changed
owners, complete affected source/error owners and exact scoped evidence.

## Alternatives, rollback and continuation

Keeping whole buffers leaves expensive work unbounded by the copy chunk.
verify-then-copy duplicates IO and leaves a race. copyfileobj/sendfile bypass
the needed cancellation and verification seams. Reusing cancel_check per chunk
alters diagnostic hook frequency. Omitting the materializer's content validation
would blame a nonconforming source on destination verification. Global root
cleanup redesign and dropping the staged capture copy are separate choices.

Revert coordinated source/tests without a data migration. No new dependency,
package/lock, image/SDK, runner/native class, schema/DDL/roles, public CLI/MCP/report
vocabulary, live/installed mutation, held-out/model study, complete local suite
or local Python coverage. No local application/SDK build or acquisition. MCP
remains read-only and extraction remains static-only. This joins the larger
connected milestone; current operator requests its eventual public staging/CI,
but this design grants no campaign or reused spent slot. Fresh exact publication
binding follows accepted source. Full W5-W8/image/platform/release gates stay open.
