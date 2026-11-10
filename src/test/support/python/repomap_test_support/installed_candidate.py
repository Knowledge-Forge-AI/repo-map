"""Shared offline candidate/incumbent wheels and the source-derived inventory (section 4).

``candidate_wheel`` copies the exact regular-file package-input census (tracked
and untracked non-ignored ``README.md``, ``LICENSE``, ``NOTICE``,
``pyproject.toml``, ``src/main/python/**`` and ``src/main/resources/**``) into an
owned source tree and runs ``pip wheel --no-index --no-deps
--no-build-isolation`` once per pytest process under ``arch7f_pip``. The memo is
keyed by the input digest; a digest change discards it. ``incumbent_wheel``
builds the immutable predecessor objects the cutover owner already uses.
``expected_inventory`` is derived from the current owners alone; the wheel
SHA-256 is a preparation binding, never an expected fact.
"""

from __future__ import annotations

import base64
import csv
import fnmatch
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from runner_coverage_bootstrap import resolve_bootstrap_capability
from runner_coverage_execution import launch_observed_process, prepare_child_coverage_environment

from installed_experience_pins import (
    CANDIDATE_INPUT_FILES, CANDIDATE_INPUT_TREES, CANDIDATE_VERSION, CANDIDATE_WHEEL_PREFIX,
    INCUMBENT_COMMIT, INCUMBENT_WHEEL_PREFIX, LEGACY_FACADE, SETUPTOOLS_DEFAULT_LICENSE_PATTERNS,
)

ROOT = Path(__file__).resolve().parents[5]
DIST_INFO = f"common_lore_index-{CANDIDATE_VERSION}.dist-info"
DATA_PREFIX = f"common_lore_index-{CANDIDATE_VERSION}.data/data/"
OPTIONAL_DIST_INFO = frozenset({f"{DIST_INFO}/top_level.txt"})
FORBIDDEN_PREFIXES = ("src/", "tools/", "test/", "resources/")
_MEMO: dict[tuple[str, str], BuiltWheel] = {}


@dataclass(frozen=True)
class BuiltWheel:
    wheel: Path
    source: Path
    input_sha256: str
    input_count: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.wheel.read_bytes()).hexdigest()


def _environment(family: str) -> dict[str, str]:
    capability = resolve_bootstrap_capability(env=os.environ)
    return prepare_child_coverage_environment(
        os.environ, family=family, capability=capability,
        extra_env={"PYTHONNOUSERSITE": "1", "PIP_NO_INDEX": "1",
                   "PIP_DISABLE_PIP_VERSION_CHECK": "1"})


def _require(args: Sequence[str], cwd: Path, family: str) -> str:
    environment = _environment(family)
    environment.pop("PYTHONPATH", None)
    completed = launch_observed_process(list(args), family=family, env=environment, cwd=cwd,
                                        timeout=600)
    if completed.returncode != 0:
        raise AssertionError(f"installed-candidate child failed: {completed.stderr[-2000:]}")
    return completed.stdout


def input_names(listed: Iterable[str]) -> list[str]:
    """Package inputs from a census listing: root files plus the two source trees."""
    return sorted({name for name in listed
                   if name in CANDIDATE_INPUT_FILES or name.startswith(CANDIDATE_INPUT_TREES)})


def listed_inputs(root: Path = ROOT) -> list[str]:
    output = _require(("git", "ls-files", "--cached", "--others", "--exclude-standard", "--",
                       *CANDIDATE_INPUT_FILES, *CANDIDATE_INPUT_TREES), root, "arch7f_probe")
    return [name for name in input_names(output.splitlines()) if (root / name).is_file()]


def input_digest(root: Path, names: Sequence[str]) -> tuple[str, int]:
    """SHA-256 of canonical ``{path: sha256}``, the cutover rule extended by NOTICE."""
    inputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    data = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest(), len(inputs)


def _copy_census(root: Path, names: Sequence[str], target: Path) -> None:
    for name in names:
        source = root / name
        if source.is_symlink() or not source.is_file():
            raise AssertionError("installed-candidate input is not a regular file")
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _build(source: Path, output: Path, prefix: str) -> Path:
    output.mkdir()
    _require((sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
              "--no-build-isolation", "--wheel-dir", str(output), str(source)),
             output.parent, "arch7f_pip")
    wheels = sorted(output.glob("*.whl"))
    if len(wheels) != 1 or not wheels[0].name.startswith(prefix):
        raise AssertionError("installed-candidate build did not yield exactly one expected wheel")
    return wheels[0]


def _scratch(factory: Any, kind: str, digest: str) -> Path:
    root = Path(factory.getbasetemp()) / "installed candidate" / f"{kind}-{digest[:16]}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def candidate_wheel(factory: Any, root: Path = ROOT) -> BuiltWheel:
    """The exact current candidate wheel, built at most once per process and input digest."""
    names = listed_inputs(root)
    digest, count = input_digest(root, names)
    memo = _MEMO.get(("candidate", digest))
    if memo is not None and memo.wheel.is_file():
        return memo
    scratch = _scratch(factory, "candidate", digest)
    source = scratch / "source"
    _copy_census(root, names, source)
    built = BuiltWheel(_build(source, scratch / "wheel", CANDIDATE_WHEEL_PREFIX), source, digest, count)
    _MEMO[("candidate", digest)] = built
    return built


