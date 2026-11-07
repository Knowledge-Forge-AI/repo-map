# REPOMAP-CLOE-CI103REPAIR1 Exit: measured D12 child repair

This source checkpoint repairs CI103's integration measurement failure.
Whole-candidate qualification remains **NOT ACCEPTED**, pending hosted CI104.
ADR0132 governs the separately bound successor campaign.

## Diagnosis and correction

[CI103 attempt1](https://github.com/Knowledge-Forge-AI/repo-map/actions/runs/41275226551)
passed eight jobs, including unit, static/security and the native system gate.
Measured integration reported 1956 passed, 12 skipped and 24 deselected, then rejected
an unregistered coverage shard. Its twentieth native AMD start remains spent;
system success is evidence for that exact candidate only.

The D12 round-trip test replaced PYTHONPATH with the running interpreter's
sys.path, losing the runner bootstrap while retaining coverage configuration.
Its Python restore shim also replaced its process through exec in the archive
listing path, bypassing terminal receipt finalization. The repaired test uses
the existing environment and observed-launch owners, and the shim exits
normally. The hosted orphan's exact test-item owner was not established.

The maintained ROUND_TRIP_PY probe, archive/hash checks, exact btree+GIN methods,
2000-row and data equality checks and owned database cleanup are preserved. The local
portability shim still decodes the custom archive, removes the single
unsupported transaction_timeout setting and replays SQL through psql. Direct
pg_restore qualification remains hosted.

Strict fixture-only process tests prove parent and Python descendant start/
terminal registration, successful combination, no-selected-hit child receipts,
environment restoration and continued rejection of an orphan whose bootstrap
was deliberately removed. Runner validation and project coverage policy are
unchanged; no local project coverage is claimed.

## Verification boundary

The implementation checkpoint passed 47 scoped unit cases and 13 containerized
integration cases using --no-coverage. Exact unit owners were
tools/test_runner_coverage_atomicity, tools/test_runner_coverage_receipts,
tools/ci/d12_system_grant, tools/system/d12_system_evidence and
tools/system/d12_system_session under src/test/unit/python, with their
.unit.test.py suffixes. Integration selected these complete owner files:

- src/test/int/python/repomap_kg/storage/lexical_restore_local_plan.int.test.py
- src/test/int/python/tools/runner_failure_recovery.int.test.py
- src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py

Retained static enforcement completed with zero cohort regressions and
unchanged governed debt. Topology, file length, suppression policy, public
export, changed-source compilation and whitespace checks passed. Final
post-binding source/grant selectors and results are recorded in the containing
phase commit; implementation evidence does not qualify a successor tree.

CI103 unit lines 57531/65359 and branches 18596/21338 exceeded the 87% target.
Integration coverage was unavailable; the 82% target remains pending. Hard
85/85 unit and 80/80 integration floors are unchanged. Complete local unit,
integration, smoke, staging, system and combined populations were intentionally
unselected. No local application/SDK build was authorized or performed.

Hosted capacity is AVAILABLE. At this source checkpoint, publication and
successor qualification are pending. The parent owns one reviewed staging push,
its exact-commit report and the CI104 handoff. No main promotion or automatic
retry follows from this checkpoint.
