"""Pure ADR0123 byte projection of moved product source files."""

from __future__ import annotations

import pytest

from ci.retained_python_namespace_contract import NEW_PREFIX, OLD_PREFIX, NamespaceProjectionError
from ci.retained_python_namespace_source import (
    DURABLE_LITERALS,
    INSTALLED_NAME_LITERALS,
    ROOT_INIT_PATH,
    project_source_bytes,
)


MODULE = f"{OLD_PREFIX}cli/facade.py"
SOURCE = (
    '"""Facade for ``repomap_kg.cli`` and src/main/python/repomap_kg/cli.py."""\n'
    "import repomap_kg\n"
    "from repomap_kg.cli import main  # repomap_kg comment stays\n"
    "from  repomap_kg . graph   import keys\t# spacing stays\r\n"
    "repomap_kgx = repomap_kg.__name__\n"
    "BRAND = 'repomap-kg'\n"
    'OTHER = "xrepomap_kg repomap_kg_extra share/repomap_kg"\n'
    "RAW = b'repomap_kg.graph'\n"
    'LABEL = f"repomap_kg.{main.__name__}"\n'
    "\n"
)
EXPECTED = (
    '"""Facade for ``common_lore_index.cli`` and src/main/python/common_lore_index/cli.py."""\n'
    "import common_lore_index\n"
    "from common_lore_index.cli import main  # repomap_kg comment stays\n"
    "from  common_lore_index . graph   import keys\t# spacing stays\r\n"
    "repomap_kgx = common_lore_index.__name__\n"
    "BRAND = 'repomap-kg'\n"
    'OTHER = "xrepomap_kg repomap_kg_extra share/repomap_kg"\n'
    "RAW = b'common_lore_index.graph'\n"
    'LABEL = f"common_lore_index.{main.__name__}"\n'
    "\n"
)
INIT = (
    '"""RepoMap knowledge graph engine."""\n'
    '__version__ = "0.0.3"\n'
    "\n"
    "# One current installed owner; ADR0118 changes these only at the atomic cutover.\n"
    'DISTRIBUTION_NAME = "repomap-kg"\n'
    'IMPORT_PACKAGE = "repomap_kg"\n'
    'PREFERRED_CLI = "repomap-kg"\n'
)
CONTRACT = (
    "from repomap_kg import IMPORT_PACKAGE as _IMPORT_PACKAGE\n"
    "\n"
    "\n"
    "def _foreground_module_class(value: str) -> str:\n"
    "    if value == _IMPORT_PACKAGE:\n"
    '        return "current"\n'
    '    return "legacy" if value == "repomap_kg" else "unrecognized"\n'
)
SUMMARY = (
    "from repomap_kg.storage.sqlite_local.raw_payload import like\n"
    "\n"
    "\n"
    "def dogfooding(path: str) -> bool:\n"
    '    return like(path, "%repomap_kg%")\n'
)


def project(path: str, source: str) -> str:
    projected = project_source_bytes(path, source.encode())
    assert projected.count(b"\n") == source.encode().count(b"\n")
    return projected.decode()


def test_python_tokens_rewrite_exact_namespace_and_preserve_other_bytes() -> None:
    assert project(MODULE, SOURCE) == EXPECTED
    comment_rewrite = EXPECTED.replace("# repomap_kg comment", "# common_lore_index comment")
    assert project(MODULE, SOURCE) != comment_rewrite


def test_physical_line_count_is_preserved_without_final_newline() -> None:
    source = 'import repomap_kg\n"""\nrepomap_kg.cli\n"""\nx = repomap_kg'
    assert project(MODULE, source) == 'import common_lore_index\n"""\ncommon_lore_index.cli\n"""\nx = common_lore_index'


def test_root_init_changes_only_selected_installed_name_constants() -> None:
    assert project(ROOT_INIT_PATH, INIT) == INIT.replace(
        'DISTRIBUTION_NAME = "repomap-kg"', 'DISTRIBUTION_NAME = "common-lore-index"'
    ).replace('IMPORT_PACKAGE = "repomap_kg"', 'IMPORT_PACKAGE = "common_lore_index"').replace(
        'PREFERRED_CLI = "repomap-kg"', 'PREFERRED_CLI = "cloe"')
    assert dict(INSTALLED_NAME_LITERALS) == {
        "DISTRIBUTION_NAME": ("repomap-kg", "common-lore-index"),
        "PREFERRED_CLI": ("repomap-kg", "cloe"),
    }


def test_installed_names_are_not_rewritten_outside_the_root_init() -> None:
    assert project(f"{OLD_PREFIX}cli/__init__.py", INIT) == INIT.replace(
        'IMPORT_PACKAGE = "repomap_kg"', 'IMPORT_PACKAGE = "common_lore_index"')


@pytest.mark.parametrize("source", [
    INIT.replace('PREFERRED_CLI = "repomap-kg"\n', ""),
    INIT.replace('PREFERRED_CLI = "repomap-kg"', 'PREFERRED_CLI = "repomap"'),
    INIT + 'DISTRIBUTION_NAME = "repomap-kg"\n',
    INIT.replace('DISTRIBUTION_NAME = "repomap-kg"', 'DISTRIBUTION_NAME = "repomap-kg" + ""'),
])
def test_root_init_refuses_missing_duplicate_or_computed_installed_names(source: str) -> None:
    with pytest.raises(NamespaceProjectionError, match="installed-name"):
        project(ROOT_INIT_PATH, source)


