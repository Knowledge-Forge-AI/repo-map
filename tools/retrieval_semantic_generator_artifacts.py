"""Byte-only verification for the optional W5 generator artifact profile."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Final, cast
ARTIFACT_SCHEMA_VERSION: Final = "cloe-w5-semantic-generator-artifact-pins-v1"
ARTIFACT_POLICY_VERSION: Final = "cloe-w5-semantic-generator-artifact-policy-v1"
DEPENDENCY_METADATA_POLICY_VERSION: Final = "cloe-w5-generator-dependency-metadata-v1"
MODEL_EXECUTION_POLICY_VERSION: Final = "cloe-w5-semantic-generator-cpu-v1"
PINS_FILENAME: Final = "retrieval_semantic_generator_pins.json"
PINS_CANONICAL_SHA256: Final = "f0237e38018f3524b87f85f7fff2bef41eda125b8f954d575aaee233541896b6"
MODEL_ID: Final = "BAAI/bge-small-en-v1.5"
MODEL_REVISION: Final = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
MODEL_DIMENSIONS: Final = 384
MODEL_MAX_SEQUENCE_LENGTH: Final = 512
MODEL_DEVICE: Final = "cpu"
MODEL_EXECUTION_MODE: Final = "ORT_SEQUENTIAL"
MODEL_THREADS: Final = 1
METADATA_SHA256: Final = "e7eb157508552e47eff1d1feb231913b3d243e89026dea9d9e1ad6f10f46f72f"
MODEL_METADATA_SHA256: Final = "83342a593581d23c4ba11c33d8204a4d626aaae6de8ca6b3e31f7244e7dee67a"
ACQUISITION_PHASE: Final = "REPOMAP-CLOE-SEMANTIC1"
EXPECTED_WHEEL_COUNT: Final = 20
EXPECTED_MODEL_FILE_COUNT: Final = 10
HASH_CHUNK_BYTES: Final = 1024 * 1024
EXTERNAL_GATE_STATUS: Final = "external_trusted_phase_required"


class ArtifactVerificationError(ValueError):
    """A public-safe, machine-readable refusal from artifact verification."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

@dataclass(frozen=True)
class WheelPin:
    name: str
    version: str
    filename: str
    sha256: str
    size: int

    @property
    def relative_path(self) -> str:
        return f"wheels/{self.filename}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "filename": self.filename,
            "path": self.relative_path, "sha256": self.sha256, "size": self.size,
        }

@dataclass(frozen=True)
class ModelFilePin:
    relative_path: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.relative_path, "sha256": self.sha256, "size": self.size}

@dataclass(frozen=True)
class VerifiedArtifactFile:
    relative_path: str
    kind: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.relative_path, "kind": self.kind,
            "size": self.size, "sha256": self.sha256,
        }

@dataclass(frozen=True)
class VerifiedArtifactProfile:
    """Immutable result; no absolute root or other machine-local path is retained."""

    schema_version: str
    policy_version: str
    model_id: str
    model_revision: str
    dimensions: int
    max_sequence_length: int
    device: str
    execution_mode: str
    intra_op_num_threads: int
    inter_op_num_threads: int
    metadata_sha256: str
    model_metadata_sha256: str
    pinned_profile_sha256: str
    wheels: tuple[WheelPin, ...]
    model_files: tuple[ModelFilePin, ...]
    verified_files: tuple[VerifiedArtifactFile, ...]
    source_identity_sha256: str
    license_security_gate: str = EXTERNAL_GATE_STATUS

    @property
    def artifact_status(self) -> str:
        return "bytes_verified_external_gates_pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "artifact_status": self.artifact_status,
            "license_security_gate": self.license_security_gate,
            "model": {
                "model_id": self.model_id, "revision": self.model_revision,
                "dimensions": self.dimensions, "max_sequence_length": self.max_sequence_length,
                "device": self.device, "execution_mode": self.execution_mode,
                "intra_op_num_threads": self.intra_op_num_threads,
                "inter_op_num_threads": self.inter_op_num_threads,
                "files": [f.to_dict() for f in self.model_files],
            },
            "metadata_sha256": self.metadata_sha256,
            "model_metadata_sha256": self.model_metadata_sha256,
            "pinned_profile_sha256": self.pinned_profile_sha256,
            "wheels": [w.to_dict() for w in self.wheels],
            "verified_files": [f.to_dict() for f in self.verified_files],
            "source_identity_sha256": self.source_identity_sha256,
        }

