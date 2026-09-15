# ADR 0053: Linux Host-Admission Signals And Profile Free-Disk Reserve Override

## Status

Accepted. This ADR extends the ADR 0048 host-admission decision to hosts that
are not macOS, and adds one new hygiene profile. It changes no watermark, no
retention rule, no reclamation rule, no existing profile's quota, and no
default admission outcome on the existing macOS development laptop.

Corrected in place before landing on `main`. The original text was written
before any hosted run existed and assumed `heavy` was the right profile for
hosted exhaustive CI. The first live run falsified that assumption; Decision 3
below records the correction. ADR 0042 requires stable ADR numbers and
basenames, and this document has never been on `main`, so the branch corrects
it rather than issuing a second ADR to amend an unlanded one.

## Date

2026-08-18

## Context

ADR 0048 decided host admission for the RepoMap test harness and named its host
signal sources concretely, including macOS `memory_pressure`. That was correct
when the only host running the harness was the development laptop.

REPOMAP-CI0 introduces a second host class: an ephemeral GitHub-hosted Linux
runner that runs the project-owned exhaustive command, at the time
`--suite all --hygiene-profile heavy --declared-complete-gates 1`. Two
properties of the current implementation refuse that host before any test runs.
Both were confirmed by executing `decide_host_admission` directly, not by
reading alone. A third property, found only once the gate ran live, is that the
command itself named the wrong profile.

First, memory pressure is unreadable. `read_memory_pressure_reading` shells out
to `memory_pressure -Q`, a macOS-only binary. On Linux the call raises `OSError`
and the reading becomes `UNAVAILABLE`. `HEAVY` and `QUALIFICATION` refuse any
reading that is not `NORMAL`, so admission fails with
`memory_pressure_not_normal`. This is not a host defect; it is a missing signal
adapter for a host class ADR 0048 did not contemplate.

Second, the per-profile free-disk reserve is not reachable by configuration.
ADR 0048's Host-Profile Table describes its free-disk column as selected
portable defaults subject to "operator overrides (configuration layers 3–5)",
and separately fixes the architectural invariant that no configuration may lower
the free-disk reserve below 10 GiB. The implementation honors the invariant but
never implemented the override layer: only `ordinary` reads
`config.min_free_disk_bytes`, while `integration`, `build`, `heavy`, and
`qualification` read a hardcoded table. `heavy` therefore demands 100 GiB free
on every host forever. No standard GitHub-hosted Ubuntu runner has a disk that
large in total, so admission fails with `free_disk_reserve`.

The 100 GiB figure was chosen as laptop headroom, where the harness shares a
disk with a full developer environment and other agent runtimes. Its purpose is
to keep a heavy run from filling a machine the operator is also living on. On a
single-tenant ephemeral runner that is destroyed after one job, the shared-host
hazard the figure was protecting against does not exist.

Third, and observed only after the first hosted run, `heavy` is the wrong
profile for this work. Workflow run 32176096998 reached disk admission, found
about 30 GiB available on a 72 GiB-class `/dev/root`, requested the 32 GiB
reserve this ADR originally prescribed, and was correctly refused. No test node
or coverage session was ever measured. The refusal was sound behavior against
an unsound resource model: `heavy`'s 32 GiB is a *runaway ceiling*, and
Decision 2's quota-derived invariant converted it into a *startup requirement*.
ADR 0048's own evidence does not support tens of GiB of demand for one
correctness run — a focused run's measured peak scratch was 16,379,904 bytes
(~15.6 MiB), and the ~182 GB historical accumulation was 381 retained run roots
plus BuildKit pressure (~478 MB/run estimated mean), not one run's working set.

This ADR deliberately does not address the separate deferred finding that
macOS/APFS changed `st_dev` across a reboot while the scratch-root inode was
stable. That is persistent-laptop index state, not host admission, and it is out
of scope here.

## Decision

### 1. Memory pressure gains a Linux reading that reuses the existing degraded contract

The harness reads memory pressure from `/proc/meminfo` when
`memory_pressure -Q` is unavailable, and reports the result as `DEGRADED` with
an exact `memory_free_percent`, computed as `MemAvailable * 100 // MemTotal`.

