#!/usr/bin/env python3
"""ADR 0089 D9 non-consuming platform preflight for the D12 candidate profile.

Runs on the host before admission consumes any budget reservation, using only
read-only Docker queries: no pull, build, probe image, emulator or builder
change. The host classification is ``native`` (the daemon's architecture),
``emulated`` (an existing host builder lists it) or ``non_executable``; it is
recorded as an observation and forecast only. The candidate is built by the
fresh inner sandbox daemon, not by the host daemon or builder, so neither a
native host architecture nor a host BuildKit builder proves execution or
pinned base availability in that daemon. No inner-daemon platform preflight is
implemented, so every platform, native included, refuses here before anything
is reserved, consumed or admitted. The refusal also names a builder without
BuildKit (``RUN --network=none`` is required) and a platform the frozen
dynamic package manifest does not yet cover.
Base acquisition, libpq and closure inspection, package resolution and P3
classification are separate, sandbox-only preflight steps not performed here.

E1 (``--d12-core-image-preflight``) explores the same profile and node: no ledger, host preflight or build
admission; in the sandbox ``explore`` reports before the owner's build, then the owner returns (ADR 0089).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Mapping, NoReturn, Sequence

import d12_libpq_runtime_probe as runtime
import d12_native_python_observer as observer
import d12_python_closure as closure
import native_apt_prerequisites as apt
from common_lore_index.runtime.release import (
    DYNAMIC_PACKAGE_MANIFEST, GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, PSYCOPG_LIBPQ_VERSION,
    PYTHON_RELEASE_IMAGE, DebPackage, PlatformPackages, validate_package_manifest,
)
from repomap_test_support import d12_core_image as d12
from repomap_test_support.d12_core_image import D12Admission, D12ProfileError

PLATFORMS = ("linux/arm64", "linux/amd64")
_NATIVE = {"aarch64": "linux/arm64", "arm64": "linux/arm64", "x86_64": "linux/amd64", "amd64": "linux/amd64"}
Runner = Callable[..., subprocess.CompletedProcess[str]]
GO_CONFIGS = {"linux/amd64": "sha256:0d494ea9b5863337de0dfb4f938062bf0261a919016eb162d2be26381dbadafe",
              "linux/arm64": "sha256:347d64c45df620f4ec8dfe652b4039b0fabb614f4238f6248ac33a56df3caf2d"}
COUNTS = ("managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
          "unmanaged_build_count", "unmanaged_pull_count")
LABELS = {"mode": "exploration", "daemon": "disposable inner daemon, destroyed at sandbox exit",
          "build_readiness": "NOT ESTABLISHED", "p3": "inputs only", "host_forecast_substituted": False}
KEYS_SH = ('command -v gpg >/dev/null || exit 127; g=$(mktemp -d) || exit 1; '
           'GNUPGHOME="$g" gpg --batch --show-keys --with-colons "$1"; s=$?; rm -rf "$g"; exit $s')
# ADR 0091: the Trixie bases' exact TLS runtime and its matching header, nothing broader. Live origins only: no
# snapshot or older-version archive fallback, so a superseding upload is an expected refusal.
HEADER = ("libssl3t64", "libssl-dev", "3.5.7-1~deb13u3")


class PreflightRefusal(D12ProfileError):
    """The platform cannot be admitted; nothing was reserved or consumed."""


_EXPLORATION: D12Admission | None = None  # E1 exploration admission; never build admission


def classify(platform: str, daemon_architecture: str, builder_platforms: Sequence[str]) -> str:
    if _NATIVE.get(daemon_architecture) == platform:
        return "native"
    return "emulated" if platform in builder_platforms else "non_executable"


def builder_facts(buildx_inspect: str) -> tuple[list[str], str | None]:
    """Offered OS/arch platforms and the BuildKit version from ``docker buildx inspect``."""
    platforms: list[str] = []
    buildkit = None
    for line in buildx_inspect.splitlines():
        key, _, value = line.strip().partition(":")
        if key == "Platforms":
            platforms.extend(item.strip().rstrip("*") for item in value.split(",") if item.strip())
        elif key == "BuildKit version" and value.strip():
            buildkit = value.strip()
    return platforms, buildkit


def manifest_refusal(
    platform: str,
    manifest: Mapping[str, object] = DYNAMIC_PACKAGE_MANIFEST,
    libpq_version: int | None = PSYCOPG_LIBPQ_VERSION,
) -> str | None:
    architecture = platform.split("/", 1)[1]
    if architecture not in manifest or libpq_version is None:
        return f"frozen dynamic package manifest does not cover {platform}"
    return None


def preflight(
    platform: str,
    *,
    run: Runner = subprocess.run,
    manifest: Mapping[str, object] = DYNAMIC_PACKAGE_MANIFEST,
    libpq_version: int | None = PSYCOPG_LIBPQ_VERSION,
) -> NoReturn:
    """Observe the host and refuse: inner-daemon readiness is unproved for every platform."""
    if platform not in PLATFORMS:
        raise PreflightRefusal(f"unsupported platform {platform}")

    def query(*command: str) -> str:
        try:
            completed = run(list(command), capture_output=True, text=True, check=False)
        except OSError as error:
            raise PreflightRefusal(f"{command[0]} is unavailable") from error
        if completed.returncode != 0:
            raise PreflightRefusal(f"{' '.join(command[:3])} failed")
        return completed.stdout.strip()

    daemon = query("docker", "version", "--format", "{{.Server.Arch}}")
    offered, buildkit = builder_facts(query("docker", "buildx", "inspect"))
    forecast = classify(platform, daemon, offered)
    record: dict[str, object] = {"platform": platform, "daemon_architecture": daemon, "builder_platforms": offered,
              "buildkit": buildkit, "host_forecast": forecast, "consumed": False,
              "inner_daemon_execution": "unproved", "inner_base_availability": "unproved"}
    reasons = [f"{platform} execution and pinned base availability in the fresh inner build daemon are unproved;"
               f" the host {forecast} classification is only a forecast and no inner-daemon preflight exists"]
    if forecast == "non_executable":
        reasons.append(f"{platform} is not executable by the existing daemon or builder")
    if buildkit is None:
        reasons.append("the existing builder reports no BuildKit; RUN --network=none is unavailable")
    refusal = manifest_refusal(platform, manifest, libpq_version)
    if refusal:
        reasons.append(refusal)
    raise PreflightRefusal("; ".join(reasons) + f" (observed {json.dumps(record, sort_keys=True)})")


def admit_exploration(args: Any, forwarded: Sequence[str], *, repo_root: Path,
                      sandbox_active: Callable[[], bool]) -> D12Admission | None:
    """E1: a ledger option refuses first; the host preflight, ``admit_profile`` and ``record_budget`` never run. The
    host returns; the sandbox fills only the separate exploration slot, so ``d12.current_admission()`` refuses."""
    global _EXPLORATION
    if getattr(args, "d12_core_image_budget_ledger", None) is not None:
        raise PreflightRefusal("--d12-core-image-preflight refuses --d12-core-image-budget-ledger (no ledger access)")
    platform = getattr(args, "d12_core_image_profile", None)
    if platform is None or not getattr(args, "d12_core_image_preflight", False):
        raise PreflightRefusal("--d12-core-image-preflight requires --d12-core-image-profile")
    d12.validate_selection(args, forwarded, repo_root=repo_root)
    inside, report_dir = sandbox_active(), repo_root / args.report_dir
    if not inside and (report_dir.exists() or report_dir.is_symlink()):
        raise PreflightRefusal("stale report directory: exploration requires an unused --report-dir")
    identity = d12.frozen_identity(repo_root, platform)
    if identity["source_sha256"] != args.d12_core_image_source_sha256:
        raise PreflightRefusal("stale source: checkout differs from --d12-core-image-source-sha256")
    if not inside:
        return None
    if d12._ADMISSION is not None or _EXPLORATION is not None:
        raise PreflightRefusal("mixed build and exploration admission in one process")
    _EXPLORATION = D12Admission(platform=platform, node_id=d12.NODE_ID, **identity)
    return _EXPLORATION


def current_exploration() -> D12Admission | None:
    return _EXPLORATION


def require_zero_builds(budget: Mapping[str, object]) -> dict[str, object]:
    """Exploration custody: every build and pull count of the run-wide boundary is zero."""
    counts = {field: budget.get(field) for field in COUNTS}
    if any(value != 0 for value in counts.values()):
        raise PreflightRefusal(f"exploration build or pull counts are not all zero: {counts}")
    return counts


def exec_runner(container: Any) -> Runner:
    """``container.exec_run`` as the APT helpers' runner: argv only, no shell, the APT environment only."""
    def run(command: Sequence[str], **_options: Any) -> subprocess.CompletedProcess[str]:
        result = container.exec_run(list(command), environment=dict(apt.APT_ENVIRONMENT), demux=True)
        stdout, stderr = result.output or (None, None)
        return subprocess.CompletedProcess(list(command), result.exit_code, (stdout or b"").decode(errors="replace"),
                                           (stderr or b"").decode(errors="replace"))
    return run


