"""Public-safe SQLite Local home and publication fixtures (REPOMAP-PRODUCT3-SQLITE-LOCAL1).

Homes declare ``[storage] backend = "sqlite"`` and carry no PostgreSQL,
runtime, credential or service settings. Publication inputs reuse the
maintained seven-family portable bundle fixtures; nothing here opens a
PostgreSQL connection.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from repomap_kg.artifacts.bundle import PublicationBundle
from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.sqlite_local.publisher import LocalPublication
from repomap_kg.storage.sqlite_local.schema import LocalGraphBinding
from repomap_test_support.portable_publication_fixtures import (
    _authority,
    _binding,
    _seven_family_bundle,
)

SERVICE_TOML = '[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
MEMORY_TOML = '[server_memory]\nenabled = false\npath = "./server-memory"\nmode = "read_only"\n'
SHELL_LIB = "helper() {\n  echo ready\n}\n"
# Two ``source`` lines give one ``sources`` edge two evidence rows (evidence paging).
SHELL_MAIN = "#!/usr/bin/env bash\nsource ./lib.sh\nsource ./lib.sh\nmain() {\n  helper\n}\nmain \"$@\"\n"


def graph_toml(
    graph_id: str,
    root: Path | str,
    *,
    enabled: bool = True,
    visible: bool = True,
    privacy: str = "public-dev",
    extra: str = "",
) -> str:
    return (
        f'[[graphs]]\nid = "{graph_id}"\nname = "{graph_id}"\nroot_path = "{root}"\n'
        f'repository_name = "{graph_id}"\nprivacy = "{privacy}"\n'
        f"enabled = {str(enabled).lower()}\nmcp_visible = {str(visible).lower()}\n"
        f'extractor_profile = "default"\nrefresh_policy = "manual"\n{extra}'
    )


def multi_graph_toml(graph_id: str, bindings: Sequence[tuple[str, Path | str]]) -> str:
    text = (
        f'[[graphs]]\nid = "{graph_id}"\nname = "{graph_id}"\nenabled = true\n'
        'mcp_visible = true\nrefresh_policy = "manual"\n'
    )
    for alias, root in bindings:
        text += (
            f'[[graphs.source_bindings]]\nschema_version = 1\nsource_definition_id = "src1:{alias}"\n'
            f'alias = "{alias}"\nrevision = 1\nkind = "folder"\nroot_path = "{root}"\n'
            f'repository_name = "{alias}"\nlogical_root = "{alias}"\nprivacy = "public-dev"\n'
            'evidence_retention = "inherit"\nextractor_profile = "default"\n'
            'resolution_policy = "isolated"\nrole = "source"\nenabled = true\n'
        )
    return text


def sqlite_home_toml(graphs: str, *, storage: str = '[storage]\nbackend = "sqlite"\n') -> str:
    return f"schema_version = 1\n{storage}{SERVICE_TOML}{graphs}{MEMORY_TOML}"


def write_sqlite_home(home: Path, graphs: str, *, name: str = "repomap.rp.toml") -> Path:
    home.mkdir(parents=True, exist_ok=True)
    (home / name).write_text(sqlite_home_toml(graphs), encoding="utf-8")
    return home


def write_shell_source(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "lib.sh").write_text(SHELL_LIB, encoding="utf-8")
    (root / "run.sh").write_text(SHELL_MAIN, encoding="utf-8")
    return root


def local_binding(graph_id: str = "portable-fixture") -> LocalGraphBinding:
    return LocalGraphBinding(graph_id, f"repo1:{graph_id}", f"graph:{graph_id}")


def publication_for(
    bundle: PublicationBundle, graph_id: str = "portable-fixture"
) -> LocalPublication:
    authority = _authority(bundle)
    return LocalPublication(
        binding=local_binding(graph_id),
        repository_name=graph_id,
        receipt=RunPublicationReceipt(
            authority.receipt().attempt,
            authority.receipt().generations,
            _binding(bundle, authority),
        ).validate(),
        privacy=bundle.privacy.value,
    )


def generation_bundle(generation: int) -> PublicationBundle:
    """Distinct public-safe generations sharing ``pkg/init.py``-style shapes."""
    names = {1: ("pkg/init.py", "pkg.init", "init_fn"), 2: ("pkg/worker.py", "pkg.worker", "work_fn")}
    file_path, module_name, function_name = names[generation]
    return _seven_family_bundle(
        job_id=f"job-sqlite-{generation}",
        file_path=file_path,
        module_name=module_name,
        function_name=function_name,
    )


__all__ = (
    "MEMORY_TOML",
    "SERVICE_TOML",
    "SHELL_LIB",
    "SHELL_MAIN",
    "generation_bundle",
    "graph_toml",
    "local_binding",
    "multi_graph_toml",
    "publication_for",
    "sqlite_home_toml",
    "write_shell_source",
    "write_sqlite_home",
)
