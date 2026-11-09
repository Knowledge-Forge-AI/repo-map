# REPOMAP-CLOE-CI135-REPAIR1 Exit: sealing and native fixture corrections

## Status

The repair passes 90 scoped unit cases and 54 containerized integration cases
using the canonical runner with `--no-coverage`. Maintained-Python static
enforcement passes. Independent source review found no blockers; the parent
retains its exact read reconciliation. A narrow fixture import-path adjustment
and concrete stream type guard are locally proved and await final independent
confirmation. Fresh binding, post-binding proof and hosted whole-candidate
acceptance remain pending. Governing decision: ADR 0179.

## Observed CI135 result

CI135 attempt 1 tested staging `2995b75ecfde511014588e7cd5f7f3cfe4006ba2`
over main `5ad00d162ad8a04430874275246a53227578c533` and is `EXECUTED_FAIL`.

- Unit: 2 failed, 17,706 passed, 40 skipped. Hard 85/85 coverage was met;
  branches were 21,854/25,152.
- Measured integration: 2 failed, 2,466 passed, 12 skipped, 29 deselected.
  Measurement is incomplete because one valid but unregistered coverage shard
  came from the maintained `refresh_worker` native custody fixture. No
  integration percentage is accepted. The abrupt leg was blocked.
- Static, security, CodeQL, native D12, native Rust and all system scenarios
  passed for the exact candidate.

The unit failures kept pre-acceptance sealing costs: a three-pass store
collision and a 6S+1 planned read lower bound. The integration failures
expected capture-only sealing to perform classification and refuse retention.
The fixture shard arose because the test copied the parent's ambient coverage
environment into a direct maintained child.

## Repair scope

Only test owners changed; product source, runner policy, launch families,
M/A roles, coverage floors and denominators are unchanged.

- `store_metered_put.unit.test.py`: the collision case now asserts the
  accepted single compare/verify pass (2S store bytes, two EOF-probed streams,
  three opens, one fsync, the incumbent reference and store version, unchanged
  bytes, no temporary or descriptor leak). A new case changes the installed
  object's stat identity during the real metered readback and asserts
  `artifact changed during read`, descriptor closure and retained custody.
- `resource_view_v2_observer.unit.test.py`: the S=30 planned lower bound is
  4S+1 = 121.
- `sealing_classification_boundaries.int.test.py`: governed ordinary discovery
  still refuses over-retained shebang and generated-Go text. Capture-only
  sealing under the same budget replays the accepted identity with zero
  discovery and classification reads, exact witnessed read bytes, no refusal
  and no store, temporary or descriptor change. The 32 parity cases also
  assert that sealing performs no discovery or classification reads.
- `governance3_native_custody.int.test.py`: each launch builds its environment
  through the existing `prepare_child_coverage_environment` helper with the
  admitted `unmeasured` family and the repository `src/main/python` source
  root. The invalid-job-context case poisons ambient
  `COVERAGE_PROCESS_START`/`COVERAGE_PROCESS_CONFIG` after its disposable
  harness is ready and asserts, at the existing delegated launch spy, that no
  `COVERAGE_*` key or runner bootstrap path reaches the native child. Genuine
  Popen, the selected reaper, primary exception identity, exact cleanup and
  unproven-custody assertions are unchanged. The fixture preserves its original
  explicit `src/main/python` import path rather than inheriting other parent
  Python paths.
- `bundle_stream_contract.unit.test.py`: one multi-chunk writable-buffer
  `readinto` contract through `FileSystemArtifactStore.open_stream`, asserting
  bytes, counts, EOF and verification. An actual concrete-type assertion narrows
  the annotated `BinaryIO`; no cast, suppression or product API change is used.

## Verification and boundaries

The final unit cohort passes all 90 cases. Integration passes all 54 selected
cases, including every classification corpus/refusal case, genuine native
custody with poisoned ambient coverage, ticketed custody, sealing I/O witnesses
and existing production-refresh instrumentation transparency. The later unit
type guard changes an integration-unselected test only; integration subject and
support bytes remain unchanged. Source/index preservation and owned cleanup
passed, with unchanged host Docker resource sets.

Static enforcement, privacy, topology, public export, length, compilation,
whitespace and suppression checks passed. Final current-byte checks remain
required after campaign binding. The first static execution found five type
errors in the new stream test; those failed receipts remain failed, and the
corrected source passed fresh unit and static proof without debt changes.

Complete local unit, integration, smoke, staging, system and combined suites
and local whole-population coverage were intentionally unselected. No local
application/SDK build, image pull or native parser qualification was selected.
Hosted state remains operator-set `AVAILABLE`; one conditional normal CI136
attempt is intended after final proof and independent review. No remote action
has yet occurred for this repair. Main/tag/release/history and W6/W7 completion
remain separate.

No coverage improvement is claimed; hosted CI must establish valid measurement
and the complete candidate result.
