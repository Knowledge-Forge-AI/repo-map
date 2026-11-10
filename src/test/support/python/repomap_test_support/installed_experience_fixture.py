"""Tiny public installed-experience material, homes and source-derived expectations (section 7).

The committed ``tiny-v1`` tree holds a small code package, one guide and one
new, manually reviewed synthetic public ``.eml`` with reserved ``example.org``
identities. Mixed-v1 mailbox bodies are never read, copied or relabelled. Every
binding is ``public-dev`` with ``inherit`` retention. Homes live under
``<tmp>/owned homes/<name>``; the space is intentional.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from common_lore_index.ops.config_layout import plan_cloe_config_filenames
from installed_experience_pins import CODE_PATH, CODE_QUERY, DOCS_PATH, DOCS_QUERY, GRAPH_ID, MESSAGE_PATH, MESSAGE_SHA256
from repomap_test_support.sqlite_local_fixtures import multi_graph_toml, sqlite_home_toml, write_sqlite_home

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "installed_experience" / "tiny-v1"
BINDINGS: tuple[str, ...] = ("code", "docs", "messages")
LEGACY_BASE = "repomap.rp.toml"
LEGACY_LOCAL = "zz-local.rpl.toml"
LEGACY_LOCAL_TEXT = 'schema_version = 1\n\n[storage]\nbackend = "sqlite"\n'
REVIEWED_MESSAGE_HEADERS = {
    "From": "Ledger Notices <notices@example.org>",
    "To": "Ledger Readers <readers@example.org>",
    "Subject": "Public ledger reconciliation note",
}


@dataclass(frozen=True)
class TinyExpectations:
    """Predeclared from the fixture text by the test process, never from a run."""

    code_query: str
    code_path: str
    code_line: int
    docs_query: str
    docs_path: str


def expectations(fixture: Path = FIXTURE_ROOT) -> TinyExpectations:
    lines = (fixture / "code" / CODE_PATH).read_text(encoding="utf-8").splitlines()
    line = next(index for index, text in enumerate(lines, start=1)
                if text.startswith(f"def {CODE_QUERY}("))
    guide = (fixture / "docs" / DOCS_PATH).read_text(encoding="utf-8")
    if f"## {DOCS_QUERY}" not in guide:
        raise AssertionError("tiny guide lost its declared heading")
    return TinyExpectations(CODE_QUERY, CODE_PATH, line, DOCS_QUERY, DOCS_PATH)


def message_is_reviewed_public(fixture: Path = FIXTURE_ROOT) -> bool:
    """The message file is the reviewed synthetic public one, not a mailbox body."""
    text = (fixture / MESSAGE_PATH).read_text(encoding="ascii")
    headers = dict(line.split(": ", 1) for line in text.split("\n\n", 1)[0].splitlines())
    addresses = [value for key, value in headers.items() if key in ("From", "To")]
    return (all(headers.get(key) == value for key, value in REVIEWED_MESSAGE_HEADERS.items())
            and all(value.endswith("@example.org>") for value in addresses))


def write_tiny_material(root: Path, fixture: Path = FIXTURE_ROOT) -> Path:
    """Copy the reviewed fixture into an owned, absent material root."""
    if hashlib.sha256((fixture / MESSAGE_PATH).read_bytes()).hexdigest() != MESSAGE_SHA256:
        raise AssertionError("installed-message-fixture-unreviewed")
    if root.exists() or root.is_symlink():
        raise AssertionError("tiny material root must be absent")
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copytree(fixture, root, symlinks=False)
    return root


def tiny_graphs(material: Path) -> str:
    return multi_graph_toml(GRAPH_ID, [(alias, material / alias) for alias in BINDINGS])


def current_config_name() -> str:
    """The CLOE base name the product's own planner assigns, computed before any child."""
    plan = plan_cloe_config_filenames([LEGACY_BASE], occupied_names=[LEGACY_BASE])
    return str(plan["changes"][0]["target"])


def _private(home: Path) -> Path:
    os.chmod(home, 0o700)
    for child in home.iterdir():
        if child.is_file() and not child.is_symlink():
            os.chmod(child, 0o600)
    return home


def tiny_home(home: Path, material: Path, *, config_name: str) -> Path:
    """One owner-private SQLite home over the tiny bindings."""
    return _private(write_sqlite_home(home, tiny_graphs(material), name=config_name))


def legacy_tiny_home(home: Path, material: Path) -> Path:
    """``repomap.rp.toml`` plus a same-backend ``zz-local.rpl.toml`` overlay."""
    tiny_home(home, material, config_name=LEGACY_BASE)
    (home / LEGACY_LOCAL).write_text(LEGACY_LOCAL_TEXT, encoding="utf-8")
    return _private(home)


def driverless_postgres_home(home: Path, material: Path) -> Path:
    """A PostgreSQL home for the driver-absent refusal; it is never connected."""
    storage = ('[storage]\nbackend = "postgresql"\n\n[postgres]\nhost = "127.0.0.1"\nport = 9\n'
               'database = "unused"\nuser = "unused"\n')
    home.mkdir(mode=0o700, parents=True)
    (home / current_config_name()).write_text(sqlite_home_toml(tiny_graphs(material), storage=storage),
                                              encoding="utf-8")
    return _private(home)


def provisioned_postgres_home(
    home: Path, material: Path, *, host: str, port: int, database: str, user: str,
    password: str | None,
) -> Path:
    """A private PostgreSQL home addressing the parent-owned temporary cluster."""
    home.mkdir(mode=0o700, parents=True)
    password_line = ""
    if password is not None:
        secret = home / "pgpass.secret"
        secret.write_text(password, encoding="utf-8")
        os.chmod(secret, 0o600)
        password_line = f'password_file = "{secret.resolve().as_posix()}"\n'
    graphs = tiny_graphs(material).replace(
        "enabled = true\nmcp_visible = true\n", f'database = "{database}"\nenabled = true\nmcp_visible = true\n', 1)
    text = (
        'schema_version = 1\n\n[storage]\nbackend = "postgresql"\n\n'
        '[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n\n'
        f'[postgres]\nhost = "{host}"\nport = {port}\ndatabase = "{database}"\nuser = "{user}"\n'
        f"{password_line}\n"
        '[runtime]\ncoordinator_mode = "native"\nbind_host = "127.0.0.1"\n\n'
        f'[runtime.postgres]\ndirect_host_port_enabled = true\nhost_port = {port}\nbind_host = "{host}"\n\n'
        '[server_memory]\nenabled = false\npath = "./server-memory"\nmode = "read_only"\n\n'
        f"{graphs}"
    )
    (home / current_config_name()).write_text(text, encoding="utf-8")
    return _private(home)


__all__ = [
    "BINDINGS", "FIXTURE_ROOT", "LEGACY_BASE", "LEGACY_LOCAL", "TinyExpectations",
    "current_config_name", "driverless_postgres_home", "expectations", "legacy_tiny_home",
    "message_is_reviewed_public", "provisioned_postgres_home", "tiny_graphs", "tiny_home",
    "write_tiny_material",
]
