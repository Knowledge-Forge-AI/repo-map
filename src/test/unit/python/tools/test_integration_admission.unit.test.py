"""Unit tests verifying integration test admission discipline and scratch conventions."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[5]
INT_TEST_ROOT = REPO_ROOT / "src" / "test" / "int" / "python"


class IntegrationAdmissionDisciplineUnitTests(unittest.TestCase):
    def test_target_integration_modules_reject_direct_execution_at_seam(self) -> None:
        targets = sorted(INT_TEST_ROOT.rglob("*.int.test.py"))
        self.assertTrue(targets, "Integration owner discovery must be nonempty")
        guarded = 0
        for target in targets:
            with self.subTest(target=target.relative_to(INT_TEST_ROOT).as_posix()):
                tree = ast.parse(target.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "unittest"
                            and node.func.attr == "main"):
                        self.fail("Integration owners cannot invoke unittest.main")
                guards = [node for node in tree.body
                          if isinstance(node, ast.If)
                          and isinstance(node.test, ast.Compare)
                          and isinstance(node.test.left, ast.Name)
                          and node.test.left.id == "__name__"]
                for guard in guards:
                    guarded += 1
                    assert isinstance(guard.test, ast.Compare)
                    self.assertEqual(len(guard.test.ops), 1)
                    self.assertIsInstance(guard.test.ops[0], ast.Eq)
                    self.assertEqual(len(guard.test.comparators), 1)
                    self.assertEqual(ast.literal_eval(guard.test.comparators[0]), "__main__")
                    actions = [node for node in guard.body
                               if not isinstance(node, (ast.Import, ast.ImportFrom))]
                    self.assertEqual(len(actions), 1, "Direct entry must only refuse")
                    action = actions[0]
                    assert isinstance(action, ast.Expr)
                    call = action.value
                    assert isinstance(call, ast.Call)
                    self.assertEqual(ast.unparse(call.func), "sys.exit")
                    self.assertEqual(len(call.args), 1)
                    message = ast.literal_eval(call.args[0])
                    self.assertIn("Direct execution unsupported", message)
                    self.assertIn("container sandbox admission", message)
        self.assertGreater(guarded, 0, "Expected direct-entry refusal owners")

    def test_pipeline_integration_modules_allocate_temp_under_managed_scratch(self) -> None:
        checked = 0
        for target in sorted(INT_TEST_ROOT.rglob("*.int.test.py")):
            tree = ast.parse(target.read_text(encoding="utf-8"))
            imports_selection = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "repomap_test_support.test_scratch"
                and any(alias.name == "select_scratch_root" for alias in node.names)
                for node in ast.walk(tree)
            )
            if not imports_selection:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "mkdtemp"):
                    with self.subTest(target=target.relative_to(INT_TEST_ROOT).as_posix()):
                        directories = [kw.value for kw in node.keywords if kw.arg == "dir"]
                        self.assertEqual(len(directories), 1)
                        self.assertEqual(ast.unparse(directories[0]), "select_scratch_root()")
                        checked += 1
        self.assertGreater(checked, 0, "Managed scratch allocation cohort must be nonempty")

    def test_conftest_sandbox_admission_source_contract(self) -> None:
        # Parse only: importing this owner can execute container/service setup.
        tree = ast.parse((INT_TEST_ROOT / "conftest.py").read_text(encoding="utf-8"))
        self._assert_admission_contract(tree)

    def test_sandbox_contract_rejects_weakened_refusal_paths(self) -> None:
        source = (INT_TEST_ROOT / "conftest.py").read_text(encoding="utf-8")
        for mutation in ("exit_code", "missing_exit", "error_text", "false_text",
                         "lost_error", "handler_initialization", "false_initialization"):
            with self.subTest(mutation=mutation):
                tree = ast.parse(source)
                refusal = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                               and node.name == "_require_authenticated_sandbox")
                attempt, unauthenticated = refusal.body
                assert isinstance(attempt, ast.Try) and isinstance(unauthenticated, ast.If)
                handler = attempt.handlers[0]
                statement = handler.body[0]
                assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                call = statement.value
                if mutation == "exit_code":
                    call.keywords[0].value = ast.Constant(value=0)
                elif mutation == "missing_exit":
                    handler.body.clear()
                elif mutation == "error_text":
                    call.args[0] = ast.Constant(value="refused")
                elif mutation == "false_text":
                    false_statement = unauthenticated.body[0]
                    assert isinstance(false_statement, ast.Expr)
                    assert isinstance(false_statement.value, ast.Call)
                    false_statement.value.args[0] = ast.Constant(value="refused")
                elif mutation == "lost_error":
                    call.args[0] = ast.Constant(
                        value="ERROR: RepoMap integration tests require the authenticated container sandbox")
                else:
                    body = handler.body if mutation == "handler_initialization" else unauthenticated.body
                    body.append(ast.parse("initialize_session()").body[0])
                with self.assertRaises(AssertionError):
                    self._assert_admission_contract(tree)

    def _assert_admission_contract(self, tree: ast.Module) -> None:
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        refusal = functions["_require_authenticated_sandbox"]
        self.assertEqual(len(refusal.body), 2)
        attempt, unauthenticated = refusal.body
        assert isinstance(attempt, ast.Try)
        self.assertEqual([ast.unparse(node) for node in attempt.body],
                         ["authenticated = active_sandbox()"])
        self.assertEqual(len(attempt.handlers), 1)
        handler = attempt.handlers[0]
        assert handler.type is not None
        self.assertEqual(ast.unparse(handler.type), "RuntimeError")
        self.assertEqual(handler.name, "error")
        self.assertFalse(attempt.orelse)
        self.assertFalse(attempt.finalbody)
        assert isinstance(unauthenticated, ast.If)
        self.assertEqual(ast.unparse(unauthenticated.test), "not authenticated")
        self.assertFalse(unauthenticated.orelse)
        for body in (handler.body, unauthenticated.body):
            self.assertEqual(len(body), 1, "Refusal must only exit, without initialization or return")
            call_statement = body[0]
            assert isinstance(call_statement, ast.Expr)
            call = call_statement.value
            assert isinstance(call, ast.Call)
            self.assertEqual(ast.unparse(call.func), "pytest.exit")
            self.assertEqual(len(call.args), 1)
            self.assertEqual([(kw.arg, ast.literal_eval(kw.value)) for kw in call.keywords],
                             [("returncode", 2)])
            message = call.args[0]
            literal_parts = [node.value for node in ast.walk(message)
                             if isinstance(node, ast.Constant) and isinstance(node.value, str)]
            self.assertIn("require the authenticated container sandbox", "".join(literal_parts))
        error_call = handler.body[0]
        assert isinstance(error_call, ast.Expr) and isinstance(error_call.value, ast.Call)
        self.assertTrue(any(isinstance(node, ast.FormattedValue)
                            and isinstance(node.value, ast.Name) and node.value.id == "error"
                            for node in ast.walk(error_call.value.args[0])))

        # Compare the AST rather than whitespace chosen by ast.unparse.
        expected = ast.parse("__name__.split('.')[-1] == 'conftest'", mode="eval").body
        guards = [node for node in tree.body if isinstance(node, ast.If)
                  and ast.dump(node.test) == ast.dump(expected)]
        self.assertEqual(len(guards), 1)
        self.assertEqual([ast.unparse(node) for node in guards[0].body],
                         ["_require_authenticated_sandbox()"])
        self.assertFalse(guards[0].orelse)
        self.assertLess(tree.body.index(guards[0]), tree.body.index(functions["pytest_sessionstart"]))


if __name__ == "__main__":
    unittest.main()
