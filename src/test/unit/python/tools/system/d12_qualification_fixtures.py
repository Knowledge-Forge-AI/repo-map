"""Synthetic D12 runtime observations; never native qualification evidence."""
from __future__ import annotations

from typing import Any
from repomap_kg.runtime.release import POSTGRES_RELEASE_VERSION, PYTHON_RELEASE_VERSION, PSYCOPG_RELEASE_VERSION
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST
from repomap_test_support.d12_image_probes import SERVER, CLIENTS, NOTICES

LIBC = "/usr/lib/x86_64-linux-gnu/libc.so.6"

def _valid_packaging_report() -> dict[str, Any]:
    pg_ver = f"postgres (PostgreSQL) {POSTGRES_RELEASE_VERSION}"
    return {
        "python": PYTHON_RELEASE_VERSION, "psycopg": PSYCOPG_RELEASE_VERSION, "implementation": "c",
        "libpq": D12_CANDIDATE_LIBPQ_VERSION, "has_cancel_safe": True, "pip_absent": True,
        "setuptools_absent": True, "ensurepip_absent": True, "go_absent": True, "migrations": [1, 1],
        "go_helper_protocol": "1", "bundled_libpq": [], "versions": {p: pg_ver for p in (SERVER, *CLIENTS)},
    }


def _valid_linkage_report() -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    return {
        "psycopg": PSYCOPG_RELEASE_VERSION, "psycopg_c": PSYCOPG_RELEASE_VERSION, "implementation": "c",
        "libpq_runtime": D12_CANDIDATE_LIBPQ_VERSION, "libpq_build": D12_CANDIDATE_LIBPQ_VERSION,
        "has_cancel_safe": True, "psycopg_impl_env": None, "binary_module": False, "binary_distribution": False,
        "extensions": [{
            "path": "/usr/local/lib/python3.12/site-packages/psycopg_c/pq.so", "sha256": "1" * 64,
            "needed": ["libpq.so.5", "libc.so.6"], "libpq_undefined": ["PQlibVersion"],
            "libpq_defined": [], "prefix_defined_not_libpq": [],
        }],
        "loaded_libpq": [{
            "mapped": pkg.libpq_path, "real_path": pkg.libpq_path, "sha256": pkg.libpq_sha256,
            "owner": "libpq5", "owner_version": pkg.libpq5_version, "verify_lines": 0,
            "verify_problems": [], "verify_names_library": False, "verify_returncode": 0, "verify_stderr": "",
        }],
        "usr_local_libpq": [],
    }


def _valid_inventory() -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    return {
        "files": [{
            "role": "libpq", "invoked": pkg.libpq_path, "resolved": pkg.libpq_path, "kind": "elf",
            "sha256": pkg.libpq_sha256, "interpreter": "-", "owner": "libpq5", "md5": "match",
        }, {"role": "library", "invoked": "/lib/x86_64-linux-gnu/libc.so.6", "resolved": LIBC, "kind": "elf",
            "sha256": "e" * 64, "interpreter": "-", "owner": "libc6", "md5": "match"}],
        "links": [[SERVER, "libc.so.6", "/lib/x86_64-linux-gnu/libc.so.6"]],
        "packages": [["libpq5", pkg.libpq5_version, "amd64"], ["libssl3t64", "3.5.7-1~deb13u3", "amd64"],
                     ["libc6", "2.41-12+deb13u4", "amd64"], ["libc-bin", "2.41-12+deb13u4", "amd64"]],
        "verify_mismatches": [], "verify_count": 0, "unowned_usr_lib": [], "unowned_count": 0,
        "notices": {path: "c" * 64 for path in NOTICES}, "os": ["Debian GNU/Linux 13 (trixie)", "x86_64", "amd64"],
    }


def _valid_round_trip() -> dict[str, Any]:
    obs = {
        "server_version": f"{POSTGRES_RELEASE_VERSION} (Debian {POSTGRES_RELEASE_VERSION}-1.pgdg13+1)",
        "fixture_rows": 2000, "fixture_md5": "0123456789abcdef0123456789abcdef",
        "graph_schema": "CURRENT", "extensions": ["plpgsql"], "replication_slots": 0,
        "index_access_methods": ["btree"],
    }
    return {
        "archive_sha256_before": "a" * 64, "archive_sha256_after": "a" * 64,
        "source": dict(obs), "restored": dict(obs),
    }