def read_bytes(container: Any, path: str) -> bytes | None:
    result = container.exec_run(["cat", "--", path], demux=True)
    return ((result.output or (None, None))[0] or b"") if result.exit_code == 0 else None


def engine_facts(steps: dict[str, Any], client: Any, admission: D12Admission, inspected: Any,
                 bases: Mapping[str, Mapping[str, object]]) -> None:
    """E-b/E-c: inner builder, engine and local bases (Go config: ADR 0090 D1, never run); host Buildx is no proof."""
    if inspected.returncode != 0:
        raise PreflightRefusal(f"docker buildx inspect failed in the inner daemon with exit {inspected.returncode}")
    offered, buildkit = builder_facts(inspected.stdout)
    fields = dict(line.strip().partition(":")[::2] for line in inspected.stdout.splitlines())
    info, version, platform = client.info(), client.version(), admission.platform
    classes = {item: classify(item, str(info.get("Architecture", "")), offered) for item in PLATFORMS}
    pg, py, go = (dict(bases.get(name) or {}) for name in (
        POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE, GO_RELEASE_IMAGE))
    steps["engine"] = {"driver": fields.get("Driver", "").strip(), "status": fields.get("Status", "").strip(),
                       "buildkit": buildkit, "builder_platforms": offered, "classification": classes,
                       "others": "classified from builder offers only", "architecture": info.get("Architecture"),
                       "storage_driver": info.get("Driver"), "engine": version.get("Version"),
                       "api": version.get("ApiVersion")}
    identity = steps["identity"] = {
        "postgres": pg.get("id"), "postgres_sealed": pg.get("config_digest_verified") is True,
        "python": py.get("id"), "go": go.get("id"), "go_expected": GO_CONFIGS.get(platform), "go_run": False}
    if buildkit is None:
        raise PreflightRefusal("the inner builder reports no BuildKit; RUN --network=none is unavailable")
    if classes[platform] != "native":
        raise PreflightRefusal(f"{platform} is {classes[platform]} in the inner daemon; E1 explores native only")
    if not identity["postgres_sealed"] or not identity["python"] or identity["go"] != identity["go_expected"]:
        raise PreflightRefusal(f"unknown base identity: {identity}")


