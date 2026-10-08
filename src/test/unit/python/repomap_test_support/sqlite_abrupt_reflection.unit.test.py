"""Synthetic maintained-source reflection and slot-policy counterexamples."""
import ast
import pytest


@pytest.mark.parametrize("code", [
    "def f():\n child = harness.start('ops')\n name = 'barrier'\n name = unknown\n object.__setattr__(child, name, value)\n",
    "name = 'barrier'\ndef f(child: ManagedChild, name):\n object.__setattr__(child, name, value)\n",
    "def f():\n child = harness.start('ops')\n a, b = '_abrupt', '_ManagedChild__process'\n object.__setattr__(child, a, True)\n object.__getattribute__(child, b)\n",
    "def f():\n MC = ManagedChild\n p = MC(raw)\n object.__setattr__(p, unknown, True)\n",
])
def test_uncertain_or_aliased_protected_names_are_refused(code):
    from repomap_test_support.sqlite_abrupt_ownership import AbruptOwnershipVisitor

    visitor = AbruptOwnershipVisitor("synth_shadowed_names.py")
    visitor.visit(ast.parse(code))
    assert visitor.bypasses


def test_ast_scanner_detects_reflection_bypasses_and_aliases() -> None:
    """Prove the AST scanner rejects object.__setattr__, object.__getattribute__, and aliases."""
    from repomap_test_support.sqlite_abrupt_ownership import AbruptOwnershipVisitor

    cases = [
        # Direct object.__setattr__ on _abrupt and abrupt
        ("def f():\n p = harness.start('ops')\n object.__setattr__(p, '_abrupt', True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n object.__setattr__(p, 'abrupt', True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n object.__setattr__(p, '_ManagedChild__process', raw)\n", "object.__setattr__ bypass"),
        # Aliased object.__setattr__
        ("def f():\n p = harness.start('ops')\n fn = object.__setattr__\n fn(p, '_abrupt', True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n fn = getattr(object, '__setattr__')\n fn(p, '_abrupt', True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n getattr(object, '__setattr__')(p, '_abrupt', True)\n", "object.__setattr__ bypass"),
        # Constant variable name and alias for object.__setattr__
        ("def f():\n p = harness.start('ops')\n name = '_abrupt'\n object.__setattr__(p, name, True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n name = 'abrupt'\n object.__setattr__(p, name, True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n name = '_ManagedChild__process'\n object.__setattr__(p, name, raw)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n name = '__process'\n object.__setattr__(p, name, raw)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n a = '_abrupt'\n b = a\n object.__setattr__(p, b, True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n fn = object.__setattr__\n name = '_abrupt'\n fn(p, name, True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n fn = getattr(object, '__setattr__')\n name = '_abrupt'\n fn(p, name, True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n m = '__setattr__'\n fn = getattr(object, m)\n name = '_abrupt'\n fn(p, name, True)\n", "object.__setattr__ bypass"),
        ("def f():\n p = harness.start('ops')\n object.__setattr__(p, unknown_var, True)\n", "object.__setattr__ bypass"),
        ("def f(child: ManagedChild):\n object.__setattr__(child, unknown_var, True)\n", "object.__setattr__ bypass"),
        # Direct object.__getattribute__ on _ManagedChild__process
        ("def f():\n p = harness.start('ops')\n proc = object.__getattribute__(p, '_ManagedChild__process')\n", "object.__getattribute__ bypass"),
        # Aliased object.__getattribute__
        ("def f():\n p = harness.start('ops')\n fn = object.__getattribute__\n proc = fn(p, '_ManagedChild__process')\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n fn = getattr(object, '__getattribute__')\n proc = fn(p, '_ManagedChild__process')\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n proc = getattr(object, '__getattribute__')(p, '_ManagedChild__process')\n", "object.__getattribute__ bypass"),
        # Constant variable name and alias for object.__getattribute__
        ("def f():\n p = harness.start('ops')\n name = '_ManagedChild__process'\n proc = object.__getattribute__(p, name)\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n name = '__process'\n proc = object.__getattribute__(p, name)\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n name = '_abrupt'\n val = object.__getattribute__(p, name)\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n a = '_ManagedChild__process'\n b = a\n proc = object.__getattribute__(p, b)\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n fn = object.__getattribute__\n name = '_ManagedChild__process'\n proc = fn(p, name)\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n fn = getattr(object, '__getattribute__')\n name = '_ManagedChild__process'\n proc = fn(p, name)\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n m = '__getattribute__'\n fn = getattr(object, m)\n name = '_ManagedChild__process'\n proc = fn(p, name)\n", "object.__getattribute__ bypass"),
        ("def f():\n p = harness.start('ops')\n proc = object.__getattribute__(p, unknown_var)\n", "object.__getattribute__ bypass"),
        ("def f(child: ManagedChild):\n proc = object.__getattribute__(child, unknown_var)\n", "object.__getattribute__ bypass"),
    ]

    for code, exp in cases:
        v = AbruptOwnershipVisitor("synth_reflection.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject reflection pattern '{exp}' in:\n{code}\nFound bypasses: {v.bypasses}"


def test_ast_scanner_detects_slot_descriptor_bypasses_and_aliases() -> None:
    """Prove the AST scanner rejects slot descriptor calls (__set__, __get__, __delete__) and aliases."""
    from repomap_test_support.sqlite_abrupt_ownership import AbruptOwnershipVisitor

    descriptor_cases = [
        # Direct ManagedChild slot descriptors
        ("def f():\n ManagedChild._abrupt.__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n ManagedChild._abrupt.__set__(child, False)\n", "descriptor bypass"),
        ("def f():\n ManagedChild._abrupt.__delete__(child)\n", "descriptor bypass"),
        ("def f():\n proc = ManagedChild._ManagedChild__process.__get__(child, ManagedChild)\n", "descriptor bypass"),
        ("def f():\n proc = ManagedChild._ManagedChild__process.__get__(child)\n", "descriptor bypass"),
        # Descriptor aliases
        ("def f():\n desc = ManagedChild._abrupt\n desc.__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n desc = ManagedChild._ManagedChild__process\n proc = desc.__get__(child, ManagedChild)\n", "descriptor bypass"),
        ("def f():\n d1 = ManagedChild._abrupt\n d2 = d1\n d2.__set__(child, True)\n", "descriptor bypass"),
        # Descriptor method aliases
        ("def f():\n setter = ManagedChild._abrupt.__set__\n setter(child, True)\n", "descriptor bypass"),
        ("def f():\n getter = ManagedChild._ManagedChild__process.__get__\n proc = getter(child, ManagedChild)\n", "descriptor bypass"),
        ("def f():\n s1 = ManagedChild._abrupt.__set__\n s2 = s1\n s2(child, True)\n", "descriptor bypass"),
        # Class aliases
        ("def f():\n MC = ManagedChild\n MC._abrupt.__set__(child, True)\n", "descriptor bypass"),
        ("from repomap_test_support.sqlite_managed_child import ManagedChild as MC\ndef f():\n MC._abrupt.__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n MC = ManagedChild\n C = MC\n C._abrupt.__set__(child, True)\n", "descriptor bypass"),
        # Dynamic class access
        ("def f():\n child = harness.start('ops')\n type(child)._abrupt.__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n child = harness.start('ops')\n child.__class__._ManagedChild__process.__get__(child, ManagedChild)\n", "descriptor bypass"),
        # getattr on class for descriptor and method
        ("def f():\n getattr(ManagedChild, '_abrupt').__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n getattr(ManagedChild._abrupt, '__set__')(child, True)\n", "descriptor bypass"),
        ("def f():\n slot = getattr(ManagedChild, '_ManagedChild__process')\n proc = slot.__get__(child, ManagedChild)\n", "descriptor bypass"),
        ("def f():\n name = '_abrupt'\n getattr(ManagedChild, name).__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n name = '_ManagedChild__process'\n slot = getattr(ManagedChild, name)\n getter = getattr(slot, '__get__')\n proc = getter(child, ManagedChild)\n", "descriptor bypass"),
        # Dict and vars descriptor patterns
        ("def f():\n ManagedChild.__dict__['_abrupt'].__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n vars(ManagedChild)['_ManagedChild__process'].__get__(child, ManagedChild)\n", "descriptor bypass"),
        # Conservative rejection of unresolved descriptor on ManagedChild
        ("def f():\n desc = getattr(ManagedChild, dynamic_name)\n desc.__set__(child, True)\n", "descriptor bypass"),
        ("def f():\n child = harness.start('ops')\n desc.__set__(child, True)\n", "descriptor bypass"),
    ]

    for code, exp in descriptor_cases:
        v = AbruptOwnershipVisitor("synth_desc.py")
        v.visit(ast.parse(code))
        assert any(exp in b for b in v.bypasses), f"Failed to reject descriptor pattern '{exp}' in:\n{code}\nFound bypasses: {v.bypasses}"


def test_ast_scanner_allows_unrelated_reflection_and_approved_child_api() -> None:
    """Prove the AST scanner does not reject unrelated object reflection or approved ManagedChild APIs."""
    from repomap_test_support.sqlite_abrupt_ownership import AbruptOwnershipVisitor

    safe_cases = [
        # Unrelated object reflection
        "def f():\n object.__setattr__(model, 'name', value)\n",
        "def f():\n object.__setattr__(model, var_name, value)\n",
        "def f():\n proc = object.__getattribute__(other, 'attr')\n",
        "def f():\n OtherClass.field.__set__(instance, value)\n",
        # Approved ManagedChild public property readback
        "def f():\n child = harness.start('ops')\n val = child.abrupt\n",
        "def f():\n child = harness.start('ops')\n pid = child.pid\n",
        "def f():\n child = harness.start('ops')\n rc = child.returncode\n",
        # Approved ManagedChild methods
        "def f():\n child = harness.start('ops', extra_env=paused_env('p', b, abrupt=True))\n child.kill_abruptly()\n",
        "def f():\n child = harness.start('ops')\n child.cleanup()\n",
        "def f():\n child = harness.start('ops')\n child.terminate()\n",
        "def f():\n child = harness.start('ops')\n child.wait()\n",
        "def f():\n child = harness.start('ops')\n child.poll()\n",
        "def f():\n child = harness.start('ops')\n child.communicate()\n",
    ]

    for code in safe_cases:
        v = AbruptOwnershipVisitor("synth_safe_reflection.py")
        v.visit(ast.parse(code))
        assert not v.bypasses, f"Unexpected false-positive bypass on safe reflection/API code:\n{code}\nBypasses: {v.bypasses}"
