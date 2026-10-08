"""New files and aliases cannot bypass the abrupt guard/holder contract."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repomap_test_support.sqlite_abrupt_ownership import AbruptOwnershipVisitor, scan_maintained_scope
from repomap_test_support.sqlite_local_harness import kill_paused_child


@pytest.mark.parametrize("termination", [
    "proc.send_signal(signal.SIGKILL)", "proc.kill()",
    "os.kill(proc.pid, signal.SIGKILL)", "kill_holder(proc)",
])
def test_new_owner_outside_old_glob_fails_static_owner(tmp_path: Path, termination: str) -> None:
    owner = tmp_path / "src/test/support/python/added_owner/arbitrary.py"
    owner.parent.mkdir(parents=True)
    owner.write_text(
        "from repomap_test_support.sqlite_local_lock_children import start_holder\n"
        "def new_case():\n    proc, ready = start_holder(db, env, abrupt=False)\n"
        f"    {termination}\n"
    )
    _, _, violations = scan_maintained_scope(tmp_path)
    assert violations
    assert any("added_owner/arbitrary.py" in message for message in violations)
    assert any("abrupt=False" in message for message in violations)


def test_aliases_and_fake_helper_name_do_not_exempt_direct_kill() -> None:
    code = """
from repomap_test_support.sqlite_local_lock_children import start_holder as spawn
def kill_holder():
    target, ready = spawn(db, env, abrupt=True)
    target.kill()
"""
    visitor = AbruptOwnershipVisitor("src/test/unit/python/new_owner.py")
    visitor.visit(ast.parse(code))
    assert any("target.kill() bypass" in message for message in visitor.bypasses)


def test_named_harness_return_and_process_alias_are_related() -> None:
    code = """
from repomap_test_support.sqlite_local_harness import LocalHarness as Harness
def owner():
    rig = Harness(scratch)
    proc = rig.start('ops')
    alias = proc
    alias.send_signal(signal.SIGKILL)