def trust_facts(steps: dict[str, Any], container: Any) -> dict[str, bytes]:
    """E-e: the PostgreSQL base's APT sources and signed-by keyrings, by exact bytes and SHA-256. Fingerprints come
    only from a key-listing tool already in the base (exit 127: none), never from a new parser."""
    listed = apt.command_output(exec_runner(container), ["find", "/etc/apt", "-path", "*/sources.list*", "-type", "f"])
    sources = {p: read_bytes(container, p) or b"" for p in sorted(listed.split())}
    signed = {p: sorted(set(re.findall(r"(?im)(?:signed-by=|^Signed-By:\s*)(/[^\s\]]+)", b.decode(errors="replace"))))
              for p, b in sources.items()}
    keyrings = {key: read_bytes(container, key) for key in sorted({k for keys in signed.values() for k in keys})}
    facts = steps["trust"] = {
        "sources": {p: {"sha256": hashlib.sha256(b).hexdigest(), "signed_by": signed[p]} for p, b in sources.items()},
        "keyrings": {k: None if b is None else hashlib.sha256(b).hexdigest() for k, b in keyrings.items()},
        "fingerprints": "unobserved"}
    pgdg = [p for p, b in sources.items() if re.search(rb"\b[a-z]+-pgdg\b", b)]
    if len(pgdg) != 1 or len(signed[pgdg[0]]) != 1 or keyrings.get(signed[pgdg[0]][0]) is None:
        raise PreflightRefusal(f"the PGDG source or its one signed-by keyring is absent or ambiguous: {pgdg}")
    source = facts["pgdg_source"] = pgdg[0]
    keyring = facts["pgdg_keyring"] = signed[source][0]
    listing = container.exec_run(["sh", "-c", KEYS_SH, "sh", keyring], demux=True)
    if listing.exit_code != 0:
        raise PreflightRefusal("signing-key fingerprints unobserved: " + (
            "the PostgreSQL base has no existing key-listing tool; only the keyring SHA-256 is recorded"
            if listing.exit_code == 127 else f"the existing key-listing tool exited {listing.exit_code}"))
    text = ((listing.output or (None, None))[0] or b"").decode(errors="replace")
    primary = re.findall(r"^pub:.*\nfpr:+([0-9A-F]{40}):", text, re.M)
    facts["fingerprints"] = {"primary": primary, "subkeys": re.findall(r"^sub:.*\nfpr:+([0-9A-F]{40}):", text, re.M)}
    if not primary:
        raise PreflightRefusal("the existing key-listing tool reported no primary key fingerprint")
    return {source: sources[source], keyring: keyrings[keyring] or b""}


