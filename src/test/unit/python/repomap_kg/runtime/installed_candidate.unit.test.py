"""Source-derived inventory, input census and wheel inventory witnesses over temporary trees."""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest

from repomap_test_support.installed_candidate import (
    DIST_INFO, expected_entry_points, expected_inventory, expected_requires, input_digest, input_names,
    inventory_sha256, license_bytes_match, license_members, rows_sha256, wheel_inventory,
)

PYPROJECT = """[project]
name = "common-lore-index"
version = "0.0.4"
dependencies = ["typing-extensions==4.16.0"]

[project.scripts]
cloe = "common_lore_index.entrypoints:cloe_main"
repomap-kg = "common_lore_index.entrypoints:legacy_main"

[tool.setuptools.data-files]
"share/common-lore-index/rdbms" = ["src/main/resources/rdbms/changelog.yaml"]
"share/common-lore-index/rdbms/2026/06" = ["src/main/resources/rdbms/2026/06/*.sql"]
"""
LISTED = [
    "LICENSE", "NOTICE", "README.md", "pyproject.toml", "tools/run_tests.py", "src/test/x.py",
    "src/main/python/common_lore_index/__init__.py", "src/main/python/common_lore_index/cli/main.py",
    "src/main/python/common_lore_index/third_party_licenses/a.json",
    "src/main/python/common_lore_index/__pycache__/x.cpython-313.pyc",
    "src/main/python/repomap_kg/__init__.py",
    "src/main/resources/rdbms/changelog.yaml", "src/main/resources/rdbms/2026/06/01.sql",
    "src/main/resources/rdbms/2026/06/nested/02.sql",
]


def _tree(root: Path) -> Path:
    for name in LISTED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PYPROJECT if name == "pyproject.toml" else name + "\n", encoding="utf-8")
    return root


