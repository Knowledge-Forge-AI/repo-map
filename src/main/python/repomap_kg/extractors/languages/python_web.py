"""Python web framework raw observation extraction."""

from __future__ import annotations

import ast
from typing import Any, Mapping

from repomap_kg import __version__
from repomap_kg.extractors.languages.python_common import (
    EXTRACTOR_NAME,
    end_line,
    slug,
)
from repomap_kg.extractors.languages.python_symbols import _ast_name
from repomap_kg.extractors.languages.python_web_helpers import (
    PYTHON_WEB_MAX_METADATA_STRING,
    PYTHON_WEB_SECRET_MARKERS,
    WEB_HTTP_METHODS,
    _assignment_names,
    _assignment_target_nodes,
    _assignment_value,
    _assigns_name,
    _bounded_metadata_string,
    _call_arg,
    _call_receiver_attr,
    _expression_kind,
    _fastapi_dependencies,
    _is_secret_like_name,
    _keyword,
    _line_slug,
    _literal_string,
    _literal_string_list,
    _looks_credentialed_url,
    _looks_like_django_settings_path,
    _methods_from_keyword,
    _python_web_import_aliases,
    _qualified_ast_name,
    _route_path_metadata,
    _safe_reference_name,
    _sha256_text,
    _value_looks_credentialed,
)
from repomap_kg.extractors.languages.python_web_django import (
    _django_app_observation,
    _django_model_observation,
    _django_setting_observations,
    _django_urlpattern_observations,
    _function_default_redactions,
    add_config_redaction_if_needed,
)
from repomap_kg.extractors.languages.python_web_route_frameworks import (
    FASTAPI_METHOD_DECORATORS,
    FLASK_METHOD_DECORATORS,
    _fastapi_include_router_reference,
    _fastapi_route_from_decorator,
    _flask_add_url_rule_observation,
    _flask_route_from_decorator,
)
from repomap_kg.extractors.languages.python_web_observations import (
    python_web_parse_error_observation,
    python_web_profile_observation,
    python_web_redaction_observation,
    python_web_reference_observation,
)
from repomap_kg.graph.keys import (
    external_key,
    python_class_key,
    python_function_key,
)
from repomap_kg.observations.raw import RawObservation


PYTHON_WEB_MAX_OBSERVATIONS = 512
PYTHON_WEB_MAX_ROUTES_PER_FILE = 64


