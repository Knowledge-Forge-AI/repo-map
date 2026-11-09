# CLOE resource governance3 contract

Status: accepted by the parent for bounded source implementation, with proof
and independent resulting-source review pending. Phase `REPOMAP-CLOE-RESOURCE-GOVERNANCE3`.
Source parent `efdb5286b8a0bc40e242cdfc89a37b99dec89e18`; public base `5ad00d162ad8a04430874275246a53227578c533`.

This milestone contains two connected epics. The worker custody contract is
owned by [cloe-worker-custody-v1.md](cloe-worker-custody-v1.md). The sealing
contract below preserves the separately accepted E2 design. This record grants
no dependency, runner-policy class, image/build, native campaign, installed/live
mutation or complete local suite/coverage authority. The current user roadmap
continuation and parent disposition authorize ordinary source work.

CI134 is EXECUTED_FAIL: all tests passed, integration is one branch below its
hard floor, and two setup jobs failed on HTTP504. Neither design acceptance
nor scoped proof establishes whole-candidate qualification. Preserve hard
85/85 and80/80 floors, desired87/82 margins and the complete source denominator.

## Preserved boundaries

- Ordinary discover_repository keeps classification and FileInfo.content_hash.
- No global cache, new wire fields, graph vocabulary or CLI/report schema.
- Native graph.discovery closure gains no concrete artifact-meter import.
- New/modified owners require clean enrollment and append-only lineage; no debt,
  suppression, threshold, exclusion, rounding or receipt relaxation.
- New Python owners target350lines and every included owner remains<=400.

## Baseline reader inventory

The following observations describe source parent `efdb5286b8a0bc40e242cdfc89a37b99dec89e18`, before E2.

### 2.5 Sealing readers (per unique canonical selected file of size `s`)

| Id | Reader | Owner | Bytes per scan | Use in sealing |
|---|---|---|---|---|
| T0 | walk and selection | `_discovery_selection.selected_files`, `os.walk` or `metered_walk` | metadata | the selected set |
| C0 | `Path.resolve().relative_to(root)` | `classify_path:128-130`; `preflight_inventory` (`_metered_discovery.py:134`) | metadata | snapshot path and deduplication |
| R2 | `first_line` | `discovery_file_metadata.py:9-14` | first line or more | language; **discarded** |
| R3 | `is_go_generated_file`, 40 lines | `_discovery_classify.py:264-270` | ≤40 lines | `generated` flag; **discarded** |
| R4 | `is_zsh_completion_candidate`, whole file | `_discovery_classify.py:209-214` | `s` | language; **discarded** |
| R1 | `content_hash` | `discovery_file_metadata.py:17-22`, called at `_discovery_classify.py:157-159` | `s` | replaced at `multi_source_capture.py:154`; **discarded** |
| R5 | `_read_stable_file` or `read_stable_file_metered`, ≤3 attempts | `multi_source_capture.py:60-126`; `_metered_capture.py:34-75` | `s` per attempt | snapshot |
| R6 | `open_source_body`, exact size | `artifacts/_source_sealing_io.py` (P-E2-5) | `s` | store copy |
| R7 | `verify_stream_path` or `metered_verify_path` | `_store_stream.py:242-280`; `_store_metered.py:112-158` | `s` | store custody |
| R7c | collision comparison | `_store_stream.py:194-239`; `_store_metered.py:66-109` | `2s` | collision defense |
| R8 | manifest put and readback | `source_sealer.py:161-168` | `m` (+`2m` on collision) | manifest custody |

**Incumbent per-file cost:** R1+R5 in each of the two scans, plus R6 and R7, gives 6s for a new object and 8s on a collision. On top of that:

- each retry adds s, up to 4;
- R4-eligible files add 2s plus the R2 and R3 bytes;
- each encountered alias adds R1 plus R2 to R4 in each scan.

