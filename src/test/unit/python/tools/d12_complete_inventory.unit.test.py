"""ADR0104 preserves complete package evidence and refuses ambiguous observations."""

from __future__ import annotations

import subprocess

import pytest

from repomap_test_support import d12_image_probes as legacy
from repomap_test_support.d12_complete_inventory import (
    D12InventoryError,
    MAX_SECTION_ROWS,
    MD5_LOOKUP_AWK,
    REQUESTED_PATHS,
    SCHEMA,
    complete_inventory,
    complete_inventory_script,
    parse_complete_inventory,
)


def metadata(package: str = "libexample1") -> str:
    return f"M\t{package}\t0\t" + "a" * 64 + "\t" + "b" * 64 + "\t0\tinstalled"


def observation(count: int = 0) -> str:
    return "\n".join([
        "P\tlibexample1\t1.2-3\tamd64", "S\tlibexample1\texample\t1.2-3", metadata(),
        *[f"F\tinvoked\t{p}\t{p}\telf\t" + "c" * 64 + "\t-\tlibexample1\tmatch" for p in REQUESTED_PATHS],
        "F\tlibrary\t/usr/lib/libexample.so\t/usr/lib/libexample.so\telf\t" + "d" * 64 + "\t-\tlibexample1\tmatch",
        "L\t/usr/local/bin/python3\tlibexample.so\t/usr/lib/libexample.so",
        f"FC\t{len(REQUESTED_PATHS) + 1}", "LC\t1", "MP\t0", "MC\t0", "QC\t0",
        f"VC\t{count}", *[f"V\tlibexample1\tmissing    /usr/share/doc/example/{n}" for n in range(count)],
        "UC\t1", "U\t/usr/lib/generated-file",
        "O\tDebian GNU/Linux 13 (trixie)\tx86_64\tamd64",
        "D\t/etc/dpkg/dpkg.cfg.d/excludes\t" + "a" * 64,
        "X\t/etc/dpkg/dpkg.cfg.d/excludes\tpath-exclude=/usr/share/doc/*",
        *[f"C\t{path}\t" + "b" * 64 for path in legacy.NOTICES],
        "END\t" + SCHEMA,
    ])


def test_more_than_the_old_1500_rows_are_retained_with_source_and_verification_coverage() -> None:
    inventory = parse_complete_inventory(observation(3559))
    verification = inventory["package_verification"]
    assert inventory["schema"] == SCHEMA
    assert verification["count"] == len(verification["rows"]) == 3559
    assert verification["rows"][-1]["path"] == "/usr/share/doc/example/3558"
    assert verification["checks"][0]["package"] == "libexample1"
    assert inventory["source_packages"] == [["libexample1", "example", "1.2-3"]]
    assert inventory["unowned_usr_lib"] == ["/usr/lib/generated-file"]
    assert set(inventory["notices"]) == set(legacy.NOTICES)
    assert "verify_mismatches" not in inventory  # no misleading legacy global-verification projection


@pytest.mark.parametrize("old,new,match", [
    ("VC\t1", "VC\t3559", "incomplete V"),
    ("UC\t1", "UC\t2", "incomplete U"),
    ("VC\t1", "VC\t1\nVC\t1", "one exact VC"),
    ("VC\t1", "VC\t-1", "one exact VC"),
    ("S\tlibexample1\texample\t1.2-3", "S\tforeign\texample\t1.2-3", "population"),
    ("S\tlibexample1\texample\t1.2-3", "S\tlibexample1\texample", "malformed"),
    ("D\t/etc/dpkg/dpkg.cfg.d/excludes\t" + "a" * 64,
     "D\t/etc/dpkg/dpkg.cfg.d/excludes\tinvalid", "provenance"),
    ("X\t/etc/dpkg/dpkg.cfg.d/excludes", "X\t/etc/dpkg/foreign", "provenance"),
    ("UC\t1", "UC\t1\nUNKNOWN\tvalue", "unknown"),
    ("P\tlibexample1\t1.2-3\tamd64", "P\tlibexample1\t1.2-3\tamd64\nP\tlibexample1\t1.2-3\tamd64", "duplicate P"),
    (metadata(), "", "verification coverage"),
    (metadata(), metadata() + "\n" + metadata(), "verification coverage"),
    ("\tinstalled", "\tconfig-files", "not installed"),
    ("\t1.2-3\tamd64", "\t1.2-3\tarm64", "foreign package architecture"),
])
def test_incomplete_ambiguous_or_foreign_observations_refuse(old: str, new: str, match: str) -> None:
    with pytest.raises(D12InventoryError, match=match):
        parse_complete_inventory(observation(1).replace(old, new))


@pytest.mark.parametrize("prefix,match", [
    ("F\t", "incomplete F"),
    ("L\t", "incomplete L"),
    ("C\t", "notice observation"),
])
def test_executable_library_and_notice_population_cannot_silently_disappear(prefix: str, match: str) -> None:
    text = "\n".join(line for line in observation().splitlines() if not line.startswith(prefix))
    with pytest.raises(D12InventoryError, match=match):
        parse_complete_inventory(text)


def test_section_bound_refuses_instead_of_truncating() -> None:
    with pytest.raises(D12InventoryError, match="row bound"):
        parse_complete_inventory(observation(MAX_SECTION_ROWS + 1))


def test_shared_paths_retain_distinct_package_owners_and_original_text() -> None:
    text = observation(1).replace("VC\t1", "VC\t2").replace("END\t" + SCHEMA, "") + "\n" + "\n".join([
        "P\tlibexample2\t1.2-3\tamd64", "S\tlibexample2\texample\t1.2-3", metadata("libexample2"),
        "V\tlibexample2\tmissing    /usr/share/doc/example/0",
        "END\t" + SCHEMA,
    ])
    verification = parse_complete_inventory(text)["package_verification"]
    assert verification["count"] == 2
    assert [r["path"] for r in verification["rows"]] == ["/usr/share/doc/example/0"] * 2
    assert [r["package"] for r in verification["rows"]] == ["libexample1", "libexample2"]


