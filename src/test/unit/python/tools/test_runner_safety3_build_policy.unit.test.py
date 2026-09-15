from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import run_tests
import repomap_test_support.test_cov5k_r2_fix1_executors as fix1_executors
from repomap_test_support.test_cov5k_r2_fix1_catalog import build_closed_catalog
from repomap_test_support.build_profile_debt import (
    DEFERRED_BUILD_PROFILE_NODE_IDS,
    enforce_build_profile_authority,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_CURRENT_CANONICAL_COMMAND_DOCS = (
    Path("README.md"),
    Path("docs/contrib/refactor-roadmap.md"),
    Path("docs/contrib/skills/repo-map-testing-standards/SKILL.md"),
    Path("docs/contrib/testing-standards.md"),
    Path("docs/testing/containerized-smoke-test-design.md"),
    Path("docs/testing/test-runner-policy.md"),
)


def _documented_runner_commands(text: str) -> tuple[str, ...]:
    command = "python3 tools/run_tests.py"
    blocks = tuple(block for block in text.split("\n\n") if command in block)
    return tuple(block[block.index(command) :] for block in blocks)


def test_safety3_canonical_staging_applies_closed_build_deselection() -> None:
    plugin = run_tests.RecordingPytestPlugin(suite="staging", full_population=True)
    items = [
        SimpleNamespace(
            nodeid=node_id,
            get_closest_marker=lambda name: object()
            if name == "requires_build_profile"
            else None,
        )
        for node_id in DEFERRED_BUILD_PROFILE_NODE_IDS
    ]
    ordinary = SimpleNamespace(
        nodeid="src/test/int/python/ordinary.int.test.py::test_ordinary",
        get_closest_marker=lambda _name: None,
    )
    items.append(ordinary)
    deselected = []
    config = SimpleNamespace(
        hook=SimpleNamespace(
            pytest_deselected=lambda *, items: deselected.extend(items)
        )
    )

    plugin.pytest_collection_modifyitems(None, config, items)

    assert items == [ordinary]
    assert len(deselected) == len(DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert plugin.deferred_build_count == 12


def test_safety3_deferred_build_debt_is_exact_and_visible() -> None:
    assert len(DEFERRED_BUILD_PROFILE_NODE_IDS) == 12
    assert any(node.endswith("[K07]") for node in DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert any("scale15" in node for node in DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert any("scale14_postgres_storage" in node for node in DEFERRED_BUILD_PROFILE_NODE_IDS)
    assert any("fix1_rehearsal" in node for node in DEFERRED_BUILD_PROFILE_NODE_IDS)


def test_safety3_direct_build_debt_execution_fails_without_authority(
) -> None:
    with pytest.raises(RuntimeError, match="build-profile authority"):
        enforce_build_profile_authority()


def test_safety3_k07_producer_boundary_refuses_before_creating_dockerfile(
    tmp_path: Path,
) -> None:
    entry = next(
        item for item in build_closed_catalog() if item.condition_id == "K07"
    )
    temporary = tmp_path / "temporary"
    temporary.mkdir()

    with pytest.raises(RuntimeError, match="build-profile authority"):
        fix1_executors.execute_group_k(tmp_path, temporary, entry)

    assert not temporary.joinpath("K07", "Dockerfile").exists()


def test_safety3_ambient_environment_cannot_authorize_build_debt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOMAP_TEST_BUILD_PROFILE_AUTHORIZED", "1")

    with pytest.raises(RuntimeError, match="build-profile authority"):
        enforce_build_profile_authority()


@pytest.mark.parametrize(
    "arguments",
    (
        ["-m", "requires_build_profile"],
        ["-mrequires_build_profile"],
        ["--markexpr", "requires_build_profile"],
        ["--markexpr=requires_build_profile"],
    ),
)
def test_safety3_runner_rejects_forwarded_marker_override(
    arguments: list[str],
) -> None:
    with pytest.raises(RuntimeError, match="canonical marker selection"):
        run_tests.build_pytest_args(("unit", "int"), arguments)


def test_safety3_manifest_paths_are_repository_visible() -> None:
    for node_id in DEFERRED_BUILD_PROFILE_NODE_IDS:
        path = Path(node_id.split("::", 1)[0])
        assert path.is_file(), node_id


def test_safety3_current_canonical_staging_examples_are_executable() -> None:
    for path in _CURRENT_CANONICAL_COMMAND_DOCS:
        document = _REPOSITORY_ROOT / path
        commands = _documented_runner_commands(document.read_text(encoding="utf-8"))
        canonical_staging = tuple(
            command
            for command in commands
            if "--suite staging" in command
        )
        assert canonical_staging, document
        for command in canonical_staging:
            profiles = tuple(
                profile
                for profile in ("heavy", "exhaustive")
                if f"--hygiene-profile {profile}" in command
            )
            assert len(profiles) == 1, document
            assert "--declared-complete-gates 1" in command, document
            assert "--smoke-image-reference" not in command, document
