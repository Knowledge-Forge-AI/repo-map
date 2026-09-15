"""Native helper batch accounting across parse diagnostics and a later path refusal."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.languages import go_protocol
from repomap_kg.extractors.languages.go_helper import resolve_go_helper_command
from repomap_kg.observations.raw import RawObservation


def test_native_batch_keeps_diagnostic_accounting_and_refuses_later_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.go").write_text("package sample\nconst A = 1\n", encoding="utf-8")
    (root / "b.go").write_text(
        "package sample\nconst BeforeError = 2\nfunc broken(\n", encoding="utf-8"
    )
    (root / "c.go").write_text("package sample\nfunc C() {}\n", encoding="utf-8")
    command = resolve_go_helper_command()
    ends: list[tuple[int, str, int, int]] = []
    validate = go_protocol.validate_go_protocol_message

    def record_end(
        payload: object, expected_sequence: int, expected_path: str,
    ) -> go_protocol.GoProtocolMessage:
        message = validate(payload, expected_sequence, expected_path)
        if message.file_end is not None:
            ends.append((
                expected_sequence, expected_path,
                message.file_end.observation_count, message.file_end.diagnostic_count,
            ))
        return message

    with mock.patch.object(go_protocol, "validate_go_protocol_message", record_end):
        observations = list(go_protocol.iter_go_protocol_observations(
            root, ["c.go", "b.go", "a.go", "a.go"], command,
        ))
    assert [(sequence, path) for sequence, path, _, _ in ends] == [
        (0, "a.go"), (1, "b.go"), (2, "c.go"),
    ]
    for _, path, observation_count, diagnostic_count in ends:
        owned = [item for item in observations if item.path == path]
        diagnostics = [item for item in owned if item.kind == "go.parse_error"]
        assert len(owned) == observation_count + diagnostic_count
        assert len(diagnostics) == diagnostic_count
        assert bool(diagnostics) is (path == "b.go")
        assert any(item.kind == "go.package" for item in owned)
    assert any(item.name == "BeforeError" for item in observations)
    assert any(item.name == "C" for item in observations)

    partial: list[RawObservation] = []
    with pytest.raises(go_protocol.GoProtocolError, match="helper exited before file_end") as caught:
        for item in go_protocol.iter_go_protocol_observations(
            root, ["a.go", "b.go", "c.go", "zz/../../outside.go"], command,
        ):
            partial.append(item)
    assert partial == observations
    assert str(root) not in str(caught.value)
    assert "outside.go" not in str(caught.value)

    recovered = list(go_protocol.iter_go_protocol_observations(root, ["a.go", "c.go"], command))
    expected = [item for item in observations if item.path != "b.go"]
    assert recovered == expected
    files = [RawObservation(
        kind="file", source_id=f"file:{path}", path=path,
        confidence="extracted", extractor="fixture", extractor_version="1.0",
        metadata={"language": "go", "role": "source"},
    ) for path in ("a.go", "c.go")]
    result = canonicalize_observations((*files, *recovered), repository_scope="native-batch")
    assert result.ok
    assert any(node.kind == "go.source_function" for node in result.graph.nodes)
    assert result.graph.node_evidence_links
    assert any(item.category == "go_canonical_accounting" for item in result.diagnostics)


def test_native_batch_preserves_diagnostic_cap_and_settled_recovery(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "first.go").write_text(
        "package sample\n\nfunc First() string {\n\treturn \"ok\"\n}\n",
        encoding="utf-8",
    )
    illegal_lines = "\n".join("@" for _ in range(80))
    (root / "overflow.go").write_text(
        f"package broken\nimport \"example.invalid/safe\"\nconst BeforeCap = 10\ntype Broken struct {{\n{illegal_lines}\n",
        encoding="utf-8",
    )
    (root / "settled.go").write_text(
        "package sample\n\nfunc Settled() int {\n\treturn 42\n}\n",
        encoding="utf-8",
    )
    command = resolve_go_helper_command()
    ends: list[tuple[int, str, int, int, bool]] = []
    validate = go_protocol.validate_go_protocol_message

    def record_end(
        payload: object, expected_sequence: int, expected_path: str,
    ) -> go_protocol.GoProtocolMessage:
        message = validate(payload, expected_sequence, expected_path)
        if message.file_end is not None:
            ends.append((
                expected_sequence, expected_path,
                message.file_end.observation_count, message.file_end.diagnostic_count,
                message.file_end.truncated,
            ))
        return message

    with mock.patch.object(go_protocol, "validate_go_protocol_message", record_end):
        observations = list(go_protocol.iter_go_protocol_observations(
            root, ["settled.go", "overflow.go", "first.go"], command,
        ))

    assert [(seq, path, d_count, trunc) for seq, path, _, d_count, trunc in ends] == [
        (0, "first.go", 0, False),
        (1, "overflow.go", 32, True),
        (2, "settled.go", 0, False),
    ]

    first_obs = [item for item in observations if item.path == "first.go"]
    assert any(item.kind == "go.function" and item.name == "First" for item in first_obs)
    assert not any(item.kind == "go.parse_error" for item in first_obs)

    overflow_obs = [item for item in observations if item.path == "overflow.go"]
    overflow_diags = [item for item in overflow_obs if item.kind == "go.parse_error"]
    # parserDiagnostics reserves one of MaxDiagnostics=32 slots for truncation.
    # The 80 distinct illegal lines supply more than 31 unique line/message keys.
    assert len(overflow_diags) == 32
    parse_errors = [item for item in overflow_diags if item.name == "go-parse-error"]
    assert len(parse_errors) == 31
    for diag in parse_errors:
        assert diag.metadata["code"] == "go-parse-error"
        assert diag.metadata["severity"] == "warning"

    trunc_diag = next(item for item in overflow_diags if item.name == "go-parse-errors-truncated")
    assert trunc_diag.metadata["code"] == "go-parse-errors-truncated"
    assert trunc_diag.metadata["bounded_message"] == "additional syntax errors omitted"
    assert trunc_diag.metadata["severity"] == "warning"
    assert any(item.name == "BeforeCap" and item.kind == "go.const" for item in overflow_obs)
    assert any(item.kind == "go.package" and item.metadata.get("partial_parse") is True for item in overflow_obs)

    settled_obs = [item for item in observations if item.path == "settled.go"]
    assert any(item.kind == "go.function" and item.name == "Settled" for item in settled_obs)
    assert not any(item.kind == "go.parse_error" for item in settled_obs)

    valid_observations = [item for item in observations if item.path != "overflow.go"]
    files = [RawObservation(
        kind="file", source_id=f"file:{path}", path=path,
        confidence="extracted", extractor="fixture", extractor_version="1.0",
        metadata={"language": "go", "role": "source"},
    ) for path in ("first.go", "settled.go")]
    canonical_result = canonicalize_observations(
        (*files, *valid_observations), repository_scope="native-batch-recovery",
    )
    assert canonical_result.ok
    node_names = {node.display_name for node in canonical_result.graph.nodes if node.kind == "go.source_function"}
    assert node_names == {"First", "Settled"}
    assert canonical_result.graph.node_evidence_links
    assert any(item.category == "go_canonical_accounting" for item in canonical_result.diagnostics)
