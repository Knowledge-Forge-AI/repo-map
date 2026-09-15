"""Flask and FastAPI route observation builders."""

from __future__ import annotations

import ast
from typing import Mapping

from repomap_kg.extractors.languages.python_web_helpers import (
    _bounded_metadata_string,
    _call_arg,
    _call_receiver_attr,
    _fastapi_dependencies,
    _keyword,
    _literal_string,
    _literal_string_list,
    _methods_from_keyword,
    _route_path_metadata,
    _safe_reference_name,
    _sha256_text,
)
from repomap_kg.extractors.languages.python_web_observations import (
    python_web_profile_observation,
    python_web_reference_observation,
)
from repomap_kg.graph.keys import external_key, python_function_key
from repomap_kg.observations.raw import RawObservation


FLASK_METHOD_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
}
FASTAPI_METHOD_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "options": "OPTIONS",
    "head": "HEAD",
}



def _flask_route_from_decorator(
    relative_path: str,
    module: str,
    call: ast.Call,
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    flask_apps: set[str],
    flask_blueprints: Mapping[str, str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if receiver not in flask_apps and receiver not in flask_blueprints:
        return None
    if attr == "route":
        methods = _methods_from_keyword(call, default=("GET",))
    elif attr in FLASK_METHOD_DECORATORS:
        methods = (FLASK_METHOD_DECORATORS[attr],)
    else:
        return None
    route_metadata = _route_path_metadata(_call_arg(call, 0))
    metadata = {
        "framework": "flask",
        "handler_name": function_node.name,
        "decorator_name": f"{receiver}.{attr}",
        "receiver_name": receiver,
        "http_methods": list(methods),
        "dynamic": route_metadata["dynamic"],
        **route_metadata,
    }
    if receiver in flask_blueprints:
        metadata["blueprint_name"] = flask_blueprints[receiver]
        metadata["blueprint_variable"] = receiver
    return python_web_profile_observation(
        "python.flask_route",
        relative_path,
        module,
        function_node,
        name=function_node.name,
        metadata=metadata,
        target=python_function_key(module, function_node.name),
        confidence="heuristic" if route_metadata["dynamic"] else "extracted",
    )


def _fastapi_route_from_decorator(
    relative_path: str,
    module: str,
    call: ast.Call,
    function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    fastapi_apps: set[str],
    fastapi_routers: set[str],
    aliases: Mapping[str, str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if receiver not in fastapi_apps and receiver not in fastapi_routers:
        return None
    if attr == "api_route":
        methods = _methods_from_keyword(call, default=("GET",))
    elif attr in FASTAPI_METHOD_DECORATORS:
        methods = (FASTAPI_METHOD_DECORATORS[attr],)
    else:
        return None
    route_metadata = _route_path_metadata(_call_arg(call, 0))
    metadata = {
        "framework": "fastapi",
        "handler_name": function_node.name,
        "decorator_name": f"{receiver}.{attr}",
        "receiver_name": receiver,
        "http_methods": list(methods),
        "dependency_count": len(_fastapi_dependencies(function_node, aliases)),
        "dynamic": route_metadata["dynamic"],
        **route_metadata,
    }
    response_model = _keyword(call, "response_model")
    if response_model is not None:
        metadata["response_model"] = _bounded_metadata_string(
            _safe_reference_name(response_model)
        )
    tags = _keyword(call, "tags")
    tag_values = _literal_string_list(tags)
    if tag_values is not None:
        metadata["tag_count"] = len(tag_values)
    for text_key in ("summary", "description"):
        text_node = _keyword(call, text_key)
        text_value = _literal_string(text_node)
        if text_value is not None:
            metadata[f"{text_key}_present"] = True
            metadata[f"{text_key}_length"] = len(text_value)
            metadata[f"{text_key}_sha256"] = _sha256_text(text_value)
    status_code = _keyword(call, "status_code")
    if isinstance(status_code, ast.Constant) and isinstance(status_code.value, int):
        metadata["status_code"] = status_code.value
    return python_web_profile_observation(
        "python.fastapi_route",
        relative_path,
        module,
        function_node,
        name=function_node.name,
        metadata=metadata,
        target=python_function_key(module, function_node.name),
        confidence="heuristic" if route_metadata["dynamic"] else "extracted",
    )


def _flask_add_url_rule_observation(
    relative_path: str,
    module: str,
    call: ast.Call,
    *,
    flask_apps: set[str],
    flask_blueprints: Mapping[str, str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if attr != "add_url_rule":
        return None
    if receiver not in flask_apps and receiver not in flask_blueprints:
        return None
    handler_node = _call_arg(call, 2) or _keyword(call, "view_func")
    handler_name = _safe_reference_name(handler_node) if handler_node else "unknown"
    route_metadata = _route_path_metadata(_call_arg(call, 0))
    methods = _methods_from_keyword(call, default=("GET",))
    metadata = {
        "framework": "flask",
        "handler_name": handler_name,
        "decorator_name": f"{receiver}.add_url_rule",
        "receiver_name": receiver,
        "http_methods": list(methods),
        "dynamic": route_metadata["dynamic"],
        **route_metadata,
    }
    if receiver in flask_blueprints:
        metadata["blueprint_name"] = flask_blueprints[receiver]
        metadata["blueprint_variable"] = receiver
    return python_web_profile_observation(
        "python.flask_route",
        relative_path,
        module,
        call,
        name=handler_name,
        metadata=metadata,
        target=python_function_key(module, handler_name),
        confidence="heuristic" if route_metadata["dynamic"] else "extracted",
    )


def _fastapi_include_router_reference(
    relative_path: str,
    module: str,
    call: ast.Call,
    *,
    fastapi_apps: set[str],
    fastapi_routers: set[str],
) -> RawObservation | None:
    receiver, attr = _call_receiver_attr(call)
    if attr != "include_router":
        return None
    if receiver not in fastapi_apps and receiver not in fastapi_routers:
        return None
    target_node = _call_arg(call, 0)
    target_name = _safe_reference_name(target_node) if target_node else "unknown"
    return python_web_reference_observation(
        relative_path,
        module,
        call,
        name=target_name,
        target=external_key("python.fastapi_router", target_name),
        framework="fastapi",
        reference_kind="fastapi_include_router",
        metadata={"receiver_name": receiver, "router_name": target_name},
    )
