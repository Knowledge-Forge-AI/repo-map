"""ADR 0089 D2 linkage reading and refusal rules on synthetic ELF objects."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from repomap_test_support import d12_dynamic_linkage as linkage
from repomap_test_support import resource_test_image_commands as materializer


def _elf(needed, undefined, defined, *, wide=True, little=True) -> bytes:
    """Build a minimal ELF with .dynstr, .dynsym and .dynamic sections."""
    order = "<" if little else ">"
    names = [*needed, *undefined, *defined]
    strtab, offsets = b"\0", {}
    for name in names:
        offsets[name] = len(strtab)
        strtab += name.encode() + b"\0"
    sym_format, dyn_format = ("IBBHQQ", "qQ") if wide else ("IIIBBH", "iI")
    symbols = struct.pack(order + sym_format, *([0] * 6))
    for name, index in [*((n, 0) for n in undefined), *((n, 7) for n in defined)]:
        fields = (offsets[name], 0x12, 0, index, 0, 0) if wide else (offsets[name], 0, 0, 0x12, 0, index)
        symbols += struct.pack(order + sym_format, *fields)
    dynamic = b"".join(struct.pack(order + dyn_format, 1, offsets[n]) for n in needed)
    dynamic += struct.pack(order + dyn_format, 0, 0)
    header_size = 64 if wide else 52
    bodies = [strtab, symbols, dynamic]
    starts, cursor = [], header_size
    for body in bodies:
        starts.append(cursor)
        cursor += len(body)
    section_format = "IIQQQQIIQQ" if wide else "IIIIIIIIII"
    sections = struct.pack(order + section_format, *([0] * 10))
    for kind, start, body, link in ((3, starts[0], strtab, 0), (11, starts[1], symbols, 1),
                                    (6, starts[2], dynamic, 1)):
        sections += struct.pack(order + section_format, 0, kind, 0, 0, start, len(body), link, 0, 0, 0)
    ident = b"\x7fELF" + bytes([2 if wide else 1, 1 if little else 2, 1]) + b"\0" * 9
    header = bytearray(ident + b"\0" * (header_size - 16))
    if wide:
        struct.pack_into(order + "Q", header, 0x28, cursor)
        struct.pack_into(order + "HH", header, 0x3A, struct.calcsize(order + section_format), 4)
    else:
        struct.pack_into(order + "I", header, 0x20, cursor)
        struct.pack_into(order + "HH", header, 0x2E, struct.calcsize(order + section_format), 4)
    return bytes(header) + b"".join(bodies) + sections


@pytest.mark.parametrize("wide,little", [(True, True), (True, False), (False, True), (False, False)])
def test_elf_reader_returns_needed_and_split_dynamic_symbols(wide, little):
    data = _elf(["libpq.so.5", "libc.so.6"], ["PQconnectdb", "malloc"], ["PyInit_pq"], wide=wide, little=little)
    elf = linkage.elf_dynamic(data)
    assert elf.needed == ("libpq.so.5", "libc.so.6"), elf
    assert elf.undefined == ("PQconnectdb", "malloc"), elf
    assert elf.defined == ("PyInit_pq",), elf


def test_elf_reader_refuses_non_elf_bytes():
    with pytest.raises(ValueError, match="not a supported ELF"):
        linkage.elf_dynamic(b"\xcf\xfa\xed\xfe" + b"\0" * 60)


EXPORTS = frozenset({"PQconnectdb", "lo_open", "pg_char_to_encoding", "PQlibVersion"})


def _report(**changes):
    extension = linkage.extension_linkage(
        "/usr/local/lib/python3.12/site-packages/psycopg_c/pq.so",
        _elf(["libpq.so.5"], ["PQconnectdb", "lo_open", "pg_char_to_encoding", "malloc"],
             ["PyInit_pq", "pg_lltoa"]), EXPORTS)
    report = {
        "psycopg": "3.3.6", "psycopg_c": "3.3.6", "implementation": "c", "psycopg_impl_env": None,
        "libpq_runtime": 150014, "libpq_build": 150014, "binary_module": False, "binary_distribution": False,
        "has_cancel_safe": False,
        "usr_local_libpq": [], "extensions": [extension],
        "loaded_libpq": [{"mapped": "/usr/lib/aarch64-linux-gnu/libpq.so.5.15",
                          "real_path": "/usr/lib/aarch64-linux-gnu/libpq.so.5.15", "sha256": "0" * 64,
                          "owner": "libpq5", "owner_version": "15.14-0+deb12u1", "verify_lines": 2,
                          "verify_problems": [], "verify_names_library": False,
                          "verify_returncode": 1, "verify_stderr": ""}],
    }
    report.update(changes)
    return report


def test_complete_dynamic_report_has_no_refusal():
    report = _report()
    assert report["extensions"][0]["libpq_undefined"] == ["PQconnectdb", "lo_open", "pg_char_to_encoding"]
    # psycopg-c's own PostgreSQL-derived helper is not a libpq export, so it is reported, not refused.
    assert report["extensions"][0]["prefix_defined_not_libpq"] == ["pg_lltoa"], report["extensions"][0]
    assert linkage.assess(report, psycopg_version="3.3.6") == []
    assert linkage.assess(report, psycopg_version="3.3.6", libpq_version=150014) == []


@pytest.mark.parametrize("changes,expected", [
    ({"implementation": "python"}, "implementation is not c"),
    ({"psycopg_impl_env": "c"}, "implementation is not c"),
    ({"libpq_build": 170006}, "differs from build headers"),
    ({"binary_distribution": True}, "psycopg-binary is present"),
    ({"usr_local_libpq": ["/usr/local/lib/libpq.so.5"]}, "private libpq"),
    ({"psycopg_c": "3.2.12"}, "version differs"),
    ({"loaded_libpq": []}, "exactly one mapped libpq"),
])
def test_each_unmet_condition_refuses(changes, expected):
    failures = linkage.assess(_report(**changes), psycopg_version="3.3.6")
    assert any(expected in failure for failure in failures), failures


def test_static_or_unlinked_libpq_and_unowned_load_refuse():
    static = linkage.extension_linkage("/x/pq.so", _elf(["libc.so.6"], ["malloc"], ["PQconnectdb"]), EXPORTS)
    failures = linkage.assess(_report(extensions=[static]), psycopg_version="3.3.6")
    assert any("lacks DT_NEEDED libpq.so.5" in f for f in failures), failures
    assert any("defines libpq symbols locally" in f for f in failures), failures
    unrelated = linkage.extension_linkage("/x/other.so", _elf(["libc.so.6"], ["malloc", "pg_x"], []), EXPORTS)
    assert any("no psycopg-c ELF references" in f
               for f in linkage.assess(_report(extensions=[unrelated]), psycopg_version="3.3.6"))
    for change in ({"verify_problems": ["??5?????? c /etc/x"]}, {"verify_names_library": True}, {"owner": "libpq-dev"}):
        loaded = dict(_report()["loaded_libpq"][0], **change)
        failures = linkage.assess(_report(loaded_libpq=[loaded]), psycopg_version="3.3.6")
        assert any("not a verified libpq5 file" in f for f in failures), (change, failures)
    assert any("frozen 160000" in f for f in linkage.assess(_report(), psycopg_version="3.3.6",
                                                             libpq_version=160000))


@pytest.mark.parametrize("change", [
    {"verify_returncode": 2}, {"verify_returncode": None}, {"verify_returncode": 0, "verify_stderr": "dpkg: error"},
    {"verify_returncode": 1, "verify_lines": 0},
])
def test_dpkg_verify_that_did_not_complete_refuses(change):
    loaded = dict(_report()["loaded_libpq"][0], **change)
    failures = linkage.assess(_report(loaded_libpq=[loaded]), psycopg_version="3.3.6")
    assert any("did not complete" in failure for failure in failures), (change, failures)
    clean = dict(_report()["loaded_libpq"][0], verify_returncode=0, verify_lines=0)
    assert linkage.assess(_report(loaded_libpq=[clean]), psycopg_version="3.3.6") == []


def test_probe_source_is_the_stdlib_module_with_its_entry_point():
    source = linkage.probe_source()
    assert source == Path(str(linkage.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(source, "probe")  # static syntax and structure only; the int gate executes the probe
    imported = {alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
    imported |= {str(node.module) for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "fnmatch", "hashlib", "importlib.metadata", "importlib.util", "json", "os", "re",
                        "struct", "subprocess", "sys", "pathlib", "typing"}, imported
    entry = [node for node in tree.body if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test)]
    assert [ast.unparse(node.test) for node in entry] == ["__name__ == '__main__' and sys.argv[1:] == ['probe']"]
    calls = {ast.unparse(node.func) for node in ast.walk(entry[0]) if isinstance(node, ast.Call)}
    assert {"probe", "print"} <= calls, calls


def test_private_libpq_check_names_libraries_not_cython_declarations():
    assert linkage.LIBRARY_FILE.search("libpq.so.5.15") and linkage.LIBRARY_FILE.search("libpq.a")
    assert not linkage.LIBRARY_FILE.search("libpq.pxd")


def test_dpkg_verify_ignores_only_files_the_image_filters_never_installed(tmp_path):
    (tmp_path / "docker").write_text("path-exclude /usr/share/doc/*\npath-include /usr/share/doc/*/copyright\n"
                                     "path-exclude /usr/share/locale/*\n")
    rules = linkage.dpkg_filters(tmp_path)
    lines = ["missing     /usr/share/doc/libpq5/changelog.Debian.gz", "missing     /usr/share/locale/de/x.mo",
             "missing     /usr/share/doc/libpq5/copyright", "??5??????   /usr/lib/aarch64-linux-gnu/libpq.so.5.15",
             "missing     /usr/lib/aarch64-linux-gnu/libpq.so.5"]
    assert linkage.verify_problems(lines, rules) == lines[2:], linkage.verify_problems(lines, rules)
    assert linkage.dpkg_filters(tmp_path / "absent") == []


def test_materializer_records_stay_whole_lines_when_a_later_child_shares_stdout():
    """The int owner parses each record line strictly (ADR 0089 framing)."""
    records = [line for line in materializer._INSTALL_AND_PROBE.splitlines() if line.startswith('print("REPOMAP_')]
    prefixes = [line.split('"')[1] for line in records]
    assert prefixes == ["REPOMAP_APT_PREREQUISITES=", "REPOMAP_DEPENDENCY_VERSIONS="], prefixes
    payload = {"added": ["x" * 40000], "manifest_sha256": "0" * 64}
    # Over the write buffer, then a child writes to the same stdout (as pip check does).
    child = "subprocess.run([sys.executable, '-c', 'print(\"No broken requirements found.\")'], check=True)"
    program = "\n".join(["import json, subprocess, sys", f"custody = resolved = {payload!r}",
                         *(f"{record}\n{child}" for record in records)])
    done = subprocess.run([sys.executable, "-I", "-c", program], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    lines = done.stdout.splitlines()
    assert lines[1::2] == ["No broken requirements found."] * 2, [line[-60:] for line in lines]
    for prefix, line in zip(prefixes, lines[0::2], strict=True):
        assert line.startswith(prefix) and json.loads(line.removeprefix(prefix)) == payload, line[-60:]
