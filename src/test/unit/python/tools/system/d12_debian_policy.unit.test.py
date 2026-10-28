"""Debian findings are informational; RepoMap assembly defects still refuse."""

from __future__ import annotations

import copy

import pytest

from tools.system.d12_debian_policy import DebianDeltaError, assess_debian_delta


def inventories():
    base = {
        "schema": "repomap-d12-complete-inventory-v2",
        "os": ["Debian GNU/Linux 13 (trixie)", "x86_64", "amd64"],
        "packages": [["libc6", "2.41-12+deb13u4", "amd64"]],
        "source_packages": [["libc6", "glibc", "2.41-12+deb13u4"]],
        "files": [{"role": "library", "invoked": "/lib/libc.so.6", "resolved": "/usr/lib/libc.so.6",
                   "kind": "elf", "sha256": "a" * 64, "owner": "libc6", "md5": "match"}],
        "links": [["/usr/bin/tool", "libc.so.6", "/lib/libc.so.6"]],
        "package_verification": {"count": 1, "rows": [{"package": "libc6", "status": "missing",
            "conffile": False, "path": "/usr/share/doc/libc6/NEWS", "raw": "missing /usr/share/doc/libc6/NEWS"}],
            "checks": [{"package": "libc6", "md5sums_sha256": "b" * 64}]},
        "unowned_usr_lib": [], "dpkg_configs": {"/etc/dpkg/dpkg.cfg": "c" * 64}, "path_filters": [],
    }
    return copy.deepcopy(base), base, {"postgres": {"/usr/lib/libc.so.6": "a" * 64}, "python": {}}


def test_inherited_debian_findings_and_slim_omissions_are_informational():
    candidate, base, stages = inventories()
    for data in (candidate, base):
        data["findings"] = [{"class": "affected", "severity": "critical"}, {"class": "unknown"}]
    result = assess_debian_delta(candidate, base, stages)
    assert result["policy"] == "ADR0105"
    assert result["upstream_debian_findings_blocking"] is False
    assert result["inherited_verification_rows"] == 1
    assert result["runtime_files_verified"] == 1


@pytest.mark.parametrize("change", ["changed_bytes", "introduced_missing", "unresolved_link", "new_dpkg_problem",
    "changed_checksum_database", "new_unowned_library", "changed_package", "foreign_source", "incomplete"])
def test_product_delta_or_incomplete_evidence_refuses(change):
    candidate, base, stages = inventories()
    if change == "changed_bytes":
        candidate["files"][0]["sha256"] = "c" * 64
    elif change == "introduced_missing":
        candidate["files"][0]["kind"] = "missing"
    elif change == "unresolved_link":
        candidate["links"][0][-1] = "not"
    elif change == "new_dpkg_problem":
        candidate["package_verification"]["rows"][0]["path"] = "/usr/lib/libc.so.6"
    elif change == "changed_checksum_database":
        candidate["package_verification"]["checks"][0]["md5sums_sha256"] = "c" * 64
    elif change == "new_unowned_library":
        candidate["unowned_usr_lib"] = ["/usr/lib/libforeign.so"]
    elif change == "changed_package":
        candidate["packages"][0][1] = "999"
    elif change == "foreign_source":
        candidate["source_packages"][0][1] = "foreign"
    elif change == "incomplete":
        del candidate["schema"]
    with pytest.raises(DebianDeltaError):
        assess_debian_delta(candidate, base, stages)


def test_inherited_absent_optional_command_is_recorded_but_missing_dependency_refuses():
    candidate, base, stages = inventories()
    absent = {"role": "invoked", "invoked": "/usr/bin/optional", "resolved": "-", "kind": "missing",
              "sha256": "-", "owner": "-", "md5": "-"}
    candidate["files"].append(absent)
    base["files"].append(copy.deepcopy(absent))
    assert assess_debian_delta(candidate, base, stages)["inherited_missing_observations"] == 1
    candidate["files"][-1]["role"] = "library"
    with pytest.raises(DebianDeltaError):
        assess_debian_delta(candidate, base, stages)


def test_path_prefix_or_pip_stage_label_does_not_establish_provenance():
    candidate, base, stages = inventories()
    candidate["files"][0].update(resolved="/usr/local/lib/python3.12/site-packages/foreign.so",
                                  stage="python-runtime-pip")
    with pytest.raises(DebianDeltaError):
        assess_debian_delta(candidate, base, stages)
