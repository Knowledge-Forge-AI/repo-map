from __future__ import annotations

import ast
from pathlib import Path


def _module_imports(module: object) -> set[str]:
    file_path = getattr(module, "__file__", None)
    assert file_path is not None
    path = Path(file_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports


def test_arch1i_format_modules_use_neutral_contracts_not_generic_registry() -> None:
    import repomap_kg.extractors.config.generic_contracts as contracts
    import repomap_kg.extractors.config.infrastructure as owner_0
    import repomap_kg.extractors.config.javascript as owner_1
    import repomap_kg.extractors.config.openapi_helpers as owner_2
    import repomap_kg.extractors.config.python_support as owner_3
    import repomap_kg.extractors.config.terraform_hcl_observations as owner_4
    import repomap_kg.extractors.config.terraform_json as owner_5
    import repomap_kg.extractors.config.xml as owner_6
    import repomap_kg.extractors.config.xml_references as owner_7
    import repomap_kg.extractors.config.yaml as owner_8
    import repomap_kg.extractors.config.yaml_profiles as owner_9
    for module in (owner_0, owner_1, owner_2, owner_3, owner_4, owner_5, owner_6, owner_7, owner_8, owner_9,):
        imports = _module_imports(module)
        assert "repomap_kg.extractors.config.generic" not in imports
        assert callable(contracts._profile_observation)


def test_arch1i_generic_facade_preserves_neutral_contract_identities() -> None:
    import repomap_kg.extractors.config.generic_contracts as contracts
    import repomap_kg.extractors.config.generic as generic
    assert contracts.__file__ is not None
    contracts_source = Path(contracts.__file__).read_text(encoding="utf-8")
    assert "sys.modules" not in contracts_source

    for name in (
        "EXTRACTOR_NAME",
        "GENERIC_XML_FORMAT",
        "PLIST_XML_FORMAT",
        "YAML_FORMAT",
        "_document_observation",
        "_profile_observation",
        "_safe_value_summary",
        "_structure_observations",
    ):
        assert getattr(generic, name) is getattr(contracts, name)