"""
    visitor = AbruptOwnershipVisitor("new_owner.py")
    visitor.visit(ast.parse(code))
    assert any("alias.send_signal() bypass" in message for message in visitor.bypasses)


def test_unrelated_writer_cleanup_is_allowed() -> None:
    visitor = AbruptOwnershipVisitor("new_owner.py")
    visitor.visit(ast.parse("def owner():\n    writer = external.launch()\n    writer.kill()\n"))
    assert not visitor.bypasses


def test_signal_alias_is_detected_and_graceful_holder_signal_is_allowed() -> None:
    visitor = AbruptOwnershipVisitor("new_owner.py")
    visitor.visit(ast.parse(
        "import os as operating\nfrom signal import SIGKILL as abrupt_signal\n"
        "def owner():\n    child, ready = start_holder(db, env)\n"
        "    operating.kill(child.pid, abrupt_signal)\n"
    ))
    assert any("os.kill bypass" in message for message in visitor.bypasses)
    graceful = AbruptOwnershipVisitor("new_owner.py")
    graceful.visit(ast.parse(
        "def owner():\n    child, ready = start_holder(db, env)\n"
        "    child.send_signal(signal.SIGTERM)\n    os.kill(child.pid, signal.SIGTERM)\n"
    ))
    assert not graceful.bypasses


def test_raw_guard_launcher_is_related_to_annotated_process() -> None:
    visitor = AbruptOwnershipVisitor("new_owner.py")
    visitor.visit(ast.parse(
        "def owner():\n    child: Popen = subprocess.Popen([python, 'sqlite_local_guard.py'])\n    child.kill()\n"
    ))
    assert any("child.kill() bypass" in message for message in visitor.bypasses)


@pytest.mark.parametrize("receipt", [None, "pid=123\ncomplete=0\n"])
def test_abrupt_cleanup_cannot_stamp_missing_or_incomplete_receipt_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt: str | None,
) -> None:
    monkeypatch.setenv("COVERAGE_CHILD_MANIFEST_DIR", str(tmp_path))
    exit_path = tmp_path / "123.exit"
    if receipt is not None:
        exit_path.write_text(receipt)
    (tmp_path / "123.start").write_text("pid=123\n")
    process = MagicMock(pid=123)
    process.poll.return_value = None
    with pytest.raises(AssertionError, match="terminal_receipt_incomplete"):
        kill_paused_child(process)
    process.send_signal.assert_called_once()
    assert exit_path.read_text() == receipt if receipt is not None else not exit_path.exists()


def test_omission_proof_ast_scanner_verifies_whole_maintained_scope() -> None:
    """Prove all intentional SIGKILL pause sites across whole maintained scope opt in via abrupt=True and use central helpers."""
    from repomap_test_support.sqlite_abrupt_ownership import scan_maintained_scope

    repo_root = Path(__file__).resolve().parents[5]
    kills, launches, bypasses = scan_maintained_scope(repo_root)
    assert not bypasses, f"Bypasses found in maintained scope: {bypasses}"

    # Verify that central abrupt helpers own all intentional kills
    assert all(helper in {"kill_paused_child", "kill_holder"} for _, helper, _ in kills)

    # Verify new owner sqlite_local_locking.unit.test.py is detected in maintained scope
    kill_filenames = {Path(fn).name for fn, _, _ in kills}
    launch_filenames = {Path(fn).name for fn, _, _ in launches}
    assert "sqlite_local_locking.unit.test.py" in kill_filenames
    assert "sqlite_local_locking.unit.test.py" in launch_filenames


def test_ast_scanner_detects_four_illegal_patterns_and_related_process_aliases() -> None:
    """Prove the AST scanner rejects each of the 4 illegal patterns across launchers and related aliases."""
    from repomap_test_support.sqlite_abrupt_ownership import AbruptOwnershipVisitor

    cases = [
        # Pattern 1: explicit abrupt=False on paused_env and start_holder
        ("def f():\n env = paused_env('p', b, abrupt=False)\n kill_paused_child(p)\n", "abrupt=False"),
        ("def f():\n h, r = start_holder(db, env, abrupt=False)\n kill_holder(h)\n", "abrupt=False"),
        # Pattern 2: direct .kill() bypass on launcher process, alias, and synthetic target
        ("def f():\n writer = harness.start('ops')\n writer.kill()\n", "writer.kill() bypass"),
        ("def f():\n p = harness.start('ops')\n p.kill()\n", ".p.kill() bypass"),
        ("def f():\n p = harness.start('ops')\n alias = p\n alias.kill()\n", ".alias.kill() bypass"),
        ("def f():\n h, _ = start_holder(db, env, abrupt=True)\n h.kill()\n", ".h.kill() bypass"),
        # Pattern 3: direct .send_signal() bypass on launcher process, alias, and synthetic target
        ("def f():\n killed, _ = start_holder(db, env)\n killed.send_signal(signal.SIGKILL)\n", "killed.send_signal() bypass"),
        ("def f():\n p = harness.start('ops')\n p.send_signal(signal.SIGKILL)\n", ".p.send_signal() bypass"),
        ("def f():\n h, _ = start_holder(db, env, abrupt=True)\n alias = h\n alias.send_signal(signal.SIGKILL)\n", ".alias.send_signal() bypass"),
        # Pattern 4: direct os.kill bypass on launcher process pid, alias pid, and synthetic target
        ("def f():\n writer = harness.start('ops')\n os.kill(writer.pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n os.kill(p.pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n alias = p\n os.kill(alias.pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n p_pid = p.pid\n os.kill(p_pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n h, _ = start_holder(db, env, abrupt=True)\n os.kill(h.pid, signal.SIGKILL)\n", "os.kill bypass"),
    ]

    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject pattern '{exp}' in code:\n{code}\nFound bypasses: {v.bypasses}"


def test_ast_scanner_does_not_false_positive_on_unrelated_cleanups() -> None:
    """Prove the AST scanner does not false-positive on unrelated subprocess cleanups or signal 0 probes."""
    from repomap_test_support.sqlite_abrupt_ownership import AbruptOwnershipVisitor

    safe_cases = [
        "def f():\n unrelated = subprocess.Popen(['ls'])\n unrelated.kill()\n",
        "def f():\n process = subprocess.Popen(['ls'])\n process.kill()\n",
        "def f():\n process = subprocess.Popen(['ls'])\n process.send_signal(signal.SIGTERM)\n",
        "def f():\n process = subprocess.Popen(['ls'])\n os.kill(process.pid, signal.SIGTERM)\n",
        "def f():\n child = subprocess.run(['ls'])\n",
        "def f():\n os.kill(grandchild, 0)\n",
        "def f():\n os.kill(writer.pid, 0)\n",
        "def f():\n h, r = start_holder(db, env, abrupt=True)\n kill_holder(h)\n",
        "def f():\n env = paused_env('p', b, abrupt=True)\n p = harness.start('ops', extra_env=env)\n kill_paused_child(p)\n",
    ]

    for code in safe_cases:
        v = AbruptOwnershipVisitor("synth_safe.py")
        v.visit(ast.parse(code))
        assert not v.bypasses, f"Unexpected false-positive bypass on safe code:\n{code}\nBypasses: {v.bypasses}"


def test_ast_scanner_detects_container_and_attribute_bypasses() -> None:
    cases = [
        ("def f():\n self.writer = harness.start('ops')\n self.writer.kill()\n", ".self.writer.kill() bypass"),
        ("def f():\n self.writer = harness.start('ops')\n os.kill(self.writer.pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n box = [harness.start('ops')]\n box[0].kill()\n", ".box[0].kill() bypass"),
        ("def f():\n d = {'child': harness.start('ops')}\n d['child'].kill()\n", ".d['child'].kill() bypass"),
        ("def f():\n box = [harness.start('ops')]\n os.kill(box[0].pid, signal.SIGKILL)\n", "os.kill bypass"),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_attr.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject pattern '{exp}' in code:\n{code}\nFound bypasses: {v.bypasses}"


def test_ast_scanner_detects_context_manager_and_fixture_returns() -> None:
    cases = [
        ("def f():\n with harness.start('ops') as p:\n  p.kill()\n", ".p.kill() bypass"),
        (
            "@pytest.fixture\ndef guard_fixture():\n return harness.start('ops')\n"
            "def test_it(guard_fixture):\n guard_fixture.kill()\n",
            ".guard_fixture.kill() bypass",
        ),
        (
            "@pytest.fixture\ndef guard_fixture():\n p = harness.start('ops')\n yield p\n"
            "def test_it(guard_fixture):\n guard_fixture.kill()\n",
            ".guard_fixture.kill() bypass",
        ),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_ctx.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject pattern '{exp}' in code:\n{code}\nFound bypasses: {v.bypasses}"


def test_ast_scanner_detects_wrapper_return_launch() -> None:
    code = """
