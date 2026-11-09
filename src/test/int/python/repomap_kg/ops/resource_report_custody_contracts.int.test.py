"""Resource-report file and delivery custody contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from common_lore_index.cli._resource_report_session import ResourceReportSession
from common_lore_index.ops.resource_reports._admission import ResourceReportRefusal, configured_roots
from common_lore_index.ops.resource_reports._codec import (
    MAX_FILE_BYTES_V2, ResourceReportError, decode_report, encode_report,
)
from common_lore_index.ops.resource_reports._delivery import DeliveryError, admit_destination, deliver
from common_lore_index.ops.resource_reports._files import read_report_file
from common_lore_index.ops.resource_view._context_projection import unfinished_compact_context
from repomap_test_support.resource_report_cli_files import private_directory, report_leftovers


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def _private_report(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _valid_payload() -> tuple[dict[str, object], bytes]:
    data = encode_report(unfinished_compact_context())
    return json.loads(data), data


@pytest.mark.parametrize("schema", ("cloe-resource-view-v1", "cloe-resource-view-v2"))
@pytest.mark.parametrize("field", ("metrics", "limits"))
def test_private_report_shape_refusals_cross_file_reader_and_codec(
    tmp_path: Path, schema: str, field: str,
) -> None:
    reports = private_directory(tmp_path / "reports")
    payload, _ = _valid_payload()
    payload["schema"] = schema
    payload[field] = {}
    path = reports / f"{schema[-2:]}-{field}.json"
    _private_report(path, _canonical(payload))
    data = read_report_file(path)
    with pytest.raises(ResourceReportError) as raised:
        decode_report(data)
    assert raised.value.category == "invalid_shape"


def test_private_depth_bound_refusal_crosses_file_reader_and_codec(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / "too-deep.json"
    _private_report(path, b'{"metrics":[[[[0]]]]}\n')
    data = read_report_file(path)
    with pytest.raises(ResourceReportError) as raised:
        decode_report(data)
    assert raised.value.category == "too_deep"


def test_private_file_over_v2_bound_refuses_at_the_finite_reader_boundary(
    tmp_path: Path,
) -> None:
    reports = private_directory(tmp_path / "reports")
    path = reports / "oversized.json"
    _private_report(path, b"x" * (MAX_FILE_BYTES_V2 + 1))
    with pytest.raises(ResourceReportError) as raised:
        read_report_file(path)
    assert raised.value.category == "too_large"
    assert not report_leftovers(reports)


def test_closed_held_descriptor_refuses_new_delivery_and_keeps_earlier_report(
    tmp_path: Path,
) -> None:
    reports = private_directory(tmp_path / "reports")
    data = encode_report(unfinished_compact_context())
    earlier = reports / "earlier.json"
    first = admit_destination(str(earlier))
    try:
        deliver(first, data)
    finally:
        first.close()

    admitted = admit_destination(str(reports / "next.json"))
    admitted.close()
    with pytest.raises(DeliveryError) as raised:
        deliver(admitted, data)
    assert raised.value.category == "parent_changed"
    assert read_report_file(earlier) == data
    assert not (reports / "next.json").exists()
    assert report_leftovers(reports) == []


def test_session_uses_canonical_config_and_binding_roots_before_private_delivery(tmp_path: Path) -> None:
    config_dir = private_directory(tmp_path / "config")
    config_alias = tmp_path / "config-alias"
    config_alias.symlink_to(config_dir)
    memory = private_directory(tmp_path / "memory")
    source = private_directory(tmp_path / "source")
    binding = private_directory(tmp_path / "binding")
    config = SimpleNamespace(
        config_home=None, config_path=str(config_alias),
        server_memory=SimpleNamespace(path_expanded=str(memory)),
        graphs=(SimpleNamespace(root_path_expanded=str(source), effective_source_bindings=(
            SimpleNamespace(root_path_expanded=str(source)), SimpleNamespace(root_path_expanded=str(binding)),
        )),),
    )
    roots = configured_roots(config, overrides=(binding, "", None))
    assert roots == tuple(map(str, (config_alias, config_dir, memory, source, binding)))
    for root in (config_alias, config_dir, memory, source, binding):
        rejected = ResourceReportSession(str(root / "refused.json"))
        try:
            category = "parent_symlink" if root == config_alias else "protected_root_overlap"
            with pytest.raises(ResourceReportRefusal, match=category):
                rejected.admit(config, overrides=(binding,))
            assert not rejected.admitted and not (root / "refused.json").exists()
        finally:
            rejected.close()
    reports = private_directory(tmp_path / "reports")
    target = reports / "accepted.json"
    accepted = ResourceReportSession(str(target))
    try:
        accepted.admit(config)
        assert accepted.admitted
        accepted.deliver(unfinished_compact_context)
    finally:
        accepted.close()
    assert decode_report(read_report_file(target)) == unfinished_compact_context()
    assert not report_leftovers(reports)
