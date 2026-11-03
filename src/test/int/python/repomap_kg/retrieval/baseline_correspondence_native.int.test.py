"""Container-owned native materialization and byte-layer regression proof."""
from __future__ import annotations


from pathlib import (Path)

import pytest

from repomap_test_support.retrieval_evaluation_fixture import (MIXED_V1_FIXTURE_ROOT, materialize_mixed_v1_working_copy, write_mixed_v1_sqlite_home)

from repomap_test_support.retrieval_evaluation_publication import (publish_and_load_sqlite_corpus)

from retrieval_evaluation_accounting import (EVALUATOR_BYTE_BREAKDOWN_SCHEMA_V1)

from retrieval_evaluation_grading import (ExecutionState)

from retrieval_evaluation_native import (DEFAULT_MAX_STDOUT_BYTES, execute_native_baseline_task_with_breakdown)

from retrieval_evaluation_schema import (load_task_catalog)

from retrieval_evaluation_views import (NATIVE_MATERIALIZATION_WITNESS_SCHEMA_V1, build_native_materialization_witness, materialize_native_search_view, verify_native_materialization_witness)

def test_native_materialization_witness_verifies_raw_and_rendered_metadata_and_refuses_drift(
    tmp_path: Path,
) -> None:
    """NativeMaterializationWitness recomputes raw body and rendered metadata bytes and refuses disk drift."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc)
    state = publish_and_load_sqlite_corpus(sq_home, selected_aliases=("core", "companion", "feeds"))
    view = materialize_native_search_view(
        tmp_path / "native_view",
        manifest=state.manifest,
        bundle=state.bundle,
        store=state.store,
        policy=state.policy,
        selected_aliases=("core", "companion", "feeds", "mailbox"),
    )
    assert view.materialization_witness is not None
    witness, bytes_verified, elapsed_ns = verify_native_materialization_witness(
        view,
        witness=view.materialization_witness,
        manifest=state.manifest,
        bundle=state.bundle,
        store=state.store,
        policy=state.policy,
        selected_aliases=("core", "companion", "feeds", "mailbox"),
    )
    assert witness.schema == NATIVE_MATERIALIZATION_WITNESS_SCHEMA_V1
    assert witness.publication_bundle_id == state.bundle.bundle_id
    assert witness.snapshot_manifest_id == state.manifest.manifest_id
    assert witness.total_bytes_verified > 0
    assert bytes_verified == witness.total_bytes_verified
    assert elapsed_ns >= 0
    surfaces = {f.surface_kind for f in witness.files}
    assert surfaces == {"raw_body", "rendered_extracted_metadata"}

    # Recompute from bundle + manifest + store + policy and verify exact equality
    recomputed = build_native_materialization_witness(
        manifest=state.manifest,
        bundle=state.bundle,
        store=state.store,
        policy=state.policy,
        selected_aliases=("core", "companion", "feeds", "mailbox"),
    )
    assert recomputed == witness

    # Tamper with a rendered metadata file on disk -> fail closed
    meta_rel = next(f.view_relative_path for f in witness.files if f.surface_kind == "rendered_extracted_metadata")
    meta_file = view.view_root / meta_rel
    orig_bytes = meta_file.read_bytes()
    try:
        meta_file.write_bytes(orig_bytes + b"\ntampered\n")
        with pytest.raises(ValueError, match="digest drift"):
            verify_native_materialization_witness(
                view, witness=view.materialization_witness,
                manifest=state.manifest, bundle=state.bundle, store=state.store, policy=state.policy,
                selected_aliases=("core", "companion", "feeds", "mailbox"),
            )
    finally:
        meta_file.write_bytes(orig_bytes)

    # Inject an unrecorded file under view_root -> fail closed
    extra_file = view.view_root / "core" / "untracked_injected.py"
    extra_file.write_bytes(b"x = 1\n")
    try:
        with pytest.raises(ValueError, match="unexpected unrecorded files"):
            verify_native_materialization_witness(
                view, witness=view.materialization_witness,
                manifest=state.manifest, bundle=state.bundle, store=state.store, policy=state.policy,
                selected_aliases=("core", "companion", "feeds", "mailbox"),
            )
    finally:
        extra_file.unlink()

def test_native_byte_breakdown_separates_raw_stdout_candidates_and_envelope_bytes_on_cal07(
    tmp_path: Path,
) -> None:
    """cal-07 native execution preserves 495781 raw stdout bytes under 1 MiB cap while separating layers."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)
    sq_home = write_mixed_v1_sqlite_home(tmp_path / "sq_home", wc)
    state = publish_and_load_sqlite_corpus(sq_home)
    view = materialize_native_search_view(
        tmp_path / "native_view",
        manifest=state.manifest,
        bundle=state.bundle,
        store=state.store,
        policy=state.policy,
        selected_aliases=("core", "companion", "feeds", "mailbox"),
    )
    catalog = load_task_catalog(MIXED_V1_FIXTURE_ROOT / "tasks" / "catalog-v1.json")
    cal_07 = next(t for t in catalog.calibration_tasks() if t.task_id == "cal-07")

    exec_state, env, elapsed_ns, legacy_acct, breakdown = execute_native_baseline_task_with_breakdown(
        cal_07, view
    )
    assert exec_state == ExecutionState.COMPLETED
    assert elapsed_ns >= 0
    assert legacy_acct.observed_output_payload_bytes == 495781
    assert breakdown.schema_version == EVALUATOR_BYTE_BREAKDOWN_SCHEMA_V1
    assert breakdown.raw_process_stdout_bytes == 495781
    assert breakdown.native_process_stdout_cap_bytes == DEFAULT_MAX_STDOUT_BYTES == 1048576
    assert breakdown.raw_process_stdout_bytes < breakdown.native_process_stdout_cap_bytes
    assert breakdown.decoded_candidate_count >= breakdown.returned_hit_count
    assert breakdown.returned_hit_count == 10 == len(env.hits)
    assert 0 < breakdown.serialized_envelope_bytes < breakdown.raw_process_stdout_bytes
