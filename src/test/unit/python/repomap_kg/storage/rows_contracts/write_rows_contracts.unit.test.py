from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

from repomap_test_support.storage_rows_contracts import (
CRITICAL_WRITE_ROW_FIELDS,
_file_observation,
_shell_observation,
)

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage import rows
from repomap_kg.graph.discovery import classify_path
from repomap_kg.storage.staged_rows import build_staged_rows


def test_discovery_files_supply_seven_durable_rows_and_preserve_source_relative_paths(tmp_path):
    paths = ('scripts/deploy.sh', 'scripts/common.sh', 'scripts/parse.awk',
             'scripts/env.zsh', 'scripts/provision.ps1', 'tests/suite.bats', 'tests/runner.zunit')
    observations = []
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text('# fixture\n')
        observations.append(classify_path(tmp_path, path).to_observation())
    specialized = _shell_observation('scripts/deploy.sh#call:echo', 'scripts/deploy.sh', 'tool:echo')
    assert not rows.file_rows_from_observations([specialized])
    assert tuple(row.path for row in rows.file_rows_from_observations(observations)) == tuple(sorted(paths))
    prepared = build_staged_rows([*observations, specialized], repository_name='fixture', stage_id='fixture-stage')
    try:
        assert prepared.files == 7
        assert prepared.row_counts['files'] == 7
        first = list(prepared.family_rows['files'])
        assert [row['path'] for row in first] == sorted(paths)
        assert list(prepared.family_rows['files']) == first
    finally:
        prepared.close()


def test_maintenance_file_path_is_unchanged_at_actual_staged_adapter():
    observation = _file_observation('src/recovered.py')
    prepared = build_staged_rows([observation], repository_name='fixture', stage_id='recovery-stage')
    try:
        assert prepared.files == 1
        assert [row['path'] for row in prepared.family_rows['files']] == ['src/recovered.py']
    finally:
        prepared.close()


@pytest.mark.parametrize(
    ("class_name", "expected_fields"),
    sorted(CRITICAL_WRITE_ROW_FIELDS.items()),
)
def test_storage_rows_write_dataclass_field_order_and_frozen_contracts(
    class_name: str,
    expected_fields: tuple[str, ...],
) -> None:
    row_class = getattr(rows, class_name)

    assert is_dataclass(row_class)
    assert getattr(row_class, "__dataclass_params__").frozen
    assert tuple(field.name for field in fields(row_class)) == expected_fields
    assert class_name in rows.__all__

def test_storage_rows_frozen_instances_reject_mutation() -> None:
    row = rows.FileRow(
        path="src/app.py",
        language="python",
        role="source",
        confidence="manual",
        content_hash=None,
        executable=False,
        generated=False,
        metadata_json={},
    )

    with pytest.raises(FrozenInstanceError):
        setattr(row, "path", "src/changed.py")

def test_file_rows_sort_and_preserve_null_false_zero_and_empty_metadata() -> None:
    observations = [
        _file_observation("z.py", source_id="source:z"),
        RawObservation(
            kind="shell.command",
            source_id="script#call:echo",
            path="script",
            target="tool:echo",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="1",
        ),
        _file_observation("a.py", source_id="source:a"),
    ]

    file_rows = rows.file_rows_from_observations(observations)

    assert tuple(row.path for row in file_rows) == ("a.py", "z.py")
    first = file_rows[0]
    assert first.content_hash is None
    assert first.executable is False
    assert first.generated is False
    assert first.metadata_json == {
        "raw_source_id": "source:a",
        "confidence": "manual",
        "extractor": "fixture-discovery",
        "extractor_version": "1",
        "source_metadata": {
            "language": "python",
            "role": "source",
            "content_hash": None,
            "generated": False,
            "executable": False,
            "line_count": 0,
            "description": "",
            "tags": [],
            "settings": {},
        },
    }

