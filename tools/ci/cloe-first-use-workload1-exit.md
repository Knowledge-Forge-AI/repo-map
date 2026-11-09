# REPOMAP-CLOE-FIRST-USE-WORKLOAD1 Exit

Status: **accepted design implemented as a source candidate; hosted acceptance pending.**
The three connected epics below have executable tooling and real backend
workflows. Local proof remains scoped and has no Python coverage claim.
Fresh campaign binding, final independent review and exact-source proof are
recorded in the exact-commit local report before publication. The normal hosted
campaign must export all three bundles, and their host checks remain required
before bounded first-use acceptance. Full W7 remains open.

Design authority:
[ADR 0180](../../docs/adr/2026/11/0180-reproducible-first-use-workloads-and-evidence.md)
and the [first-use workload contract](../../docs/specs/cloe-first-use-workload-v1.md).
Declared source parent (informational only): `cc6c91e1e4170d2775540945e5996d734bc0800e`.

## Epics

1. Frozen workload and evidence harness: census codec and fixture digest,
   code-owned recipe, strict record codecs, exclusive bundle writer and
   descriptor-anchored reader, source identity and the `plan` intent.
2. Real execution: Local, Server and mixed step adapters over the guarded
   `LocalHarness`, in-process product calls and `temporary_postgres`, with a
   driver that records preparation, call, witness and cleanup spans and scoped
   CPU, and never retries.
3. Reconciliation and inspection: pure per-action rules and reconciler with
   the closed categories of contract section 9.2, `check`/`show`, and real
   bundle negatives of section 9.3.

## Owned files

| Family | Paths |
| --- | --- |
| Tools | `tools/first_use_workload.py`, `tools/first_use_workload_{recipe,recipe_shapes,census,records,bundle,rules,report_rules,readback_rules,reconcile,domains,validation,pins,cli_views,source_identity,encoding,integrity}.py` |
| Support | `src/test/support/python/repomap_test_support/first_use_workload_{driver,cleanup,call_results,witness,session,rows,local_steps,server_steps,mixed_steps,mutations,samples}.py` |
| Unit | `src/test/unit/python/tools/first_use_workload_{records,census,bundle,rules,reconcile,cli}.unit.test.py`, `src/test/unit/python/repomap_kg/ops/first_use_workload_{driver,call_returns,cleanup_precedence}.unit.test.py` |
| Integration | `src/test/int/python/repomap_kg/ops/first_use_workload_{local,server,mixed}.int.test.py` |
| Census | `src/test/fixtures/first_use_workload/mixed-v1-census-v1.json` (parent-owned freeze; read-only) |
| Inventory | `tools/ci/python_retention_inventory.json` |
| Design | `docs/adr/2026/11/0180-reproducible-first-use-workloads-and-evidence.md`, `docs/specs/cloe-first-use-workload-v1.md` |
| Roadmap | `docs/specs/cloe-roadmap-transition-v1.md` (append after the existing 1,017-LF prefix) |
| Docs | `docs/ops/first-use-workflows.md` (reproduction section) |

The frozen census `src/test/fixtures/first_use_workload/mixed-v1-census-v1.json`
is parent-owned and was not modified. Product source, resource-report and
sealing-plan vocabularies, runner, quality policy and dependencies are
unchanged.

The exact-commit private report binds every final owner listed above with its
final SHA-256 and physical line count, including the census, inventory, design
docs, roadmap append and this exit. The private report may hash the exit;
this exit never embeds its own hash or a predicted commit identity.

## Selectors