def test_durable_keep_list_is_exact_and_path_bound() -> None:
    contract_path = f"{OLD_PREFIX}service_package/contract.py"
    summary_path = f"{OLD_PREFIX}storage/sqlite_local/summary_queries.py"
    assert dict(DURABLE_LITERALS) == {
        contract_path: "repomap_kg", summary_path: "%repomap_kg%",
        OLD_PREFIX + "storage/sql_summaries_python.py": "OR payload_json->>'path' LIKE '%repomap_kg%')), ",
    }
    assert project(contract_path, CONTRACT) == CONTRACT.replace(
        "from repomap_kg import", "from common_lore_index import")
    assert project(summary_path, SUMMARY) == SUMMARY.replace(
        "from repomap_kg.storage", "from common_lore_index.storage")
    assert project(f"{OLD_PREFIX}service_package/other.py", CONTRACT) == CONTRACT.replace(
        "repomap_kg", "common_lore_index")


@pytest.mark.parametrize("path,source", [
    (f"{OLD_PREFIX}service_package/contract.py", "from repomap_kg import IMPORT_PACKAGE\n"),
    (f"{OLD_PREFIX}service_package/contract.py", CONTRACT + "SECOND = 'repomap_kg'\n"),
    (f"{OLD_PREFIX}storage/sqlite_local/summary_queries.py", "PATTERN = '%repomap_kg'\n"),
])
def test_durable_keep_list_refuses_stale_or_ambiguous_entries(path: str, source: str) -> None:
    with pytest.raises(NamespaceProjectionError, match="durable legacy literal"):
        project(path, source)


def test_non_python_resources_pass_through_byte_identical() -> None:
    payload = b"repomap_kg LICENSE \xff\x00\r\nrepomap_kg.cli"
    assert project_source_bytes(f"{OLD_PREFIX}third_party_licenses/psycopg/LICENSE.txt", payload) == payload
    assert project_source_bytes(f"{OLD_PREFIX}py.typed", b"") == b""


@pytest.mark.parametrize("path", [
    f"{NEW_PREFIX}facade.py", "src/main/python/repomap_kg_extra/facade.py", f"{OLD_PREFIX}../facade.py",
    OLD_PREFIX, "tools/ci/facade.py",
])
def test_paths_outside_the_exact_predecessor_map_refuse(path: str) -> None:
    with pytest.raises(NamespaceProjectionError, match="product path"):
        project_source_bytes(path, b"import repomap_kg\n")


@pytest.mark.parametrize("data,reason", [
    (b"import os\n\nVALUE = '\xff'\n", "valid UTF-8"),
    (b"# -*- coding: latin-1 -*-\nimport repomap_kg\n", "plain UTF-8"),
    (b"\xef\xbb\xbfimport repomap_kg\n", "plain UTF-8"),
    (b"import os\rimport repomap_kg\n", "carriage return"),
    (b"VALUE = 'unterminated\n", "tokenize"),
    (b"def broken(:\n    pass\n", "tokenize"),
    (b"import repomap_kg\x00\n", "tokenize"),
])
def test_invalid_encoding_or_token_stream_refuses(data: bytes, reason: str) -> None:
    with pytest.raises(NamespaceProjectionError, match=reason):
        project_source_bytes(MODULE, data)


@pytest.mark.parametrize("data", ["import repomap_kg\n", bytearray(b"import repomap_kg\n"), None])
def test_non_bytes_payload_refuses(data: bytes) -> None:
    with pytest.raises(NamespaceProjectionError, match="not bytes"):
        project_source_bytes(MODULE, data)


@pytest.mark.parametrize("source,reason", [
    ('VALUE = "\\trepomap_kg"\n', "escape"),
    ('VALUE = "\\x72epomap_kg.cli"\n', "escape"),
    ('VALUE = f"\\nrepomap_kg.{1}"\n', "formatted string"),
    ("import common_lore_index\n", "successor root"),
    ('VALUE = "common_lore_index"\n', "successor root"),
])
def test_hidden_spellings_and_mixed_roots_refuse(source: str, reason: str) -> None:
    with pytest.raises(NamespaceProjectionError, match=reason):
        project(MODULE, source)


def test_existing_docker_fstring_escapes_preserve_decoded_namespace_meaning() -> None:
    source = r'''VALUE = f"""RUN echo \
  repomap_kg {1}
ENTRYPOINT [\"python\", \"-m\", \"repomap_kg\"]
"""
'''
    assert project(MODULE, source) == source.replace("repomap_kg", "common_lore_index")


@pytest.mark.parametrize("formatted", [False, True])
def test_postgresql_historical_capture_predicate_stays_byte_identical(formatted: bool) -> None:
    import json
    literal = "OR payload_json->>'path' LIKE '%repomap_kg%')), "
    source = ("QUERY = (f\"SELECT {1} \" " + json.dumps(literal) + ")\n" if formatted
              else "QUERY = " + json.dumps(literal) + "\n")
    assert project(OLD_PREFIX + "storage/sql_summaries_python.py", source) == source
