"""Maintained complete file-loader function contracts."""

LOADER_TEMPLATES = {
'helper_contract_probe': r'''def _load_contract_module(name: str, path: Path) -> ModuleType:
    """Exercise real file loading only at the loader-control test boundary."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load unit contract module {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module''',
'conftest_refusal': r'''def test_direct_integration_conftest_import_refuses_before_fixture_setup():
    conftest_path = REPO_ROOT / 'src' / 'test' / 'int' / 'python' / 'conftest.py'
    spec = importlib.util.spec_from_file_location('conftest', conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch('test_sandbox.active_sandbox', return_value=False), patch('repomap_test_support.postgres_harness.postgres_container_session') as postgres, pytest.raises(pytest.exit.Exception, match='authenticated container sandbox'):
        spec.loader.exec_module(module)
    postgres.assert_not_called()''',
'conftest_inspection': r'''def test_unit_inspection_import_of_integration_conftest_does_not_activate_guard():
    conftest_path = REPO_ROOT / 'src' / 'test' / 'int' / 'python' / 'conftest.py'
    spec = importlib.util.spec_from_file_location('repomap_int_conftest_inspection', conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch('test_sandbox.active_sandbox', return_value=False) as active, patch('repomap_test_support.postgres_harness.postgres_container_session') as postgres:
        spec.loader.exec_module(module)
    active.assert_not_called()
    postgres.assert_not_called()''',
}

HELPER_DISPATCH = r'''def load_unit_contract_class(module_filename: str, class_name: str, *, load_module: Callable[[str, Path], ModuleType]) -> object:
    module_path = UNIT_REPOMAP_TEST_ROOT / module_filename
    if not module_path.exists():
        matches = sorted(UNIT_REPOMAP_TEST_ROOT.rglob(module_filename))
        if len(matches) != 1:
            raise RuntimeError(f'expected one unit contract module named {module_filename}, found {len(matches)}')
        module_path = matches[0]
    module = load_module(f'repomap_helper_contract_{class_name}', module_path)
    return getattr(module, class_name)'''
