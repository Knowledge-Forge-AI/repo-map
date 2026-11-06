# CLOE Resource Experience Exit

Phase: `REPOMAP-CLOE-RESOURCE-EXPERIENCE1`.
Feature and grant source proof is complete. Whole candidate accepted: false.
Independent review and final static/privacy/hygiene acceptance are publication
prerequisites; their resulting disposition is recorded in the phase commit.

## Scope

ADR0159 implements two connected W7 epics: an internal, optional call-owned
resource view over Local/Server refresh and lexical build, and source-level
Local, Server and mixed-material first-use workflows. Context and independently
selected staging events use pure projections. Reports contain closed status
values and numeric observations, without identities, extra queries, source
reads, worker messages, a callback sink or new enforcement.

Current owners retain arming, settling, reconciliation, locks, admission and
exception precedence. CLI/MCP fields, packet schemas, dependencies, worker
protocols, architecture placement and all inherited debt/coverage ceilings are
unchanged. Local remains independent of Psycopg, PostgreSQL, Docker, parsers
and enrichment. First-use proof uses public mixed-v1 fixtures and existing
commands, with alias-qualified scope and metadata-only mailbox/feed policy.

## Executed source proof

The final source cohort passed 150 unit cases and 61 containerized integration
cases with `--no-coverage`. The integration cohort includes observed Local and
Server concurrency, replay/refusal and actual SIGINT cleanup, a caller-selected
staging-event projection, lexical publication/refusal, context counters and
lower selected controls, and all three first-use workflows.

Independent review's packet-only applicability defect was corrected: owner
deadline/callback ceilings carry unknown applicability without the caller's
ledger. Real lower-selected controls remain exact and packet counters detached.
Unsealed observer reuse now clears the prior outcome to `not_recorded` and
limit applicability to unknown.
Documentation describes the actual descriptor-owning and publisher hook sites
and the separate observed Server wrapper. Local import proof covers the full
PostgreSQL implementation set and excludes the new Server projection adapter.
Driver-free staging records were already reachable through portable refresh
in the predecessor; the strengthened guard does not prohibit that existing import.
Grant/manifest checks and an unpatched actual-context binding check are included
in the combined source cohort below.
The mixed workflow also publishes and reads one declared alias, then a changed
several-alias set in generation 2. Empty declarations exercise the current
legacy config owner's four missing-field diagnostics, separately from the
empty lexical selection refusal. Closed location keys and registered canaries
replace the former body-key absence check.

Additional real-boundary fault tests establish ordinary post-commit clock
degradation without rejecting Local publication, degraded observer reuse across
two accepted generations, and identity-preserving KeyboardInterrupt/SystemExit
propagation from the Server finish hook after the database committed. Those
interrupts are outside the owner handlers and do not relabel the accepted run.
Test-control ACKs in the signal probes are test-only acknowledgements, not
backend telemetry or native qualification.

Earlier scoped failures were corrected, not hidden: a shadowed Local finish
helper recursed; fixture expectations confused accepted runs with latest
attempts and selected policy-excluded bindings for a positive lexical case;
new clean-owner census rows needed the existing cohort rules; explicit typing
removed new mypy findings. Server's newest failed attempt is distinct from its
accepted publication. Local's after-commit signal preserves the already
advanced database publication, and recovery reconciles that same run.
The corrective proof also caught two overstrict test assumptions: a preexisting
driver-free record import and alias order. The configuration owner sorts bindings
by binding ID; the workflow now asserts that order rather than declaration order.

New owners join the existing clean profiles; every inherited ownership rule,
selection row, numerical ceiling, historical row and relative cohort order is
preserved. Final retained-code enforcement is required before publication;
its result is recorded in the phase commit. Pure report construction was split into a sibling to meet the
length limit. Source/HEAD/index custody, process cleanup and Docker resource
parity passed. Scoped integration reported zero builds, pulls and residue.

Exact feature selectors follow. Commands also used run-owned report/scratch
directories; containerized integration reused the verified diagnostic runtime.

