"""Bounded complete probe records for ADR0104; collection grants no acceptance.

This distinct v2 observation retains package attribution and verification
coverage. An empty dpkg result never asserts verified clean bytes.
"""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from repomap_test_support import d12_image_probes as probes

SCHEMA = "repomap-d12-complete-inventory-v2"
MAX_SECTION_ROWS = 10_000
MAX_OUTPUT_BYTES = 5_000_000
REQUESTED_PATHS = (probes.SERVER, *probes.CLIENTS, "/usr/bin/psql", "/usr/local/bin/python3")
_SHA = re.compile(r"[0-9a-f]{64}")
MD5_LOOKUP_AWK = 'substr($0,35)==a || substr($0,35)==b {print substr($0,1,32); exit}'

_PACKAGE_VERIFY_SH = r""": > /tmp/verify
dpkg-query -W -f='${Package}\n' > /tmp/package-names || exit 93
while IFS= read -r package; do
  dpkg --verify "$package" > /tmp/package-verify 2>/tmp/package-verify-errors; status=$?
  [ "$status" -le 1 ] || exit 91
  arch=$(dpkg-query -W -f='${Architecture}' "$package") || exit 93
  state=$(dpkg-query -W -f='${db:Status-Status}' "$package") || exit 93
  md5=absent; databases=0
  for sums in "/var/lib/dpkg/info/$package.md5sums" "/var/lib/dpkg/info/$package:$arch.md5sums"; do
    [ -f "$sums" ] || continue
    databases=$((databases + 1)); md5=$(sha256sum "$sums" | cut -d' ' -f1)
  done
  [ "$databases" -le 1 ] || exit 93
  printf 'M\t%s\t%s\t%s\t%s\t%s\t%s\n' "$package" "$status" "$md5" \
    "$(sha256sum /tmp/package-verify-errors | cut -d' ' -f1)" \
    "$(wc -c < /tmp/package-verify-errors)" "$state"
  awk -v p="$package" '{print p "\t" $0}' /tmp/package-verify >> /tmp/verify || exit 91
done < /tmp/package-names
printf 'VC\t%s\n' "$(wc -l < /tmp/verify)"
"""

_ENUMERATIONS_SH = r"""
: > /tmp/complete-perl-modules
if grep -q 'perl' /tmp/inv; then
  perl -e 'require PgCommon; print "$_\n" for sort values %INC' > /tmp/complete-perl-modules || exit 96
  printf 'MP\t1\n'
else printf 'MP\t0\n'; fi
printf 'MC\t%s\n' "$(wc -l < /tmp/complete-perl-modules)"
while IFS= read -r module; do
  printf 'R\t%s\n' "$module"; probe module "$module" >> /tmp/inv
done < /tmp/complete-perl-modules
find / -xdev -name 'libpq*.so*' > /tmp/complete-libpq-unsorted 2>/tmp/complete-find-errors || exit 97
sort /tmp/complete-libpq-unsorted > /tmp/complete-libpq || exit 97
printf 'QC\t%s\n' "$(wc -l < /tmp/complete-libpq)"
while IFS= read -r library; do
  printf 'Q\t%s\n' "$library"; probe libpq "$library" >> /tmp/inv
done < /tmp/complete-libpq
printf 'FC\t%s\n' "$(grep -c '^F' /tmp/inv)"
printf 'LC\t%s\n' "$(grep -c '^L' /tmp/inv)"
"""


class D12InventoryError(ValueError):
    """The observation was malformed, ambiguous, unsupported or incomplete."""


