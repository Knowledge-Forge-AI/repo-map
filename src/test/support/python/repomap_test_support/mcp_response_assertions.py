"""Runtime-checked JSON shapes for MCP response assertions."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeAlias, TypeGuard, TypedDict
from unittest import TestCase


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class McpResponse(TypedDict, total=False):
    id: int
    result: JsonObject
    error: JsonObject


McpRun: TypeAlias = Callable[
    [list[dict[str, object]], dict[str, str] | None],
    list[McpResponse],
]


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item)
            for key, item in value.items()
        )
    return False


def is_json_object(value: object) -> TypeGuard[JsonObject]:
    """Return whether value is a recursively JSON-safe object."""
    return isinstance(value, dict) and all(
        isinstance(key, str) and _is_json_value(item)
        for key, item in value.items()
    )


def require_json_object(value: object, *, context: str = "JSON object") -> JsonObject:
    if not is_json_object(value):
        raise AssertionError(f"{context} must be a JSON object")
    return value


def require_json_list(value: object, *, context: str = "JSON list") -> list[JsonValue]:
    if not isinstance(value, list) or not all(_is_json_value(item) for item in value):
        raise AssertionError(f"{context} must be a JSON list")
    return value


def require_json_object_list(
    value: object,
    *,
    context: str = "JSON object list",
) -> list[JsonObject]:
    items = require_json_list(value, context=context)
    return [
        require_json_object(item, context=f"{context}[{index}]")
        for index, item in enumerate(items)
    ]


def require_json_string(value: object, *, context: str = "JSON string") -> str:
    if not isinstance(value, str):
        raise AssertionError(f"{context} must be a string")
    return value


def require_json_bool(value: object, *, context: str = "JSON boolean") -> bool:
    if not isinstance(value, bool):
        raise AssertionError(f"{context} must be a boolean")
    return value


def require_json_int(value: object, *, context: str = "JSON integer") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AssertionError(f"{context} must be an integer")
    return value


def require_optional_json_int(
    value: object,
    *,
    context: str = "optional JSON integer",
) -> int | None:
    if value is None:
        return None
    return require_json_int(value, context=context)


def _required_field(payload: JsonObject, key: str) -> JsonValue:
    try:
        return payload[key]
    except KeyError as error:
        raise AssertionError(f"JSON object is missing {key!r}") from error


def json_object_field(payload: JsonObject, key: str) -> JsonObject:
    return require_json_object(
        _required_field(payload, key),
        context=f"JSON field {key!r}",
    )


def json_object_list_field(payload: JsonObject, key: str) -> list[JsonObject]:
    return require_json_object_list(
        _required_field(payload, key),
        context=f"JSON field {key!r}",
    )


def json_string_field(payload: JsonObject, key: str) -> str:
    return require_json_string(
        _required_field(payload, key),
        context=f"JSON field {key!r}",
    )


def json_bool_field(payload: JsonObject, key: str) -> bool:
    return require_json_bool(
        _required_field(payload, key),
        context=f"JSON field {key!r}",
    )


def json_int_field(payload: JsonObject, key: str) -> int:
    return require_json_int(
        _required_field(payload, key),
        context=f"JSON field {key!r}",
    )


def json_optional_int_field(payload: JsonObject, key: str) -> int | None:
    return require_optional_json_int(
        _required_field(payload, key),
        context=f"JSON field {key!r}",
    )


def is_mcp_response(value: object) -> TypeGuard[McpResponse]:
    if not is_json_object(value):
        return False
    if type(value.get("id")) is not int:
        return False
    if "result" not in value and "error" not in value:
        return False
    for key in ("result", "error"):
        if key in value and not is_json_object(value[key]):
            return False
    return True


def require_mcp_response(value: object) -> McpResponse:
    if not is_mcp_response(value):
        raise AssertionError("MCP response must contain an integer id and object result/error")
    return value


def parse_mcp_response(line: str) -> McpResponse:
    decoded: object = json.loads(line)
    return require_mcp_response(decoded)


def response_result(response: McpResponse) -> JsonObject:
    return require_json_object(response.get("result"), context="MCP response result")


def response_error(response: McpResponse) -> JsonObject:
    return require_json_object(response.get("error"), context="MCP response error")


def response_error_text(response: McpResponse) -> str:
    return json_string_field(response_structured_content(response), "error")


def response_structured_content(response: McpResponse) -> JsonObject:
    return json_object_field(response_result(response), "structuredContent")


def assert_mcp_page(
    test_case: TestCase,
    payload: JsonObject,
    *,
    limit: int,
    offset: int,
    returned: int,
    truncated: bool,
    next_offset: int | None,
    field_name: str = "page",
) -> JsonObject:
    page = json_object_field(payload, field_name)
    test_case.assertEqual(json_int_field(page, "limit"), limit)
    test_case.assertEqual(json_int_field(page, "offset"), offset)
    test_case.assertEqual(json_int_field(page, "returned"), returned)
    test_case.assertEqual(json_bool_field(page, "truncated"), truncated)
    test_case.assertEqual(json_optional_int_field(page, "next_offset"), next_offset)
    return page


__all__ = [
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "McpResponse",
    "McpRun",
    "assert_mcp_page",
    "is_json_object",
    "is_mcp_response",
    "json_bool_field",
    "json_int_field",
    "json_object_field",
    "json_object_list_field",
    "json_optional_int_field",
    "json_string_field",
    "parse_mcp_response",
    "require_json_bool",
    "require_json_int",
    "require_json_list",
    "require_json_object",
    "require_json_object_list",
    "require_json_string",
    "require_mcp_response",
    "require_optional_json_int",
    "response_error",
    "response_error_text",
    "response_result",
    "response_structured_content",
]