The incumbent R7c reads through `BufferedReader.read(65536)` (`_store_stream.py:216-222`). For regular files that returns full chunks or EOF; no spurious-collision defect is claimed (C12).

**Unchanged, outside this boundary:**

- `discover_repository` (`graph/discovery.py:110-130`);
- worker-side discovery/classification in `capture_multi_source_candidate`
  (`multi_source_pipeline.py:147-265`); its shared R5 reader also receives the
  nonblocking final-component open described in §5.5;
- other `scan_multi_source_generations` callers.

## Sealing contract: capture-only sealing scans

### 5.1 Interface

New module `graph/_sealing_scan.py`, at most 350 lines. `graph.discovery` never imports it. The dependency-free canonical helper lives in `graph/_canonical_selection.py`; the scan may import/re-export it and metered preflight imports that leaf directly.

```python
@dataclass(frozen=True)
class SealingGenerationScan:
    source_generation: str
    config_generation: str
    snapshots: tuple[SourceSnapshot, ...]

def canonical_relative_path(repository_root: Path, file_path: Path) -> str
def scan_sealing_generations(graph: OpsGraphConfig, *, io_meter: SealingMeter | None = None) -> SealingGenerationScan
```

**`canonical_relative_path`** returns `file_path.resolve().relative_to(repository_root).as_posix()`, the exact expression in `classify_path:128-130`. The scan and preflight share that leaf helper: `_metered_discovery.preflight_inventory` (`:134`) calls it too, with its incumbent exception mapping unchanged.

Precondition P-E2-8: the import edge `_metered_discovery` → `_sealing_scan` creates no import cycle. `_sealing_scan` imports `_metered_discovery` and `_metered_capture` only inside the metered branch.

**`scan_sealing_generations`** mirrors `scan_multi_source_generations` plus `_capture_inventory`, step by step:

- binding normalization;
- the unsupported-binding refusal (`source_invalid`);
- sorted bindings;
- `root.is_dir()`, otherwise `source_unavailable`;
- `os.walk(root.resolve())` or `MeteredDiscoveryHooks(meter).walk`;
- `selected_files`, then `canonical_relative_path` with `ValueError` propagating, then `sorted(set(...))`, exactly as at `discovery.py:129-130`;
- per path: the absolute or `..` check → `_SourceInvalid`;
- R5 through a module-attribute lookup at call time: `multi_source_capture._read_stable_file(root / path)` or `_metered_capture.read_stable_file_metered`;
- `SnapshotManifestEntry` and `SourceSnapshot.create` with identical arguments (`multi_source_capture.py:225-232`);
- exception mapping identical to `:233-242`, including A7;
- generations through `multi_source_pipeline._multi_source_source_generation` and `multi_source_config_generation`.

It runs no classification readers and no R1, and builds no `FileInfo`.

### 5.2 Sealer binding and seam migration (C4)

- `artifacts/source_sealer.py` imports `scan_sealing_generations` as a module-global and calls it for both scans: `scan_sealing_generations(graph, **metered)`, where `metered` is `{}` when unmetered.
- `source_sealer` stops using `scan_multi_source_generations`. P-E2-2 must confirm that no sealer consumer reads `.files`.
- There is no identity dispatch.
- The three tests in §2.7 migrate to `monkeypatch.setattr(sealer_mod, "scan_sealing_generations", ...)`. Their wrapper signature `(g)` still matches, and `dataclasses.replace` works on the frozen `SealingGenerationScan`. The drift and tamper tests then exercise the production path.
- The `classify_path` spy covers default discovery and is unaffected.
- **Amendment:** ADR 0173 P9, which made the `_capture_inventory` facade the default sealing scan, is amended for sealing only.
- The `_read_stable_file` seam remains honored.
- P-E2-1: no other test patches the sealing scan chain. Any that does migrates in the same way.

### 5.3 Equivalence claim and proof obligations