def complete_inventory_script() -> str:
    """Render a bounded producer, refusing drift in the adapted legacy blocks."""
    script = probes.INVENTORY_SH.replace("$NOTICES", " ".join(probes.NOTICES))
    replacements = (
        ("dpkg --verify 2>/dev/null > /tmp/verify; printf 'VC\\t%s\\n' \"$(wc -l < /tmp/verify)\"\n"
         "head -n 1500 /tmp/verify | awk '{print \"V\\t\" $1 \"\\t\" $NF}'",
         _PACKAGE_VERIFY_SH + f"awk 'NR > {MAX_SECTION_ROWS} {{exit 91}} {{print \"V\\t\" $0}}' /tmp/verify || exit 91"),
        ("head -n 1500 /tmp/unowned | sed 's/^/U\\t/'",
         f"awk 'NR > {MAX_SECTION_ROWS} {{exit 92}} {{print \"U\\t\" $0}}' /tmp/unowned || exit 92"),
    )
    for old, new in replacements:
        if script.count(old) != 1:
            raise D12InventoryError("diagnostic probe truncation boundary changed")
        script = script.replace(old, new)
    start = script.find("if grep -q 'perl' /tmp/inv;")
    stop = script.find("cat /tmp/inv", start)
    if start < 0 or stop < 0 or "find / -xdev -name 'libpq*.so*'" not in script[start:stop]:
        raise D12InventoryError("diagnostic probe module/library enumeration boundary changed")
    script = script[:start] + _ENUMERATIONS_SH + script[stop:]
    md5_lines = [line for line in script.splitlines() if line.strip().startswith("want=$(grep -E ")]
    if len(md5_lines) != 1:
        raise D12InventoryError("diagnostic probe package checksum boundary changed")
    # A literal path, including libstdc++, must not become a regular expression.
    script = script.replace(md5_lines[0],
        '    want=$(awk -v a="${r#/}" -v b="${r#/usr/}" '
        + "'" + MD5_LOOKUP_AWK + "'" + ' "$sums" 2>/dev/null)')
    script += r"""
dpkg-query -W -f='S\t${Package}\t${source:Package}\t${source:Version}\n' || exit 93
for f in /etc/dpkg/dpkg.cfg /etc/dpkg/dpkg.cfg.d/*; do
  [ -f "$f" ] || continue
  printf 'D\t%s\t%s\n' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"
  awk '/^[ \t]*path-(exclude|include)[= \t]/ {
    line=$0; gsub(/\t/, " ", line); print "X\t" FILENAME "\t" line
  }' "$f" || exit 93
done
printf 'END\trepomap-d12-complete-inventory-v2\n' || exit 93
"""
    # Bound every producer scratch file before stdout logs are materialized.
    # Unsupported limits and file-size failures refuse the whole probe.
    return ("ulimit -f 4096 || exit 94\ninventory_main() {\n" + script
            + "\n}\ninventory_main \"$@\" > /tmp/d12-complete-output\nstatus=$?\n"
            + "[ \"$status\" -eq 0 ] || exit \"$status\"\n"
            + f"[ \"$(wc -c < /tmp/d12-complete-output)\" -le {MAX_OUTPUT_BYTES} ] || exit 95\n"
            + "cat /tmp/d12-complete-output\n")


def _verify_line(package: str, raw: str) -> dict[str, Any]:
    match = re.fullmatch(r"(missing|[?.0-9A-Za-z]{9})\s+(?:(c)\s+)?(/[^\t\n]+)", raw)
    if match is None:
        raise D12InventoryError("package verification output has an unsupported path/status format")
    return {"package": package, "status": match[1], "conffile": bool(match[2]), "path": match[3], "raw": raw}


def _package_checks(sections: dict[str, list[list[str]]], packages: set[str]) -> list[dict[str, Any]]:
    rows = sections["M"]
    if {row[0] for row in rows} != packages or len(rows) != len(packages):
        raise D12InventoryError("per-package verification coverage is incomplete or duplicate")
    checks = []
    for package, status, md5, stderr_sha, stderr_bytes, state in rows:
        if (status not in ("0", "1") or (md5 != "absent" and not _SHA.fullmatch(md5))
                or not _SHA.fullmatch(stderr_sha) or not stderr_bytes.isdecimal() or state != "installed"):
            raise D12InventoryError("package verification metadata is malformed or package is not installed")
        checks.append({"package": package, "exit_code": int(status), "md5sums_sha256": md5,
                       "stderr_sha256": stderr_sha, "stderr_bytes": int(stderr_bytes), "status": state})
    return checks


def _count(sections: dict[str, list[list[str]]], count_key: str, rows_key: str) -> None:
    counts = sections[count_key]
    if len(counts) != 1 or not re.fullmatch(r"[0-9]+", counts[0][0]):
        raise D12InventoryError(f"inventory requires one exact {count_key} count")
    if int(counts[0][0]) != len(sections[rows_key]):
        raise D12InventoryError(f"incomplete {rows_key} inventory: reported count differs from retained rows")


def _file_coverage(sections: dict[str, list[list[str]]]) -> list[dict[str, str]]:
    files = [dict(zip(("role", "invoked", "resolved", "kind", "sha256", "interpreter", "owner", "md5"), row))
             for row in sections["F"]]
    for row in files:
        if row["role"] not in ("invoked", "interpreter", "library", "module", "libpq"):
            raise D12InventoryError("unsupported file observation role")
        if row["kind"] not in ("elf", "script", "other", "missing"):
            raise D12InventoryError("unsupported file observation kind")
        if row["kind"] != "missing" and not _SHA.fullmatch(row["sha256"]):
            raise D12InventoryError("existing file observation lacks its byte digest")
    observed = {row[key] for row in files if row["kind"] == "elf" for key in ("invoked", "resolved")}
    for _consumer, _soname, target in sections["L"]:
        if target.startswith("/") and target not in observed:
            raise D12InventoryError("loaded library lacks its file/digest observation")
        if not target.startswith("/") and target != "not":
            raise D12InventoryError("unsupported loaded-library target")
    for role, count_key, paths_key in (("module", "MC", "R"), ("libpq", "QC", "Q")):
        _count(sections, count_key, paths_key)
        expected = sorted(row[0] for row in sections[paths_key])
        actual = sorted(row["invoked"] for row in files if row["role"] == role)
        if actual != expected:
            raise D12InventoryError(f"{role} enumeration and file observations do not reconcile")
    if sections["MP"] not in ([["0"]], [["1"]]) or bool(sections["R"]) != (sections["MP"] == [["1"]]):
        raise D12InventoryError("Perl module enumeration is incomplete or ambiguous")
    return files