`DEGRADED` is the honest classification and no new one is introduced. ADR 0048
already defined `DEGRADED` for exactly this situation — the pressure level is
not directly readable, but free memory is known — and already required a
separate `--operator-attest-pressure-degradation` attestation before `heavy` or
`qualification` may proceed on a degraded reading. A Linux host reusing that
path inherits an existing, reviewed gate.

The rejected alternative was mapping a `/proc/meminfo` percentage onto `NORMAL`
above some threshold. That would require this ADR to define what "pressure
normal" means on Linux, a claim RepoMap has no measurement basis to make, and it
would silently bypass the degradation attestation. Reporting `DEGRADED` makes
the weaker signal visible in the admission decision's `degraded_signals` rather
than laundering it into a strong one.

`/proc/meminfo` is read directly rather than shelling out. An unreadable,
malformed, or zero-`MemTotal` file yields `UNAVAILABLE`, which fails closed for
`heavy` and `qualification` exactly as today.

### 2. The per-profile free-disk reserve becomes an explicit operator override

A single new nonsecret configuration value,
`PROFILE_FREE_DISK_RESERVE_BYTES`, replaces the per-profile reserve for the
selected profile when it is set. It flows through the existing closed
configuration mechanism — the same key validation, the same layer precedence
(defaults, local TOML, environment, command line), and the same digest — so it
is recorded in the immutable admission record like every other hygiene value.

When the value is unset, every profile keeps its current reserve exactly. The
laptop's admission behavior is unchanged.

Two invariants bound the override **[invariant]**:

1. it may never fall below the ADR 0048 architectural floor of 10 GiB; and
2. it may never fall below the selected profile's own byte quota.

The second invariant is the substantive one and is new. A run must never be
admitted onto a filesystem holding less free space than that run is permitted to
allocate. It is derived from the profile's own quota rather than selected, so it
scales with the profile instead of restating a number. For `heavy` the effective
minimum is therefore 32 GiB, not 10 GiB. Violating either bound is an admission
refusal (`free_disk_reserve_override_invalid`), not a clamp — the harness does
not silently substitute a value the operator did not ask for.

### 3. Normal exhaustive CI uses a new `exhaustive` profile, not `heavy`

A new hygiene profile, `exhaustive`, represents the normal complete correctness
suite (`--suite all`). `heavy` and `qualification` remain the profiles for
genuinely resource-heavy performance, build, and qualification campaigns, and
neither is weakened here.

| Profile | Byte quota | Inode quota | Minimum host free disk |
| --- | --- | --- | --- |
| `exhaustive` | 4 GiB (4,294,967,296) | 750,000 | 10 GiB |

The 4 GiB byte quota is **operator-selected headroom, not a measurement**
**[assumption]**. RepoMap has not measured the full suite's peak. The figure is
roughly 8x the ~478 MB estimated historical mean run and ~256x the 15.6 MiB
focused measured peak: large enough that the real peak should surface below it,
small enough that multi-GiB runaway behavior still trips the ceiling, and well
inside a standard hosted runner. CI0B's live runs measure the actual working
set, and this number should be tuned against that evidence rather than kept out
of habit.

The inode quota reuses `heavy`'s existing 750,000 rather than inventing a
value. This correction is about the byte dimension; reducing inode headroom
merely for symmetry would start a second resource fight with no evidence behind
it.

Quota and reserve are separate concepts and this ADR stops conflating them
**[invariant]**:

- the **quota** is the maximum run-owned scratch tolerated before a runaway is
  killed;
- the **reserve** is the minimum host free space required before the run
  starts.

`exhaustive`'s reserve is 10 GiB — exactly ADR 0048's architectural floor, and
independent of its 4 GiB quota. There is deliberately no general
`free disk >= quota` invariant for this profile. Decision 2's quota-derived
bound on the *override* is unchanged for every profile, and is simply vacuous
for `exhaustive`, whose quota sits below the floor.

