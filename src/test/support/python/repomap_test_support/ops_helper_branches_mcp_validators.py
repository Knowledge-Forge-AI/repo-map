"""Reusable MCP validator positive and malformed-input branch contracts."""

from collections.abc import Callable
import unittest

from repomap_kg.server import mcp_core


def check_mcp_validators(self: unittest.TestCase) -> None:
    self.assertEqual(mcp_core.validate_source_id_arg("source-id"), "source-id")
    for value in ("", "https://example.test/source", "has space"):
        with self.subTest(source_id=value):
            with self.assertRaises(mcp_core.RepoMapMcpError):
                mcp_core.validate_source_id_arg(value)
    def validator_result(validator: Callable[..., object], *args: object) -> object:
        """Observe runtime return contracts, including validators typed as None."""
        return validator(*args)

    self.assertIsNone(validator_result(mcp_core.validate_feed_item_key, "feed.item:feed:item"))
    for value in ("", "bad", "python.module:mod"):
        with self.subTest(item_key=value):
            with self.assertRaises(mcp_core.RepoMapMcpError):
                mcp_core.validate_feed_item_key(value)

    def _validate_limit(validator: Callable[..., int], candidate: object) -> int:
        return validator(candidate)

    self.assertEqual(mcp_core.validate_limit(500), 500)
    self.assertEqual(_validate_limit(mcp_core.validate_limit, "500"), 500)
    for invalid_limit in (0, 501, "bad"):
        with self.subTest(limit=invalid_limit):
            with self.assertRaises(mcp_core.RepoMapMcpError):
                _validate_limit(mcp_core.validate_limit, invalid_limit)
    self.assertIsNone(validator_result(mcp_core.validate_optional_text_filter, None, "path"))
    self.assertIsNone(validator_result(mcp_core.validate_optional_text_filter, "src/app.py", "path"))
    for value in ("", "https://example.test/path"):
        with self.subTest(optional_text=value):
            with self.assertRaises(mcp_core.RepoMapMcpError):
                mcp_core.validate_optional_text_filter(value, "path")
    self.assertEqual(mcp_core.validate_identity_metadata(None), {})
    self.assertEqual(mcp_core.validate_identity_metadata({"a": 1}), {"a": 1})
    with self.assertRaises(mcp_core.RepoMapMcpError):
        mcp_core.validate_identity_metadata([])
