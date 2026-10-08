"""Child process coverage bootstrap generation, capability records, and lifecycle hooks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from runner_coverage_template import (
    BOOTSTRAP_TEMPLATE as BOOTSTRAP_TEMPLATE,
    RUNNER_BOOTSTRAP_MARKER as RUNNER_BOOTSTRAP_MARKER,
    generate_bootstrap_source as generate_bootstrap_source,
    install_bootstrap_directory as install_bootstrap_directory,
)

try:
    from test_sandbox_contract import INNER_TEST_SCRATCH_ROOT
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_sandbox_contract import INNER_TEST_SCRATCH_ROOT


@dataclass(frozen=True)
class BootstrapCapabilityRecord:
    """Namespace-aware authorized bootstrap identity and visible mount aliases."""

    identity: str
    host_visible_path: Path
    same_namespace_path: Path
    container_mount_aliases: tuple[str, ...] = ()
    additional_host_paths: tuple[Path, ...] = ()

    def is_alias(self, path: Path | str) -> bool:
        p_str = str(path).rstrip(os.sep)
        aliases = (
            str(self.host_visible_path).rstrip(os.sep),
            str(self.same_namespace_path).rstrip(os.sep),
            *(str(p).rstrip(os.sep) for p in self.additional_host_paths),
            *(str(a).rstrip(os.sep) for a in self.container_mount_aliases),
        )
        if p_str in aliases:
            return True
        try:
            p_res = Path(path).resolve()
            targets = (
                self.host_visible_path.resolve(),
                self.same_namespace_path.resolve(),
                *(p.resolve() for p in self.additional_host_paths),
            )
            return p_res in targets
        except OSError:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "host_visible_path": str(self.host_visible_path),
            "same_namespace_path": str(self.same_namespace_path),
            "container_mount_aliases": list(self.container_mount_aliases),
            "additional_host_paths": [str(p) for p in self.additional_host_paths],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BootstrapCapabilityRecord:
        return cls(
            identity=str(data["identity"]),
            host_visible_path=Path(data["host_visible_path"]),
            same_namespace_path=Path(data["same_namespace_path"]),
            container_mount_aliases=tuple(data.get("container_mount_aliases", ())),
            additional_host_paths=tuple(Path(p) for p in data.get("additional_host_paths", ())),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, *, expected_dir: Path | None = None) -> BootstrapCapabilityRecord:
        data = json.loads(path.read_text(encoding="utf-8"))
        rec = cls.from_dict(data)
        expected_ident = hashlib.sha256(BOOTSTRAP_TEMPLATE.encode("utf-8")).hexdigest()
        if rec.identity != expected_ident:
            raise ValueError(f"bootstrap capability identity mismatch: {rec.identity}")
        if expected_dir is not None:
            exp = expected_dir.resolve()
            for host_p in (rec.host_visible_path, rec.same_namespace_path, *rec.additional_host_paths):
                if not host_p.resolve().is_relative_to(exp):
                    raise ValueError(f"bootstrap capability path {host_p} escapes session {expected_dir}")
        return rec


def is_runner_bootstrap_path(
    path: Path | str,
    *,
    capability: BootstrapCapabilityRecord | None = None,
) -> bool:
    """Return True if path matches runner bootstrap capability aliases or contains the marker."""
    if capability is not None and capability.is_alias(path):
        return True
    try:
        p = Path(path)
        # Avoid probing inaccessible foreign paths that cannot exist locally
        if not p.is_absolute() or p.exists():
            sitecust = p / "sitecustomize.py" if p.is_dir() else (p if p.name == "sitecustomize.py" else None)
            if sitecust and sitecust.is_file():
                with open(sitecust, "r", encoding="utf-8") as f:
                    return RUNNER_BOOTSTRAP_MARKER in f.readline()
    except OSError:
        pass
    return False


def derive_container_mount_aliases(
    bootstrap_dir: Path,
    scratch_root: str | Path | None = None,
    container_scratch_root: str | Path | None = None,
) -> tuple[str, ...]:
    """Derive container mount aliases mapping host scratch to sandbox scratch."""
    root = scratch_root or os.environ.get("REPOMAP_TEST_SCRATCH_ROOT")
    if not root:
        return ()
    c_root = Path(container_scratch_root) if container_scratch_root else INNER_TEST_SCRATCH_ROOT
    aliases: list[str] = []
    for bp in (bootstrap_dir, bootstrap_dir.resolve()):
        for sr in (Path(root), Path(root).resolve()):
            try:
                rel = bp.relative_to(sr)
                cand = str(c_root / rel)
                if cand not in aliases:
                    aliases.append(cand)
            except ValueError:
                pass
    return tuple(aliases)


_active_capability: BootstrapCapabilityRecord | None = None


def set_active_bootstrap_capability(cap: BootstrapCapabilityRecord | None) -> None:
    global _active_capability
    _active_capability = cap


def get_active_bootstrap_capability() -> BootstrapCapabilityRecord | None:
    return _active_capability


def resolve_bootstrap_capability(
    capability: BootstrapCapabilityRecord | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> BootstrapCapabilityRecord | None:
    if capability is not None:
        return capability
    active = get_active_bootstrap_capability()
    if active is not None:
        return active
    environ = os.environ if env is None else env
    manifest_dir = environ.get("COVERAGE_CHILD_MANIFEST_DIR")
    cfg = environ.get("COVERAGE_PROCESS_START")
    session_dir = Path(manifest_dir).parent if manifest_dir else (Path(cfg).parent if cfg else None)
    if session_dir and (cap_path := session_dir / "bootstrap_capability.json").is_file():
        try:
            return BootstrapCapabilityRecord.load(cap_path, expected_dir=session_dir)
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"malformed bootstrap capability record in {cap_path}: {exc}") from exc
    return None


def extend_pythonpath(
    base_pythonpath: str | None,
    *paths: str | Path,
    capability: BootstrapCapabilityRecord | None = None,
) -> str:
    """Extend base PYTHONPATH with paths, deduplicating and scrubbing bootstrap aliases."""
    result: list[str] = []
    for p in paths:
        p_str = str(p)
        if p_str and p_str not in result:
            result.append(p_str)
    if base_pythonpath:
        for raw in base_pythonpath.split(os.pathsep):
            if raw and raw not in result and not is_runner_bootstrap_path(raw, capability=capability):
                result.append(raw)
    return os.pathsep.join(result)


__all__ = (
    "BOOTSTRAP_TEMPLATE",
    "BootstrapCapabilityRecord",
    "RUNNER_BOOTSTRAP_MARKER",
    "derive_container_mount_aliases",
    "extend_pythonpath",
    "generate_bootstrap_source",
    "get_active_bootstrap_capability",
    "install_bootstrap_directory",
    "is_runner_bootstrap_path",
    "resolve_bootstrap_capability",
    "set_active_bootstrap_capability",
)