**Claim.** On any tree where the incumbent sealing scan succeeds, `scan_sealing_generations` returns equal `snapshots`, `source_generation` and `config_generation`. The seal then returns an equal manifest, reference and `candidate_id`.

**Basis:**

1. Snapshot entries depend only on the canonical path set and R5.
2. The selection is the shared `selected_files`.
3. Canonicalization and deduplication are the identical expression.
4. Classification never filters.

**Proof.** Unit and integration tests compare the new scan against an incumbent `scan_multi_source_generations` call over the §10.2 matrix. The incumbent function remains public for other callers.

### 5.4 Store collision: single-pass verification

New function `_store_stream.compare_and_verify_collision(target, temporary, length, digest, bound, *, owner_uid, private_details_fn) -> str` returns the store version. Precedence:

1. `details = private_details_fn(target)`.
2. Size mismatch → "artifact size does not match reference".
3. `length > bound` → bounds error.
4. Opening with `O_NOFOLLOW` fails → "artifact is not a regular file".
5. `fstat` does not match by same-file and `S_ISREG` → "artifact changed during read".
6. Opening the temporary file fails → "artifact read failed".
7. Lockstep loop:
   - read a target chunk of up to 64 KiB;
   - read exactly `len(chunk)` bytes from the temporary file, looping until that count or EOF;
   - hash the target;
   - inequality sets `differs`;
   - a total above `length` → size error.
8. At target EOF, read the temporary file once more; any data sets `differs`.
9. Final checks:
   - total ≠ `length` → size error;
   - digest mismatch → "artifact digest does not match reference";
   - `differs` → "content-address collision".
10. `fstat` after reading: a different file → "changed during read"; a different version → "artifact store version is stale".

Both descriptors close in `finally`. On the collision branch only, `put` builds the reference from that version and skips `verify_stream_path`. The new-object branch is unchanged.

The metered twin in `_store_metered.metered_put`:

- calls `require_read_headroom(2*length)` before opening;
- admits each read under A1 to A3;
- closes both descriptors;
- runs no R7.

**Evidence equivalence.** The single pass proves what R7c and R7 together proved: digest, size, same file and version, bound to the descriptor actually read. Messages can arrive in a different order only for tampered or racing stores (D7).

The bounded short-read loop is a hardening for non-regular or racing inputs. It does not fix an incumbent defect (C12).

### 5.5 Race and error parity (sealing scans only)

| Event | Incumbent | New | Note |
|---|---|---|---|
| Root missing | `source_unavailable` | same | |
| Unsupported binding | `source_invalid` | same | |
| Listing error | directory skipped | same | shared walk |
| Escaping or excluded entry | excluded | same | |
| File vanishes before its first body read | `source_unavailable` if seen first by R1 or R2–R4, else `source_changed` | `source_changed` | D4 |
| Swapped to a directory | `source_capture` | `source_invalid` (R5 `S_ISREG`) | D4 |
| Swapped to a FIFO or socket | an open in R1 or R2–R4 can block | both R5 routes use `O_NONBLOCK` where available; a post-lstat FIFO opens without waiting and fails identity/type checks, while a socket open is refused by the OS | covered FIFO window closed; no general device-call preemption claim |
| Swapped to a device | the device is read | `source_invalid` when seen at `lstat` | the same window caveat |
| In-root symlink swap before canonicalization | resolved | same | |
| Symlink swap after canonicalization | R5 `source_invalid` | same | |
| EACCES or EIO | `source_capture` | same | |
| R5 signature change | ≤3 retries, then `source_changed` | same | |
| Change between scans | "source changed while sealing" | same | |
| R6 mismatch | "source changed while sealing" | same | |
| Huge unknown-extension file | R4 decodes it whole | not read | |
| Governed `classification_retention` | reachable | unreachable in sealing | name kept |
| A7 budget refusal | first | first | |

### 5.6 Numerical accounting

**Definitions:**

