"""Unit tests for Ruby extractor helper routines and branch boundaries."""

from __future__ import annotations

import unittest

from repomap_kg.extractors.languages import ruby_helpers as rh


class RubyHelpersUnitTests(unittest.TestCase):
    def test_strip_comment_handles_quotes_escapes_and_hashes(self):
        self.assertEqual(rh._strip_comment("foo = 1 # comment"), "foo = 1 ")
        self.assertEqual(rh._strip_comment("str = 'hello # not a comment'"), "str = 'hello # not a comment'")
        self.assertEqual(rh._strip_comment('str = "hello # also not" # real'), 'str = "hello # also not" ')
        self.assertEqual(rh._strip_comment(r'str = "escaped \" # quote" # comment'), r'str = "escaped \" # quote" ')
        self.assertEqual(rh._strip_comment("no_comment_here"), "no_comment_here")

    def test_dynamic_reasons_detects_all_tokens_and_deduplicates(self):
        line = 'class_eval { define_method("#{name}") { send(:eval, "1+1") } }'
        reasons = rh._dynamic_reasons(line)
        self.assertIn("interpolation", reasons)
        self.assertIn("class_eval", reasons)
        self.assertIn("define_method", reasons)
        self.assertIn("send", reasons)
        self.assertIn("eval", reasons)
        self.assertEqual(len(reasons), len(set(reasons)))

        self.assertEqual(rh._dynamic_reasons("def simple_method; end"), ())

    def test_scope_stack_helpers_and_qualify_name(self):
        stack: list[rh._Scope] = []
        self.assertIsNone(rh._current_owner(stack))
        self.assertIsNone(rh._current_source_key(stack))
        self.assertIsNone(rh._current_route_key(stack))
        self.assertIsNone(rh._current_test_case_key(stack))
        self.assertIsNone(rh._owner_key_for_scope("Missing", stack))

        # Push module scope
        mod_scope = rh._Scope("module", "Outer", canonical_key="mod:Outer")
        stack.append(mod_scope)
        self.assertEqual(rh._current_owner(stack), "Outer")
        self.assertEqual(rh._current_source_key(stack), "mod:Outer")
        self.assertEqual(rh._qualify_name("Inner", stack), "Outer::Inner")
        self.assertEqual(rh._qualify_name("Explicit::Root", stack), "Explicit::Root")

        # Push class scope with test and route keys
        cls_scope = rh._Scope(
            "class", "Inner",
            canonical_key="cls:Inner",
            test_case_key="tc:Inner",
            route_key="rt:Inner",
        )
        stack.append(cls_scope)
        self.assertEqual(rh._current_owner(stack), "Inner")
        self.assertEqual(rh._current_route_key(stack), "rt:Inner")
        self.assertEqual(rh._current_test_case_key(stack), "tc:Inner")
        self.assertEqual(rh._owner_key_for_scope("Outer", stack), "mod:Outer")
        self.assertEqual(rh._owner_key_for_scope("Inner", stack), "cls:Inner")

        # Pop scope
        rh._pop_scope(stack)
        self.assertEqual(len(stack), 1)
        rh._pop_scope(stack)
        self.assertEqual(len(stack), 0)
        rh._pop_scope(stack)  # Safe on empty stack
        self.assertEqual(len(stack), 0)

    def test_method_owner_parsing(self):
        stack = [rh._Scope("class", "User")]
        self.assertEqual(rh._method_owner("self.create", stack), ("User", "create", True))
        self.assertEqual(rh._method_owner("Admin.reset", stack), ("Admin", "reset", True))
        self.assertEqual(rh._method_owner("save", stack), ("User", "save", False))

        empty_stack: list[rh._Scope] = []
        self.assertEqual(rh._method_owner("top_level", empty_stack), (None, "top_level", False))

    def test_opens_block_detection(self):
        self.assertFalse(rh._opens_block("module Foo"))
        self.assertFalse(rh._opens_block("class Bar"))
        self.assertFalse(rh._opens_block("def baz"))
        self.assertTrue(rh._opens_block("items.each do |x|"))
        self.assertTrue(rh._opens_block("task :setup do"))
        self.assertFalse(rh._opens_block("double = 2"))

    def test_minitest_and_route_profile_heuristics(self):
        self.assertTrue(rh._is_minitest_class("Minitest::Test", "generic"))
        self.assertTrue(rh._is_minitest_class("CustomCase", "minitest"))
        self.assertFalse(rh._is_minitest_class("OtherBase", "generic"))
        self.assertFalse(rh._is_minitest_class(None, "minitest"))

        self.assertTrue(rh._looks_like_route_profile("sinatra", "", "app.rb"))
        self.assertTrue(rh._looks_like_route_profile("hanami", "", "app.rb"))
        self.assertTrue(rh._looks_like_route_profile("generic", "", "config/routes.rb"))
        self.assertTrue(rh._looks_like_route_profile("generic", "require 'sinatra'", "server.rb"))
        self.assertTrue(rh._looks_like_route_profile("generic", "module MyApp; include Hanami; end", "server.rb"))
        self.assertFalse(rh._looks_like_route_profile("generic", "class Plain; end", "plain.rb"))

    def test_require_target_classification(self):
        paths = frozenset({"lib/app.rb", "lib/util.rb"})

        # Dynamic
        target, form = rh._require_target("lib/app.rb", "require", "plugins/#{name}", paths)
        self.assertEqual(form, "dynamic")

        # require_relative existing vs candidate
        target, form = rh._require_target("lib/app.rb", "require_relative", "util", paths)
        self.assertEqual(form, "repo-local")
        self.assertEqual(target, "file:lib/util.rb")

        target, form = rh._require_target("lib/app.rb", "require_relative", "missing", paths)
        self.assertEqual(form, "repo-local-candidate")

        # require_relative repo escaping
        target, form = rh._require_target("lib/app.rb", "require_relative", "../../outside", paths)
        self.assertEqual(form, "repo-escaping")

        # require with ./ or ../
        target, form = rh._require_target("lib/app.rb", "require", "./util", paths)
        self.assertEqual(form, "repo-local")

        target, form = rh._require_target("lib/app.rb", "require", "../../escape", paths)
        self.assertEqual(form, "repo-escaping")

        # external require
        target, form = rh._require_target("lib/app.rb", "require", "json", paths)
        self.assertEqual(form, "external-ruby-require")

    def test_path_target_and_url_sanitization(self):
        paths = frozenset({"config/database.yml"})

        # Dynamic paths
        self.assertIn("dynamic-path", rh._path_target("config/#{env}.yml", paths))
        self.assertIn("dynamic-path", rh._path_target("~/data.json", paths))
        self.assertIn("dynamic-path", rh._path_target("$HOME/file", paths))
        self.assertIn("dynamic-path", rh._path_target("data/*.csv", paths))

        # Absolute file path
        self.assertIn("absolute-ruby-reference", rh._path_target("/etc/hosts", paths))

        # Escaping and root paths
        self.assertIn("repo-escaping", rh._path_target("../outside.txt", paths))
        self.assertIn("repository-root", rh._path_target(".", paths))

        # Normal relative path
        self.assertEqual(rh._path_target("config/database.yml", paths), "file:config/database.yml")

        # URLs with port and secret query
        url_target = rh._path_target("https://api.example.com:8443/v1?token=secret123&public=1", paths)
        self.assertIn("token%3DREDACTED", url_target)
        self.assertIn("public%3D1", url_target)
        self.assertIn("8443", url_target)

        # URLs without port
        url_simple = rh._path_target("https://api.example.com/v1", paths)
        self.assertIn("https%3A%2F%2Fapi.example.com%2Fv1", url_simple)

        # Invalid URL triggering fallback
        self.assertEqual(rh._sanitize_url("https://[invalid-ipv6:bad-url"), "about:invalid")

        # Unsupported scheme
        unsupported = rh._path_target("ftp://files.example.com/dump.tar", paths)
        self.assertIn("unsupported-scheme", unsupported)

    def test_safe_summary_and_literal_analysis(self):
        self.assertIsNone(rh._safe_summary(None))
        self.assertEqual(rh._safe_summary("my_api_key_here"), "REDACTED")
        long_val = "x" * 150
        summary = rh._safe_summary(long_val)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(len(summary), 120)
        self.assertTrue(summary.endswith("..."))
        self.assertEqual(rh._safe_summary("clean text"), "clean text")

        self.assertEqual(rh._literal_type("'str'"), "string")
        self.assertEqual(rh._literal_type('"str"'), "string")
        self.assertEqual(rh._literal_type("true"), "boolean")
        self.assertEqual(rh._literal_type("false"), "boolean")
        self.assertEqual(rh._literal_type("42"), "integer")
        self.assertEqual(rh._literal_type("-10"), "integer")
        self.assertEqual(rh._literal_type("[1, 2]"), "array")
        self.assertEqual(rh._literal_type("{a: 1}"), "hash")
        self.assertEqual(rh._literal_type("var + 1"), "expression")

        self.assertEqual(rh._first_literal('call("first", "second")'), "first")
        self.assertEqual(rh._first_literal("call('single')"), "single")
        self.assertIsNone(rh._first_literal("no_quotes_here"))

        self.assertFalse(rh._is_secret_prone(None))
        self.assertFalse(rh._is_secret_prone(""))
        self.assertFalse(rh._is_secret_prone("user_name"))
        self.assertTrue(rh._is_secret_prone("aws_access_key_id"))
        self.assertTrue(rh._is_secret_prone("session_secret"))


if __name__ == "__main__":
    unittest.main()