```text
tools/run_tests.py --suite unit --no-coverage --jobs 1 --
  src/test/unit/python/repomap_kg/ops/resource_view_contracts.unit.test.py
  src/test/unit/python/repomap_kg/ops/resource_view_observer.unit.test.py
  src/test/unit/python/repomap_kg/ops/resource_view_projections.unit.test.py
  src/test/unit/python/repomap_kg/ops/resource_view_attachment.unit.test.py
  src/test/unit/python/repomap_kg/ops/portable_worker_terms.unit.test.py
  src/test/unit/python/repomap_kg/ops/first_use_workflow_support.unit.test.py
  src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py
  src/test/unit/python/repomap_kg/ops/sqlite_local_refresh.unit.test.py
  src/test/unit/python/repomap_kg/ops/sqlite_local_reconcile.unit.test.py
  src/test/unit/python/repomap_kg/ops/portable_refresh_routing.unit.test.py
  src/test/unit/python/repomap_kg/coordinator/publication_phase.unit.test.py
  src/test/unit/python/tools/ci/d12_candidate_context.unit.test.py
  src/test/unit/python/tools/ci/d12_system_grant.unit.test.py
  src/test/unit/python/tools/ci/qualification_rust.unit.test.py::test_actual_frozen_manifest_validates_against_current_checkout
  src/test/unit/python/tools/ci/qualification_rust.unit.test.py::test_actual_component_closure_is_initialization_resolved_and_digest_bound
```

```text
tools/run_tests.py --suite int --no-coverage --jobs 1 --pg-container-port 55433 --
  src/test/int/python/repomap_kg/ops/resource_view_local.int.test.py
  src/test/int/python/repomap_kg/ops/resource_view_server.int.test.py
  src/test/int/python/repomap_kg/ops/resource_view_fault_custody.int.test.py
  src/test/int/python/repomap_kg/retrieval/resource_view_lexical.int.test.py
  src/test/int/python/repomap_kg/retrieval/resource_view_context.int.test.py
  src/test/int/python/repomap_kg/ops/first_use_local.int.test.py
  src/test/int/python/repomap_kg/ops/first_use_server.int.test.py
  src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py
  src/test/int/python/repomap_kg/ops/navigation33_portable_retention_and_local_ops.int.test.py
  src/test/int/python/repomap_kg/retrieval/context_sqlite_publication.int.test.py
  src/test/int/python/repomap_kg/retrieval/context_postgres_publication.int.test.py
  src/test/int/python/repomap_kg/retrieval/lexical_postgres_lifecycle.int.test.py
  src/test/int/python/repomap_kg/ops/multi_source_refresh_guard.int.test.py
  src/test/int/python/repomap_kg/source_ingestion/slice14_staging_lifecycle.int.test.py
  src/test/int/python/repomap_kg/storage/scale13_actual_refresh_path.int.test.py
  src/test/int/python/repomap_kg/storage/arch2c_staging_observability.int.test.py
  src/test/int/python/repomap_kg/cli/sqlite_local_operator_workflow.int.test.py
  src/test/int/python/repomap_kg/cli/lexical_cli_roundtrip.int.test.py
  src/test/int/python/repomap_kg/cli/sqlite_local_locking.int.test.py
  src/test/int/python/repomap_kg/storage/arch1c_publication_exclusion.int.test.py::test_shared_graph_lock_rejects_coordinator_during_direct_publication
  src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_system_hold_proof_capture_and_child_secure_writer
  src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py::test_cross_process_flock_and_o_excl_race_and_execute_system_run
  src/test/int/python/repomap_kg/extractors/rust_pilot/qualification_import_closure.int.test.py::test_full_qualification_call_path_is_guarded_over_frozen_fixture
```

The meaningful Python/Go code-and-test net delta at this source checkpoint is
4245 physical lines, excluding docs, ownership/census JSON and other metadata.
This is below the operator's 10k–100k batching aim. The two complete connected
epics reuse established owners and fixtures; no duplicated fixture bulk or
generic framework is added to manufacture size.