This makes the reserve ladder non-monotonic: `exhaustive` requires 10 GiB while
`ordinary` defaults to 20 GiB. That is intended and is stated plainly rather
than hidden. The reserve figures encode *host class*, not run size, and
`decide_host_admission` has no notion of host class to encode it in. `ordinary`
protects a shared developer laptop; `exhaustive` targets an ephemeral
single-tenant runner that is destroyed after one job and owns at most 4 GiB.
`ordinary` could already be configured down to the same 10 GiB floor, so the
ladder was never strictly monotone in practice.

`exhaustive` keeps every complete-run safety gate: exactly one declared
complete gate, at most one active mutating run, a responsive Docker daemon, the
exclusive attestation, and the pressure-degradation attestation on a degraded
reading. It requires no campaign plan, and it is refused for any suite other
than `all`. Only disk sizing is corrected here.

### 4. Nothing else about admission changes

The free-disk percentage floor, the concurrency limits, the Docker
responsiveness gate, the BuildKit image gate, the complete-gate maxima, the
exclusive attestation, and the campaign-plan requirement are untouched. The
`ordinary` profile continues to read `config.min_free_disk_bytes` when no
override is set.

## Consequences

The GitHub-hosted Linux gate runs `--suite all --hygiene-profile exhaustive
--declared-complete-gates 1` and supplies two attestations, visible in the
workflow and in version control: exclusivity and pressure degradation. Each is
an argument someone can read and challenge in review rather than an implicit
property of the runner. It supplies no reserve override and deletes no
preinstalled toolchains.

Live sandbox adoption falsified the prediction that selecting the 10 GiB floor
alone left sufficient usable headroom. Run `32691462575` recorded
13,543,022,592 bytes free immediately before the sandbox-backed command, after
the host had already installed a second Go, linter, and Python test environment.
The inner canonical runner subsequently refused admission. That pre-build
reading alone does not establish post-build backing-space availability:
PR26-STAGING-FIX2 reproduced admission measuring an 8 GiB scratch tmpfs against
the 10 GiB host floor. The historical refusal therefore cannot independently
attribute the failure to image consumption. The accepted bootstrap correction
is to omit that duplicate host candidate bootstrap: the owned sandbox recipe
provides the test toolchain. The reserve remains 10 GiB, and the workflow still
neither deletes arbitrary host content nor sets a reserve override.

The local laptop's final gate continues to use `heavy`. Two profiles now exist
for `--suite all`, so which one a given gate uses is a real choice; the
Verification Policy in `docs/contrib/testing-standards.md` names both and says
where each applies.

Admission on that host is recorded as degraded. `degraded_signals` will carry
`memory_pressure_degraded` for every CI run. That is accurate and should not be
suppressed later by inventing a Linux `NORMAL` threshold without measurements to
support it.

The override is a genuine loosening and can be misused. An operator who sets it
on the laptop weakens the shared-host protection the 100 GiB figure provides.
The quota-derived invariant bounds the damage but does not eliminate the
judgment call, and the value's presence in the configuration digest is what
makes the choice auditable after the fact.

The first hosted run already falsified one prediction: a runner has nowhere near
enough disk for `heavy`'s reserve, but it does not need it either, because
`heavy` was never the right profile for this work. The override mechanism from
Decision 2 survives that correction as a genuine but now-unused capability, and
an operator who sets it on the laptop still weakens the shared-host protection
the 100 GiB figure provides. Its presence in the configuration digest is what
makes such a choice auditable after the fact.

This ADR would still be wrong if `/proc/meminfo` were absent on the chosen
runner image, which would leave pressure `UNAVAILABLE` and refuse admission
rather than admit it unsafely; if a standard hosted runner turned out to start
with less than 10 GiB free, which would put the architectural floor itself in
tension with hosted CI; or if the exhaustive suite's measured working set
approached or exceeded 4 GiB, which would mean the quota was selected too
tightly to be a runaway ceiling. The first two are unmeasured predictions. The
third is what the workflow's two exact `df -B1` readings and the run's own quota
accounting exist to settle, and REPOMAP-CI0B owns that evidence.