def _record_row(name: str, body: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
    return f"{name},sha256={digest},{len(body)}"


def _wheel(path: Path, members: dict[str, bytes], *, break_hash: bool = False) -> Path:
    rows = [_record_row(name, body) for name, body in members.items()]
    if break_hash:
        rows[0] = rows[0].replace("sha256=", "sha256=A")
    rows.append(f"{DIST_INFO}/RECORD,,")
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
        archive.writestr(f"{DIST_INFO}/RECORD", "\n".join(rows) + "\n")
    return path


def _members(root: Path) -> dict[str, bytes]:
    return {
        "common_lore_index/__init__.py": b"x", f"{DIST_INFO}/METADATA":
            b"Metadata-Version: 2.4\nName: common-lore-index\nRequires-Dist: typing-extensions==4.16.0\n"
            b"Requires-Dist: psycopg[c]==3.3.6; extra == \"postgres\"\n",
        f"{DIST_INFO}/entry_points.txt": b"[console_scripts]\ncloe = common_lore_index.entrypoints:cloe_main\n",
        f"{DIST_INFO}/licenses/LICENSE": (root / "LICENSE").read_bytes(),
        f"{DIST_INFO}/licenses/NOTICE": (root / "NOTICE").read_bytes(),
    }


def test_input_census_includes_notice_and_excludes_tests_and_tools(tmp_path: Path) -> None:
    names = input_names(LISTED)
    assert "NOTICE" in names and "LICENSE" in names
    assert not any(name.startswith(("tools/", "src/test/")) for name in names)
    root = _tree(tmp_path)
    digest, count = input_digest(root, names)
    assert count == len(names) and len(digest) == 64
    (root / "NOTICE").write_text("changed\n", encoding="utf-8")
    assert input_digest(root, names)[0] != digest


def test_expected_inventory_is_derived_from_owners_alone(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    expected = expected_inventory(root, LISTED)
    assert "common_lore_index/cli/main.py" in expected
    assert "common_lore_index/third_party_licenses/a.json" in expected
    assert not any("__pycache__" in name for name in expected)
    assert {name for name in expected if name.startswith("repomap_kg/")} == {
        "repomap_kg/" + leaf for leaf in ("__init__.py", "__main__.py", "ops/__init__.py",
                                          "ops/config_migration.py", "server/__init__.py", "server/mcp.py")}
    data = "common_lore_index-0.0.4.data/data/share/common-lore-index/rdbms"
    assert f"{data}/changelog.yaml" in expected and f"{data}/2026/06/01.sql" in expected
    assert not any(name.endswith("02.sql") for name in expected)
    assert {f"{DIST_INFO}/licenses/LICENSE", f"{DIST_INFO}/licenses/NOTICE", f"{DIST_INFO}/RECORD"} <= expected
    assert license_members(["LICENSE", "NOTICE", "COPYING.txt", "docs/LICENSE", "README.md"]) == [
        "COPYING.txt", "LICENSE", "NOTICE"]


def test_source_entry_points_and_requirement(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    assert expected_entry_points(root) == ["cloe=common_lore_index.entrypoints:cloe_main",
                                           "repomap-kg=common_lore_index.entrypoints:legacy_main"]
    assert expected_requires(root) == ["typing-extensions==4.16.0"]
    assert rows_sha256(["a"]) != rows_sha256(["b"])


def test_wheel_inventory_reads_only_wheel_bytes(tmp_path: Path) -> None:
    root = _tree(tmp_path / "root")
    inventory = wheel_inventory(_wheel(tmp_path / "w.whl", _members(root)))
    assert inventory.groups == ("console_scripts",)
    assert inventory.entry_points == ("cloe=common_lore_index.entrypoints:cloe_main",)
    assert inventory.requires == ("typing-extensions==4.16.0",)
    assert inventory.record_valid and inventory.pth_members == 0 and inventory.forbidden_members == 0
    assert inventory.licenses == ("LICENSE", "NOTICE") and license_bytes_match(inventory, root)
    (root / "NOTICE").write_text("drifted\n", encoding="utf-8")
    assert not license_bytes_match(inventory, root)


def test_record_hash_drift_and_forbidden_members_are_visible(tmp_path: Path) -> None:
    root = _tree(tmp_path / "root")
    broken = wheel_inventory(_wheel(tmp_path / "broken.whl", _members(root), break_hash=True))
    assert not broken.record_valid
    members = dict(_members(root), **{"leak.pth": b"import x", "tools/run_tests.py": b"x"})
    leaky = wheel_inventory(_wheel(tmp_path / "leaky.whl", members))
    assert leaky.pth_members == 1 and leaky.forbidden_members == 1


def test_inventory_digest_ignores_only_optional_top_level() -> None:
    names = {"a.py", f"{DIST_INFO}/RECORD"}
    assert inventory_sha256(names) == inventory_sha256(names | {f"{DIST_INFO}/top_level.txt"})
    assert inventory_sha256(names) != inventory_sha256(names | {"b.py"})


def test_material_refuses_an_unreviewed_message_body(tmp_path: Path) -> None:
    import shutil

    from repomap_test_support.installed_experience_fixture import FIXTURE_ROOT, write_tiny_material

    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE_ROOT, fixture)
    message = fixture / "messages" / "ledger.eml"
    message.write_bytes(message.read_bytes() + b"Changed body.\n")
    target = tmp_path / "owned material"
    with pytest.raises(AssertionError, match="installed-message-fixture-unreviewed"):
        write_tiny_material(target, fixture)
    assert not target.exists()


def test_candidate_pins_follow_current_release_and_keep_incumbent_frozen() -> None:
    import tomllib

    from installed_experience_pins import (
        CANDIDATE_DISTRIBUTION, CANDIDATE_VERSION, CANDIDATE_WHEEL_PREFIX,
        INCUMBENT_COMMIT, INCUMBENT_DISTRIBUTION, INCUMBENT_WHEEL_PREFIX,
    )
    from repomap_test_support.installed_candidate import ROOT

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert CANDIDATE_DISTRIBUTION == project["name"] == "common-lore-index"
    assert CANDIDATE_VERSION == project["version"] == "0.0.4"
    assert CANDIDATE_WHEEL_PREFIX == f"common_lore_index-{project['version']}-"
    assert INCUMBENT_COMMIT == "6d818ad6d43d38d47c64b8c474c2b64b853f631a"
    assert INCUMBENT_DISTRIBUTION == "repomap-kg"
    assert INCUMBENT_WHEEL_PREFIX == "repomap_kg-0.0.3-"