def incumbent_wheel(factory: Any, root: Path = ROOT) -> BuiltWheel:
    """The immutable predecessor's wheel from ``git archive`` objects, once per process."""
    memo = _MEMO.get(("incumbent", INCUMBENT_COMMIT))
    if memo is not None and memo.wheel.is_file():
        return memo
    scratch = _scratch(factory, "incumbent", hashlib.sha256(INCUMBENT_COMMIT.encode()).hexdigest())
    archive = scratch / "incumbent.tar"
    _require(("git", "archive", "--format=tar", "--output=" + str(archive), INCUMBENT_COMMIT,
              "pyproject.toml", "README.md", "LICENSE", "src/main/python/repomap_kg",
              "src/main/resources"), root, "arch7f_probe")
    source = scratch / "incumbent"
    source.mkdir()
    with tarfile.open(archive) as members:
        members.extractall(source, filter="data")
    names = sorted(path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file())
    digest, count = input_digest(source, names)
    built = BuiltWheel(_build(source, scratch / "wheel", INCUMBENT_WHEEL_PREFIX), source, digest, count)
    _MEMO[("incumbent", INCUMBENT_COMMIT)] = built
    return built


def _pyproject(root: Path) -> dict[str, Any]:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def license_members(root_names: Iterable[str]) -> list[str]:
    """Root files the pinned setuptools default license patterns select."""
    return sorted(name for name in root_names if "/" not in name and any(
        fnmatch.fnmatchcase(name, pattern) for pattern in SETUPTOOLS_DEFAULT_LICENSE_PATTERNS))


def expected_inventory(root: Path = ROOT, listed: Sequence[str] | None = None) -> set[str]:
    """Wheel members derived from the current owners; ``top_level.txt`` is optional."""
    names = input_names(listed if listed is not None else listed_inputs(root))
    package = "src/main/python/common_lore_index/"
    expected = {"common_lore_index/" + name[len(package):] for name in names
                if name.startswith(package) and "/__pycache__/" not in name
                and not name.endswith(".pyc")}
    expected |= {"repomap_kg/" + suffix for suffix in LEGACY_FACADE}
    for target, patterns in _pyproject(root)["tool"]["setuptools"]["data-files"].items():
        for pattern in patterns:
            for name in names:
                if fnmatch.fnmatchcase(name, pattern) and "/" not in name[len(pattern.rsplit("/", 1)[0]) + 1:]:
                    expected.add(DATA_PREFIX + target + "/" + name.rsplit("/", 1)[1])
    expected |= {f"{DIST_INFO}/{leaf}" for leaf in ("METADATA", "WHEEL", "RECORD", "entry_points.txt")}
    expected |= {f"{DIST_INFO}/licenses/{name}" for name in license_members(names)}
    return expected


def inventory_sha256(names: Iterable[str]) -> str:
    rows = sorted(set(names) - OPTIONAL_DIST_INFO)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def expected_entry_points(root: Path = ROOT) -> list[str]:
    return sorted(f"{name}={target}" for name, target in _pyproject(root)["project"]["scripts"].items())


def expected_requires(root: Path = ROOT) -> list[str]:
    return sorted(str(item).replace(" ", "") for item in _pyproject(root)["project"]["dependencies"])


def rows_sha256(rows: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


@dataclass(frozen=True)
class WheelInventory:
    names: frozenset[str]
    entry_points: tuple[str, ...]
    groups: tuple[str, ...]
    requires: tuple[str, ...]
    record_valid: bool
    pth_members: int
    forbidden_members: int
    licenses: tuple[str, ...]
    license_bytes: dict[str, str]


def _record_valid(archive: zipfile.ZipFile, names: set[str]) -> bool:
    record = f"{DIST_INFO}/RECORD"
    if record not in names:
        return False
    rows = list(csv.reader(io.StringIO(archive.read(record).decode("utf-8"))))
    recorded = {row[0] for row in rows if row}
    if recorded != names:
        return False
    for row in rows:
        if not row or row[0] == record:
            continue
        algorithm, _sep, value = row[1].partition("=")
        body = archive.read(row[0])
        digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
        if algorithm != "sha256" or value != digest or row[2] != str(len(body)):
            return False
    return True


def wheel_inventory(wheel: Path) -> WheelInventory:
    """Read the built wheel only; every claim comes from its bytes."""
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_text = archive.read(f"{DIST_INFO}/entry_points.txt").decode("utf-8")
        groups: list[str] = []
        entries: list[str] = []
        for line in entry_text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                groups.append(line[1:-1])
            elif line:
                key, _sep, value = line.partition("=")
                entries.append(f"{key.strip()}={value.strip()}")
        metadata = BytesParser().parsebytes(archive.read(f"{DIST_INFO}/METADATA"))
        requires = sorted(item.replace(" ", "") for item in metadata.get_all("Requires-Dist") or []
                          if ";" not in item)
        licenses = sorted(name.rsplit("/", 1)[1] for name in names
                          if name.startswith(f"{DIST_INFO}/licenses/"))
        license_bytes = {name: hashlib.sha256(archive.read(f"{DIST_INFO}/licenses/{name}")).hexdigest()
                         for name in licenses}
        return WheelInventory(
            frozenset(names), tuple(sorted(entries)), tuple(groups), tuple(requires),
            _record_valid(archive, names), sum(name.endswith(".pth") for name in names),
            sum(name.startswith(FORBIDDEN_PREFIXES) for name in names), tuple(licenses),
            license_bytes)


def license_bytes_match(inventory: WheelInventory, root: Path = ROOT) -> bool:
    """Both selected root license files must be present byte-for-byte."""
    return bool(inventory.licenses) and all(
        (root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
        for name, digest in inventory.license_bytes.items())


__all__ = [
    "BuiltWheel", "DIST_INFO", "ROOT", "WheelInventory", "candidate_wheel", "expected_entry_points",
    "expected_inventory", "expected_requires", "incumbent_wheel", "input_digest", "input_names",
    "inventory_sha256", "license_bytes_match", "license_members", "listed_inputs", "rows_sha256",
    "wheel_inventory",
]
