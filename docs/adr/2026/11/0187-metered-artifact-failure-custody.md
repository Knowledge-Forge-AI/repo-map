# ADR 0187: Preserve metered artifact custody through failure

Status: bounded source accepted by the parent after independently audited
resulting-source review and accuracy corrections; hosted qualification pending.
Date: 2026-11-12. Phase: `REPOMAP-CLOE-RESOURCE-GOVERNANCE6`.

## Context

The metered store acquires a temporary descriptor before permission/stream
setup without a descriptor owner on either failure. Collision comparison
closes temporary then target sequentially, so the first close failure skips
the second. Close failures can replace active directory, verification, producer
or budget failures. Temporary unlink also replaces an active failure.
Buffered stream close is its own seam: its C-level close does not call the
Python os.close attribute. Source inspection is not reproduced failure evidence.

## Decision and preserved contracts

Use explicit custody through temporary descriptor-to-stream transfer, then
exactly one stream close attempt. Reuse open_temporary_stream, including its
fdopen-before-fchmod order; neither operation is counted, mkstemp remains private,
and current permission/write error conversion is preserved. Retain a module
constructor seam. The ordinary unmetered route is unchanged.

Owned raw descriptors have one local cleanup scope. Register each immediately
after acquisition. Attempt temporary then target, removing each from custody
before its close attempt. On normal completion, attempt all and raise the first
OSError. On an active body failure, attempt all while suppressing secondary
OSError, then re-raise the actual primary object. No retry after uncertain close.
Directory/readback open, read and durability mapping stays unchanged; a normal
cleanup OSError still escapes these direct helpers and maps through put as today.

Apply the same explicit normal-versus-failed control flow to buffered stream
close and temporary unlink, following ADR0185. An unrelated caller except block
must not count as this operation's primary. Normal unlink failure remains visible
and returns no reference. After replace clears temporary custody, never delete
an installed object to roll back a later refusal. Make no persistence claim
after failed synchronization or readback.

The new cleanup scopes suppress OSError only. The reused setup helper already
suppresses BaseException from its cleanup while preserving setup failure; that
bounded asymmetry is accepted. A non-OSError during later cleanup can interrupt
release and replace an active failure. No absolute asynchronous interruption,
hostile-path, fdopen-internal-close/reused-fd or closed-fd retry guarantee follows.
No general change to other metered readers or ordinary collision cleanup occurs.

Keep every existing meter admission before its operation. Cleanup never calls
the meter or adds counters. Successful new objects retain3 opens/2 fsyncs;
collisions retain3 opens/1 fsync. Headroom, read request sizing and EOF probes
stay exact. Accepted content, digest, reference, version, private identity and
no-follow checks, default routing and public category vocabulary remain unchanged.
PermissionError maps to permission_denied; other setup OSError maps to
write_failed publication failure with its cause. Non-OSError retains its type.

## Scoped proof and review disposition

Require real-descriptor RED witnesses before repair where practical. Exercise
fchmod/fdopen setup, producer and budget primaries combined with unlink or stream
close failure, and a pure custom BaseException producer without OS signals.
Collision cases cover temporary, target and both close failures, each before
and after actual release and with/without an integrity primary. Observe owned
fd identity, one attempted release, first/primary exception identity, no false
success, actual counters, and preservation of unrelated temporary files.

For buffered close, a test-only proxy delegates actual stream IO and either
releases then raises or refuses release. An os.fdopen constructor seam is valid
because both current and repaired setup reach it; tests retain the real helper
and distinguish this from os.close injection. Hold the proxy explicitly and
reclaim deliberately refused descriptors after observation; no GC proof.
New test-only classes are ordinary fixture code, not a new runtime class policy.
Require one close attempt for each actually acquired stream, zero when none
exists; the closer's blanket every-row assertion is narrowed accordingly.

Use exact canonical unit and containerized integration selectors --no-coverage.
Connected integration exercises public store/sealer setup and budget refusal,
prior manifest/object preservation and exact successful counter/reference parity.
Existing post-install custody and source-fallback owners are regression evidence,
not falsely labelled RED. Fault-injected cases remain in-process witnesses.
No native signal/worker qualification follows. Independent resulting-source
review challenges the complete source, proof and these parent dispositions.

All17 reviewer copies and actual native reads are independently reconciled.
The six review findings are incorporated: real stream-close seam, setup mapping,
BaseException producer, explicit collision matrix, scoped exclusions/asymmetry,
and accurate regression/docstring labels. Producer and closer lacked hash tools
and disclose that limitation; the reviewer supplied all17 exact hashes.
The parent also inspected the ordinary filesystem implementation and source
sealer; their routing and existing temporary helper match the stated contract.

## Alternatives, limits and rollback

Status quo retains the gaps; setup-only repair leaves failure cleanup defects.
A broad resource framework or ExitStack conversion adds unnecessary precedence
semantics. Coordinated source/tests reversion requires no data migration.
No new dependency, package/lock, runner policy/native class, public protocol,
schema, image, application/SDK build, model study, full local suite, local Python
coverage, live target or remote action is granted. All inherited quality/debt
ceilings remain; register only clean additive owners. Future dispatches use
dynamic_default. Spent CI140 application50/Rust20/wheels44 are not rearmed;
coverage cushions and full W5-W8 acceptance remain separate.
