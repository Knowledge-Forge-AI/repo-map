"""Unit contracts for the frozen W5 generator artifact profile."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import retrieval_semantic_generator_artifacts as artifacts


PINS_PATH = Path(artifacts.__file__).with_name(artifacts.PINS_FILENAME)


def _tiny_pins(root: Path) -> dict[str, Any]:
    pins = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    wheel = dict(pins["packages"][0])
    model_file = dict(pins["model"]["files"][0])
    wheel_bytes = b"tiny wheel fixture\n"
    model_bytes = b"tiny model fixture\n"
    wheel["sha256"] = hashlib.sha256(wheel_bytes).hexdigest()
    wheel["size"] = len(wheel_bytes)
    model_file["sha256"] = hashlib.sha256(model_bytes).hexdigest()
    model_file["size"] = len(model_bytes)
    pins["packages"] = [wheel]
    pins["model"]["files"] = [model_file]
    pins["artifact_bytes_verified"] = len(wheel_bytes) + len(model_bytes)
    wheel_path = root / "wheels" / wheel["filename"]
    model_path = root / model_file["path"]
    wheel_path.parent.mkdir(parents=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    wheel_path.write_bytes(wheel_bytes)
    model_path.write_bytes(model_bytes)
    return pins


def _verify(root: Path, pins: dict[str, Any]) -> artifacts.VerifiedArtifactProfile:
    return artifacts._verify_artifact_directory_with_document(root, pins)


def test_valid_fixture_is_immutable_and_public_safe(tmp_path: Path) -> None:
    pins = _tiny_pins(tmp_path / "artifacts")
    profile = _verify(tmp_path / "artifacts", pins)

    assert isinstance(profile.wheels, tuple)
    assert isinstance(profile.model_files, tuple)
    assert profile.artifact_status == "bytes_verified_external_gates_pending"
    assert profile.license_security_gate == artifacts.EXTERNAL_GATE_STATUS
    serialized = json.dumps(profile.to_dict(), sort_keys=True)
    assert str(tmp_path) not in serialized
    with pytest.raises(FrozenInstanceError):
        setattr(profile, "model_id", "substitute")


@pytest.mark.parametrize("mutation,code", [
    ("missing", "missing_or_extra_artifact"),
    ("extra", "missing_or_extra_artifact"),
    ("hash", "hash_mismatch"),
    ("size", "size_mismatch"),
    ("traversal", "path_traversal"),
    ("source", "source_archive_present"),
])
def test_fixture_refuses_drift_and_unapproved_shapes(tmp_path: Path, mutation: str, code: str) -> None:
    root = tmp_path / "artifacts"
    pins = _tiny_pins(root)
    if mutation == "missing":
        next(root.rglob("*.whl")).unlink()
    elif mutation == "extra":
        (root / "wheels" / "extra.whl").write_bytes(b"extra")
    elif mutation == "hash":
        next(root.rglob("*.whl")).write_bytes(b"tiny wheel fixture!")
    elif mutation == "size":
        pins["packages"][0]["size"] += 1
        pins["artifact_bytes_verified"] += 1
    elif mutation == "traversal":
        pins["model"]["files"][0]["path"] = "model/../escape.bin"
    else:
        pins["source_archives"] = ["source.tar.gz"]

    with pytest.raises(artifacts.ArtifactVerificationError) as exc_info:
        _verify(root, pins)
    assert exc_info.value.code == code


def test_symlink_and_root_symlink_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    pins = _tiny_pins(root)
    source = next(root.rglob("*.whl"))
    replacement = source.with_name("symlink.whl")
    source.unlink()
    replacement.symlink_to(root / "model" / "1_Pooling" / "config.json")
    pins["packages"][0]["filename"] = replacement.name
    with pytest.raises(artifacts.ArtifactVerificationError) as exc_info:
        _verify(root, pins)
    assert exc_info.value.code in {"symlink_rejected", "missing_or_extra_artifact"}

    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(artifacts.ArtifactVerificationError) as exc_info:
        _verify(linked_root, pins)
    assert exc_info.value.code == "root_symlink_or_not_directory"


def test_frozen_pin_document_and_offline_requirements() -> None:
    document = artifacts.load_pinned_artifact_document()
    assert len(document["packages"]) == artifacts.EXPECTED_WHEEL_COUNT
    assert len(document["model"]["files"]) == artifacts.EXPECTED_MODEL_FILE_COUNT
    requirements = artifacts.offline_requirements_text()
    assert "--no-index" in requirements
    assert "--require-hashes" in requirements
    assert requirements.count(" --hash=sha256:") == artifacts.EXPECTED_WHEEL_COUNT
    assert "https://" not in requirements


def test_production_profile_refuses_partial_or_substitute_pins() -> None:
    document = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    document["packages"] = document["packages"][:-1]
    with pytest.raises(artifacts.ArtifactVerificationError) as exc_info:
        artifacts._validate_pin_document(document, strict_identity=True)
    assert exc_info.value.code == "partial_wheel_closure"

    document = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    document["model"]["revision"] = "0" * 40
    with pytest.raises(artifacts.ArtifactVerificationError) as exc_info:
        artifacts._validate_pin_document(document, strict_identity=True)
    assert exc_info.value.code == "model_substitute"


def test_pin_file_hash_refuses_tampering(tmp_path: Path) -> None:
    document = json.loads(PINS_PATH.read_text(encoding="utf-8"))
    document["policy_version"] = "substitute"
    pin_path = tmp_path / artifacts.PINS_FILENAME
    pin_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(artifacts.ArtifactVerificationError) as exc_info:
        artifacts.load_pinned_artifact_document(pin_path)
    assert exc_info.value.code == "pins_tampered"
