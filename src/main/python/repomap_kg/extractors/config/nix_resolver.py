"""Bounded static Nix relation resolution across configured source bindings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import posixpath
import re

from repomap_kg.observations.raw import RawObservation


_INPUT_REF = re.compile(
    r"\binputs\.(?P<input>[A-Za-z0-9_-]+)"
    r"(?:\.nixosModules\.(?P<module>[A-Za-z0-9_-]+))?\b"
)


class ResolutionOutcome(str, Enum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    EVALUATION_DEPENDENT = "evaluation-dependent"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class NixBindingView:
    alias: str
    input_name: str | None
    files: frozenset[str]
    binding_id: str | None = None
    snapshot_id: str | None = None
    module_exports: Mapping[str, str | Sequence[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.alias, str) or not self.alias.strip():
            raise ValueError("Nix binding alias is required")
        if self.input_name is not None and (
            not isinstance(self.input_name, str) or not self.input_name.strip()
        ):
            raise ValueError("Nix binding input name is invalid")
        for name in ("binding_id", "snapshot_id"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(f"Nix binding {name} is invalid")
        if not isinstance(self.module_exports, Mapping):
            raise ValueError("Nix binding module exports are invalid")
        for module_name, paths in self.module_exports.items():
            if not isinstance(module_name, str) or not module_name.strip():
                raise ValueError("Nix module export name is invalid")
            path_values: Sequence[object]
            if isinstance(paths, str):
                path_values = (paths,)
            elif isinstance(paths, Sequence):
                path_values = paths
            else:
                raise ValueError("Nix module export paths are invalid")
            if not path_values or any(
                not isinstance(path, str) or not path.strip()
                for path in path_values
            ):
                raise ValueError("Nix module export path is invalid")


@dataclass(frozen=True)
class NixResolution:
    observation: RawObservation
    outcome: ResolutionOutcome
    source_binding: str
    target_binding: str | None
    target_path: str | None
    cross_binding: bool
    candidate_bindings: tuple[str, ...] = ()

    @property
    def evidence_class(self) -> str:
        return "static-literal" if self.outcome is ResolutionOutcome.EXACT else "bounded-unknown"


def _source_binding(observation: RawObservation) -> str | None:
    value = observation.metadata.get("binding_alias")
    return value if isinstance(value, str) and value.strip() else None


def _source_relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith(("/", "\\")) or "\\" in value:
        return None
    normalized = posixpath.normpath(value)
    if normalized in {"", ".", ".."} or normalized != value:
        return None
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        return None
    return normalized


def _validated_provenance(
    observation: RawObservation,
    views: Mapping[str, NixBindingView],
) -> tuple[str, NixBindingView] | None:
    """Return the explicitly bound source, rejecting path-derived identity."""

    metadata = observation.metadata
    alias = _source_binding(observation)
    binding_id = metadata.get("binding_id")
    snapshot_id = metadata.get("snapshot_id")
    relative_path = _source_relative_path(metadata.get("source_relative_path"))
    if (
        alias is None
        or not isinstance(binding_id, str)
        or not binding_id.strip()
        or not isinstance(snapshot_id, str)
        or not snapshot_id.strip()
        or relative_path is None
    ):
        return None
    if observation.path != f"{alias}/{relative_path}":
        return None
    view = views.get(alias)
    if view is None:
        return None
    if view.binding_id is None or view.binding_id != binding_id:
        return None
    if view.snapshot_id is None or view.snapshot_id != snapshot_id:
        return None
    return alias, view


def _unsupported_resolution(
    observation: RawObservation,
    source: str | None,
    *,
    target_binding: str | None = None,
    candidate_bindings: tuple[str, ...] = (),
    outcome: ResolutionOutcome = ResolutionOutcome.UNSUPPORTED,
) -> NixResolution:
    return NixResolution(
        observation,
        outcome,
        source or "",
        target_binding,
        None,
        bool(target_binding and source and target_binding != source),
        candidate_bindings,
    )


def _same_binding_resolution(
    observation: RawObservation, views: dict[str, NixBindingView]
) -> NixResolution:
    source = _source_binding(observation)
    provenance = _validated_provenance(observation, views)
    if provenance is None:
        return _unsupported_resolution(observation, source)
    source, view = provenance
    resolved = observation.metadata.get("resolved_path")
    if not isinstance(resolved, str):
        return _unsupported_resolution(observation, source)
    prefix = f"{source}/"
    if not resolved.startswith(prefix):
        return _unsupported_resolution(observation, source, target_binding=source)
    local_path = _source_relative_path(resolved.removeprefix(prefix))
    if local_path is not None and local_path in view.files:
        return NixResolution(
            observation, ResolutionOutcome.EXACT, source, source,
            f"{source}/{local_path}", False,
        )
    return _unsupported_resolution(observation, source, target_binding=source)


def _module_export_paths(
    view: NixBindingView,
    module: str,
) -> tuple[str, ...] | None:
    paths = view.module_exports.get(module)
    if paths is None:
        paths = view.module_exports.get(f"nixosModules.{module}")
    if paths is None:
        return None
    values: tuple[object, ...]
    if isinstance(paths, str):
        values = (paths,)
    elif isinstance(paths, Sequence):
        values = tuple(paths)
    normalized: list[str] = []
    for path in values:
        local_path = _source_relative_path(path)
        if local_path is None or local_path not in view.files:
            return None
        if local_path not in normalized:
            normalized.append(local_path)
    return tuple(normalized)


def _input_resolution(
    observation: RawObservation, bindings: Sequence[NixBindingView]
) -> NixResolution:
    source = _source_binding(observation)
    views = {item.alias: item for item in bindings}
    provenance = _validated_provenance(observation, views)
    if provenance is None:
        return _unsupported_resolution(observation, source)
    source, _ = provenance
    expression = observation.metadata.get("expression")
    if not isinstance(expression, str):
        return _unsupported_resolution(observation, source)
    if (
        observation.metadata.get("evaluation_dependency")
        in {"interpolation", "conditional"}
        or "${" in expression
        or re.search(r"\b(if|then|else)\b", expression)
    ):
        return _unsupported_resolution(
            observation,
            source,
            outcome=ResolutionOutcome.EVALUATION_DEPENDENT,
        )
    match = _INPUT_REF.fullmatch(expression.strip())
    if match is None:
        return _unsupported_resolution(observation, source)
    input_name = match.group("input")
    matches = tuple(
        sorted(
            (item for item in bindings if item.input_name == input_name),
            key=lambda item: item.alias,
        )
    )
    if not matches:
        return _unsupported_resolution(observation, source)
    if len(matches) > 1:
        return _unsupported_resolution(
            observation,
            source,
            outcome=ResolutionOutcome.AMBIGUOUS,
            candidate_bindings=tuple(item.alias for item in matches),
        )
    target = matches[0]
    module = match.group("module")
    if module is None:
        return _unsupported_resolution(
            observation,
            source,
            target_binding=target.alias,
            candidate_bindings=(target.alias,),
        )
    candidates = _module_export_paths(target, module)
    if candidates is None:
        return _unsupported_resolution(
            observation,
            source,
            target_binding=target.alias,
            candidate_bindings=(target.alias,),
        )
    if len(candidates) > 1:
        return _unsupported_resolution(
            observation,
            source,
            target_binding=target.alias,
            candidate_bindings=(target.alias,),
            outcome=ResolutionOutcome.CONFLICTING,
        )
    return NixResolution(
        observation, ResolutionOutcome.EXACT, source, target.alias,
        f"{target.alias}/{candidates[0]}", target.alias != source,
        (target.alias,),
    )


def resolve_nix_relations(
    observations: Sequence[RawObservation],
    bindings: Sequence[NixBindingView],
) -> tuple[NixResolution, ...]:
    """Resolve only literal same-binding imports and declared input references."""

    views = {item.alias: item for item in bindings}
    results: list[NixResolution] = []
    for observation in observations:
        if observation.kind == "nix.import":
            results.append(_same_binding_resolution(observation, views))
        elif observation.kind == "nix.input_ref":
            results.append(_input_resolution(observation, bindings))
    return tuple(results)


__all__ = [
    "NixBindingView",
    "NixResolution",
    "ResolutionOutcome",
    "resolve_nix_relations",
]
