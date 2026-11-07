"""Live witness: all eight bindings recomputed from retained state; inert after close (spec 10, Q14)."""

from __future__ import annotations

import ast
import copy
import hashlib
import pickle
from collections.abc import Callable
from dataclasses import replace
from importlib import resources

import pytest

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.contracts.witness import REQUIRED_BINDINGS
from common_lore_index.extractors.rust_pilot.archive_verifier import expected_install_tree, verify_wheel
from common_lore_index.extractors.rust_pilot.helper_protocol import decode_frames, invocation_nonce
from common_lore_index.extractors.rust_pilot.observations import build_file_observations
from common_lore_index.extractors.rust_pilot.prepared_profile import VerifiedProfile, profile_bytes
from common_lore_index.extractors.rust_pilot.witness_state import FileRecord, RunState
from repomap_test_support.rust_pilot_fake_tree_sitter.wheels import frames, item_frame, synthetic_wheel

RUN_NONCE = b"\x07" * 32
DATA = b"struct S;\n"


def _state() -> RunState:
    wheel = synthetic_wheel("alpha", {"alpha/__init__.py": b"A"})
    verified = verify_wheel(wheel.data, wheel.lock)
    document = profile_bytes("aarch64")
    profile = VerifiedProfile("aarch64", hashlib.sha256(document).hexdigest(), document, (verified, verified))
    expected = expected_install_tree([verified.members], b"helper", [])
    state = RunState(run_nonce=RUN_NONCE, run_id="rp1.0123456789abcdef", profile=profile, expected=expected,
                     helper_closure_sha256="c" * 64)
    digest = hashlib.sha256(DATA).hexdigest()
    nonce = invocation_nonce(RUN_NONCE, 1, digest)
    stdout = frames(nonce, [item_frame(0, -1, 4, 0, 9, n=[7, 8])])
    decoded = decode_frames(stdout, nonce=nonce, input_length=len(DATA))
    record = FileRecord("src/lib.rs", 1, digest, DATA, False, input_sha256=digest, nonce=nonce,
                        container_id="c" * 64, readback_digest=state.expected_digest, exit_status=0,
                        alive_until_settlement=True, stdout=stdout, absence_proven=True, outcome="succeeded",
                        completeness="complete", achieved=("syntax.tree",),
                        observations=build_file_observations("src/lib.rs", DATA, decoded, input_sha256=digest,
                                                             build_script_name=False).observations)
    state.add(record)
    state.residue_settled = True
    return state


def test_admission_requires_and_returns_every_recomputed_binding() -> None:
    state = _state()
    record = state.records["src/lib.rs"]
    assert state.bindings(record) == dict.fromkeys(REQUIRED_BINDINGS, True)
    admission = state.admit("src/lib.rs")
    assert admission.admitted and admission.observations == record.observations
    assert [item.kind for item in admission.observations] == ["rust.parse", "rust.item"]
    assert state.admit("src/other.rs").refused_bindings == REQUIRED_BINDINGS


def _forged(record: FileRecord) -> None:
    item = record.observations[1]
    record.observations = (record.observations[0], replace(item, name="Forged"))


MUTATIONS: list[tuple[Callable[[RunState, FileRecord], None], str]] = [
    (lambda s, r: setattr(r, "data", b"struct T;\n"), "selected_source_bytes"),
    (lambda s, r: setattr(r, "discovery_sha256", "0" * 64), "selected_source_bytes"),
    (lambda s, r: setattr(r, "nonce", "f" * 64), "active_run_nonce"),
    (lambda s, r: setattr(r, "exit_status", 1), "clean_exit"),
    (lambda s, r: setattr(r, "alive_until_settlement", False), "clean_exit"),
    (lambda s, r: setattr(r, "oom_killed", True), "clean_exit"),
    (lambda s, r: setattr(r, "stdout", r.stdout.replace(b'"items":1', b'"items":2')), "strict_protocol"),
    (lambda s, r: _forged(r), "input_matching_ranges"),
    (lambda s, r: setattr(r, "events", ("time_bound",)), "resource_outcome"),
    (lambda s, r: setattr(r, "absence_proven", False), "proven_cleanup"),
    (lambda s, r: setattr(s, "residue_settled", False), "proven_cleanup"),
    (lambda s, r: setattr(r, "readback_digest", "0" * 64), "admitted_profile"),
    (lambda s, r: setattr(s, "profile", replace(s.profile, profile_bytes=profile_bytes("x86_64"))), "admitted_profile"),
]


@pytest.mark.parametrize(("mutate", "binding"), MUTATIONS)
def test_each_binding_is_recomputed_not_trusted(mutate: Callable[[RunState, FileRecord], None], binding: str) -> None:
    state = _state()
    record = state.records["src/lib.rs"]
    mutate(state, record)
    admission = state.admit("src/lib.rs")
    assert binding in admission.refused_bindings and admission.observations == ()


def test_closed_or_halted_runs_are_inert() -> None:
    closed = _state()
    closed.close()
    assert closed.admit("src/lib.rs").refused_bindings == REQUIRED_BINDINGS and closed.records == {}
    assert not closed.live
    halted = _state()
    halted.halt("cleanup_incomplete")
    assert halted.admit("src/lib.rs").refused_bindings == REQUIRED_BINDINGS and not halted.live
    with pytest.raises(ContractError, match="invalid_file_record"):
        halted.add(FileRecord("b.rs", 2, "0" * 64, b"", False))


def test_witness_objects_cannot_be_pickled_or_copied() -> None:
    state = _state()
    for value in (state, state.records["src/lib.rs"]):
        for action in (pickle.dumps, copy.copy, copy.deepcopy):
            with pytest.raises(ContractError, match="witness_not_serializable"):
                action(value)


def test_construction_inputs_and_module_state_are_closed() -> None:
    profile = _state().profile
    for nonce in (b"short", bytes(31), bytes(33)):
        with pytest.raises(ContractError, match="invalid_run_state"):
            RunState(run_nonce=nonce, run_id="rp1.0", profile=profile, expected=(), helper_closure_sha256="c" * 64)
    state = _state()
    with pytest.raises(ContractError, match="invalid_file_record"):
        state.add(state.records["src/lib.rs"])
    tree = ast.parse(resources.files("common_lore_index.extractors.rust_pilot").joinpath(
        "witness_state.py").read_text(encoding="ascii"))
    mutable = [node for node in tree.body if isinstance(node, ast.Assign)
               and isinstance(node.value, (ast.Dict, ast.List, ast.Set, ast.Call))
               and not (isinstance(node.value, ast.Call) and getattr(node.value.func, "id", "") == "frozenset")]
    assert mutable == []