Complete local unit, integration, smoke, staging, system and combined suites,
local Python coverage, native parser commands, image builds, acquisitions and
the held-out evaluator were intentionally unselected. No complete-suite
override exists. Hosted CI owns complete-population and coverage qualification.

## Publication boundary

ADR0160 separately specifies one conditional CI123 attempt1: application start
34 after 33, native AMD Rust command 3 and two unchanged wheel transfers for a
cumulative 10. Fresh grant/manifest proof passes. The unpatched 812-file D12
context equals both JSON bindings; all 264 Rust closure paths validate and only
the existing grant-guard digest changes. Authority, reservation and before-ledger
hashes reconcile; historical roots/list prefixes and old native reports remain.
Final static/privacy/hygiene checks, independent APGR review, parent acceptance
and an exact commit report precede publication.
No allocation is execution, and old native evidence retains its old bindings.

Hosted state: AVAILABLE. Remote write or trigger at this checkpoint: none.
Execution classification: NOT_REQUESTED_CONSERVATION for the new candidate.
CI122 passed its predecessor only. New hosted static/unit/staging/system/native
gates and 87/82 branch-margin goals remain pending. Historical CI122 gaps were
34 unit and 463 integration branches. Hard 85/85 and 80/80 gates stay unchanged;
no local coverage or prediction of future percentages is claimed.

Whole W7, full W6, Local Rust, installed qualification, scientific acceptance,
image/production acceptance, main/tag promotion and v0.1.0 remain separate.

## Source checkpoint hashes

These hashes bind the code/test source cohort; the later exact commit report
binds this exit and every final publication artifact as well.