def _fail(code: str, detail: str) -> None:
    raise ArtifactVerificationError(code, detail)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ArtifactVerificationError("pins_invalid", "profile is not canonical JSON") from exc


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        _fail(code, detail)


def _valid_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _relative_path(value: Any, *, code: str = "invalid_profile_path") -> str:
    _require(type(value) is str and bool(value), code, "relative artifact path required")
    assert isinstance(value, str)
    path = PurePosixPath(value)
    _require(not path.is_absolute() and "\\" not in value and ":" not in value, "path_traversal", "unsafe artifact path")
    _require(not any(part in {"", ".", ".."} for part in path.parts), "path_traversal", "unsafe artifact path")
    _require(value == str(path), "path_traversal", "non-canonical artifact path")
    _require(not any(marker in value for marker in ("/Users/", "/home/", "/private/")), "private_path", "private path in profile")
    return value


def _validate_pin_document(document: Mapping[str, Any], *, strict_identity: bool) -> tuple[tuple[WheelPin, ...], tuple[ModelFilePin, ...]]:
    expected_keys = {
        "schema_version", "policy_version", "policy_versions", "acquisition_phase",
        "metadata_sha256", "model_metadata_sha256", "artifact_bytes_verified",
        "model", "packages", "source_archives", "license_security_gate",
    }
    _require(set(document) == expected_keys, "unknown_profile_key", "profile keys differ from the reviewed schema")
    _require(document.get("schema_version") == ARTIFACT_SCHEMA_VERSION, "profile_version_mismatch", "unsupported artifact profile")
    _require(document.get("policy_version") == ARTIFACT_POLICY_VERSION, "policy_version_mismatch", "unsupported artifact policy")
    _require(_valid_sha(document.get("metadata_sha256")), "invalid_metadata_hash", "metadata hash is not sha256")
    _require(_valid_sha(document.get("model_metadata_sha256")), "invalid_model_metadata_hash", "model metadata hash is not sha256")
    _require(type(document.get("artifact_bytes_verified")) is int and int(document["artifact_bytes_verified"]) > 0, "invalid_artifact_size", "invalid total artifact size")
    policies = cast(Mapping[str, Any], document.get("policy_versions"))
    _require(isinstance(policies, Mapping) and set(policies) == {"artifact_profile", "dependency_metadata", "model_execution"}, "invalid_policy_versions", "policy versions are incomplete")
    if strict_identity:
        _require(policies["artifact_profile"] == ARTIFACT_POLICY_VERSION and policies["dependency_metadata"] == DEPENDENCY_METADATA_POLICY_VERSION and policies["model_execution"] == MODEL_EXECUTION_POLICY_VERSION, "policy_version_mismatch", "policy identity differs")
        _require(document.get("metadata_sha256") == METADATA_SHA256 and document.get("model_metadata_sha256") == MODEL_METADATA_SHA256, "metadata_identity_mismatch", "metadata identity differs")
        _require(document.get("acquisition_phase") == ACQUISITION_PHASE, "acquisition_phase_mismatch", "acquisition phase differs")
    model = cast(Mapping[str, Any], document.get("model"))
    _require(isinstance(model, Mapping), "invalid_model_profile", "model profile is not an object")
    model_keys = {"model_id", "revision", "dimensions", "max_sequence_length", "device", "execution_mode", "intra_op_num_threads", "inter_op_num_threads", "files"}
    _require(set(model) == model_keys, "unknown_model_key", "model profile keys differ from the reviewed schema")
    if strict_identity:
        _require(model.get("model_id") == MODEL_ID and model.get("revision") == MODEL_REVISION, "model_substitute", "model identity is not the approved revision")
        _require(model.get("dimensions") == MODEL_DIMENSIONS and model.get("max_sequence_length") == MODEL_MAX_SEQUENCE_LENGTH, "model_profile_mismatch", "model dimensions or sequence bound differ")
        _require(model.get("device") == MODEL_DEVICE and model.get("execution_mode") == MODEL_EXECUTION_MODE, "model_profile_mismatch", "non-CPU or non-sequential execution selected")
        _require(model.get("intra_op_num_threads") == MODEL_THREADS and model.get("inter_op_num_threads") == MODEL_THREADS, "model_profile_mismatch", "thread policy differs")
    _require(isinstance(model.get("files"), list), "invalid_model_files", "model files are not a list")
    model_files: list[ModelFilePin] = []
    for raw in cast(list[Any], model["files"]):
        _require(isinstance(raw, Mapping) and set(raw) == {"path", "sha256", "size"}, "unknown_model_file_key", "model file pin has unknown keys")
        path = _relative_path(raw.get("path"), code="unknown_model_file")
        _require(path.startswith("model/"), "unknown_model_file", "model file is outside model directory")
        _require(_valid_sha(raw.get("sha256")), "invalid_model_hash", "model file hash is not sha256")
        _require(type(raw.get("size")) is int and int(raw["size"]) > 0, "invalid_model_size", "model file size is invalid")
        model_files.append(ModelFilePin(path, str(raw["sha256"]), int(raw["size"])))
    _require(len({f.relative_path for f in model_files}) == len(model_files), "duplicate_model_file", "duplicate model file")
    if strict_identity:
        _require(len(model_files) == EXPECTED_MODEL_FILE_COUNT, "partial_model_closure", "approved model file closure is incomplete")
    packages = cast(list[Any], document.get("packages"))
    _require(isinstance(packages, list), "invalid_wheel_profile", "wheel pins are not a list")
    wheels: list[WheelPin] = []
    for raw in packages:
        keys = {"name", "version", "filename", "sha256", "size"}
        _require(isinstance(raw, Mapping) and set(raw) == keys, "unknown_wheel_key", "wheel pin has unknown keys")
        name, version, filename = raw.get("name"), raw.get("version"), raw.get("filename")
        _require(type(name) is str and bool(name) and type(version) is str and bool(version), "invalid_wheel_identity", "wheel name/version is invalid")
        _relative_path(f"wheels/{filename}", code="unknown_wheel")
        _require(type(filename) is str and filename.endswith(".whl") and "/" not in filename, "unknown_wheel", "wheel filename is invalid")
        _require(_valid_sha(raw.get("sha256")), "invalid_wheel_hash", "wheel hash is not sha256")
        _require(type(raw.get("size")) is int and int(raw["size"]) > 0, "invalid_wheel_size", "wheel size is invalid")
        wheels.append(WheelPin(str(name), str(version), filename, str(raw["sha256"]), int(raw["size"])))
    _require(len({w.relative_path for w in wheels}) == len(wheels), "duplicate_wheel", "duplicate wheel")
    if strict_identity:
        _require(len(wheels) == EXPECTED_WHEEL_COUNT, "partial_wheel_closure", "approved twenty-wheel closure is incomplete")
    _require(document.get("source_archives") == [], "source_archive_present", "source archives are not admitted")
    gate = cast(Mapping[str, Any], document.get("license_security_gate"))
    _require(isinstance(gate, Mapping) and set(gate) == {"status", "license_review", "security_review"}, "invalid_external_gate", "external gate record is incomplete")
    _require(gate.get("status") == EXTERNAL_GATE_STATUS, "external_gate_mismatch", "artifact bytes cannot self-accept license or security review")
    return tuple(sorted(wheels, key=lambda w: w.relative_path)), tuple(sorted(model_files, key=lambda f: f.relative_path))


