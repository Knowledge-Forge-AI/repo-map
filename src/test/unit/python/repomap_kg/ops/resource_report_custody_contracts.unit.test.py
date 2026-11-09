"""Resource-report admission metadata contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from common_lore_index.ops.resource_reports import _admission as admission
from common_lore_index.ops.resource_reports._delivery import admit_destination
from repomap_test_support.resource_report_cli_files import private_directory


def _config(tmp_path: Path) -> tuple[SimpleNamespace, Path, Path]:
    config_dir = private_directory(tmp_path / "config")
    config_alias = tmp_path / "config-alias"
    config_alias.symlink_to(config_dir)
    memory = private_directory(tmp_path / "memory")
    graph_root = private_directory(tmp_path / "graph")
    binding_root = private_directory(tmp_path / "binding")
    graph = SimpleNamespace(
        root_path_expanded=str(graph_root),
        effective_source_bindings=(
            SimpleNamespace(root_path_expanded=str(graph_root)),
            SimpleNamespace(root_path_expanded=str(binding_root)),
        ),
    )
    return SimpleNamespace(
        config_home=None,
        config_path=str(config_alias),
        server_memory=SimpleNamespace(path_expanded=str(memory)),
        graphs=(graph,),
    ), memory, binding_root


def test_config_path_alias_memory_and_bindings_are_composed_and_deduplicated(
    tmp_path: Path,
) -> None:
    config, memory, binding_root = _config(tmp_path)
    roots = admission.configured_roots(config, overrides=(binding_root, "", None))
    assert roots == (
        str(tmp_path / "config-alias"), str(tmp_path / "config"), str(memory),
        str(tmp_path / "graph"), str(binding_root),
    )
    assert len(roots) == len(set(roots))

    destination = private_directory(tmp_path / "reports") / "report.json"
    admitted = admit_destination(str(destination))
    admitted.close()
    protected = memory / "report.json"
    with pytest.raises(admission.ResourceReportRefusal) as raised:
        admission.admit_report_destination(str(protected), roots)
    assert raised.value.category == "protected_root_overlap"
    assert not protected.exists()


def test_protected_root_refusal_after_a_canonical_ancestor_disappears(
    tmp_path: Path,
) -> None:
    anchor = private_directory(tmp_path / "anchor")
    reports = private_directory(anchor / "reports")
    admitted = admit_destination(str(reports / "report.json"))
    moved = tmp_path / "moved-anchor"
    try:
        anchor.rename(moved)
        with pytest.raises(admission.ResourceReportRefusal) as raised:
            admission.check_separation(admitted, ())
        assert raised.value.category == "protected_root_unresolvable"
    finally:
        admitted.close()
    assert (moved / "reports").is_dir() and not anchor.exists()
