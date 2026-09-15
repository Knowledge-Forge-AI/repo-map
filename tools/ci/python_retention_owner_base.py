"""Maintained complete owner context; parsed but never executed."""
SOURCE = r'''
from __future__ import annotations
import builtins
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch
import tomllib
import repomap_kg
_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]

def test_scale_tools_extra_has_only_the_selected_exact_pins() -> None:
    metadata = tomllib.loads((_REPOSITORY_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert metadata['project']['optional-dependencies']['scale-tools'] == ['psutil==7.2.2', 'docker==7.2.0']
    assert metadata['project']['dependencies'] == ['psycopg[binary]==3.2.12', 'typing-extensions==4.16.0']

def test_base_package_import_does_not_require_scale_tools(monkeypatch) -> None:
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
        specification.loader.exec_module(module)
'''
