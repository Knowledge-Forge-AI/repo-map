#!/usr/bin/env python3
"""Exact Debian prerequisite custody before installation (ADR 0089 D5/D6 holds the full contract).

Canonical self-contained stdlib module: hosts import it; image recipes stage, hash and run these exact bytes.
Failed-command output is redacted idempotently before it is bounded to whole lines; nothing is retried.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Iterator, Mapping, Sequence

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
SCHEMA = "repomap-apt-prerequisites-v1"
APT_ENVIRONMENT = {"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"}
REPRODUCIBILITY = "current repository resolution; not release reproducibility"
FILENAME_ROLE = "canonical diagnostic: least trusted-index path of the bound bytes, not the path APT fetched"
_NAME = re.compile(r"[a-z0-9][a-z0-9+.-]+")
_VERSION = re.compile(r"(?:[0-9]+:)?[0-9][A-Za-z0-9.+~-]*")
_ARCH = re.compile(r"[a-z0-9][a-z0-9-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_INST = re.compile(r"Inst (\S+) (?:\[(\S+)\] )?\((\S+) (.+?) \[([a-z0-9-]+)\]\)(?: \[[^\]]*\])?")
_CONF = re.compile(r"Conf (\S+) \((\S+) (.+?) \[([a-z0-9-]+)\]\)")
_DPKG_FORMAT = "${Package}\t${Architecture}\t${Version}\t${db:Status-Abbrev}\t${source:Package}\t${source:Version}\n"
_ORIGIN_FIELDS = ("Origin", "Label", "Suite", "Codename", "Component", "Repo-URI", "Signed-By")
_HEALTHY = ("ii ", "rc ")  # ${db:Status-Abbrev}: want, state and error flag (blank when healthy)
_TAIL_LINES, _TAIL_CHARS, _JOIN = 40, 4000, " | "
_SENSITIVE_NAME = re.compile(r"(?i)token|secret|pass|key|auth|cred|cookie|session|proxy")
# Rules run in order. No marker matches a rule, so a second redaction cannot erase later lines.
_MARKERS = "<redacted><url><userinfo><path><host><address><environment>"


def _ipv6(match: re.Match[str]) -> str:  # a time or an epoch version is not an address
    try:
        ipaddress.IPv6Address(match.group())
    except ValueError:
        return match.group()
    return "<address>"


_REDACTIONS: tuple[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"(?i)\b(?:authorization|bearer|token|password|passwd|secret|api[-_]?key|cookie|credentials?)\b.*"),
     "<redacted>"),
    (re.compile(r"(?<!\S)\S*?://\S*"), "<url>"),  # the whole token, even after an environment-value marker
    (re.compile(r"[^\s@'\"]+@[^\s@'\"]+"), "<userinfo>"),
    (re.compile(r"(?<![\w.~-])[~/][^\s'\":;,()\[\]]*"), "<path>"),
    (re.compile(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"), "<host>"),
    (re.compile(r"(?<![\w:.%])[0-9A-Fa-f:.]*:[0-9A-Fa-f:.]*(?:%[\w.-]+)?(?![\w:.%])"), _ipv6),  # bare or [IP: a p]
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b|\[[0-9A-Fa-f]*:[0-9A-Fa-f:]*\]"), "<address>"),
    # single-label host names after APT's resolve/connect phrases, or as name:port (not Get:1 progress)
    (re.compile(r"(?i)(\bresolv(?:e|ing)\s+(?:host:?\s+['\"]?|['\"])|\bconnect(?:ing|ion)? to\s+['\"(]?)"
                r"[A-Za-z0-9][\w.-]*"), r"\1<host>"),
    (re.compile(r"(?<![\w.<-])(?!(?:Hit|Get|Ign|Err):)[A-Za-z][A-Za-z0-9-]*(?=:\d{1,5}(?![\w.:/]))"), "<host>"),
)


class PrerequisiteRefused(RuntimeError):
    """The native prerequisite transaction or attestation cannot be proved exact."""


def redact(text: str, environment: Mapping[str, str]) -> str:
    """Remove environment values and private identifiers, before any bounding, until the text is stable."""
    values = sorted({value for name, value in environment.items() if value not in APT_ENVIRONMENT.values()
                     and value not in _MARKERS and (len(value) >= 12 or (len(value) >= 4 and _SENSITIVE_NAME.search(
                         name)))}, key=len, reverse=True)
    for _round in range(8):  # every round redacts fully; repetition only makes the result a fixed point
        previous = text
        for value in values:
            text = text.replace(value, "<environment>")
        for pattern, replacement in _REDACTIONS:
            text = pattern.sub(replacement, text)
        text = "".join(char if char.isprintable() or char == "\n" else "?" for char in text)
        if text == previous:
            break
    return text


def bounded_tail(redacted: str) -> str:
    """The last whole redacted lines within the bound; an over-long last line is cut after a space."""
    lines = [line.strip() for line in redacted.splitlines() if line.strip()][-_TAIL_LINES:]
    while len(lines) > 1 and len(_JOIN.join(lines)) > _TAIL_CHARS:
        lines.pop(0)
    tail = _JOIN.join(lines)
    return tail if len(tail) <= _TAIL_CHARS else (tail[-_TAIL_CHARS:].partition(" ")[2] or tail[-_TAIL_CHARS:])


def command_output(run: Runner, command: Sequence[str], *, accept: Sequence[int] = (0,)) -> str:
    environment = {**os.environ, **APT_ENVIRONMENT}
    try:
        completed = run(list(command), capture_output=True, text=True, check=False, env=environment)
    except OSError as error:
        raise PrerequisiteRefused(f"{command[0]} is unavailable (a Debian-family environment is required)") from error
    if completed.returncode not in accept:
        output = redact(f"{completed.stdout or ''}\n{getattr(completed, 'stderr', None) or ''}", environment)
        detail = f"; redacted output tail: {tail}" if (tail := bounded_tail(output)) else ""
        raise PrerequisiteRefused(
            f"{redact(' '.join(command[:3]), environment)} failed with exit {completed.returncode}{detail}")
    return completed.stdout or ""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stanzas(text: str) -> Iterator[dict[str, str]]:
    """Yield deb822 stanzas as single-line fields; continuation lines are not needed here."""
    record: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if record:
                yield record
            record = {}
        elif not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            record[key] = value.strip()
    if record:
        yield record


def installed_packages(run: Runner) -> dict[str, dict[str, str]]:
    """Every package database row keyed ``name:arch``; a half-installed or error-flagged state refuses."""
    rows: dict[str, dict[str, str]] = {}
    for line in command_output(run, ["dpkg-query", "-W", "-f=" + _DPKG_FORMAT]).splitlines():
        fields = line.split("\t")
        if len(fields) != 6 or fields[3] not in _HEALTHY or not all(fields[:3]):
            raise PrerequisiteRefused(f"package database state is not ii/rc without an error flag: {line!r}")
        name, architecture, version, status, source, source_version = fields
        rows[f"{name}:{architecture}"] = {"name": name, "architecture": architecture, "version": version,
                                          "status": status[:2], "source": source or name,
                                          "source_version": source_version or version}
    if not rows:
        raise PrerequisiteRefused("package database is empty")
    return rows


def _installed(rows: Mapping[str, Mapping[str, str]], name: str) -> list[Mapping[str, str]]:
    return [row for row in rows.values() if row["name"] == name and row["status"] == "ii"]


def baseline_pins(before: Mapping[str, Mapping[str, str]], native: str, exclude: Sequence[str]) -> list[str]:
    """Hold each installed package at its installed version; native and arch-all rows are unqualified."""
    return sorted(f"{row['name']}={row['version']}" if row["architecture"] in (native, "all")
                  else f"{row['name']}:{row['architecture']}={row['version']}"
                  for row in before.values() if row["status"] == "ii" and row["name"] not in exclude)


def plan(simulation: str, before: Mapping[str, Mapping[str, str]], native: str) -> list[dict[str, str]]:
    """Parse an apt simulation; refuse anything but additions of native or arch-all packages."""
    current = {key for key, row in before.items() if row["status"] == "ii"}
    selected: dict[tuple[str, str, str], str] = {}
    configured: set[tuple[str, str, str]] = set()
    for line in simulation.splitlines():
        keyword = line.split(" ", 1)[0]
        if keyword in ("Remv", "Purg"):
            raise PrerequisiteRefused(f"transaction removes an installed package: {line}")
        if keyword not in ("Inst", "Conf"):
            continue
        match = (_INST if keyword == "Inst" else _CONF).fullmatch(line)
        if match is None:
            raise PrerequisiteRefused(f"unrecognized simulated transaction line: {line}")
        if keyword == "Conf":
            name, version, _release, architecture = match.groups()
            configured.add((name.split(":", 1)[0], version, architecture))
            continue
        name, previous, version, release, architecture = match.groups()
        name = name.split(":", 1)[0]
        if previous is not None or f"{name}:{architecture}" in current:
            raise PrerequisiteRefused(
                f"transaction changes installed {name}:{architecture} {previous or 'same'} -> {version}")
        if architecture not in (native, "all"):
            raise PrerequisiteRefused(f"foreign architecture is not admitted: {name}:{architecture}")
        if not (_NAME.fullmatch(name) and _VERSION.fullmatch(version)) or (name, version, architecture) in selected:
            raise PrerequisiteRefused(f"ambiguous or malformed selection: {line}")
        selected[(name, version, architecture)] = release
    if configured != set(selected):
        raise PrerequisiteRefused("simulation configures a different package set than it installs")
    return [{"name": name, "version": version, "architecture": architecture, "simulated_release": release}
            for (name, version, architecture), release in sorted(selected.items())]


def bind_to_trusted_index(run: Runner, packages: Sequence[Mapping[str, str]]) -> tuple[list[dict[str, object]],
                                                                                         list[dict[str, str]]]:
    """Bind each selection to one size/SHA-256 identity in trusted Packages indexes, keeping every location."""
    targets = [target for target in stanzas(command_output(run, ["apt-get", "indextargets"]))
               if target.get("Created-By") == "Packages"]
    if not targets:
        raise PrerequisiteRefused("no Packages index target is configured")
    untrusted = [target.get("Description", "?") for target in targets if target.get("Trusted") != "yes"]
    if untrusted or any(not target.get("Filename") for target in targets):
        raise PrerequisiteRefused(f"Packages index trust is unknown or absent: {untrusted}")
    unresolved = [target["Filename"] for target in targets if not (
        target.get("Repo-URI") and target.get("Origin") and (target.get("Suite") or target.get("Codename")))]
    if unresolved:
        raise PrerequisiteRefused(
            f"Packages index provenance is unresolved (Repo-URI, Origin and Suite or Codename): {unresolved}")
    wanted = {(item["name"], item["version"], item["architecture"]): item for item in packages}
    found: dict[tuple[str, str, str], list[tuple[dict[str, str], ...]]] = {key: [] for key in wanted}
    origins = [{field: target.get(field, "") for field in _ORIGIN_FIELDS} for target in targets]
    for target, origin in zip(targets, origins):
        for record in stanzas(command_output(run, ["/usr/lib/apt/apt-helper", "cat-file", target["Filename"]])):
            key = (record.get("Package", ""), record.get("Version", ""), record.get("Architecture", ""))
            if key in found:  # the bytes are the identity; each path stays paired with its own index's origin
                found[key].append(({"filename": record.get("Filename", ""), **origin}, record, origin))
    bound: list[dict[str, object]] = []
    for key, item in sorted(wanted.items()):
        identities = {(record.get("SHA256", ""), record.get("Size", "")) for _place, record, _origin in found[key]}
        if len(identities) != 1:
            raise PrerequisiteRefused(f"{key[0]}={key[1]}:{key[2]} has {len(identities)} trusted index identities")
        (sha256, size), = identities
        if not _SHA256.fullmatch(sha256) or not size.isdigit():
            raise PrerequisiteRefused(f"{key[0]} has no exact SHA-256 and size (no MD5 substitute)")
        locations = [json.loads(text) for text in sorted({json.dumps(place) for place, *_ in found[key]})]
        if not all(place["filename"] for place in locations):
            raise PrerequisiteRefused(f"{key[0]} has a trusted index record without a Filename")
        bound.append({**item, "sha256": sha256, "size": int(size), "filename": min(p["filename"] for p in locations),
                      "locations": locations, "origins": sorted((origin for *_, origin in found[key]), key=json.dumps)})
    paths = [path for key in wanted for path in {place["filename"] for place, *_ in found[key]}]
    if len({item["sha256"] for item in bound}) != len(bound) or len(set(paths)) != len(paths):
        raise PrerequisiteRefused("distinct selections share one archive sha256 or filename")
    return bound, sorted(origins, key=json.dumps)


def verify_archives(run: Runner, packages: Sequence[Mapping[str, object]], cache: Path) -> list[str]:
    """Match every cached archive to one manifest entry by bytes and control fields."""
    expected = {str(item["sha256"]): item for item in packages}
    if len(expected) != len(packages):
        raise PrerequisiteRefused("ambiguous archive identity: manifest entries share a SHA-256")
    archives = sorted(path for path in cache.iterdir() if path.is_file() and path.name not in ("lock", "manifest.json"))
    observed: dict[str, Path] = {}
    for path in archives:
        data = path.read_bytes()
        digest = _sha256(data)
        item = expected.get(digest)
        if item is None or digest in observed or len(data) != item["size"]:
            raise PrerequisiteRefused(f"cached archive {path.name} does not match the frozen manifest")
        observed[digest] = path
        fields = command_output(run, ["dpkg-deb", "--field", str(path), "Package", "Version", "Architecture"])
        control = next(stanzas(fields), {})
        if (control.get("Package"), control.get("Version"), control.get("Architecture")) != (
                item["name"], item["version"], item["architecture"]):
            raise PrerequisiteRefused(f"cached archive {path.name} control fields differ: {control}")
    if set(observed) != set(expected):
        raise PrerequisiteRefused(f"cached archives are missing: {sorted(set(expected) - set(observed))}")
    return [observed[digest].name for digest in sorted(observed)]


def _changes(before: Mapping[str, Mapping[str, str]],
             after: Mapping[str, Mapping[str, str]]) -> tuple[dict[str, list[str | None]], dict[str, str]]:
    current = {key: row["version"] for key, row in before.items() if row["status"] == "ii"}
    final = {key: row["version"] for key, row in after.items() if row["status"] == "ii"}
    changed = {key: [value, final.get(key)] for key, value in sorted(current.items()) if final.get(key) != value}
    return changed, {key: value for key, value in sorted(final.items()) if key not in current}


def install_prerequisites(run: Runner, requested: Sequence[str], cache: str | Path) -> dict[str, Any]:
    """Resolve, bind, download, verify and freeze before installing exactly the frozen archives."""
    names = sorted(set(requested))
    if not names or not all(_NAME.fullmatch(name) for name in names):
        raise PrerequisiteRefused(f"requested package names are not exact: {list(requested)}")
    cache = Path(cache)
    if cache.exists() and any(cache.iterdir()):
        raise PrerequisiteRefused("the private archive cache is not empty")
    command_output(run, ["apt-get", "update"])
    native = command_output(run, ["dpkg", "--print-architecture"]).strip()
    if not _ARCH.fullmatch(native):
        raise PrerequisiteRefused(f"native architecture is unknown: {native!r}")
    before = installed_packages(run)
    already = {}
    for name in names:
        rows = _installed(before, name)
        if len(rows) > 1:
            raise PrerequisiteRefused(f"{name} is installed for several architectures")
        if rows:
            already[name] = rows[0]["version"]
    held = baseline_pins(before, native, names) + [f"{name}={version}" for name, version in sorted(already.items())]
    request = [name for name in names if name not in already]  # every APT operation below carries the same holds
    simulation = command_output(run, ["apt-get", "install", "--simulate", "--no-install-recommends", *held, *request])
    packages = plan(simulation, before, native)
    missing = sorted(set(names) - set(already) - {item["name"] for item in packages})
    if missing:
        raise PrerequisiteRefused(f"the simulation does not install requested packages: {missing}")
    evidence: dict[str, Any] = {"schema": SCHEMA, "reproducibility": REPRODUCIBILITY, "requested": names,
                                "already_installed": already, "native_architecture": native, "packages": [],
                                "added": [], "manifest_sha256": None, "filename_role": FILENAME_ROLE,
                                "preexisting_unchanged": sum(row["status"] == "ii" for row in before.values())}
    if not packages:
        return evidence
    bound, origins = bind_to_trusted_index(run, packages)
    option = f"Dir::Cache::Archives={cache}/"
    pins = [f"{item['name']}={item['version']}" for item in bound]
    (cache / "partial").mkdir(parents=True, exist_ok=True)
    install = ["apt-get", "install", "--yes", "--no-install-recommends", "--no-remove", "-o", option]
    command_output(run, [*install, "--download-only", *held, *pins])
    archives = verify_archives(run, bound, cache)
    manifest = {"schema": SCHEMA, "native_architecture": native, "requested": names, "packages": bound,
                "trusted_targets": origins, "archives": archives, "filename_role": FILENAME_ROLE}
    frozen = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (cache / "manifest.json").write_bytes(frozen)
    for name in archives:
        (cache / name).chmod(0o444)
    if verify_archives(run, bound, cache) != archives or installed_packages(run) != before:
        raise PrerequisiteRefused("frozen archives or installed state drifted before installation")
    command_output(run, [*install, "--no-download", *held, *pins])
    dependencies = sorted({str(item["name"]) for item in bound} - set(names))
    if dependencies:
        command_output(run, ["apt-mark", "auto", *dependencies])
    changed, added = _changes(before, installed_packages(run))
    expected = {f"{item['name']}:{item['architecture']}": item["version"] for item in bound}
    if changed or added != expected:
        raise PrerequisiteRefused(f"installed state differs from the frozen manifest: {changed} {added}")
    shutil.rmtree(cache)
    evidence.update(packages=bound, trusted_targets=origins, manifest_sha256=_sha256(frozen),
                    added=[f"{key}={value}" for key, value in added.items()])
    return evidence


def package_of(run: Runner, path: str) -> str:
    """The single dpkg owner of a path (also tried without ``/usr``); diversions refuse."""
    for candidate in dict.fromkeys((path, "/" + path.removeprefix("/usr/"))):
        output = command_output(run, ["dpkg-query", "-S", candidate], accept=(0, 1))
        if any(line.startswith("diversion by") for line in output.splitlines()):
            raise PrerequisiteRefused(f"{candidate} is diverted")
        owners = {item.strip().split(":", 1)[0] for line in output.splitlines()
                  if line.endswith(f": {candidate}") for item in line[: -len(candidate) - 2].split(",")}
        if len(owners) > 1:
            raise PrerequisiteRefused(f"{candidate} has several owners: {sorted(owners)}")
        if owners:
            return owners.pop()
    return ""


def attest_libpq(run: Runner, *, which: Callable[[str], str | None] = shutil.which,
                 realpath: Callable[[str], str] = os.path.realpath) -> dict[str, Any]:
    """Bind PATH pg_config, the selected header and the runtime to one libpq source version."""
    installed = installed_packages(run)
    pair = {name: _installed(installed, name) for name in ("libpq-dev", "libpq5")}
    if any(len(rows) != 1 for rows in pair.values()):
        raise PrerequisiteRefused("libpq-dev and libpq5 are not each installed exactly once")
    dev, runtime = pair["libpq-dev"][0], pair["libpq5"][0]
    if (dev["version"], dev["source"], dev["source_version"]) != (
            runtime["version"], runtime["source"], runtime["source_version"]):
        raise PrerequisiteRefused(f"libpq headers and runtime differ: {dev['version']} != {runtime['version']}")
    executable = which("pg_config")
    if not executable:
        raise PrerequisiteRefused("pg_config is not on PATH")
    real = realpath(executable)
    owner = package_of(run, real)
    rows = _installed(installed, owner) if owner else []
    if len(rows) != 1 or (rows[0]["source"], rows[0]["source_version"]) != (dev["source"], dev["source_version"]):
        raise PrerequisiteRefused(
            f"PATH pg_config {executable} -> {real} is owned by {owner or 'no package'}, "
            f"not by the {dev['source']} {dev['source_version']} source of libpq-dev/libpq5")
    selected = {flag: command_output(run, [executable, flag]).strip()
                for flag in ("--includedir", "--libdir", "--version")}
    paths = {"libpq-fe.h": realpath(os.path.join(selected["--includedir"], "libpq-fe.h")),
             "libpq.so.5": realpath(os.path.join(selected["--libdir"], "libpq.so.5"))}
    owners = {name: package_of(run, path) for name, path in paths.items()}
    if owners != {"libpq-fe.h": "libpq-dev", "libpq.so.5": "libpq5"}:
        raise PrerequisiteRefused(f"libpq header or runtime is not owned by that pair: {owners}")
    return {"pg_config": {"path": executable, "realpath": real, "package": owner,
                          "package_version": rows[0]["version"], "version": selected["--version"]},
            "libpq_dev": dev["version"], "libpq5": runtime["version"], "source": dev["source"],
            "source_version": dev["source_version"], "includedir": selected["--includedir"],
            "libdir": selected["--libdir"], "paths": paths, "owners": {"pg_config": owner, **owners}}


def main(argv: Sequence[str] | None = None, run: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Exact Debian prerequisite custody before installation")
    commands = parser.add_subparsers(dest="command", required=True)
    install, attest = commands.add_parser("install"), commands.add_parser("attest-libpq")
    install.add_argument("--cache", required=True)
    install.add_argument("package", nargs="+")
    for command in (install, attest):
        command.add_argument("--evidence")
    args = parser.parse_args(argv)
    try:
        evidence = (install_prerequisites(run, args.package, args.cache) if args.command == "install"
                    else attest_libpq(run))
    except (PrerequisiteRefused, OSError, ValueError) as error:
        print(f"apt prerequisites refused: {redact(str(error), os.environ)}", file=sys.stderr)
        return 2
    text = json.dumps(evidence, sort_keys=True)
    if args.evidence:
        Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