def closure_facts(steps: dict[str, Any], container: Any, platform: str) -> dict[str, Any]:
    """E-f in this owned container: d12_python_closure runs the product's exact Python payload contract."""
    return closure.closure_facts(steps, exec_runner(container), platform, refusal=PreflightRefusal)


def builder_request(request: Sequence[str], before: Mapping[str, Any], native: str, *,
                    missing_only: bool = False) -> list[str]:
    """E-g only: append the exact matching header for exactly one installed native runtime row; else refuse."""
    names = [item.partition("=")[0].partition(":")[0] for item in request]
    if missing_only or "libpq-dev" not in names:
        return list(request)
    runtime, header, version = HEADER
    if not all(isinstance(row, Mapping) for row in before.values()):
        raise PreflightRefusal("malformed installed package rows before the builder simulation")
    rows = {name: [(row.get("status"), row.get("architecture"), row.get("version")) for row in before.values()
                   if row.get("name") == name] for name in (runtime, header)}
    if rows[runtime] != [("ii", native, version)] or rows[header] or header in names:
        raise PreflightRefusal(f"builder header refused before simulation: need one ii {native} {runtime}={version}"
                               f" and no {header} row or request; rows {rows}")
    return [*request, f"{header}={version}"]


def resolve(container: Any, platform: str, request: Sequence[str], *, trust: Mapping[str, bytes] | None = None,
            missing_only: bool = False) -> dict[str, Any]:
    """E-g/E-h: simulate additions only, every installed row held; bind each to one trusted index identity."""
    run = exec_runner(container)
    for path, data in sorted((trust or {}).items()):  # the PostgreSQL base's exact bytes, then proved by hash
        apt.command_output(run, ["sh", "-c", 'mkdir -p "${1%/*}" && printf %s "$2" | base64 -d > "$1"', "sh",
                                 path, base64.b64encode(data).decode()])
        if read_bytes(container, path) != data:
            raise PreflightRefusal(f"PGDG trust bytes differ between the PostgreSQL and Python bases: {path}")
    apt.command_output(run, ["apt-get", "update"])
    native = apt.command_output(run, ["dpkg", "--print-architecture"]).strip()
    if native != platform.split("/", 1)[1]:
        raise PreflightRefusal(f"native architecture {native!r} is not {platform}")
    before = apt.installed_packages(run)
    request = builder_request(request, before, native, missing_only=missing_only)
    held = {row["name"] for row in before.values() if row["status"] == "ii"}
    wanted = [item for item in request if not (missing_only and item.partition("=")[0] in held)]
    packages = apt.plan(apt.command_output(run, ["apt-get", "install", "--simulate", "--no-install-recommends",
                                                 "--no-remove", *apt.baseline_pins(before, native, ()), *wanted]),
                        before, native) if wanted else []
    got = {item["name"]: item["version"] for item in packages}
    clash = sorted(set(got) & {row["name"] for row in before.values()})
    absent = [item for item in wanted if (name := item.partition("=")[0]) not in got or item not in (
        name, f"{name}={got[name]}")]
    if clash or absent:
        raise PreflightRefusal(f"additions with an existing ii or rc row: {clash}; requests not added: {absent}")
    bound, origins = apt.bind_to_trusted_index(run, packages) if packages else ([], [])
    return {"native": native, "preexisting_rows": len(before), "packages": bound, "trusted_targets": origins}