def parse_complete_inventory(text: str) -> dict[str, Any]:
    """Reconcile producer populations and explicit coverage, preserving raw findings."""
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise D12InventoryError("inventory exceeds the existing bounded report envelope")
    widths = {"F": 9, "L": 4, "P": 4, "V": 3, "VC": 2, "U": 2,
              "UC": 2, "C": 3, "O": 4, "S": 4, "D": 3, "X": 3, "M": 7, "END": 2,
              "FC": 2, "LC": 2, "MP": 2, "MC": 2, "R": 2, "QC": 2, "Q": 2}
    sections: dict[str, list[list[str]]] = {key: [] for key in widths}
    for line in text.splitlines():
        if not line:
            continue
        row = line.split("\t", 2) if line.startswith(("V\t", "X\t")) else line.split("\t")
        if row[0] not in widths or len(row) != widths[row[0]] or any(not v for v in row[1:]):
            raise D12InventoryError("unknown, malformed or empty inventory row")
        sections[row[0]].append(row[1:])
        if len(sections[row[0]]) > MAX_SECTION_ROWS:
            raise D12InventoryError("inventory section exceeds its declared row bound")
    if sections["END"] != [[SCHEMA]] or text.splitlines()[-1] != "END\t" + SCHEMA:
        raise D12InventoryError("inventory producer did not complete its terminal record")
    for count_key, rows_key in (("VC", "V"), ("UC", "U"), ("FC", "F"), ("LC", "L")):
        _count(sections, count_key, rows_key)
    if len(sections["O"]) != 1 or not sections["P"] or not sections["L"]:
        raise D12InventoryError("inventory requires OS, package and loaded-library observations")
    for key in ("P", "S", "U", "C", "D"):
        identities = [row[0] for row in sections[key]]
        if len(identities) != len(set(identities)):
            raise D12InventoryError(f"duplicate {key} inventory identity")
    packages = {row[0] for row in sections["P"]}
    if {row[0] for row in sections["S"]} != packages:
        raise D12InventoryError("package/source population does not reconcile")
    if any(row[2] not in ("all", sections["O"][0][2]) for row in sections["P"]):
        raise D12InventoryError("foreign package architecture is outside this single-native-platform probe")
    checks = _package_checks(sections, packages)
    if len(sections["V"]) != len({tuple(row) for row in sections["V"]}):
        raise D12InventoryError("duplicate package verification row")
    if any(row[0] not in packages for row in sections["V"]):
        raise D12InventoryError("verification row names an unobserved package")
    verify = [_verify_line(package, raw) for package, raw in sections["V"]]
    invoked = [row[1] for row in sections["F"] if row[0] == "invoked"]
    if set(invoked) != set(REQUESTED_PATHS) or len(invoked) != len(REQUESTED_PATHS):
        raise D12InventoryError("requested executable observation population is incomplete or duplicate")
    if set(row[0] for row in sections["C"]) != set(probes.NOTICES):
        raise D12InventoryError("notice observation population is incomplete or foreign")
    for path, digest in sections["D"]:
        if not path.startswith("/etc/dpkg/") or not _SHA.fullmatch(digest):
            raise D12InventoryError("dpkg configuration provenance is malformed")
    configs = dict(sections["D"])
    for path, directive in sections["X"]:
        if path not in configs or not re.match(r"\s*path-(?:exclude|include)[= \t]", directive):
            raise D12InventoryError("package filter lacks its configuration provenance")
    files = _file_coverage(sections)
    return {
        "schema": SCHEMA, "files": files, "links": sections["L"], "packages": sections["P"],
        "package_verification": {"count": len(verify), "rows": verify, "checks": checks},
        "unowned_usr_lib": [row[0] for row in sections["U"]], "unowned_count": int(sections["UC"][0][0]),
        "notices": dict(sections["C"]), "os": sections["O"][0],
        "source_packages": sections["S"], "dpkg_configs": configs, "path_filters": sections["X"],
        "enumerations": {"files": len(files), "links": len(sections["L"]),
                         "perl_invoked": sections["MP"] == [["1"]],
                         "modules": [row[0] for row in sections["R"]],
                         "libpq": [row[0] for row in sections["Q"]]},
    }


def complete_inventory(owner: Any, client: Any, image: str, platform: str | None, role: str, *,
                       deadline: Any | None = None,
                       create_fn: Callable[..., tuple[str, Any]] = probes._create,
                       run_once_fn: Callable[..., str] = probes._run_once) -> dict[str, Any]:
    """Use one existing owned network-less execution; its owner proves cleanup."""
    text = run_once_fn(owner, client, image,
        ["-c", complete_inventory_script(), "sh", *REQUESTED_PATHS],
        role=role, entrypoint=["sh"], platform=platform, deadline=deadline, create_fn=create_fn)
    return parse_complete_inventory(text)
