"""Private evidence custody and actual input retention, without a model or database."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from repomap_test_support.w5_public_text_evidence import (
    private_generation_inputs, read_private_file, retain_raw_members, write_private_file,
)
from retrieval_semantic_raw_component_anchors import MEMBER_ROLES


def test_private_files_are_exclusive_owned_bounded_and_exact(tmp_path: Path) -> None:
    root = tmp_path.resolve() / "private"
    path = root / "actual.json"
    write_private_file(path, b'{"actual":true}\n')
    assert root.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_private_file(path) == b'{"actual":true}\n'
    with pytest.raises(FileExistsError):
        write_private_file(path, b"replaced")
    with pytest.raises(ValueError, match="private_evidence_file"):
        read_private_file(path, 1)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private_evidence_file"):
        read_private_file(path)


def test_private_paths_refuse_links_and_fifo_without_opening_a_writer(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    real = root / "real"
    real.mkdir()
    link = root / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        write_private_file(link / "unsafe.json", b"{}")
    target = real / "data.json"
    write_private_file(target, b"{}")
    alias = real / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        read_private_file(alias)
    fifo = real / "owned.fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError, match="private_evidence_file"):
        read_private_file(fifo)


def test_raw_response_bytes_are_retained_without_claiming_verification(tmp_path: Path) -> None:
    root = tmp_path.resolve() / "raw-export"
    members = {name: b"invalid parser input" for name in MEMBER_ROLES}
    retain_raw_members(root, "w5-semantic-g1", members)
    assert all(read_private_file(root / "raw-components" / "w5-semantic-g1" / name) == value
               for name, value in members.items())
    with pytest.raises(ValueError, match="private_raw_exists"):
        retain_raw_members(root, "w5-semantic-g1", members)
    with pytest.raises(ValueError, match="private_raw_members"):
        retain_raw_members(root, "../../escape", members)
    with pytest.raises(ValueError, match="private_raw_members"):
        retain_raw_members(root, "w5-semantic-g2", {"report.json": b"{}"})


def test_private_inputs_retain_printed_gate_and_original_questions_and_golds() -> None:
    value = lambda payload: SimpleNamespace(to_dict=lambda: payload)
    prepared = SimpleNamespace(pin=value({"actual_pin": 1}), preparation=value({"actual_preparation": 2}),
                               census=value({"actual_census": 3}))
    original = {"question": "original question", "gold": {"accepted_files": ["public.py"]}}
    selected = SimpleNamespace(pins=value({"original_pins": 4}), tasks=(value(original),),
                               to_dict=lambda: {"actual_selection": 5})
    printed = b'{"actual_generation_gate":true}\n'
    inputs = private_generation_inputs(prepared, selected, printed)
    assert set(inputs) == {"generation-gate.json", "publication.json", "task-pins.json", "selected-task-set.json",
                           "selected-task-objects.json", "preparation.json", "census.json"}
    assert inputs["generation-gate.json"] is printed
    assert json.loads(inputs["selected-task-objects.json"]) == [original]
    assert json.loads(inputs["publication.json"]) == {"actual_pin": 1}
    assert json.loads(inputs["preparation.json"]) == {"actual_preparation": 2}
    assert json.loads(inputs["census.json"]) == {"actual_census": 3}