- `S` = Σ s over unique canonical selected files.
- `C` = Σ s over puts whose digest already exists.
- `m` = manifest bytes; `m_c = m` if the manifest put collides, otherwise 0.
- `r` = bytes read by failed R5 attempts (≤ 4·s per file).

**Read totals:**

- Incumbent: `6S + 2C + m + 2m_c + A + K + r`, where `A` is the alias R1 and classification bytes and `K` the R2 to R4 bytes.
- New: `4S + C + m + m_c + r`.
- Exact-need budget: `new + 1`. The extra byte covers the R5/R7 EOF probes under A2; R6 never probes (P-E2-5).
- Writes are unchanged.

| Case (one file, no retry) | Incumbent | New |
|---|---|---|
| New object | 6s | 4s |
| Collision | 8s | 5s |
| Each extra alias encounter | +2s + classification | 0 |
| R4-eligible file | +2s | 0 |
| Maximum with retries, new / collision | 10s / 12s | 8s / 9s |

**Constants and the plan:**

- `FULL_BODY_READS_PER_FILE` goes from 6 to 4. `COLLISION_EXTRA_READS_PER_FILE` goes from 2 to 1. `planned_min_read_bytes(S) = 4S + 1`.
- Governed refusal: `4S + 1 > remaining_read` → `planned_read_bytes`.
- `cloe-sealing-plan-v1` fields and bounds are unchanged. The factors become 4/1/3 (D5). `projected_directory_entries` stays at 3× preflight, because the walks are unchanged.

**v2 metrics:**

- `sealing_discovery_read_bytes = 0` and `sealing_classification_read_bytes = 0`, with basis `call_meter_exact` when closed.
- `sealing_opens` drops by the R1 and R2–R4 opens and by one target open per collision.

**v2 limits (C2).** `governance_limits` keeps the `classification_max_retained_chars` row, with name, value, unit and enforcement `governed_owner_bound` unchanged. Its `applies` value becomes `False` for every sealing call, because sealing no longer runs a classification owner.

- Implementation: replace `entered and governed` at `_sealing_projection.py:106` with `False`, citing ADR 0177.
- P-E2-9: the v2 encoder and validators accept `applies=False` for this row in the governed state. If they do not, stop and report.
- `stable_capture_max_attempts` is unchanged.
- No row, basis, reason or enforcement value is added.

These are derived counts of owned-reader program bytes. They are not physical I/O figures and make no efficiency claim.

### 5.7 Descriptors, short reads, budgets

- R5 keeps its incumbent behavior. Bytes from failed attempts stay charged.
- The merged comparison charges exactly the bytes returned. A zero-byte read counts as one call. Both descriptors close on every refusal.
- A refusal inside `put` propagates through the incumbent unlink of the temporary file. No refusal deletes an installed object or the attempt root.
- The governed preflight is unchanged and precedes any body read. Each refusal precedes the next read, open, entry, write or fsync (A1).

### 5.8 Containment

- No edit to `graph/discovery.py`, `_discovery_classify.py` or `_discovery_selection.py`.
- `graph/_sealing_scan.py` is reachable only from `artifacts/source_sealer.py` and `graph/_metered_discovery.py`. Both are outside the native closure.
- P-E2-4: the closure resolver must report an unchanged path set.

## Connected first-use proof

Extend current Local, Server and mixed-v1 first-use owners with only their actual
delta. Independently inventory fixture bytes/digests and verify the accepted
stored manifest to derive S, C and m. Compare the mixed manifest/snapshot vector
with an incumbent scan. Local and Server v2 reports must show zero discovery/
classification reads and classification applies=false. A4S read budget refuses
planned_read_bytes before worker launch and leaves the exact accepted pin
unchanged. Lower-bound I/O owners separately prove no body open on that refusal;
the CLI proof checks delivered counters and accepted-state preservation.

