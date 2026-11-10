"""Reviewed frozen constants of the installed-experience proof (ADR 0181).

The ``typing-extensions`` digests are the parent-gated offline observation of
the canonical sandbox SDK (``SDK-INSTALLED-DISTRIBUTION-VERIFIED``, image
``sha256:575e0004…``, CPython 3.13.12, setuptools 83.0.0). They were reviewed
before this implementation and are compared byte-for-byte at run time; they are
never learned from a run. A different SDK refuses with ``projection-drift``
(gate G1), never with an automatic replacement or download.
"""

from __future__ import annotations

TE_DISTRIBUTION = "typing-extensions"
TE_VERSION = "4.16.0"
TE_MODULE_SHA256 = "4040ca1a1ecbee00d1385c12a93084d1c5bd46f0b774f07e5ae7e91c4f55e696"
TE_RECORD_SHA256 = "d7a220918ed91a6af1abf9508f734fe5d2c2f6b438ee519cc73ee4e60e6e665d"
TE_PROJECTION_SOURCE_CLASS = "sdk-installed-record"

SANDBOX_PYTHON = "3.13.12"
SANDBOX_IMAGE = "sha256:575e0004d8be9a5a8fa73e3301d1e7033280208b9020c1a3155b5d4866598c42"
SETUPTOOLS_VERSION = "83.0.0"
# Observed in the pinned setuptools/dist.py (line 460) before freezing inventory.
SETUPTOOLS_DEFAULT_LICENSE_PATTERNS: tuple[str, ...] = (
    "LICEN[CS]E*", "COPYING*", "NOTICE*", "AUTHORS*",
)
PIP_VERSION = "25.3"

CANDIDATE_DISTRIBUTION = "common-lore-index"
CANDIDATE_VERSION = "0.0.3"
CANDIDATE_WHEEL_PREFIX = "common_lore_index-0.0.3-"
INCUMBENT_COMMIT = "6d818ad6d43d38d47c64b8c474c2b64b853f631a"
INCUMBENT_DISTRIBUTION = "repomap-kg"
INCUMBENT_WHEEL_PREFIX = "repomap_kg-0.0.3-"
CONSOLE_SCRIPTS: tuple[str, ...] = ("cloe", "common-lore-index", "repomap-kg")
LEGACY_FACADE: tuple[str, ...] = (
    "__init__.py", "__main__.py", "ops/__init__.py", "ops/config_migration.py",
    "server/__init__.py", "server/mcp.py",
)

# Candidate input census roots (cutover rule extended by root NOTICE).
CANDIDATE_INPUT_FILES: tuple[str, ...] = ("README.md", "LICENSE", "NOTICE", "pyproject.toml")
CANDIDATE_INPUT_TREES: tuple[str, ...] = ("src/main/python/", "src/main/resources/")

# Optional families that must be absent from a pure-Local interpreter (section 6).
ABSENT_FAMILIES: tuple[str, ...] = (
    "psycopg", "psycopg_c", "psycopg_binary", "psycopg2", "psycopg_pool", "onnxruntime",
    "numpy", "tree_sitter", "tree_sitter_rust",
)
PSYCOPG_VERSION = "3.3.6"
PSYCOPG_IMPL = "c"
POSTGRES_BIN = "/usr/lib/postgresql/17/bin"

GRAPH_ID = "tiny"
USEFUL_QUESTION = "Where is ledger reconciliation implemented and documented?"
CODE_QUERY = "reconcile_ledger_totals"
DOCS_QUERY = "Ledger reconciliation"
CODE_KIND = "python.function"
CODE_PATH = "tinypkg/ledger.py"
DOCS_PATH = "guide.md"
MESSAGE_PATH = "messages/ledger.eml"

CHILD_DEADLINE_SECONDS = 300
MCP_STDOUT_LIMIT = 2 * 1024 * 1024
MCP_STDERR_LIMIT = 64 * 1024
MCP_REPLY_LIMIT = 64
MESSAGE_SHA256 = "3ee85e5ca8ecc4ab2432cf2e2696c0284a4490f5bc227b1e154d6d271ba56da0"

__all__ = [
    "ABSENT_FAMILIES", "CANDIDATE_DISTRIBUTION", "CANDIDATE_INPUT_FILES", "CANDIDATE_INPUT_TREES",
    "CANDIDATE_VERSION", "CANDIDATE_WHEEL_PREFIX", "CHILD_DEADLINE_SECONDS", "CODE_KIND",
    "CODE_PATH", "CODE_QUERY", "CONSOLE_SCRIPTS", "DOCS_PATH", "DOCS_QUERY", "GRAPH_ID",
    "INCUMBENT_COMMIT", "INCUMBENT_DISTRIBUTION", "INCUMBENT_WHEEL_PREFIX", "LEGACY_FACADE",
    "MCP_REPLY_LIMIT", "MCP_STDERR_LIMIT", "MCP_STDOUT_LIMIT", "MESSAGE_PATH", "MESSAGE_SHA256", "PIP_VERSION",
    "POSTGRES_BIN", "PSYCOPG_IMPL", "PSYCOPG_VERSION", "SANDBOX_IMAGE", "SANDBOX_PYTHON",
    "SETUPTOOLS_DEFAULT_LICENSE_PATTERNS", "SETUPTOOLS_VERSION", "TE_DISTRIBUTION",
    "TE_MODULE_SHA256", "TE_PROJECTION_SOURCE_CLASS", "TE_RECORD_SHA256", "TE_VERSION",
    "USEFUL_QUESTION",
]
