"""Maintained complete optional-dependency function contracts."""

BASE_PACKAGE_IMPORT_TEMPLATE = r'''def test_base_package_import_does_not_require_scale_tools(monkeypatch) -> None:
    package_path = Path(repomap_kg.__file__)
    module_name = '_repomap_without_scale_tools'
    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {'psutil', 'docker'}:
            raise ModuleNotFoundError(f'No module named {name!r}', name=name)
        return real_import(name, globals, locals, fromlist, level)
    with monkeypatch.context() as import_patch, patch.dict(sys.modules):
        import_patch.setattr(builtins, '__import__', blocked_import)
        specification = importlib.util.spec_from_file_location(module_name, package_path, submodule_search_locations=[str(package_path.parent)])
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        specification.loader.exec_module(module)'''

SAMPLING_MISSING_DEPENDENCY_TEMPLATE = r'''@pytest.mark.parametrize('missing_name', ['psutil', 'docker'])
def test_sampling_module_fails_fast_when_scale_dependency_is_missing(monkeypatch: pytest.MonkeyPatch, missing_name: str) -> None:
    from unittest.mock import patch
    module_path = Path(resource_sampling.__file__)
    module_name = f'_scale28_missing_{missing_name}'
    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == missing_name:
            raise ModuleNotFoundError(f'No module named {missing_name!r}', name=missing_name)
        return real_import(name, globals, locals, fromlist, level)
    with monkeypatch.context() as import_patch, patch.dict(sys.modules):
        import_patch.setattr(builtins, '__import__', blocked_import)
        specification = importlib.util.spec_from_file_location(module_name, module_path)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        with pytest.raises(RuntimeError, match='scale-tools'):
            specification.loader.exec_module(module)'''

SUBSTITUTION_TEMPLATES = {"base_package_import": BASE_PACKAGE_IMPORT_TEMPLATE, "sampling_missing_psutil": SAMPLING_MISSING_DEPENDENCY_TEMPLATE, "sampling_missing_docker": SAMPLING_MISSING_DEPENDENCY_TEMPLATE}
