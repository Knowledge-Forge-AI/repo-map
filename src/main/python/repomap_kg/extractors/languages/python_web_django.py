"""Django URL, model, app, setting, and redaction builders."""

from __future__ import annotations

import ast
from typing import Any, Mapping

from repomap_kg.extractors.languages.python_symbols import _ast_name
from repomap_kg.extractors.languages.python_web_helpers import (
    _assignment_names,
    _assignment_value,
    _bounded_metadata_string,
    _call_arg,
    _expression_kind,
    _is_secret_like_name,
    _literal_string,
    _looks_like_django_settings_path,
    _route_path_metadata,
    _safe_reference_name,
    _value_looks_credentialed,
)
from repomap_kg.extractors.languages.python_web_observations import (
    python_web_profile_observation,
    python_web_redaction_observation,
    python_web_reference_observation,
)
from repomap_kg.graph.keys import external_key, python_class_key
from repomap_kg.observations.raw import RawObservation


def _django_urlpattern_observations(
    relative_path: str,
    module: str,
    node: ast.Assign | ast.AnnAssign,
) -> tuple[RawObservation, ...]:
    value = _assignment_value(node)
    if not isinstance(value, (ast.List, ast.Tuple)):
        return ()
    observations: list[RawObservation] = []
    for item in value.elts:
        if not isinstance(item, ast.Call):
            continue
        call_name = _ast_name(item.func).split(".")[-1]
        if call_name not in ("path", "re_path"):
            continue
        view_node = _call_arg(item, 1)
        include_target = None
        urlpattern_kind = call_name
        if isinstance(view_node, ast.Call) and _ast_name(view_node.func).split(".")[-1] == "include":
            urlpattern_kind = "include"
            include_target = _literal_string(_call_arg(view_node, 0))
        route_metadata = _route_path_metadata(
            _call_arg(item, 0),
            regex=call_name == "re_path",
        )
        view_name = _safe_reference_name(view_node) if view_node is not None else "unknown"
        metadata = {
            "framework": "django",
            "urlpattern_kind": urlpattern_kind,
            "view_name": _bounded_metadata_string(view_name),
            "dynamic": route_metadata["dynamic"],
            **route_metadata,
        }
        if include_target is not None:
            metadata["include_target"] = _bounded_metadata_string(include_target)
        observations.append(
            python_web_profile_observation(
                "python.django_urlpattern",
                relative_path,
                module,
                item,
                name=view_name,
                metadata=metadata,
                confidence="heuristic" if route_metadata["dynamic"] else "extracted",
            )
        )
        if view_node is not None and urlpattern_kind != "include":
            observations.append(
                python_web_profile_observation(
                    "python.django_view",
                    relative_path,
                    module,
                    view_node,
                    name=view_name,
                    metadata={
                        "framework": "django",
                        "view_name": _bounded_metadata_string(view_name),
                        "urlpattern_kind": urlpattern_kind,
                    },
                    target=external_key("python.view", view_name),
                )
            )
            observations.append(
                python_web_reference_observation(
                    relative_path,
                    module,
                    view_node,
                    name=view_name,
                    target=external_key("python.view", view_name),
                    framework="django",
                    reference_kind="django_urlpattern_view",
                    metadata={"urlpattern_kind": urlpattern_kind},
                )
            )
        if include_target is not None:
            observations.append(
                python_web_reference_observation(
                    relative_path,
                    module,
                    item,
                    name=include_target,
                    target=external_key("python.module", include_target),
                    framework="django",
                    reference_kind="django_include",
                    metadata={"include_target": include_target},
                )
            )
    return tuple(observations)


def _django_model_observation(
    relative_path: str,
    module: str,
    node: ast.ClassDef,
) -> RawObservation | None:
    if not any(_ast_name(base) in ("models.Model", "django.db.models.Model", "Model") for base in node.bases):
        return None
    field_count = 0
    for child in node.body:
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            value = _assignment_value(child)
            if isinstance(value, ast.Call):
                call_name = _ast_name(value.func)
                if call_name.startswith("models.") or call_name.endswith("Field"):
                    field_count += len(_assignment_names(child)) or 1
    return python_web_profile_observation(
        "python.django_model",
        relative_path,
        module,
        node,
        name=node.name,
        target=python_class_key(module, node.name),
        metadata={
            "framework": "django",
            "model_name": node.name,
            "class_name": node.name,
            "model_field_count": field_count,
        },
    )


def _django_app_observation(
    relative_path: str,
    module: str,
    node: ast.ClassDef,
) -> RawObservation | None:
    if not any(_ast_name(base).endswith("AppConfig") for base in node.bases):
        return None
    return python_web_profile_observation(
        "python.django_app",
        relative_path,
        module,
        node,
        name=node.name,
        target=python_class_key(module, node.name),
        metadata={
            "framework": "django",
            "class_name": node.name,
        },
    )


def _django_setting_observations(
    relative_path: str,
    module: str,
    node: ast.Assign | ast.AnnAssign,
) -> tuple[RawObservation, ...]:
    value = _assignment_value(node)
    observations: list[RawObservation] = []
    for name in _assignment_names(node):
        if not name.isupper():
            continue
        sensitive = _is_secret_like_name(name) or _value_looks_credentialed(value)
        observations.append(
            python_web_profile_observation(
                "python.django_setting_reference",
                relative_path,
                module,
                node,
                name=name,
                metadata={
                    "framework": "django",
                    "setting_name": name,
                    "value_kind": _expression_kind(value),
                    "redacted": sensitive,
                },
            )
        )
        if sensitive:
            observations.append(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="django",
                    name=name,
                    redaction_reason="secret-like-django-setting",
                    field_name=name,
                )
            )
    return tuple(observations)


def add_config_redaction_if_needed(
    add: Any,
    relative_path: str,
    module: str,
    node: ast.Assign | ast.AnnAssign,
    target: ast.expr,
    value: ast.expr | None,
    *,
    flask_apps: set[str],
    aliases: Mapping[str, str],
    relative_path_for_settings: str,
) -> None:
    if isinstance(target, ast.Subscript):
        key = _literal_string(target.slice)
        container_name = _ast_name(target.value)
        if (
            key is not None
            and container_name.endswith(".config")
            and container_name.split(".", 1)[0] in flask_apps
            and (_is_secret_like_name(key) or _value_looks_credentialed(value))
        ):
            add(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="flask",
                    name=key,
                    redaction_reason="secret-like-flask-config",
                    field_name=key,
                )
            )
    if _looks_like_django_settings_path(relative_path_for_settings):
        return
    for name in _assignment_names(node):
        if _is_secret_like_name(name) and value is not None:
            add(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="python-web",
                    name=name,
                    redaction_reason="secret-like-assignment",
                    field_name=name,
                )
            )


def _function_default_redactions(
    relative_path: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[RawObservation, ...]:
    observations = []
    args = [*node.args.args, *node.args.kwonlyargs]
    defaults = [*node.args.defaults, *node.args.kw_defaults]
    padded_defaults: list[ast.expr | None] = [None] * (len(args) - len(defaults))
    padded_defaults.extend(defaults)
    for argument, default in zip(args, padded_defaults, strict=False):
        if default is None:
            continue
        if _is_secret_like_name(argument.arg) or _value_looks_credentialed(default):
            observations.append(
                python_web_redaction_observation(
                    relative_path,
                    module,
                    node,
                    framework="python-web",
                    name=argument.arg,
                    redaction_reason="secret-like-default",
                    field_name=argument.arg,
                )
            )
    return tuple(observations)