def spawn():
    return harness.start('ops')

def test_wrapper():
    c = spawn()
    c.kill()
"""
    v = AbruptOwnershipVisitor("synth_wrap.py")
    v.visit(ast.parse(code))
    assert any(".c.kill() bypass" in b for b in v.bypasses), f"Bypasses: {v.bypasses}"


def test_ast_scanner_detects_variable_guard_path() -> None:
    cases = [
        (
            "def f():\n guard_script = 'sqlite_local_guard.py'\n"
            " p = subprocess.Popen([sys.executable, guard_script])\n p.kill()\n",
            ".p.kill() bypass",
        ),
        (
            "def f():\n guard_path = Path('sqlite_local_guard.py')\n"
            " p = subprocess.Popen([sys.executable, guard_path])\n p.kill()\n",
            ".p.kill() bypass",
        ),
        (
            "def f():\n from repomap_test_support import sqlite_local_guard\n"
            " cmd = [sys.executable, sqlite_local_guard.__file__]\n"
            " p = subprocess.Popen(cmd)\n p.kill()\n",
            ".p.kill() bypass",
        ),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_var.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject pattern '{exp}' in code:\n{code}\nFound bypasses: {v.bypasses}"


def test_ast_scanner_detects_killpg_bypass() -> None:
    cases = [
        ("def f():\n p = harness.start('ops')\n os.killpg(p.pid, signal.SIGKILL)\n", "os.killpg bypass"),
        ("def f():\n p = harness.start('ops')\n os.killpg(os.getpgid(p.pid), signal.SIGKILL)\n", "os.killpg bypass"),
        ("def f():\n p = harness.start('ops')\n p_pid = p.pid\n os.killpg(os.getpgid(p_pid), signal.SIGKILL)\n", "os.killpg bypass"),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_killpg.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject pattern '{exp}' in code:\n{code}\nFound bypasses: {v.bypasses}"


def test_ast_scanner_detects_signal_aliases_and_constant_values() -> None:
    cases = [
        ("def f():\n p = harness.start('ops')\n sig = signal.SIGKILL\n os.kill(p.pid, sig)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n KILL = 9\n os.kill(p.pid, KILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n SIG = signal.SIGKILL.value\n os.kill(p.pid, SIG)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n sig = int(signal.SIGKILL)\n os.kill(p.pid, sig)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n sig = signal.SIGKILL\n p.send_signal(sig)\n", ".p.send_signal() bypass"),
        ("def f():\n p = harness.start('ops')\n sig = signal.SIGKILL\n sig_alias = sig\n os.kill(p.pid, sig_alias)\n", "os.kill bypass"),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_sig.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject signal pattern '{exp}' in:\n{code}\nBypasses: {v.bypasses}"


def test_ast_scanner_detects_pid_expressions_and_getattr() -> None:
    cases = [
        ("def f():\n p = harness.start('ops')\n p_pid = int(p.pid)\n os.kill(p_pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n p_pid = int(str(p.pid))\n os.kill(p_pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n p_pid = getattr(p, 'pid')\n os.kill(p_pid, signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n os.kill(int(p.pid), signal.SIGKILL)\n", "os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n os.kill(getattr(p, 'pid'), signal.SIGKILL)\n", "os.kill bypass"),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_pid_expr.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject PID expr pattern '{exp}' in:\n{code}\nBypasses: {v.bypasses}"


def test_ast_scanner_detects_os_kill_import_and_method_getattr_or_alias() -> None:
    cases = [
        ("from os import kill\ndef f():\n p = harness.start('ops')\n kill(p.pid, signal.SIGKILL)\n", "direct os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n getattr(os, 'kill')(p.pid, signal.SIGKILL)\n", "direct os.kill bypass"),
        ("def f():\n p = harness.start('ops')\n getattr(p, 'kill')()\n", ".p.kill() bypass"),
        ("def f():\n p = harness.start('ops')\n getattr(p, 'send_signal')(signal.SIGKILL)\n", ".p.send_signal() bypass"),
        ("def f():\n p = harness.start('ops')\n fn = getattr(p, 'kill')\n fn()\n", ".fn() bypass"),
        ("def f():\n p = harness.start('ops')\n fn = p.kill\n fn()\n", ".fn() bypass"),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_method_alias.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject method alias pattern '{exp}' in:\n{code}\nBypasses: {v.bypasses}"


def test_ast_scanner_detects_cross_module_helper(tmp_path: Path) -> None:
    helper_file = tmp_path / "src/test/support/python/fake_helper.py"
    helper_file.parent.mkdir(parents=True)
    helper_file.write_text(
        "def make_guard(harness):\n"
        "    return harness.start('ops')\n"
        "def make_holder(db, env):\n"
        "    return start_holder(db, env)\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "src/test/unit/python/consumer_test.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_kill(harness):\n"
        "    p = make_guard(harness)\n"
        "    p.kill()\n"
        "def test_holder(db, env):\n"
        "    h, r = make_holder(db, env)\n"
        "    h.kill()\n",
        encoding="utf-8",
    )
    _, _, violations = scan_maintained_scope(tmp_path)
    assert any(".p.kill() bypass" in v for v in violations)
    assert any(".h.kill() bypass" in v for v in violations)


def test_ast_scanner_detects_wrapper_managed_child() -> None:
    cases = [
        ("def f():\n w = ChildWrapper(harness.start('ops'))\n w.child.kill()\n", ".w.child.kill() bypass"),
        ("def f():\n w = ChildWrapper(harness.start('ops'))\n w.kill()\n", ".w.kill() bypass"),
        ("def f():\n w = ChildWrapper(harness.start('ops'))\n os.kill(w.child.pid, signal.SIGKILL)\n", "os.kill bypass"),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_wrap_cls.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject wrapper pattern '{exp}' in:\n{code}\nBypasses: {v.bypasses}"


def test_ast_scanner_detects_hold_and_spawn_contract() -> None:
    cases = [
        ("def f():\n h, r = start_holder(db, env, script=HOLD_AND_SPAWN, abrupt=False)\n", "explicit abrupt=False"),
        ("def f():\n h, r = start_holder(db, env, script=HOLD_AND_SPAWN)\n kill_holder(h)\n", "abrupt=True launcher contract"),
        ("def f():\n h, r = start_holder(db, env, script=HOLD_AND_SPAWN, abrupt=True)\n h.kill()\n", ".h.kill() bypass"),
        ("def f():\n p = subprocess.Popen([sys.executable, '-c', HOLD_AND_SPAWN, db])\n p.kill()\n", ".p.kill() bypass"),
        ("def f():\n p = subprocess.Popen([sys.executable, '-c', HOLD_AND_SPAWN, db])\n os.kill(p.pid, signal.SIGKILL)\n", "os.kill bypass"),
    ]
    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_hold_spawn.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject HOLD_AND_SPAWN pattern '{exp}' in:\n{code}\nBypasses: {v.bypasses}"