def candidate(steps: dict[str, Any], platform: str, server_inventory: Mapping[str, Any]) -> None:
    """E-i: validate an assembled manifest; never written to source. Its libpq number is only the builder's verified
    runtime PQlibVersion (ADR 0091); the dpkg-derived forecast is a separate equality check, never a fallback."""
    trust, version, architecture = steps["trust"], steps["libpq5_version"], platform.split("/", 1)[1]
    libs = sorted({(f.get("resolved"), f.get("sha256")) for f in server_inventory.get("files", [])
                   if f.get("role") == "libpq" and f.get("owner") == "libpq5"})
    if len(libs) != 1:
        raise PreflightRefusal(f"the PostgreSQL base libpq5 file is absent or ambiguous: {libs}")
    forecast = int(parts[1]) * 10000 + int(parts[2]) if (parts := re.match(r"(\d+)\.(\d+)", version)) else None
    debs = [tuple(DebPackage(p["name"], p["version"], p["architecture"], p["sha256"]) for p in steps[key]["packages"])
            for key in ("builder", "final_closure")]
    item = PlatformPackages(
        steps["identity"]["postgres"], (trust["pgdg_source"], trust["sources"][trust["pgdg_source"]]["sha256"]),
        (trust["pgdg_keyring"], trust["keyrings"][trust["pgdg_keyring"]]), tuple(trust["fingerprints"]["primary"]),
        libs[0][0], libs[0][1], version, debs[0], debs[1], tuple(steps["closure"]["imports"]))
    steps["candidate"] = {"architecture": architecture, "manifest": item._asdict(), "libpq_version": None,
                          "package_forecast": forecast,
                          "libpq_label": "runtime PQlibVersion; forecast is equality only",
                          "written_to_source": False}
    try:  # a missing, invalid or unbound observation refuses; no derived fallback
        number = runtime.consume(steps.get("libpq_runtime"), steps, server_inventory, platform)
        if number != forecast:
            raise ValueError(f"runtime libpq {number} differs from the package forecast {forecast}")
        validate_package_manifest({architecture: item}, number)
    except (ValueError, apt.PrerequisiteRefused) as error:
        raise PreflightRefusal(f"candidate manifest refused: {error}") from error
    steps["candidate"].update(libpq_version=number, valid=True)  # validated only; never written to source


