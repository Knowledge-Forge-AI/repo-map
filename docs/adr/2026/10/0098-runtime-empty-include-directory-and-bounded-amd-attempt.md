# ADR 0098: Fail-closed removal of the runtime empty include directory

## Status

Accepted design before implementation. On 2026-10-27 the operator approved
Route A against decision SHA-256
`939e0d8b59f027b4ba759228bf1518c0f725f9349e3d0bdf27a8ceda0140b5fa`.
Independent proposal review and parent disposition preceded this approval.
Implementation, scoped proof, image, platform, P3, merge and deployment remain
unaccepted at this design record.

## Date

2026-10-27

## Context

CI71 passed8/9jobs and reached the final release probe's combined absence guard
for four build-only modules and /usr/local/include. The log does not identify
the failing conjunct. Builder-stage module removal/checking passed. COPY of a
cleaned /usr/local into the PostgreSQL base is a merge, so an existing runtime
include directory can remain. Its emptiness is a hypothesis to be tested, not
an observed native AMD fact. All three application starts and local11/9/13
proof ceilings are spent. P3 and image/platform acceptance remain separate.

## Decision

Permit only one runtime RUN rmdir /usr/local/include after COPY, frozen closure
and ldconfig, before runtime Python. Missing paths, symlinks, regular files and
nonempty directories must refuse. Do not delete retained headers recursively or
alter the complete final probe, package checks, loader checks or linking route.

Prove the cached native PostgreSQL base's real empty-directory condition within
the one new clean integration owner. Use no pulls/emulation, no PostgreSQL
entrypoint or SQL, and an exact run-owned networkless container with declared
data-volume path on tmpfs. Require config_digest_verified=true from the
existing base owner; a manifest-digest-only fallback cannot prove config identity.
Record its actual native platform, never upgrading
ARM observation to AMD qualification. Refutation, missing cached identity or a
need for broader removal stops the phase before any application start or push.
The existing canonical sandbox already preloads the exact PostgreSQL pin;
preserve its prerequisite policy and permit no extra pull from this test. The
new mandatory owner also runs in hosted staging M on native AMD, without any
discovery/optional-owner/skip changes. That job runs alongside the main-system
builder and cannot gate its fourth start. A missing/nonempty/symlink AMD path
can fail rmdir before the module guard and consumes that fourth slot. Local ARM
observation only gates pre-publication readiness; it cannot qualify native AMD.

Separately prove actual rmdir/header-operand behavior in a disposable canonical
dependency-only Python container. Select the exact rendered instruction and
header-presence operand of RELEASE_FINAL_PROBE_PY's AST; use real paths and OS
calls, no rewritten predicate. Test empty removal, retained nonempty header,
directory-target and dangling-symlink rmdir refusal, and absent-path refusal.
Record os.path.exists behavior faithfully: a dangling target is absent to that
operand even though rmdir still refuses the symlink. Restore any original include directory in
finally after removing only the known controlled fixture before original
directory restoration; perform exact cleanup/baseline verification. This is a component
proof only, with no claim of complete build-module absence or assembled image.

Use the existing d12_release_manifest unit owner for renderer ordering and
unchanged full probe/default refusal, defining its own nonempty PlatformPackages
fixture rather than importing another test module's private helper. Add only
the new d12_runtime_hygiene int
owner and a clean test-owner cohort/file record; no debt or policy relaxation.
Keep existing393/400 and400/400-line integration owners unchanged.

The explicit Route A approval raises additional scoped execution limits by
two per class to cumulative13/11/15, first one then conditional correction only,
and permits one fourth native AMD application start, total4/AMD4. RED1/exact
diagnostic1, complete local suite and coverage exclusions stay. All historical
attempts stay spent. Default/generic/ARM remain held; uncertain start spends the
new slot; no retry/reset/rearm. Source review/parent acceptance precede any push.

Closed grant/proof v1 binds phaseCI71FIX1, ordinal72/attempt1, before0ad2dbe,
main24d1565, approved decision, immutable reconciled PRE-APPEND ledger and fresh
actual context. Grant only carries4/4 maxima; refuse all three spent pairs and
every stale/rerun/later identity. Keep the grant file<=400 and every predicate.
After exact commit/report and postcommit/remote gates, atomically append the
exception/reservation/audit together immediately before one normal staging push.
No silent ledger/remote drift rebind or independent trigger is allowed.

## Scope and exclusions

The exact packet enumerates source/test/metadata owners and selectors. Protected
private source/HEAD/index remains intact, with only this accepted ADR and a fresh
primary Exit added after approval. Public author and committer stays Samuel
Leighton Lair <sam.lair@knowledge-forge.ai>. All new dispatches use gemini_sub
sequentially and never interrupt an existing dispatcher without fresh authority.

No runtime/test dependency, lock, base/SDK pin, SDK build, static linking,
infrastructure, emulation, pgvector admission, graph/runtime deployment or
main/tag/history/PR-state mutation follows. Native AMD qualification remains
hosted; P3/incumbent comparison/image/platform/merge/deploy remains unaccepted.

## Alternatives and residual risk

Keeping the hold is valid. Recursive include deletion, suppressing status,
loosening the final assertion, assuming the compound diagnostic proves a
particular conjunct, and treating component evidence as a qualified image are
rejected. The next build can reveal another defect and spend the entire new
slot without a final image. Full hosted coverage still applies to that candidate.
