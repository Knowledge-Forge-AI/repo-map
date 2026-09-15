"""Focused tests for typed MCP response shape assertions."""

from __future__ import annotations

import unittest

from repomap_test_support.mcp_response_assertions import (
    is_json_object,
    is_mcp_response,
    json_bool_field,
    json_int_field,
    json_object_list_field,
    json_optional_int_field,
    json_string_field,
    parse_mcp_response,
    require_json_list,
    require_json_object,
    require_mcp_response,
    response_error,
    response_error_text,
    response_result,
    response_structured_content,
)


class McpResponseAssertionsUnitTests(unittest.TestCase):
    def test_response_helpers_narrow_nested_json_shapes(self) -> None:
        response = require_mcp_response(
            {
                "id": 7,
                "result": {
                    "isError": False,
                    "structuredContent": {
                        "items": [{"name": "first"}],
                        "has_more": True,
                        "next_offset": 1,
                        "message": "ready",
                    },
                },
            }
        )

        result = response_result(response)
        content = response_structured_content(response)
        items = json_object_list_field(content, "items")
        self.assertIs(json_bool_field(result, "isError"), False)
        self.assertEqual(json_string_field(items[0], "name"), "first")
        self.assertTrue(json_bool_field(content, "has_more"))
        self.assertEqual(json_int_field(content, "next_offset"), 1)
        self.assertEqual(json_string_field(content, "message"), "ready")

    def test_error_helpers_preserve_error_response_shape(self) -> None:
        response = parse_mcp_response(
            '{"id": 8, "error": {"code": -1, "message": "refused"}, '
            '"result": {"structuredContent": {"error": "refused"}, "isError": true}}'
        )

        error_result = response_result(response)
        error_content = response_error(response)
        self.assertTrue(json_bool_field(error_result, "isError"))
        self.assertEqual(json_int_field(error_content, "code"), -1)
        self.assertEqual(json_string_field(error_content, "message"), "refused")
        self.assertEqual(response_error_text(response), "refused")

        protocol_error = require_mcp_response({"id": 10, "error": {"code": -32601}})
        with self.assertRaises(AssertionError):
            response_result(protocol_error)

    def test_optional_and_list_guards_reject_wrong_shapes(self) -> None:
        response = require_mcp_response(
            {
                "id": 9,
                "result": {
                    "structuredContent": {"next_offset": None, "items": []},
                },
            }
        )
        content = response_structured_content(response)
        self.assertIsNone(json_optional_int_field(content, "next_offset"))
        self.assertEqual(require_json_list(content["items"]), [])

        with self.assertRaises(AssertionError):
            json_optional_int_field({"next_offset": True}, "next_offset")
        with self.assertRaises(AssertionError):
            require_json_list({"items": []})

    def test_response_and_object_guards_reject_malformed_values(self) -> None:
        self.assertTrue(is_json_object({"ok": [1, "two", None]}))
        self.assertFalse(is_json_object({1: "non-string-key"}))
        self.assertTrue(is_mcp_response({"id": 1, "error": {"code": -1}}))

        malformed = (
            None,
            {"id": "one", "result": {}},
            {"id": 1, "result": []},
            {"id": 1, "result": None},
            {"id": 1, "error": None},
            {"id": 1},
            {"id": 1, "result": {"bad": object()}},
        )
        for value in malformed:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(AssertionError):
                    require_mcp_response(value)

        with self.assertRaises(AssertionError):
            require_json_object(["not", "an", "object"])


if __name__ == "__main__":
    unittest.main()
