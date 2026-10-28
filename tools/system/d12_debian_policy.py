"""ADR0105: inherited Debian diagnostics do not excuse changes made by RepoMap."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any

from repomap_test_support.d12_complete_inventory import SCHEMA


class DebianDeltaError(ValueError):
    """The assembly differs from its admitted supplier inputs without provenance."""


def _need(condition: object, message: str) -> None:
    if not condition:
        raise DebianDeltaError(message)


def _rows(inventory: Mapping[str, Any], key: str) -> list[Any]:
    rows = inventory.get(key)
    if not isinstance(rows, list):
        raise DebianDeltaError(f"missing complete {key} evidence")
    return rows


def _identities(rows: list[Any]) -> set[str]:
    return {json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows}


def assess_debian_delta(
    candidate: Mapping[str, Any], server: Mapping[str, Any],
    stage_hashes: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Compare actual candidate bytes with actual pinned bases, never a directory-name inference.

    Complete collector validation precedes this assessment. Debian's own missing
    files, checksum diagnostics and findings are retained as information. New
    assembly damage, unresolved libraries or foreign payload still refuse.
    """
    _need(candidate.get("schema") == server.get("schema") == SCHEMA, "complete inventories are required")
    _need(candidate.get("os") == server.get("os") and candidate.get("os") in (
          ["Debian GNU/Linux 13 (trixie)", "x86_64", "amd64"],
          ["Debian GNU/Linux 13 (trixie)", "aarch64", "arm64"]), "native stable Debian identity differs")
    for key in ("packages", "source_packages"):
        observed, inherited = _identities(_rows(candidate, key)), _identities(_rows(server, key))
        _need(observed == inherited,
              f"candidate {key} changed outside the frozen closure")
    _need(candidate.get("dpkg_configs") == server.get("dpkg_configs"), "candidate dpkg configuration changed")
    _need(candidate.get("path_filters") == server.get("path_filters"), "candidate dpkg exclusions changed")
    candidate_verify, base_verify = candidate.get("package_verification"), server.get("package_verification")
    if not isinstance(candidate_verify, Mapping) or not isinstance(base_verify, Mapping):
        raise DebianDeltaError("verification evidence missing")
    candidate_rows, base_rows = _rows(candidate_verify, "rows"), _rows(base_verify, "rows")
    _need(candidate_verify.get("count") == len(candidate_rows) and base_verify.get("count") == len(base_rows),
          "verification count mismatch")
    _need(_identities(candidate_rows) <= _identities(base_rows), "RepoMap introduced a package verification problem")
    by_package = {row["package"]: row for row in _rows(candidate_verify, "checks")}
    for row in _rows(base_verify, "checks"):
        actual = by_package.get(row["package"])
        _need(actual is not None and actual.get("md5sums_sha256") == row.get("md5sums_sha256"),
              "candidate changed an inherited package checksum database")
    _need(set(_rows(candidate, "unowned_usr_lib")) <= set(_rows(server, "unowned_usr_lib")),
          "RepoMap introduced an unowned system library")
    _need(all(isinstance(link, list) and len(link) == 3 and str(link[2]).startswith("/")
              for link in _rows(candidate, "links")), "candidate has an unresolved runtime library")
    def missing_identity(row):
        return {key: value for key, value in row.items() if key != "stage"}
    inherited_missing = _identities([missing_identity(row) for row in _rows(server, "files")
                                    if row.get("kind") == "missing"])
    missing, verified = 0, 0
    for row in _rows(candidate, "files"):
        if row.get("kind") == "missing":
            _need(row.get("role") == "invoked" and _identities([missing_identity(row)]) <= inherited_missing,
                  "RepoMap introduced a missing runtime file")
            missing += 1
            continue
        digest = row.get("sha256")
        _need(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "runtime byte digest missing")
        _need(any(values.get(row.get("resolved")) == digest for values in stage_hashes.values()),
              "runtime bytes are not attributable to the pinned supplier images")
        verified += 1
    _need(verified > 0, "no runtime files were verified")
    return {"policy": "ADR0105", "upstream_debian_findings_blocking": False,
            "inherited_verification_rows": len(candidate_rows), "inherited_missing_observations": missing,
            "runtime_files_verified": verified, "assembly_delta_verified": True}
