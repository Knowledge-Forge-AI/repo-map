"""Graph-local source-binding configuration parsing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repomap_kg.graph.multi_source import (
    MultiSourceIdentityError,
    SourceKind,
    graph_source_binding_id,
    is_reserved_compatibility_extractor_profile,
    source_binding_input_name,
    source_binding_role,
    source_selection_policy_id,
)
from repomap_kg.ops.config_helpers import (
    PRIVATE_PRIVACY,
    OpsConfigDiagnostic,
    expand_user_path,
    optional_bool,
    optional_text,
    required_int,
    required_text,
    unknown_field_diagnostics,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig


_KNOWN_FIELDS = frozenset(
    (
        "schema_version",
        "binding_id",
        "source_definition_id",
        "alias",
        "revision",
        "kind",
        "root_path",
        "repository_name",
        "logical_root",
        "privacy",
        "evidence_retention",
        "extractor_profile",
        "exclude_paths",
        "resolution_policy",
        "enabled",
        "role",
        "input_name",
    )
)
_SUPPORTED_PRIVACY = PRIVATE_PRIVACY | {"public-dev", "inherit"}


def _relative_paths(
    payload: Any, path: str, diagnostics: list[OpsConfigDiagnostic]
) -> tuple[str, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error", "invalid-source-binding-exclude-paths", path,
                "source binding exclude_paths must be an array of strings",
            )
        )
        return ()
    values: list[str] = []
    for index, item in enumerate(payload):
        item_path = f"{path}[{index}]"
        if (
            not isinstance(item, str)
            or not item.strip()
            or Path(item).is_absolute()
            or ".." in Path(item).parts
        ):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "invalid-source-binding-exclude-path", item_path,
                    "source binding exclude path must be a non-empty relative string",
                )
            )
            continue
        if item in values:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "duplicate-source-binding-exclude-path", item_path,
                    "duplicate source binding exclude path is not allowed",
                )
            )
            continue
        values.append(item)
    return tuple(values)


def parse_graph_source_bindings(
    payload: Any,
    *,
    graph_id: str,
    graph_path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> tuple[OpsGraphSourceBindingConfig, ...]:
    path = f"{graph_path}.source_bindings"
    if not isinstance(payload, list) or not payload:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error", "invalid-source-bindings-section", path,
                "source_bindings must be a non-empty array of tables",
            )
        )
        return ()
    bindings: list[OpsGraphSourceBindingConfig] = []
    seen_ids: set[str] = set()
    seen_aliases: set[str] = set()
    seen_input_names: set[str] = set()
    definition_kinds: dict[str, SourceKind] = {}
    for index, item in enumerate(payload):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "invalid-source-binding", item_path,
                    "source binding entry must be a table",
                )
            )
            continue
        diagnostics.extend(unknown_field_diagnostics(item, _KNOWN_FIELDS, item_path))
        schema_version = required_int(
            item, "schema_version", f"{item_path}.schema_version", diagnostics
        )
        raw_binding_id = optional_text(item.get("binding_id"))
        definition_id = required_text(
            item, "source_definition_id", f"{item_path}.source_definition_id", diagnostics
        )
        alias = required_text(item, "alias", f"{item_path}.alias", diagnostics)
        if raw_binding_id:
            binding_id = raw_binding_id
        elif graph_id and alias:
            try:
                binding_id = graph_source_binding_id(graph_id, alias)
            except MultiSourceIdentityError:
                binding_id = ""
        else:
            binding_id = ""
        revision = required_int(item, "revision", f"{item_path}.revision", diagnostics)
        kind_text = required_text(item, "kind", f"{item_path}.kind", diagnostics)
        root_path = required_text(
            item, "root_path", f"{item_path}.root_path", diagnostics
        )
        repository_name = required_text(
            item, "repository_name", f"{item_path}.repository_name", diagnostics
        )
        logical_root = required_text(
            item, "logical_root", f"{item_path}.logical_root", diagnostics
        )
        privacy = required_text(
            item, "privacy", f"{item_path}.privacy", diagnostics
        )
        retention = required_text(
            item, "evidence_retention", f"{item_path}.evidence_retention", diagnostics
        )
        extractor = required_text(
            item, "extractor_profile", f"{item_path}.extractor_profile", diagnostics
        )
        if extractor and is_reserved_compatibility_extractor_profile(extractor):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-source-binding-identity",
                    f"{item_path}.extractor_profile",
                    "extractor profile uses a reserved compatibility identity",
                )
            )
        resolution = required_text(
            item, "resolution_policy", f"{item_path}.resolution_policy", diagnostics
        )
        role = optional_text(item.get("role"))
        if "role" not in item:
            role = "source"
        input_name = optional_text(item.get("input_name"))
        for field, value, validator in (
            ("role", role, source_binding_role),
            ("input_name", input_name, source_binding_input_name),
        ):
            if value is None and field == "input_name" and field not in item:
                continue
            try:
                if value is None:
                    raise MultiSourceIdentityError("source binding value is missing")
                validator(value)
            except MultiSourceIdentityError:
                diagnostics.append(
                    OpsConfigDiagnostic(
                        "error",
                        f"invalid-source-binding-{field.replace('_', '-')}",
                        f"{item_path}.{field}",
                        f"source binding {field.replace('_', ' ')} is invalid",
                    )
                )
        excludes = _relative_paths(
            item.get("exclude_paths"), f"{item_path}.exclude_paths", diagnostics
        )
        enabled = optional_bool(item.get("enabled"))
        if schema_version != 1:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "unsupported-source-binding-version",
                    f"{item_path}.schema_version",
                    "source binding schema version is not supported",
                )
            )
        if privacy and privacy not in _SUPPORTED_PRIVACY:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "unsupported-source-binding-privacy",
                    f"{item_path}.privacy", "source binding privacy is not supported",
                )
            )
        try:
            kind = SourceKind(kind_text or "")
        except (TypeError, ValueError):
            kind = SourceKind.FOLDER
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "unsupported-source-kind", f"{item_path}.kind",
                    "source binding kind is not supported",
                )
            )
        try:
            selection_policy_id = source_selection_policy_id((), excludes)
        except MultiSourceIdentityError as error:
            selection_policy_id = source_selection_policy_id((), ())
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "invalid-source-binding-selection-policy",
                    f"{item_path}.exclude_paths", str(error),
                )
            )
        binding = OpsGraphSourceBindingConfig(
            schema_version=schema_version or 0,
            binding_id=binding_id or "",
            source_definition_id=definition_id or "",
            alias=alias or "",
            revision=revision or 0,
            source_kind=kind,
            root_path=root_path or "",
            root_path_expanded=expand_user_path(root_path or ""),
            repository_name=repository_name or "",
            logical_root=logical_root or "",
            privacy=privacy or "",
            evidence_retention=retention or "",
            extractor_profile=extractor or "",
            include_paths=(),
            exclude_paths=excludes,
            selection_policy_id=selection_policy_id,
            resolution_policy=resolution or "",
            enabled=True if enabled is None else enabled,
            role=role or "",
            input_name=input_name,
        )
        try:
            binding.domain_binding(graph_id)
        except MultiSourceIdentityError as error:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "invalid-source-binding-identity", item_path, str(error)
                )
            )
        if binding.binding_id in seen_ids:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "duplicate-source-binding-id", f"{item_path}.binding_id",
                    "duplicate source binding identity is not allowed",
                )
            )
        seen_ids.add(binding.binding_id)
        if binding.alias in seen_aliases:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "duplicate-source-binding-alias", f"{item_path}.alias",
                    "duplicate source binding alias is not allowed",
                )
            )
        seen_aliases.add(binding.alias)
        effective_input_name = binding.input_name or binding.alias
        if effective_input_name in seen_input_names:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "duplicate-source-binding-input-name",
                    f"{item_path}.input_name" if binding.input_name is not None else f"{item_path}.alias",
                    "duplicate source binding input name is not allowed",
                )
            )
        seen_input_names.add(effective_input_name)
        previous_kind = definition_kinds.get(binding.source_definition_id)
        if previous_kind is not None and previous_kind is not binding.source_kind:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error", "source-definition-collision",
                    f"{item_path}.source_definition_id",
                    "source definition identity has conflicting source kinds",
                )
            )
        definition_kinds[binding.source_definition_id] = binding.source_kind
        bindings.append(binding)
    return tuple(sorted(bindings, key=lambda item: item.binding_id))


__all__ = ["parse_graph_source_bindings"]
