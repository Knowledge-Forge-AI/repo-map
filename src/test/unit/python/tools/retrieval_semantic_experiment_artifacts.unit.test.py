"""Bounded stdout framing tests for optional semantic experiment evidence."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest

from retrieval_semantic_experiment_artifacts import (
    ARTIFACT_LINE_PREFIX,
    ArtifactRefusal,
    MEMBER_LIMITS,
    MEMBER_NAMES,
    decode_attempt_artifacts,
    emit_attempt_artifacts,
)


def _write_attempt(
    root: Path, attempt_id: str, overrides: dict[str, bytes] | None = None
) -> Path:
    values = {
        "declaration.json": b'{"attempt_id":"' + attempt_id.encode() + b'"}\n',
        "source-manifest.json": b'{"source_files":{}}\n',
        "sources.zip": b"PK\x03\x04opaque-public-archive",
        "observations.jsonl": b'{"event":"ready"}\n',
        "report.json": b'{"status":"completed"}\n',
        "terminal.json": b'{"status":"completed"}\n',
    }
    if overrides:
        values.update(overrides)
    directory = root / attempt_id
    directory.mkdir(parents=True)
    for member in MEMBER_NAMES:
        (directory / member).write_bytes(values[member])
    return directory


def _capsule(tmp_path: Path) -> tuple[bytes, tuple[Path, Path]]:
    root = tmp_path / "attempts"
    directories = (
        _write_attempt(root, "w5-semantic-g1"),
        _write_attempt(root, "w5-semantic-g2"),
    )
    output = io.StringIO()
    emit_attempt_artifacts(directories, stream=output)
    return output.getvalue().encode("ascii"), directories


def _replace_first_member(raw: bytes, **changes: object) -> bytes:
    prefix = ARTIFACT_LINE_PREFIX.encode("ascii")
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        frame = json.loads(line[len(prefix) :].decode("ascii"))
        if frame.get("kind") != "member":
            continue
        frame.update(changes)
        lines[index] = (
            prefix
            + json.dumps(frame, sort_keys=True, separators=(",", ":")).encode("ascii")
            + b"\n"
        )
        return b"".join(lines)
    raise AssertionError("member frame not found")


def _replace_footer(raw: bytes, replacement: bytes) -> bytes:
    prefix = ARTIFACT_LINE_PREFIX.encode("ascii")
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith(prefix) and b'"kind":"footer"' in line:
            lines[index] = prefix + replacement + b"\n"
            return b"".join(lines)
    raise AssertionError("footer frame not found")


def test_complete_roundtrip_has_fixed_members_and_ignores_ordinary_stdout(
    tmp_path: Path,
) -> None:
    raw, _directories = _capsule(tmp_path)
    decoded = decode_attempt_artifacts(b"controller diagnostic\n" + raw + b"tail\n")

    assert len(decoded) == 12
    assert decoded["w5-semantic-g1/declaration.json"].startswith(b"{\"attempt_id\"")
    assert decoded["w5-semantic-g2/sources.zip"].startswith(b"PK")
    assert raw.startswith(b"\n" + ARTIFACT_LINE_PREFIX.encode("ascii"))


def test_missing_member_is_rejected_as_incomplete(tmp_path: Path) -> None:
    raw, _directories = _capsule(tmp_path)
    prefix = ARTIFACT_LINE_PREFIX.encode("ascii")
    lines = raw.splitlines(keepends=True)
    removed = False
    retained: list[bytes] = []
    for line in lines:
        if not removed and line.startswith(prefix) and b'"kind":"member"' in line:
            removed = True
            continue
        retained.append(line)

    with pytest.raises(ArtifactRefusal, match="artifact_"):
        decode_attempt_artifacts(b"".join(retained))


def test_duplicate_member_is_rejected(tmp_path: Path) -> None:
    raw, _directories = _capsule(tmp_path)
    lines = raw.splitlines(keepends=True)
    member_index = next(i for i, line in enumerate(lines) if b'"kind":"member"' in line)
    lines.insert(member_index + 1, lines[member_index])

    with pytest.raises(ArtifactRefusal, match="artifact_duplicate_member"):
        decode_attempt_artifacts(b"".join(lines))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("length", 999),
        ("sha256", "sha256:" + "0" * 64),
        ("data", base64.b64encode(b"tampered").decode("ascii")),
    ),
)
def test_member_size_hash_or_payload_tampering_is_rejected(
    tmp_path: Path, field: str, value: object
) -> None:
    raw, _directories = _capsule(tmp_path)

    with pytest.raises(ArtifactRefusal, match="artifact_"):
        decode_attempt_artifacts(_replace_first_member(raw, **{field: value}))


def test_extra_field_nonfinite_and_unsafe_frame_values_are_rejected(tmp_path: Path) -> None:
    raw, _directories = _capsule(tmp_path)

    with pytest.raises(ArtifactRefusal, match="artifact_member_frame_fields"):
        decode_attempt_artifacts(_replace_first_member(raw, extra="refused"))
    with pytest.raises(ArtifactRefusal, match="artifact_attempt_invalid"):
        decode_attempt_artifacts(_replace_first_member(raw, attempt_id="../unsafe"))
    with pytest.raises(ArtifactRefusal, match="artifact_member_invalid"):
        decode_attempt_artifacts(_replace_first_member(raw, member="../unsafe"))

    nonfinite = b'{"kind":"footer","manifest":NaN,"manifest_sha256":"bad"}'
    with pytest.raises(ArtifactRefusal, match="artifact_"):
        decode_attempt_artifacts(_replace_footer(raw, nonfinite))


def test_symlinked_attempt_member_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "attempts"
    directory = _write_attempt(root, "w5-semantic-g1")
    target = tmp_path / "outside-report.json"
    target.write_bytes(b'{"status":"completed"}\n')
    (directory / "report.json").unlink()
    (directory / "report.json").symlink_to(target)

    with pytest.raises(ArtifactRefusal, match="artifact_member_unsafe|artifact_member_unreadable"):
        emit_attempt_artifacts((directory,), stream=io.StringIO())


def test_oversized_member_is_refused_before_reading_payload(tmp_path: Path) -> None:
    root = tmp_path / "attempts"
    directory = _write_attempt(
        root,
        "w5-semantic-g1",
        {"terminal.json": b"x" * (MEMBER_LIMITS["terminal.json"] + 1)},
    )

    with pytest.raises(ArtifactRefusal, match="artifact_member_size"):
        emit_attempt_artifacts((directory,), stream=io.StringIO())


def test_symlinked_ancestor_and_self_consistent_partial_capsule_are_refused(tmp_path: Path) -> None:
    _raw, directories = _capsule(tmp_path)
    link = tmp_path / "linked-attempts"
    link.symlink_to(directories[0].parent, target_is_directory=True)
    with pytest.raises(ArtifactRefusal, match="artifact_attempt_unsafe"):
        emit_attempt_artifacts((link / directories[0].name,), stream=io.StringIO())
    output = io.StringIO()
    emit_attempt_artifacts((directories[0],), stream=output)
    with pytest.raises(ArtifactRefusal, match="artifact_incomplete"):
        decode_attempt_artifacts(output.getvalue().encode("ascii"))


@pytest.mark.parametrize("value", [42, "path", b"path", (42,)])
def test_untyped_attempt_inputs_are_refused_without_coercion(value: object) -> None:
    with pytest.raises(ArtifactRefusal, match="artifact_attempt"):
        emit_attempt_artifacts(value, stream=io.StringIO())