```text
python3 tools/run_tests.py --suite unit --no-coverage -- \
  src/test/unit/python/tools/first_use_workload_records.unit.test.py \
  src/test/unit/python/tools/first_use_workload_census.unit.test.py \
  src/test/unit/python/tools/first_use_workload_bundle.unit.test.py \
  src/test/unit/python/tools/first_use_workload_rules.unit.test.py \
  src/test/unit/python/tools/first_use_workload_reconcile.unit.test.py \
  src/test/unit/python/tools/first_use_workload_cli.unit.test.py \
  src/test/unit/python/repomap_kg/ops/first_use_workload_driver.unit.test.py \
  src/test/unit/python/repomap_kg/ops/first_use_workload_call_returns.unit.test.py \
  src/test/unit/python/repomap_kg/ops/first_use_workload_cleanup_precedence.unit.test.py \
  src/test/unit/python/repomap_kg/ops/first_use_workflow_support.unit.test.py \
  src/test/unit/python/repomap_kg/ops/sealing_plan.unit.test.py

python3 tools/run_tests.py --suite int --no-coverage --pg-container-port 55433 -- \
  src/test/int/python/repomap_kg/ops/first_use_workload_local.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_workload_server.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_workload_mixed.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_local.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_server.int.test.py \
  src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py \
  src/test/int/python/repomap_kg/ops/sealing_plan_cli.int.test.py \
  src/test/int/python/repomap_kg/ops/resource_report_v2_local_cli.int.test.py \
  src/test/int/python/repomap_kg/ops/resource_report_v2_server_cli.int.test.py
```

Required host check after the hosted CI137 artifact is exported, before
subsequent source edits. The check must use the same-attempt staging
`candidate_identity.source_sha256` and recorded merge commit/tree. A staging
head is eligible only when its complete candidate census equals that reported
executed tree; otherwise obtain the exact recorded tree. Never repin the
artifact or weaken the check. If the exact tree is unavailable, acceptance is
held. Local --no-coverage proof does not select --report:

```text
python3 tools/first_use_workload.py check --bundle <DIR>/first-use-workload/<scenario>-<attempt>
```

## Results

| Gate | Result |
| --- | --- |
| Scoped unit selectors | passed; final exact-source counts and receipts in the private report; no Python coverage |
| Scoped containerized integration selectors | 15 passed before campaign binding; no coverage |
| Three in-sandbox `accepted` bundles and section 9.3 negatives | passed, including checkout CLI `check` on each real bundle |
| Host `check` of the three exact-source hosted bundles | pending hosted CI137; not accepted locally |
| Ruff, mypy, compileall, length, privacy/topology, suppression, diff checks | pre-binding diagnostic checks pass; final exact-source results in local report |
| Quality-root enrollment of the new owners | existing clean profiles; inherited records, quality roots and debt ceilings preserved |
| Export headroom against the measured staging artifact | forecast 391 members and 24,593,122 bytes; final hosted artifact remains pending |
| Candidate `source_sha256` binding | pre-publication private report binds the source census; post-CI evidence binds the actual executed merge commit/tree |

## Not claimed

No installed-wheel, image, native Windows, W6, full W7, held-out evaluation,
physical PostgreSQL cost, peak-RSS, efficiency or coverage-margin result is
claimed. Bundles carry no signature; a host `check` is not an authenticity
claim. No design-only CI, main, tag, release or automatic successor follows.

## Verification boundaries

Failed development runs were retained and corrected: local report admission,
fixture construction, disconnected publication pins, cleanup control/error
accounting, location membership, CLI classifications, type errors, and bounded
reader/encoder refusals. No failed run is counted as a pass.

Complete unit, integration, smoke, staging and system populations were not
selected locally; no complete-suite override was requested or consumed.
Hosted CI owns their normal qualification. No application/SDK build or native
Rust qualification was run by this local proof. No dependency/version selection
changed; existing canonical harness prerequisite handling remains in force.

Hosted CI state remains operator-set AVAILABLE. The intended remote action is
one reviewed staging publication triggering CI137 attempt 1. At this record's
freeze there has been no remote write; final source/commit and automatic run
readback belong to the local report. No CI138, automatic retry, second push,
main promotion, tag or release is authorized by this record.
