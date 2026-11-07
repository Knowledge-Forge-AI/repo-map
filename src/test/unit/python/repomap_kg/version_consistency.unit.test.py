from __future__ import annotations

from pathlib import Path
import tomllib

import sys

import common_lore_index

repo_root = Path(__file__).resolve().parents[5]
tools_dir = repo_root / "tools"
if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

from ci.public_export_policy import DEFAULT_TARGET_VERSION


def test_version_consistency() -> None:
    pyproject_path = repo_root / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)
    pyproject_version = pyproject["project"]["version"]
    assert pyproject_version == "0.0.3"
    assert common_lore_index.__version__ == "0.0.3"
    assert DEFAULT_TARGET_VERSION == "0.0.3"
    assert common_lore_index.__version__ == pyproject_version
    assert DEFAULT_TARGET_VERSION == pyproject_version