def test_raw_rows_preserve_input_order_ordinals_and_optional_payload_omission() -> None:
    observations = [
        _file_observation("README.md"),
        _shell_observation(
            "bin/tool#call:echo",
            "bin/tool",
            "tool:echo",
            start_line=4,
            end_line=4,
            command="echo",
        ),
    ]

    raw_rows = rows.raw_observation_rows_from_observations(observations)

    assert tuple(row.ordinal for row in raw_rows) == (0, 1)
    assert tuple(row.source_id for row in raw_rows) == (
        "README.md",
        "bin/tool#call:echo",
    )
    assert "start_line" not in raw_rows[0].payload_json
    assert "end_line" not in raw_rows[0].payload_json
    assert "target" not in raw_rows[0].payload_json
    assert raw_rows[1].payload_json["start_line"] == 4
    assert raw_rows[1].payload_json["target"] == "tool:echo"
    assert raw_rows[0].payload_hash == rows.raw_observation_payload_hash(
        observations[0]
    )

def test_hash_and_canonical_json_contracts_are_deterministic() -> None:
    left = RawObservation(
        kind="file",
        source_id="README.md",
        path="README.md",
        confidence="manual",
        extractor="fixture-discovery",
        extractor_version="1",
        metadata={"z": 1, "a": {"nested": True}},
    )
    same = RawObservation(
        kind="file",
        source_id="README.md",
        path="README.md",
        confidence="manual",
        extractor="fixture-discovery",
        extractor_version="1",
        metadata={"a": {"nested": True}, "z": 1},
    )
    changed = RawObservation(
        kind="file",
        source_id="README.md",
        path="README.md",
        confidence="manual",
        extractor="fixture-discovery",
        extractor_version="1",
        metadata={"a": {"nested": True}, "z": 2},
    )

    assert rows.raw_observation_payload_hash(left) == rows.raw_observation_payload_hash(
        same
    )
    assert rows.raw_observation_payload_hash(left) != rows.raw_observation_payload_hash(
        changed
    )
    assert rows.identity_metadata_hash({"b": [2, 1], "a": {"ok": True}}) == (
        rows.identity_metadata_hash({"a": {"ok": True}, "b": [2, 1]})
    )
    assert rows.identity_metadata_hash({"b": [2, 1]}) != rows.identity_metadata_hash(
        {"b": [1, 2]}
    )
    assert rows.canonical_json_value(
        {"b": Counter({"z": 2, "a": 1}), "a": {"nested": True}}
    ) == {"a": {"nested": True}, "b": {"a": 1, "z": 2}}
    assert (
        rows.canonical_json_text(
            {
                "b": Counter({"z": 2, "a": 1}),
                "a": {"nested": True},
                "c": [3, {"d": False}],
            }
        )
        == '{"a":{"nested":true},"b":{"a":1,"z":2},"c":[3,{"d":false}]}'
    )

def test_canonical_rows_preserve_result_order_and_edge_link_identity() -> None:
    observations = [
        _shell_observation(
            "bin/a#call:echo",
            "bin/a",
            "tool:echo",
            start_line=1,
            end_line=1,
            command="echo",
        ),
        _shell_observation(
            "bin/b#call:cat",
            "bin/b",
            "tool:cat",
            start_line=2,
            end_line=2,
            command="cat",
        ),
    ]
    result = canonicalize_observations(observations)

    canonical_rows = rows.canonical_rows_from_result(result)

    assert tuple(row.canonical_key for row in canonical_rows.nodes) == (
        "file:bin/a",
        "tool:echo",
        "file:bin/b",
        "tool:cat",
    )
    assert tuple(
        (row.source_key, row.edge_kind, row.target_key) for row in canonical_rows.edges
    ) == (
        ("file:bin/a", "executes", "tool:echo"),
        ("file:bin/b", "executes", "tool:cat"),
    )
    assert tuple(row.raw_observation_ordinal for row in canonical_rows.evidence) == (
        0,
        1,
    )
    assert tuple(link.evidence_key for link in canonical_rows.edge_evidence_links) == (
        "evidence:0:bin/a:1-1:fixture-shell:bin/a#call:echo",
        "evidence:1:bin/b:2-2:fixture-shell:bin/b#call:cat",
    )
    assert tuple(
        link.identity_metadata_hash for link in canonical_rows.edge_evidence_links
    ) == tuple(row.identity_metadata_hash for row in canonical_rows.edges)
