# File-Length Profile

RepoMap owns the deterministic `file-length` profile. It is independently
executable now and is the stable repository entrypoint that `repo-map_runner`
will orchestrate in a later phase.

## Invocation

Run the human-readable profile from the repository root:

```sh
python3 tools/ci/check_file_lengths.py
```

The default format is `text`; it may also be selected explicitly:

```sh
python3 tools/ci/check_file_lengths.py --format text
```

Emit the machine-readable contract with:

```sh
python3 tools/ci/check_file_lengths.py --format json
```

`--repo-root <path>` is available for tests and controlled local invocation.
It is not part of a runner request protocol.

## Scope

The profile uses Git's tracked-file set as its inventory authority and includes
only `.py` files under:

- `src/main/python/`;
- `src/test/`;
- `tools/`.

Untracked and ignored files, virtual environments, generated caches, build
directories, and temporary files are not scanned. Markdown, SQL, shell, Nix,
JSON, YAML, and other non-Python files are outside this profile.

A generated-file exclusion requires both the conventional generated-code marker
and a documented deterministic generator. No current tracked Python file meets
both conditions, so CI-LENGTH0 scans every tracked `.py` file in the approved
paths. A marker alone does not exclude a file. This repository-wide profile has
no baseline, ratchet, waiver, path allowlist, per-path threshold, or
grandfathered exception. The separate retained-production ratchet below does
not change that contract.

## Physical-Line Definition

Files are read in binary mode. Each LF byte ends one physical line; CRLF
therefore counts once. A nonempty file whose final byte is not LF contributes
one final line. An empty file has zero lines, and a trailing newline does not
create a phantom line. This definition does not depend on platform-native
newline translation.

The policy boundaries are:

- 0 through 400 lines: pass;
- 401 through 1,000 lines: warning;
- 1,001 or more lines: failure.

Warnings do not make the command fail.

## Exit Status

- `0`: the check completed with no file above 1,000 lines;
- `1`: the check completed with one or more files above 1,000 lines;
- `2`: usage or operational error.

Operational errors are written to stderr and are not represented as successful
profile JSON.

### Known Repository-Wide Failure (2026-08)

`REPOMAP-PREVIEW-HYGIENE1` reduced `tools/system/scenario.py` from 1,130 to
972 physical lines by extracting its MCP public-readback behavior into
`tools/system/scenario_mcp.py` at 203 lines. Final closeout measured the
unstaged dispatcher candidate as 1,546 tracked Python files plus that one new
candidate file. The tracked repository-wide scan reported 326 warnings and one
failure; the candidate-scoped helper scan passed at 203 lines. Together, the
exact candidate inventory contains 1,547 Python files, 326 warnings, and one
failure. The dispatcher owns adding the new helper to Git inventory and must
re-establish the tracked-inventory result after staging.

The final repository-wide failure —
`tools/scale14_actual_refresh_supervisor.py` at 1,003 lines (outside the
retained-production selection) — was resolved by `PYLEN-SCALE14-FIX1`
([status 00833](../status/2026/09/02/00833-pylen-scale14-fix1-refactor-actual-refresh-supervisor-file-length-exit.md)).
That phase reduced the supervisor to 803 lines and extracted
`tools/actual_refresh_terminal_coordinator.py` at 316 lines. This remains a
**record, not a waiver**. The profile still fails closed at repository scope, no
exception mechanism is introduced, and nothing in the Scope section above is
relaxed: there remains no baseline, ratchet, waiver, path allowlist, per-path
threshold, or grandfathered exception. With that refactor complete, the
repository-wide tracked file-length exit status is `0`.

## Retained-Production Ratchet

`tools/ci/retained_python_ratchets.py` adds a separate architecture-derived
growth ceiling for production Python expected to remain Python. It selects
every tracked module under `src/main/python/repomap_kg` whose longest-prefix
ownership resolution is `cross_language_contract` or `python_retained`; this
is the T0, T1-seed, and T1-future set. T2 transitional Python and T3 planned-Go
or planned-Go/Rust implementation are excluded.

For this retained set, files at 400 lines or below have no file-length baseline
entry, files from 401 through 1,000 record their exact current ceiling, and any
file above 1,000 always fails. New warning-band files, growth above a ceiling,
and stale ceilings after a decrease all fail until reconciled. This reuses the
physical-line definition above but does not waive or replace the global profile,
including its known non-retained failures.