def explore(owner: Any, client: Any, admission: D12Admission, *, bases: Mapping[str, Mapping[str, object]],
            availability: Mapping[str, object], inspected: Any, server_inventory: Mapping[str, Any],
            create: Callable[..., Any], bindings: Mapping[str, object],
            write_report: Callable[[str, dict[str, object]], object] = d12.write_report,
            statvfs: Callable[[str], Any] = os.statvfs) -> dict[str, Any]:
    """E-b to E-j once in the admitted inner daemon; save the (partial) report, then propagate any refusal."""
    platform, steps, refusals, failure = admission.platform, dict[str, Any](), list[str](), None
    report: dict[str, object] = {**LABELS, "admission": dict(vars(admission)), "bindings": dict(bindings),
                                 "availability": availability, "bases": bases, "steps": steps, "refusals": refusals}

    def observe(name: str, image: str, network: str, action: Callable[[Any], Any]) -> Any:  # one owned container
        identity, container = create(owner, client, image, ["infinity"], role=f"d12-explore-{name}",
                                     entrypoint=["sleep"], environment={}, network_mode=network, platform=platform)
        try:
            container.start()
            return action(container)
        except (D12ProfileError, apt.PrerequisiteRefused) as error:
            refusals.append(f"{name}: {error}"[:4000])
            return None
        finally:
            owner.cleanup(identity)

    try:
        engine_facts(steps, client, admission, inspected, bases)
        observer.observe_exploration(steps, client, owner, admission, exploration=_EXPLORATION)  # ADR 0102 slot
        rows = [row[1] for row in server_inventory.get("packages", []) if row[:1] == ["libpq5"]]
        libpq = steps["libpq5_version"] = rows[0] if len(rows) == 1 else None
        refusals.extend([] if libpq else ["libpq: the sealed PostgreSQL base has no single libpq5 version"])
        trust = observe("trust", POSTGRES_RELEASE_IMAGE, "none", lambda c: trust_facts(steps, c))
        closure = observe("closure", PYTHON_RELEASE_IMAGE, "none", lambda c: closure_facts(steps, c, platform))
        observer.cross_check(steps)
        def builder(c: Any) -> None:  # E-g, then the accepted numeric proof in this same owned builder (ADR 0091)
            pkgs = ["gcc", "binutils", "libc6-dev", f"libpq-dev={libpq}", f"libpq5={libpq}"]
            steps["builder"] = resolve(c, platform, pkgs,
                                       trust=trust)
            steps["libpq_runtime"] = runtime.observe(c, steps, server_inventory, platform, bindings)
        if not refusals:  # E-g, then E-h, run only after every earlier fact passed
            observe("builder", PYTHON_RELEASE_IMAGE, "bridge", builder)
        if not refusals:
            steps["final_closure"] = observe("final", POSTGRES_RELEASE_IMAGE, "bridge", lambda c: resolve(
                c, platform, [f"{name}={ver}" for name, ver, _arch in closure["packages"]], missing_only=True))
        if not refusals:
            candidate(steps, platform, server_inventory)
    except Exception as error:
        failure = error
        refusals.append(f"{type(error).__name__}: {error}"[:4000])
    finally:
        try:
            free = statvfs("/var/lib/docker")
            steps["capacity"] = {"free_bytes": free.f_bavail * free.f_frsize, "role": "forecast only; no increase"}
        except OSError as error:
            steps["capacity"] = {"observed": False, "error": type(error).__name__}
        report["result"] = "refused" if refusals else "observed"
        write_report("exploration", report)
    if refusals:
        raise PreflightRefusal("E1 exploration refused; nothing built or consumed: " + "; ".join(refusals)) from failure
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=PLATFORMS)
    args = parser.parse_args(argv)
    try:
        preflight(args.platform)
    except PreflightRefusal as error:
        print(f"D12 platform preflight refused without consuming a reservation: {error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
