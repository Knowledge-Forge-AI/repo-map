"""Terraform JSON and tfvars profile observation helpers."""

from __future__ import annotations

from typing import Any

from repomap_kg.graph.keys import external_key
from repomap_kg.observations.raw import RawObservation


def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _profile_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_profile_observation")(*args, **kwargs)


def _safe_value_summary(value: Any) -> Any:
    return _generic_helper("_safe_value_summary")(value)


def _value_shape(value: Any) -> Any:
    return _generic_helper("_value_shape")(value)


def _value_type(value: Any) -> str:
    return _generic_helper("_value_type")(value)


def _terraform_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = [
        _profile_observation(
            "terraform.file",
            relative_path,
            profile="terraform_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "variant": "tf.json",
                "declared_sections": sorted(str(key) for key in value),
            },
            source_suffix="terraform-file",
        )
    ]
    terraform = value.get("terraform")
    if isinstance(terraform, dict):
        required_version = _safe_value_summary(terraform.get("required_version"))
        if isinstance(required_version, str):
            observations.append(
                _profile_observation(
                    "terraform.required_version",
                    relative_path,
                    profile="terraform_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={"version_constraint": required_version},
                    source_suffix="terraform-required-version",
                )
            )
        required_providers = terraform.get("required_providers")
        if isinstance(required_providers, dict):
            for provider_name in sorted(str(key) for key in required_providers):
                provider_config = required_providers.get(provider_name)
                source = provider_name
                version = None
                if isinstance(provider_config, dict):
                    source = str(provider_config.get("source") or provider_name)
                    version = _safe_value_summary(provider_config.get("version"))
                observations.append(
                    _profile_observation(
                        "terraform.required_provider",
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            "provider_name": provider_name,
                            "provider_source": source,
                            "version_constraint": version,
                        },
                        name=provider_name,
                        target=external_key("terraform.provider", source),
                        source_suffix=f"terraform-required-provider:{provider_name}",
                    )
                )
                observations.append(
                    _terraform_reference_observation(
                        relative_path,
                        "provider_source",
                        source,
                        target=external_key("terraform.provider", source),
                        confidence="heuristic",
                        format_name=format_name,
                    )
                )
        backend = terraform.get("backend")
        if isinstance(backend, dict):
            for backend_type in sorted(str(key) for key in backend):
                observations.append(
                    _profile_observation(
                        "terraform.backend",
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={"backend_type": backend_type},
                        name=backend_type,
                        source_suffix=f"terraform-backend:{backend_type}",
                    )
                )
    observations.extend(
        _terraform_named_block_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    return observations


def _terraform_named_block_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for provider_name in _terraform_block_names(value.get("provider")):
        observations.append(
            _profile_observation(
                "terraform.provider",
                relative_path,
                profile="terraform_json",
                format_name=format_name,
                confidence=confidence,
                metadata={"provider_name": provider_name},
                name=provider_name,
                source_suffix=f"terraform-provider:{provider_name}",
            )
        )
    for kind, raw_kind, type_key, name_key in (
        ("resource", "terraform.resource", "resource_type", "resource_name"),
        ("data", "terraform.data_source", "data_source_type", "data_source_name"),
    ):
        section = value.get(kind)
        if not isinstance(section, dict):
            continue
        for block_type in sorted(str(key) for key in section):
            instances = section.get(block_type)
            if not isinstance(instances, dict):
                continue
            for block_name in sorted(str(key) for key in instances):
                observations.append(
                    _profile_observation(
                        raw_kind,
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={type_key: block_type, name_key: block_name},
                        name=f"{block_type}.{block_name}",
                        source_suffix=(
                            f"{raw_kind.replace('.', '-')}:{block_type}:{block_name}"
                        ),
                    )
                )
    modules = value.get("module")
    if isinstance(modules, dict):
        for module_name in sorted(str(key) for key in modules):
            module_config = modules.get(module_name)
            source = None
            if (
                isinstance(module_config, dict)
                and isinstance(module_config.get("source"), str)
            ):
                source = module_config["source"]
            metadata = {"module_name": module_name}
            if source is not None:
                metadata["source_summary"] = _safe_value_summary(source)
            observations.append(
                _profile_observation(
                    "terraform.module",
                    relative_path,
                    profile="terraform_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=module_name,
                    source_suffix=f"terraform-module:{module_name}",
                )
            )
            if source is not None:
                observations.append(
                    _terraform_reference_observation(
                        relative_path,
                        "module_source",
                        source,
                        target=external_key("terraform.module", source),
                        confidence="heuristic",
                        format_name=format_name,
                    )
                )
    for section_name, observation_kind, metadata_key in (
        ("variable", "terraform.variable", "variable_name"),
        ("output", "terraform.output", "output_name"),
    ):
        section = value.get(section_name)
        if isinstance(section, dict):
            for item_name in sorted(str(key) for key in section):
                observations.append(
                    _profile_observation(
                        observation_kind,
                        relative_path,
                        profile="terraform_json",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={metadata_key: item_name},
                        name=item_name,
                        source_suffix=(
                            f"{observation_kind.replace('.', '-')}:{item_name}"
                        ),
                    )
                )
    locals_section = value.get("locals")
    if isinstance(locals_section, dict):
        for local_name in sorted(str(key) for key in locals_section):
            observations.append(
                _profile_observation(
                    "terraform.local",
                    relative_path,
                    profile="terraform_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={"local_name": local_name},
                    name=local_name,
                    source_suffix=f"terraform-local:{local_name}",
                )
            )
    return observations


def _terraform_block_names(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(sorted(str(key) for key in value))
    if isinstance(value, list):
        names = []
        for item in value:
            if isinstance(item, dict):
                names.extend(str(key) for key in item)
        return tuple(sorted(set(names)))
    return ()


def _terraform_reference_observation(
    relative_path: str,
    reference_kind: str,
    raw_value: str,
    *,
    target: str,
    confidence: str,
    format_name: str,
) -> RawObservation:
    return _profile_observation(
        "terraform.reference",
        relative_path,
        profile="terraform_json",
        format_name=format_name,
        confidence=confidence,
        metadata={
            "reference_kind": reference_kind,
            "raw_value_summary": _safe_value_summary(raw_value),
            "not_fetched": True,
        },
        target=target,
        source_suffix=f"terraform-reference:{reference_kind}:{raw_value}",
    )


def _terraform_tfvars_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations = [
        _profile_observation(
            "terraform.file",
            relative_path,
            profile="terraform_tfvars_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "variant": "tfvars.json",
                "all_values_sensitive": True,
                "variable_count": len(value),
            },
            source_suffix="terraform-file",
        )
    ]
    for variable_name in sorted(str(key) for key in value):
        variable_value = value[variable_name]
        observations.append(
            _profile_observation(
                "terraform.variable",
                relative_path,
                profile="terraform_tfvars_json",
                format_name=format_name,
                confidence=confidence,
                metadata={
                    "variable_name": variable_name,
                    "value_type": _value_type(variable_value),
                    "value_shape": _value_shape(variable_value),
                    "redacted": True,
                    "redaction_reason": "tfvars-sensitive-by-default",
                },
                name=variable_name,
                source_suffix=f"terraform-variable:{variable_name}",
            )
        )
    return observations