Ordinary read-only check mode is:

```sh
MYPYPATH=src/main/python \
python3 tools/ci/retained_python_ratchets.py \
  --baseline tools/ci/retained_python_ratchets.json \
  --scope-transitions tools/ci/retained_python_scope_transitions.json
```

The explicit generation mode is only for later downward-only refreshes. The
RepoMap baseline is already initialized; ordinary generation refuses a missing
baseline and cannot create a new genesis:

```sh
MYPYPATH=src/main/python \
python3 tools/ci/retained_python_ratchets.py \
  --baseline tools/ci/retained_python_ratchets.json \
  --scope-transitions tools/ci/retained_python_scope_transitions.json \
  --generate-baseline
```

Generation is atomic and deterministic. Both check and generation audit the
unique trusted genesis and every reachable baseline transition in complete Git
history before comparing committed `HEAD` with a dirty worktree candidate.
Ordinary linear transitions remain fully audited, and every divergent merge
parent remains directly audited. For a merge commit, an ancestor edge already
represented through another carrying parent may be skipped as redundant only
when that carrier descends from the trusted baseline genesis and the merge
commit's baseline and scope-registry blobs are both byte-identical to it,
ensuring no merge-local baseline or registry change can bypass audit. Shallow
or incomplete history is a tool failure. New or increased debt can never be
authorized. Removed or reclassified retained modules require an exact
append-only record in `tools/ci/retained_python_scope_transitions.json`; clean
new retained modules may enter without one. Registry records remain in
append order; their digest keys need not sort lexicographically. A scope record
must be committed with its baseline transition, and its referenced exit status
must be present in that commit or earlier. Splitting either authority after the
transition fails historical replay, while committing an unused record earlier
fails the unused-authority check. Promotion history must preserve one reachable
baseline genesis: independently introducing the baseline through mixed squash
and merge histories fails closed and requires a separately reviewed lineage
change, not an override. Resolve regressions first, then refresh removed
findings or lowered ceilings in the same candidate.

## JSON Contract

The JSON document has protocol version `1` and profile name `file-length`.
Status is one of `passed`, `passed_with_warnings`, or `failed`. The document
records warning and failure limits, scanned-file count, warning count, failure
count, and only warning or failure findings.

Findings use repository-relative POSIX paths and are sorted by path. Object
keys are sorted, output ends with one newline, and timestamps, durations,
absolute paths, remote information, and passing-file records are omitted. The
same repository tree and tool version therefore produce identical JSON bytes.

Text output sorts failures before warnings, then by descending line count and
ascending path. It omits passing files.

RepoMap owns this policy and executable contract. Future runner work may invoke
the repository entrypoint at an exact commit but must not redefine the profile.


### Retention authority and incremental progress

ADR 0062 governs retention inventory evidence. Immutable predecessor lineage,
explicit fixture ownership and content bindings, and cross-authority consistency
are prerequisites to enforcement. Migration forecasts keep living Python eligible;
`python_retention_transitions.json` preserves specific superseded ownership rules
and explicit pending admissions. New admissions add no historical debt.

Per-root clean-under-profile diagnostics describe actual completed checks and are
separate from effective enforcement. Root/profile closure remains fail-closed;
a historical ratchet pass is not proof of zero findings. Required governing inputs
and referenced transition evidence are bound by SHA-256 and size and checked
around execution. Live machine JSON retains complete findings. ADR 0064 governs the compact
retained evidence projection with explicit summaries, counts and commitments
under the unchanged 200,000-byte log and 5 MiB aggregate evidence limits.

ADR 0063 adds stable inventory-owned non-product cohorts. Each admitted member
retains a zero-debt 400-line ceiling; no cohort baseline or grandfathering is
allowed. Passing cohorts contribute effective paths while residual leaves the
root open. An admitted cohort that fails current evidence is a hard ratchet
regression, separate from pending residual. The global profile is unchanged.

### Atomic retention cycles (ADR 0065)

Multi-cohort dependency SCCs may pass atomically only within one root/profile,
with complete passing member evidence and independently governed external
obligations. All constituents must be admitted before any group governance is
effective. Clean all-pending groups are diagnostic only; mixed admission and
cross-root groups remain blocked. A failed admitted constituent remains a
regression. Stable cohort membership and immutable history are unchanged.