@pytest.mark.parametrize("package,match", [("libexample1", "duplicate package"), ("foreign", "unobserved package")])
def test_duplicate_or_foreign_verification_refuses(package: str, match: str) -> None:
    text = observation(1).replace("VC\t1", "VC\t2").replace("END\t" + SCHEMA, "")
    with pytest.raises(D12InventoryError, match=match):
        parse_complete_inventory(text + f"\nV\t{package}\tmissing    /usr/share/doc/example/0\nEND\t" + SCHEMA)


def test_paths_with_spaces_conffile_flags_and_missing_md5_database_remain_explicit() -> None:
    raw = "??5??????\tc /etc/example config"
    text = observation(1).replace("missing    /usr/share/doc/example/0", raw)
    text = text.replace(metadata(), metadata().replace("a" * 64, "absent"))
    result = parse_complete_inventory(text)["package_verification"]
    assert result["rows"] == [{
        "package": "libexample1", "status": "??5??????", "conffile": True,
        "path": "/etc/example config", "raw": raw,
    }]
    assert result["checks"][0]["md5sums_sha256"] == "absent"  # explicit coverage gap, never verified-clean


def test_missing_terminal_record_cannot_be_a_successful_partial_generation() -> None:
    with pytest.raises(D12InventoryError, match="terminal record"):
        parse_complete_inventory(observation().replace("END\t" + SCHEMA, ""))


def test_balanced_counts_cannot_hide_a_loaded_library_without_its_file_evidence() -> None:
    text = "\n".join(line for line in observation().splitlines() if not line.startswith("F\tlibrary\t"))
    text = text.replace(f"FC\t{len(REQUESTED_PATHS) + 1}", f"FC\t{len(REQUESTED_PATHS)}")
    with pytest.raises(D12InventoryError, match="loaded library lacks"):
        parse_complete_inventory(text)


@pytest.mark.parametrize("count_key,path_key,mode", [("QC", "Q", "libpq"), ("MC", "R", "module")])
def test_enumerated_module_or_libpq_cannot_disappear_before_its_file_probe(count_key: str, path_key: str, mode: str) -> None:
    text = observation().replace(f"{count_key}\t0", f"{count_key}\t1\n{path_key}\t/usr/lib/example-{mode}")
    if mode == "module":
        text = text.replace("MP\t0", "MP\t1")
    with pytest.raises(D12InventoryError, match="enumeration and file observations"):
        parse_complete_inventory(text)


def test_module_and_libpq_enumerations_retain_their_complete_positive_observations() -> None:
    module, library = "/usr/share/perl5/PgCommon.pm", "/usr/lib/libpq.so.5"
    text = observation().replace(f"FC\t{len(REQUESTED_PATHS) + 1}", f"FC\t{len(REQUESTED_PATHS) + 3}")
    text = text.replace("MP\t0", "MP\t1").replace("MC\t0", "MC\t1\nR\t" + module)
    text = text.replace("QC\t0", "QC\t1\nQ\t" + library)
    extra = (f"F\tmodule\t{module}\t{module}\tother\t" + "e" * 64 + "\t-\tlibexample1\tmatch\n"
             + f"F\tlibpq\t{library}\t{library}\telf\t" + "f" * 64 + "\t-\tlibexample1\tmatch\n")
    text = text.replace("END\t" + SCHEMA, extra + "END\t" + SCHEMA)
    result = parse_complete_inventory(text)
    assert result["enumerations"] == {"files": len(REQUESTED_PATHS) + 3, "links": 1,
                                      "perl_invoked": True, "modules": [module], "libpq": [library]}


def test_renderer_refuses_legacy_boundary_drift_and_result_is_valid_shell(monkeypatch) -> None:
    subprocess.run(["/bin/sh", "-n"], input=complete_inventory_script(), text=True, check=True)
    monkeypatch.setattr(legacy, "INVENTORY_SH", legacy.INVENTORY_SH.replace("head -n 1500", "head -n 1000"))
    with pytest.raises(D12InventoryError, match="boundary changed"):
        complete_inventory_script()


def test_package_checksum_lookup_uses_literal_complete_paths_including_plus_and_spaces() -> None:
    path = "usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.33"
    spaced = "usr/share/example data/file"
    sums = "\n".join([
        "1" * 32 + "  usr/lib/x86_64-linux-gnu/libstdcc.so.6.0.33",
        "2" * 32 + "  " + path,
        "3" * 32 + "  " + spaced,
    ])
    for name, expected in ((path, "2" * 32), (spaced, "3" * 32)):
        result = subprocess.run(["awk", "-v", "a=" + name, "-v", "b=unused", MD5_LOOKUP_AWK],
                                input=sums, text=True, capture_output=True, check=True)
        assert result.stdout.strip() == expected


def test_complete_probe_uses_one_owned_execution_and_preserves_failure() -> None:
    calls = []

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return observation(2)

    result = complete_inventory(None, None, "sha256:" + "1" * 64, "linux/amd64", "inventory", run_once_fn=execute)
    assert result["package_verification"]["count"] == 2 and len(calls) == 1
    assert calls[0][1]["role"] == "inventory" and calls[0][1]["platform"] == "linux/amd64"

    def failed(*_args, **_kwargs):
        raise RuntimeError("owned cleanup failed")

    with pytest.raises(RuntimeError, match="owned cleanup failed"):
        complete_inventory(None, None, "image", None, "inventory", run_once_fn=failed)
