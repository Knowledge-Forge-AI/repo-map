# ADR 0097: Runtime linker-cache repair and one additional bounded AMD attempt

## Status

Accepted design before implementation. The operator approved Route A on
2026-10-26 against decision SHA-256
`36aabdbb9b35dcd540d88cb67b8054e8c89fecc92b9f24fb1c9a569b8fd3544c`.
Independent proposal review and parent disposition precede this record.
Implementation, proof, image, platform, P3, merge and deployment results remain
unaccepted; this record grants only the bounded approved phase.

## Date

2026-10-26

## Context

CI70's unit, staging, static, security and zero-build native exploration jobs
passed. The sole system build failed in the actual final probe because
`/usr/local/lib/libpython3.so` could not resolve `libpython3.12.so.1.0`.
The renderer copies the pinned Python stage's `/usr/local` into the PostgreSQL
runtime and never refreshes that runtime's linker cache. Its exact AMD closure
is empty. The previous two application starts and local proof allocations are
spent; a new attempt requires explicit operator exception to ADR0096.

## Decision

Add one runtime-stage `RUN ldconfig` after the copied Python payload and frozen
closure, before any runtime Python command. Leave the strict final release
probe byte-identical. Dynamic C Psycopg 3.3.6 stays linked to distribution-owned
shared libpq; static or bundled-binary alternatives are excluded. Package,
source, license, hash, ABI, unsupported-platform and build-only-tool refusals
remain. No package manifests, dependencies, locks, base pins or SDK inputs change.

Prove renderer ordering in the existing release-resource unit owner and the
actual cache mechanism in the existing isolated dynamic-linkage integration
owner. Renderer tests cover actual empty AMD and nonempty fixture closures,
exactly one runtime-stage cache refresh before any runtime Python, and preserved
default refusal. Other renderer consumers remain hosted-only. The disposable
dependency-only container executes the complete actual ELF discovery/ldd/owner
block selected structurally from RELEASE_FINAL_PROBE_PY's AST, including its
private-libpq guard, the probe's own stdlib import statement that binds os and
pathlib, and existing shared helpers. Refuse missing/ambiguous structure or
selected psycopg imports. Initialize imports/helpers with intact libraries.
Use no copied predicates,
generic snippet API or production probe change. It may remove its own linker
cache, require the specific libpython failure, refresh with actual ldconfig and
require that entire block to pass, then temporarily remove the exact dependency
and require real ldd/loader refusal. All three phases run in ONE already-live
Python process, which performs the dependency move and its finally restoration.
Match the missing libpython SONAME text, not a first-file traversal order. No new
Python interpreter starts while the library is moved; startup failure and any
unrelated failure cannot satisfy the negative. No Python-child substitute is
permitted. Restore any temporarily moved file in `finally`, remove
the exact container and verify the canonical resource baseline. No host or SDK
root filesystem is mutated and no image is built by this case. This does not
observe PostgreSQL's loader search configuration. The original native preflight
checks Python-base payload and separate PostgreSQL package closure; it never
assembles the copied payload/cache. Earlier runtime Python startup succeeded;
an interpreter-relative lookup is only a hypothesis without pinned RUNPATH
observation. The current probe stops at its first ELF failure, so all later
assembled-image ELF and package predicates remain unobserved. Classify its
positive result as mechanism evidence only; assembled native AMD remains hosted.

Under the explicit Route A approval, allow two further exact scoped executions
per class: cumulative unit11/integration9/static13, all prior attempts counted;
one first and a second only after a finding/correction. Unit expands only by the
affected arch7f release-resource owner to 41 paths; integration keeps its two
owners; --no-coverage and the existing static profile remain. Complete local
suites, local coverage and existing exhausted RED/diagnostic classes stay out.

Under the explicit Route A approval, allow exactly one new native AMD
application start, cumulative total3 and AMD3, solely through the existing
system builder. Append its exception/reservation to the original ledger; never
edit old reservations, limits or observations. Keep default/generic/ARM holds.
An actual or uncertain start consumes the new slot and authorizes no retry.

Bind the closed grant/proof v1 records to the exact reviewed decision and ledger,
fresh source/recipe/Dockerfile, unchanged SDK, PR13 synchronize from the actual
staging a0c1f1d parent against unchanged main24d1565 and workflow71/attempt1.
Explicitly refuse spent CI69/70 nonce/reservation pairs, all other ordinals,
reruns, stale identities and reused/racing intents. Retain host admission before
SDK work and same-inner-daemon preflight before exclusive fsynced intent/build.

The complete implementation scope includes commands.py, existing grant/proof
validation in tools/ci/d12_system_grant.py, the one-use grant JSON and frozen
hosted candidate JSON, the affected existing scoped test owners and fresh
ADR/Exit/handoff records. Grant source is currently 399 lines; keep it <=400
without adding a module or raising a ceiling. Preserve imported CI69 names,
add the CI70 pair and recover the few lines through the identical byte-cap
assignment and compact key-set closings within 120 columns. Keep all closed keys
and predicates. Only grant v1 has maxima3/3; proof v1 changes its ordinal and
binders and retains its validated grant hash. Re-derive changed context digests
mechanically with the existing frozen_identity owner and preserve SDK bytes.
The grant and reservation pin PRE-APPEND ledger hash cc8f1d65...; compute the
canonical reservation/grant from that unchanged state. After all final gates,
verify it unchanged and atomically append the exception/reservation/audit
together immediately before the one push. Do not append an exception first or
silently rebind drift. The frozen public staging candidate is the source/test/metadata target.
Protected private source is preserved; private custody evidence stays outside
the public export.
Metadata derivation executes no tests/static profiles/Docker/builds and earns
no proof credit; record it separately. Do not replay an old one-shot generator.

This narrowly supersedes the old renderer hold only for that cache instruction
and ADR0096's total2/AMD2 no-retry, local9/7/11 and spent candidate binder only
for the newly approved total3/AMD3, local11/9/13, ordinal71/attempt1 exception.
Every historical record and other constraint remains.

Independent review and fresh parent acceptance precede source publication.
One normal staging push may trigger one existing automatic campaign. Main,
tags, history, PR state, manual triggers, infrastructure and live data remain
outside scope. P3/incumbent comparison/image/platform/merge acceptance stays
separate and false or unresolved; system scenarios remain diagnostic.

## Alternatives and residuals

Retaining the hold is valid. Removing or relaxing the `ldd` assertion, masking
the problem with ambient library search variables, copying another stage's
linker cache, static linkage, additional dependencies and automatic retries are
rejected. The current evidence establishes the actual loader failure and a
plausible narrow repair; only the future scoped proof can demonstrate the
mechanism, and only the future hosted build can demonstrate assembly. A later
defect can still consume the entire new slot without yielding an image.