| Path | SHA-256 |
|---|---|
| `src/main/python/common_lore_index/ops/_portable_worker_terms.py` | `5bb8e02c7be6a947ab71bcd1a8e1a777f9b7dfedd33de72d0bec93951d719b56` |
| `src/main/python/common_lore_index/ops/lexical_service.py` | `f2431d0c1b32c9ff8364f883b3dcac8917873ca743a81005e69a8f56d544f1a8` |
| `src/main/python/common_lore_index/ops/local_refresh.py` | `892997ebe5094a7a4440ee0efa92ee217913ce30073282cf8f5b01135041c407` |
| `src/main/python/common_lore_index/ops/portable_refresh.py` | `9d63a25e4d50a88817e96fdac34fd84c7fa485d5f35828b864a2708b2211046f` |
| `src/main/python/common_lore_index/ops/refresh.py` | `bae651adb2b1bac835c94a493027b4b0425b83b2953bbb1452db41ad16e7d721` |
| `src/main/python/common_lore_index/ops/resource_view/__init__.py` | `1fcc3059aa08205a238daf7e981fcd43fdea1ebc6912a7bff6b66e8c52ee0667` |
| `src/main/python/common_lore_index/ops/resource_view/_contracts.py` | `a52d66e6098ab4530f1417b68547892b8a43166a3245fc6322aa6e75fcf834ac` |
| `src/main/python/common_lore_index/ops/resource_view/_controls.py` | `c4d4c660e89e1d7593396441980004b2598101e0aab641b1c885127ce2a45c10` |
| `src/main/python/common_lore_index/ops/resource_view/_observer.py` | `0e9f10e0d396125c05d402b208eb496bb2f3f2a4256ff09ac7e354c545dfdf84` |
| `src/main/python/common_lore_index/ops/resource_view/_observer_reporting.py` | `6f0997549b895f7cc7645546eb32801a734cc0cdf5441573e832693f8793fed1` |
| `src/main/python/common_lore_index/ops/resource_view/_projections.py` | `344429dec9e4713c377540a1f1767b0b29f4c2218276ce7433b6215cf9000d60` |
| `src/test/int/python/repomap_kg/ops/first_use_local.int.test.py` | `73ced5232fd226f3431b46d578b4b3bdb7b5232b3d949ab81c1ec29422e3c485` |
| `src/test/int/python/repomap_kg/ops/first_use_mixed.int.test.py` | `df3b9ba5664092607b577c826d6cba7b88db054b053b93d86de32e11f15dc596` |
| `src/test/int/python/repomap_kg/ops/first_use_server.int.test.py` | `41e3a163c2f0c6c13a5ab81eabcdddebd728c97c1cc7ca9e86979beb13007040` |
| `src/test/int/python/repomap_kg/ops/resource_view_fault_custody.int.test.py` | `5bd00c4c845a01bcd141d38fa1435b72ac82a25707543f25f0c7a68fc4d2c890` |
| `src/test/int/python/repomap_kg/ops/resource_view_local.int.test.py` | `246cb79ee083a01e1a1f047f7b66a168d9a7f2d33d6e36bd5dc277e39f1ffde4` |
| `src/test/int/python/repomap_kg/ops/resource_view_server.int.test.py` | `103e9806ec4bc1c87a2d84528080b1ea5f7ca3c08a4642fbe4579c197680845a` |
| `src/test/int/python/repomap_kg/retrieval/resource_view_context.int.test.py` | `718605ef7b5363d9ae96599de33c1a0fab65fd0c6382131271c8b85b97a7a2a2` |
| `src/test/int/python/repomap_kg/retrieval/resource_view_lexical.int.test.py` | `d1471a53b01d2efa200e4f6bc814618c45a0f2d073c61d1eabd001f45ae9f463` |
| `src/test/int/python/repomap_kg/runtime/d12_system_admission.int.test.py` | `0f89f255f2d7cd42da0399c0ccd34c954b4e923f417fda61198365b4f0ac515f` |
| `src/test/support/python/repomap_test_support/first_use_workflow.py` | `9a77b06b9bf11c5d54972ec714afa1a9a8b61b824c3a46df3cf79003c6b76611` |
| `src/test/unit/python/repomap_kg/cli/sqlite_local_import_boundary.unit.test.py` | `4c8d1c1605885202281c49d3e69c6314fe674a324c3e75ad322f2f9d0ba23e1b` |
| `src/test/unit/python/repomap_kg/ops/first_use_workflow_support.unit.test.py` | `ebd07c8e38c155906f1d2f054484063803aa7034d936d131b0090b67ef4e7abc` |
| `src/test/unit/python/repomap_kg/ops/portable_worker_terms.unit.test.py` | `bf2781b367caffb2af0f0dc4b2bc0757aa2ef50ac734469f3f31a250ab589fbc` |
| `src/test/unit/python/repomap_kg/ops/resource_view_attachment.unit.test.py` | `7d87652e8aa41f8b04726f928d0ce3e031af578643661a29155ec94d181c2738` |
| `src/test/unit/python/repomap_kg/ops/resource_view_contracts.unit.test.py` | `5f67a166236fc93295307751cb9e51a3367b1e8d6a65d7fab9a2fbc512a13e86` |
| `src/test/unit/python/repomap_kg/ops/resource_view_observer.unit.test.py` | `d1dddb14e0057ee5ad3b42571cf7b250c46d01f803881c465b70271a0d3b7234` |
| `src/test/unit/python/repomap_kg/ops/resource_view_projections.unit.test.py` | `a85488932a830a640c3c86b6adad3d3757f8c02202ce7582023f16db96b3327e` |
| `src/test/unit/python/tools/ci/d12_candidate_context.unit.test.py` | `7fcd370c93ea8411dd6a0222aad0c1c285fbb78eb449568746b62aea71e49d7a` |
| `src/test/unit/python/tools/ci/d12_system_grant.unit.test.py` | `d792435d0416f776a0ff43f16e7f2159a4302d01ea59a1b61d24a1c0cd5053fb` |
| `tools/ci/d12_system_grant.py` | `c4161ce574059560bfbf267803d83e59f02d3da82c6eb281ee73a83b65bcdaf4` |