Do not duplicate complete workflow sequences or derive expected counts from
the planner/report under test. No local coverage or whole-W7 claim follows.

### 10.2 E2

**Unit tests:**

- Capture-only versus incumbent snapshot equality across this matrix:
  - ignored and excluded globs;
  - in-root aliases, including an alias whose target is an excluded name;
  - escaping links;
  - non-regular entries;
  - unreadable directories;
  - empty files;
  - `.profile`, `.sh`, `.go` and unknown-extension files;
  - invalid UTF-8.
- The migrated sealer tests detect tampering and drift through the `scan_sealing_generations` seam.
- The `_read_stable_file` seam is honored.
- `canonical_relative_path` agrees with the incumbent expression; preflight uses it.
- The §5.5 categories, driven by deterministic mutation.
- Single-pass comparison:
  - every precedence step;
  - short reads on either stream;
  - extra temporary bytes;
  - a version change and an identity change;
  - descriptors closed after every refusal.
- Constants: `S ∈ {0, 1, 2^20, 2^63−1 // 4}`, with overflow refused.
- The classification v2 row reports `applies=false`.

**Integration tests:**

- Exact counters on trees with file sizes {0, 1, 65535, 65536, 65537, 1 MiB, 1 MiB+1}, one alias, one in-seal duplicate and a replay attempt (C = S). Checked for read bytes, read calls, opens, writes and fsyncs.
- Real deletion, FIFO and directory swaps after R5's `lstat` and before its open,
  through both full plain and governed sealing: sanitized refusal, no body reads
  or writes, descriptor closure and accepted-store preservation. Both R5 readers
  gain the same nonblocking flag; regular-file hashing and retry semantics stay.
- A real deletion race → `source_changed`.
- A real signature-change retry, charged cumulatively.
- Governed budgets:
  - `4S` → `planned_read_bytes`;
  - `4S+C+m+m_c+1` succeeds;
  - one byte less refuses.

  `m` comes from a prior identical attempt where the store version is fixed. Otherwise the refusal and measured-success pair from §6 is used.
- Default and metered manifests are identical.
- The plan CLI reports factors 4/1/3 and `4S+1`.
- The containment owner reports an unchanged path set.

**Coverage.** Each new branch has an owner. New branches enlarge the denominator, and no local gain is claimed.

## Sealing preconditions

- **P-E2-1.** Enumerate every test that patches the sealing scan chain. Each one migrates to `scan_sealing_generations` or targets non-sealing code.
- **P-E2-2.** No sealer consumer reads `MultiSourceGenerationScan.files`.
- **P-E2-3.** `ManifestArtifact` and `SnapshotManifestEntry` carry no field derived from classification.
- **P-E2-4.** The D12 closure path set is unchanged.
- **P-E2-5.** R6 `open_source_body` (unread) reads exactly `s` with no probe.
- **P-E2-6.** The collision twin fits `_store_metered.py` under 400 lines. If not, extract `_store_metered_collision.py`.
- **P-E2-7.** `_sealing_meter` (unread) requires no nonzero discovery or classification class.
- **P-E2-8.** The shared helper introduces no import cycle.
- **P-E2-9.** The v2 encoder accepts `applies=False` for `classification_max_retained_chars` in a governed call.

## Implementation and final acceptance

Use exact scoped unit and containerized integration selectors through
tools/run_tests.py with --no-coverage. Complete suites and local Python coverage
are unselected. Required unexpected refusal is a named blocking gap, not a gate
waiver. Preserve descriptors, retries, alias/collision costs, race categories
and exact independently derived counters. Update affected current owners and
the connected first-use owners in this same milestone.

Final acceptance requires changed-file quality/privacy/containment/topology
checks, a fresh independent frozen resulting-source APGR review, and final
campaign binding before one substantive staging publication. Record the
worker-contract deferrals and every unselected complete suite in the exit.
Full W6/W7, native Windows, installed/release and main promotion remain open.