def load_pinned_artifact_document(path: Path | None = None) -> Mapping[str, Any]:
    """Load and hash-check the repository-local public pin document."""
    pin_path = Path(__file__).with_name(PINS_FILENAME) if path is None else Path(path)
    try:
        raw = pin_path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError("pins_unreadable", "artifact pin document cannot be read") from exc
    _require(isinstance(document, Mapping), "pins_invalid", "artifact pin document is not an object")
    digest = hashlib.sha256(_canonical_json(document)).hexdigest()
    _require(digest == PINS_CANONICAL_SHA256, "pins_tampered", "artifact pin document hash differs")
    _validate_pin_document(document, strict_identity=True)
    return document
def _root_path(root: Path) -> Path:
    _require(isinstance(root, Path), "invalid_root", "artifact root must be pathlib.Path")
    absolute = Path(os.path.abspath(os.fspath(root)))
    current = absolute
    while True:
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise ArtifactVerificationError("root_missing", "artifact root or parent is missing") from exc
        _require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "root_symlink_or_not_directory", "artifact root parents must be fixed directories")
        if current.parent == current:
            break
        current = current.parent
    return absolute


def _enumerate_tree(root: Path, expected_dirs: set[str]) -> set[str]:
    found: set[str] = set()

    def visit(directory: Path, relative: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise ArtifactVerificationError("artifact_unreadable", "artifact directory cannot be enumerated") from exc
        for entry in entries:
            child_rel = f"{relative}/{entry.name}" if relative else entry.name
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ArtifactVerificationError("artifact_unreadable", "artifact entry cannot be inspected") from exc
            if stat.S_ISLNK(info.st_mode):
                _fail("symlink_rejected", "artifact tree contains a symbolic link")
            if stat.S_ISDIR(info.st_mode):
                _require(child_rel in expected_dirs, "extra_path", "artifact tree contains an unapproved directory")
                visit(Path(entry.path), child_rel)
            elif stat.S_ISREG(info.st_mode):
                found.add(child_rel)
            else:
                _fail("non_regular_file", "artifact tree contains a non-regular entry")

    visit(root, "")
    return found
def _hash_file(root: Path, pin: WheelPin | ModelFilePin, kind: str) -> VerifiedArtifactFile:
    relative = pin.relative_path if isinstance(pin, WheelPin) else pin.relative_path
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        before = os.lstat(path)
        _require(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode), "symlink_rejected", "artifact file is not a fixed regular file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except ArtifactVerificationError:
        raise
    except OSError as exc:
        raise ArtifactVerificationError("artifact_unreadable", "artifact file cannot be opened") from exc
    try:
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(fd, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            _require(stat.S_ISREG(opened.st_mode) and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), "artifact_changed_while_hashing", "artifact file changed before hashing")
            while True:
                chunk = stream.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > pin.size:
                    _fail("size_mismatch", "artifact file is larger than its pin")
                digest.update(chunk)
            after_fd = os.fstat(stream.fileno())
        after = os.lstat(path)
    except ArtifactVerificationError:
        raise
    except (OSError, ValueError) as exc:
        raise ArtifactVerificationError("artifact_unreadable", "artifact file could not be hashed") from exc
    _require(
        (after_fd.st_dev, after_fd.st_ino, after_fd.st_size, after_fd.st_mtime_ns) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        and (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
        "artifact_changed_while_hashing", "artifact file changed while hashing",
    )
    observed = digest.hexdigest()
    _require(total == pin.size, "size_mismatch", "artifact file size differs from its pin")
    _require(observed == pin.sha256, "hash_mismatch", "artifact file hash differs from its pin")
    return VerifiedArtifactFile(relative, kind, total, observed)


def _identity_hash(document: Mapping[str, Any], files: tuple[VerifiedArtifactFile, ...]) -> str:
    identity = {
        "profile": hashlib.sha256(_canonical_json(document)).hexdigest(),
        "files": [f.to_dict() for f in files],
    }
    return "sha256:" + hashlib.sha256(_canonical_json(identity)).hexdigest()
def _verify_with_document(root: Path, document: Mapping[str, Any], *, strict_identity: bool) -> VerifiedArtifactProfile:
    wheels, model_files = _validate_pin_document(document, strict_identity=strict_identity)
    fixed_root = _root_path(root)
    expected_records: dict[str, tuple[WheelPin | ModelFilePin, str]] = {
        **{w.relative_path: (w, "wheel") for w in wheels},
        **{f.relative_path: (f, "model") for f in model_files},
    }
    expected_dirs = {""}
    for relative in expected_records:
        parent = PurePosixPath(relative).parent
        while str(parent) != ".":
            expected_dirs.add(str(parent))
            parent = parent.parent
    expected_dirs.discard(".")
    found = _enumerate_tree(fixed_root, expected_dirs)
    _require(found == set(expected_records), "missing_or_extra_artifact", "artifact tree does not equal the frozen file set")
    verified = tuple(_hash_file(fixed_root, expected_records[path][0], expected_records[path][1]) for path in sorted(expected_records))
    _require(sum(f.size for f in verified) == int(document["artifact_bytes_verified"]), "total_size_mismatch", "total artifact size differs from the pin")
    model = document["model"]
    profile_hash = hashlib.sha256(_canonical_json(document)).hexdigest()
    return VerifiedArtifactProfile(
        str(document["schema_version"]), str(document["policy_version"]), str(model["model_id"]), str(model["revision"]),
        int(model["dimensions"]), int(model["max_sequence_length"]), str(model["device"]), str(model["execution_mode"]),
        int(model["intra_op_num_threads"]), int(model["inter_op_num_threads"]), str(document["metadata_sha256"]),
        str(document["model_metadata_sha256"]), "sha256:" + profile_hash, wheels, model_files, verified,
        _identity_hash(document, verified), str(document["license_security_gate"]["status"]),
    )


def verify_artifact_directory(root: Path) -> VerifiedArtifactProfile:
    """Verify the exact approved profile without executing or installing anything."""
    return _verify_with_document(root, load_pinned_artifact_document(), strict_identity=True)


def _verify_artifact_directory_with_document(root: Path, document: Mapping[str, Any]) -> VerifiedArtifactProfile:
    """Test seam for tiny synthetic pins; production verification uses the frozen document."""
    return _verify_with_document(root, document, strict_identity=False)


def derive_offline_requirements(profile: VerifiedArtifactProfile | None = None) -> str:
    """Render a no-index, hash-locked requirements file; this function performs no install."""
    selected = profile if profile is not None else _verify_profile_without_directory()
    lines = [
        "# Generated from the frozen public artifact profile; text only.",
        "--no-index", "--find-links wheels", "--only-binary=:all:", "--require-hashes",
    ]
    lines.extend(f"{wheel.name}=={wheel.version} --hash=sha256:{wheel.sha256}" for wheel in selected.wheels)
    return "\n".join(lines) + "\n"


def offline_requirements_text(profile: VerifiedArtifactProfile | None = None) -> str:
    return derive_offline_requirements(profile)


def _verify_profile_without_directory() -> VerifiedArtifactProfile:
    document = load_pinned_artifact_document()
    wheels, model_files = _validate_pin_document(document, strict_identity=True)
    model = document["model"]
    return VerifiedArtifactProfile(
        str(document["schema_version"]), str(document["policy_version"]), str(model["model_id"]), str(model["revision"]),
        int(model["dimensions"]), int(model["max_sequence_length"]), str(model["device"]), str(model["execution_mode"]),
        int(model["intra_op_num_threads"]), int(model["inter_op_num_threads"]), str(document["metadata_sha256"]),
        str(document["model_metadata_sha256"]), "sha256:" + hashlib.sha256(_canonical_json(document)).hexdigest(), wheels, model_files, (),
        "sha256:" + hashlib.sha256(_canonical_json(document)).hexdigest(), str(document["license_security_gate"]["status"]),
    )


__all__ = [
    "ARTIFACT_POLICY_VERSION", "ARTIFACT_SCHEMA_VERSION", "ArtifactVerificationError", "ModelFilePin", "WheelPin",
    "VerifiedArtifactFile", "VerifiedArtifactProfile", "derive_offline_requirements", "load_pinned_artifact_document",
    "offline_requirements_text", "verify_artifact_directory",
]