def python_web_framework_observations(
    relative_path: str,
    module: str,
    tree: ast.Module,
) -> tuple[RawObservation, ...]:
    aliases = _python_web_import_aliases(tree)
    flask_apps: set[str] = set()
    flask_blueprints: dict[str, str] = {}
    fastapi_apps: set[str] = set()
    fastapi_routers: set[str] = set()
    observations: list[RawObservation] = []
    route_count = 0
    route_limit_reported = False

    def add(observation: RawObservation) -> None:
        nonlocal route_count, route_limit_reported
        if observation.kind in (
            "python.flask_route",
            "python.fastapi_route",
            "python.django_urlpattern",
        ):
            if route_count >= PYTHON_WEB_MAX_ROUTES_PER_FILE:
                if not route_limit_reported:
                    observations.append(
                        python_web_parse_error_observation(
                            relative_path,
                            module,
                            observation,
                            error_kind="python-web-profile-limit",
                            framework=observation.metadata.get(
                                "framework", "python-web"
                            ),
                            message_summary="route observation limit reached",
                            recovered=True,
                        )
                    )
                    route_limit_reported = True
                return
            route_count += 1
        observations.append(observation)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = _assignment_value(node)
            if isinstance(value, ast.Call):
                call_name = _qualified_ast_name(value.func, aliases)
                for target_name in _assignment_names(node):
                    if call_name == "flask.Flask":
                        flask_apps.add(target_name)
                        add(
                            python_web_profile_observation(
                                "python.flask_app",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "flask",
                                    "app_name": target_name,
                                },
                            )
                        )
                    elif call_name == "flask.Blueprint":
                        blueprint_name = (
                            _literal_string(value.args[0])
                            if value.args
                            else None
                        ) or target_name
                        flask_blueprints[target_name] = _bounded_metadata_string(
                            blueprint_name
                        )
                        add(
                            python_web_profile_observation(
                                "python.flask_blueprint",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "flask",
                                    "blueprint_name": flask_blueprints[target_name],
                                    "blueprint_variable": target_name,
                                },
                            )
                        )
                    elif call_name == "fastapi.FastAPI":
                        fastapi_apps.add(target_name)
                        add(
                            python_web_profile_observation(
                                "python.fastapi_app",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "fastapi",
                                    "app_name": target_name,
                                },
                            )
                        )
                    elif call_name == "fastapi.APIRouter":
                        fastapi_routers.add(target_name)
                        add(
                            python_web_profile_observation(
                                "python.fastapi_router",
                                relative_path,
                                module,
                                node,
                                name=target_name,
                                metadata={
                                    "framework": "fastapi",
                                    "router_name": target_name,
                                },
                            )
                        )
            for target in _assignment_target_nodes(node):
                add_config_redaction_if_needed(
                    add,
                    relative_path,
                    module,
                    node,
                    target,
                    value,
                    flask_apps=flask_apps,
                    aliases=aliases,
                    relative_path_for_settings=relative_path,
                )

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    flask_route = _flask_route_from_decorator(
                        relative_path,
                        module,
                        decorator,
                        node,
                        flask_apps=flask_apps,
                        flask_blueprints=flask_blueprints,
                    )
                    if flask_route is not None:
                        add(flask_route)
                        add(
                            python_web_reference_observation(
                                relative_path,
                                module,
                                decorator,
                                name=node.name,
                                target=python_function_key(module, node.name),
                                framework="flask",
                                reference_kind="flask_route_handler",
                                metadata={"handler_name": node.name},
                            )
                        )
                        if flask_route.metadata.get("dynamic"):
                            add(
                                python_web_parse_error_observation(
                                    relative_path,
                                    module,
                                    decorator,
                                    error_kind="dynamic-python-web-route",
                                    framework="flask",
                                    message_summary="dynamic Flask route expression",
                                    recovered=True,
                                    dynamic=True,
                                )
                            )
                    fastapi_route = _fastapi_route_from_decorator(
                        relative_path,
                        module,
                        decorator,
                        node,
                        fastapi_apps=fastapi_apps,
                        fastapi_routers=fastapi_routers,
                        aliases=aliases,
                    )
                    if fastapi_route is not None:
                        add(fastapi_route)
                        add(
                            python_web_reference_observation(
                                relative_path,
                                module,
                                decorator,
                                name=node.name,
                                target=python_function_key(module, node.name),
                                framework="fastapi",
                                reference_kind="fastapi_route_handler",
                                metadata={"handler_name": node.name},
                            )
                        )
                        if fastapi_route.metadata.get("dynamic"):
                            add(
                                python_web_parse_error_observation(
                                    relative_path,
                                    module,
                                    decorator,
                                    error_kind="dynamic-python-web-route",
                                    framework="fastapi",
                                    message_summary="dynamic FastAPI route expression",
                                    recovered=True,
                                    dynamic=True,
                                )
                            )
            for dependency in _fastapi_dependencies(node, aliases):
                add(
                    python_web_profile_observation(
                        "python.fastapi_dependency",
                        relative_path,
                        module,
                        dependency["node"],
                        name=dependency["name"],
                        metadata={
                            "framework": "fastapi",
                            "handler_name": node.name,
                            "dependency_name": dependency["name"],
                            "dependency_kind": dependency["kind"],
                        },
                    )
                )
                if dependency["target"]:
                    add(
                        python_web_reference_observation(
                            relative_path,
                            module,
                            dependency["node"],
                            name=dependency["name"],
                            target=external_key(
                                "python.dependency", dependency["target"]
                            ),
                            framework="fastapi",
                            reference_kind="fastapi_dependency",
                            metadata={"handler_name": node.name},
                        )
                    )
            for redaction in _function_default_redactions(
                relative_path,
                module,
                node,
            ):
                add(redaction)
        elif isinstance(node, ast.ClassDef):
            django_model = _django_model_observation(relative_path, module, node)
            if django_model is not None:
                add(django_model)
            django_app = _django_app_observation(relative_path, module, node)
            if django_app is not None:
                add(django_app)

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if _looks_like_django_settings_path(relative_path):
                for setting in _django_setting_observations(relative_path, module, node):
                    add(setting)
            if _assigns_name(node, "urlpatterns"):
                for item in _django_urlpattern_observations(
                    relative_path, module, node
                ):
                    add(item)
                    if item.metadata.get("dynamic"):
                        add(
                            python_web_parse_error_observation(
                                relative_path,
                                module,
                                item,
                                error_kind="dynamic-python-web-route",
                                framework="django",
                                message_summary="dynamic Django URL pattern",
                                recovered=True,
                                dynamic=True,
                            )
                        )
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            flask_add_rule = _flask_add_url_rule_observation(
                relative_path,
                module,
                node.value,
                flask_apps=flask_apps,
                flask_blueprints=flask_blueprints,
            )
            if flask_add_rule is not None:
                add(flask_add_rule)
                handler_name = flask_add_rule.metadata.get("handler_name")
                if isinstance(handler_name, str):
                    add(
                        python_web_reference_observation(
                            relative_path,
                            module,
                            node.value,
                            name=handler_name,
                            target=python_function_key(module, handler_name),
                            framework="flask",
                            reference_kind="flask_route_handler",
                            metadata={"handler_name": handler_name},
                        )
                    )
            fastapi_include = _fastapi_include_router_reference(
                relative_path,
                module,
                node.value,
                fastapi_apps=fastapi_apps,
                fastapi_routers=fastapi_routers,
            )
            if fastapi_include is not None:
                add(fastapi_include)

    if len(observations) > PYTHON_WEB_MAX_OBSERVATIONS:
        observations = observations[:PYTHON_WEB_MAX_OBSERVATIONS]
        observations.append(
            python_web_parse_error_observation(
                relative_path,
                module,
                tree,
                error_kind="python-web-profile-limit",
                framework="python-web",
                message_summary="framework observation limit reached",
                recovered=True,
            )
        )
    return tuple(observations)
