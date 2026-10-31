"""ADR 0102 native Python 3.12.16 component diagnostic: pure provenance, capture and payload validators.

Stdlib and the payload contract only; no Docker. Every check refuses missing, duplicate, ambiguous, tampered,
foreign or stale evidence. The requested platform comes from admission; the daemon only confirms it. A component
record is diagnostic: it never qualifies an image, P3, the whole preflight or a default enrollment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from common_lore_index.runtime import python_payload as payload

COMPONENT_SCHEMA = "repomap-d12-python31216-component-v1"
ENVELOPE_PATH = "tools/ci/d12_python31216_native_inputs.json"
ENVELOPE_SHA256 = "cce7fccabbde1fe56bf6a543ed03c49243457708300c061202a96caf6ce137de"
ENVELOPE_SCHEMA = "repomap-python31216-native-inputs-v1"
ENVELOPE_LIMIT, CAPTURE_LIMIT, RECORD_LIMIT = 65_536, 1_000_000, 700_000
METADATA_KEYS = ("amd64-config", "amd64-manifest", "arm64-config", "arm64-manifest", "index")
INDEX_MEDIA = "application/vnd.oci.image.index.v1+json"
MANIFEST_MEDIA = "application/vnd.oci.image.manifest.v1+json"
RAW_OVERRIDE_ENV = "REPOMAP_TEST_RUNTIME_IMAGE"
RAW_PREFIX, INNER_PREFIX = "REPOMAP_PY31216_COMPONENT_RAW=", "REPOMAP_PY31216_COMPONENT="
ERROR_PREFIX = "REPOMAP_PY31216_COMPONENT_ERROR="
EXPECTED_PYTHON_VERSION, EXPECTED_PYTHON_BANNER = "3.12.16", "Python 3.12.16"
TK_REASON = "unusable Tk bridge: Tcl/Tk libraries are absent from the base"
MACHINES = {"arm64": "aarch64", "amd64": "x86_64"}
CONFIGS = {"arm64": payload.PYTHON_31216_ARM64_CONFIG, "amd64": payload.PYTHON_31216_AMD64_CONFIG}
MANIFESTS = {"arm64": payload.PYTHON_31216_ARM64_MANIFEST, "amd64": payload.PYTHON_31216_AMD64_MANIFEST}
NON_QUALIFICATION = {"image": False, "p3": False, "whole_preflight": False, "default_enrollment": False}
REPORT_KEYS = frozenset({"schema", "architecture", "result", "reasons", "baseline", "exclusion", "retained"})
BASELINE_KEYS = frozenset({"machine", "entries", "digest", "elves", "dynload", "dynload_real", "imports", "failed",
                           "targets"})
INNER_KEYS = frozenset({"python_version", "python_banner", "machine", "rc_raw", "rc_trimmed", "default_enrolled",
                        "default_matches", "entry_delta", "removed", "modified_survivors", "trimmed_report"})
_DAEMON = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PRIVATE = re.compile(r"(?:/Users|/home|/private|/var/folders|/tmp|/runner|/github|/root)/[^\s'\"]*")
_BARE_ID = re.compile(r"(?<!sha256:)(?<![0-9a-f])[0-9a-f]{12,}(?![0-9a-f])")


class NativeComponentError(ValueError):
    """Raised when ADR 0102 component evidence is missing, malformed, foreign or inconsistent."""


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def integrity(data: bytes) -> dict[str, Any]:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def redact(text: str) -> str:
    """Private host paths and bare container identifiers removed; digests kept."""
    return _BARE_ID.sub("<id>", _PRIVATE.sub("<path>", text))


def public_reason(stage: str, error: BaseException) -> str:
    """A bounded reason with private host paths and bare container identifiers removed."""
    return f"{stage}: {redact(f'{type(error).__name__}: {error}')}"[:600]


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise NativeComponentError(f"duplicate JSON keys: {sorted({k for k in keys if keys.count(k) > 1})[:5]}")
    return dict(pairs)


def _constant(name: str) -> Any:
    raise NativeComponentError(f"non-finite JSON constant {name}")


def strict_json(data: str | bytes, *, limit: int, what: str) -> Any:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > limit:
        raise NativeComponentError(f"{what} exceeds {limit} bytes")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeComponentError(f"malformed {what} ({type(error).__name__})") from error


def load_envelope(data: bytes, *, expected_sha256: str = ENVELOPE_SHA256) -> dict[str, bytes]:
    """The exact public metadata envelope: hash first, then a strict closed schema."""
    if len(data) > ENVELOPE_LIMIT or hashlib.sha256(data).hexdigest() != expected_sha256:
        raise NativeComponentError("the public metadata envelope is oversized, altered or stale")
    doc = strict_json(data, limit=ENVELOPE_LIMIT, what="metadata envelope")
    meta = doc.get("metadata_utf8") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or set(doc) != {"metadata_utf8", "schema"} or doc["schema"] != ENVELOPE_SCHEMA:
        raise NativeComponentError("the metadata envelope schema is not exact")
    if not isinstance(meta, dict) or tuple(sorted(meta)) != METADATA_KEYS or not all(
            isinstance(value, str) for value in meta.values()):
        raise NativeComponentError("the metadata envelope documents are missing, foreign or not text")
    return {key: value.encode("utf-8") for key, value in meta.items()}


def read_envelope(repo_root: Path) -> dict[str, bytes]:
    with (repo_root / ENVELOPE_PATH).open("rb") as handle:
        return load_envelope(handle.read(ENVELOPE_LIMIT + 1))


def platform_architecture(platform: str) -> str:
    os_name, _sep, architecture = str(platform).partition("/")
    if os_name != "linux" or architecture not in MACHINES:
        raise NativeComponentError(f"unsupported requested platform {platform!r}")
    return architecture


def require_native(daemon_architecture: str, platform: str) -> str:
    """The admitted request selects the platform; a foreign daemon refuses before any image access."""
    architecture = platform_architecture(platform)
    observed = _DAEMON.get(str(daemon_architecture).strip().lower())
    if observed is None:
        raise NativeComponentError(f"unknown daemon architecture {daemon_architecture!r}")
    if observed != architecture:
        raise NativeComponentError(f"native {platform} component refuses the {observed} daemon; "
                                   "nothing is inferred across architectures")
    return architecture


def verify_hierarchy(metadata: Mapping[str, bytes], platform: str, *,
                     expected: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Index, one platform manifest, its config and rootfs, each bound by hash and descriptor."""
    arch = platform_architecture(platform)
    pins = dict(expected or {"index": payload.PYTHON_31216_INDEX, "manifest": MANIFESTS[arch],
                             "config": CONFIGS[arch]})
    blobs = {"index": metadata["index"], "manifest": metadata[f"{arch}-manifest"],
             "config": metadata[f"{arch}-config"]}
    for name, blob in blobs.items():
        if digest(blob) != pins[name]:
            raise NativeComponentError(f"{arch} {name} bytes do not hash to the approved {pins[name]}")
    index, manifest, config = (strict_json(blobs[n], limit=ENVELOPE_LIMIT, what=n) for n in blobs)
    found = index.get("manifests") if isinstance(index, dict) else None
    if (not isinstance(index, dict) or index.get("schemaVersion") != 2 or index.get("mediaType") != INDEX_MEDIA
            or not isinstance(found, list) or not all(
                isinstance(d, dict) and isinstance(d.get("platform"), dict) for d in found)):
        raise NativeComponentError("the approved index is malformed")
    selected = [d for d in found if d["platform"].get("os") == "linux" and d["platform"].get("architecture") == arch]
    if len(selected) != 1 or [d.get("digest") for d in found].count(pins["manifest"]) != 1:
        raise NativeComponentError(f"the index has {len(selected)} linux/{arch} descriptors or a duplicate digest")
    one = selected[0]
    if (one.get("digest") != pins["manifest"] or one.get("mediaType") != MANIFEST_MEDIA
            or type(one.get("size")) is not int or one["size"] != len(blobs["manifest"])):
        raise NativeComponentError("the index descriptor does not bind the exact platform manifest")
    descriptor = manifest.get("config") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2
            or manifest.get("mediaType") != MANIFEST_MEDIA or not isinstance(descriptor, dict)
            or descriptor.get("digest") != pins["config"] or type(descriptor.get("size")) is not int
            or descriptor["size"] != len(blobs["config"]) or not isinstance(manifest.get("layers"), list)
            or not manifest["layers"]):
        raise NativeComponentError("the platform manifest does not bind the exact config")
    rootfs = config.get("rootfs") if isinstance(config, dict) else None
    diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else None
    if (not isinstance(config, dict) or config.get("os") != "linux" or config.get("architecture") != arch
            or not isinstance(rootfs, dict) or rootfs.get("type") != "layers" or not isinstance(diff_ids, list)
            or not diff_ids or not all(isinstance(item, str) and _DIGEST.fullmatch(item) for item in diff_ids)):
        raise NativeComponentError("the config platform or rootfs diff IDs are not exact")
    return {"platform": platform, "architecture": arch, **pins, "diff_ids": list(diff_ids),
            "layers": len(manifest["layers"])}


def verify_image(attrs: Mapping[str, Any], hierarchy: Mapping[str, Any]) -> dict[str, Any]:
    """Observed config ID, every RepoDigest, OS/architecture and exact rootfs; an environment value proves none."""
    repo, rootfs = attrs.get("RepoDigests"), attrs.get("RootFS")
    if attrs.get("Id") != hierarchy["config"]:
        raise NativeComponentError(f"the observed image ID is not the selected config {hierarchy['config']}")
    if not isinstance(repo, list) or not repo or any(
            not isinstance(item, str) or item.rpartition("@")[2] != hierarchy["index"] for item in repo):
        raise NativeComponentError("RepoDigests are missing, foreign or not the approved index")
    if attrs.get("Os") != "linux" or attrs.get("Architecture") != hierarchy["architecture"]:
        raise NativeComponentError(f"the observed image is {attrs.get('Os')}/{attrs.get('Architecture')}")
    layers = rootfs.get("Layers") if isinstance(rootfs, Mapping) else None
    if not isinstance(rootfs, Mapping) or rootfs.get("Type") != "layers" or layers != hierarchy["diff_ids"]:
        raise NativeComponentError("the observed rootfs diff IDs differ from the approved config")
    return {**{key: hierarchy[key] for key in ("platform", "index", "manifest", "config")},
            "manifest_source": "public metadata envelope", "image_config_verified": True,
            "repo_digests": len(repo), "rootfs_layers": len(hierarchy["diff_ids"]), "component_pulled": False}


def verify_override(selected: str | None, hierarchy: Mapping[str, Any], *, required: bool) -> dict[str, Any]:
    exact = selected == hierarchy["config"]
    if required and not exact:
        raise NativeComponentError("the exact raw Python config override is missing or foreign")
    return {"variable": RAW_OVERRIDE_ENV, "selected": exact, "required": required,
            "identity_source": "observed image attributes"}


def configured_default(architecture: str, exclusions: Mapping[str, Any] | None = None) -> payload.PayloadExclusion:
    """ADR 0103: the configured source default; missing, None, malformed and foreign refuse distinctly."""
    found = payload.PYTHON_PAYLOAD_EXCLUSIONS if exclusions is None else exclusions
    if architecture not in found:
        raise NativeComponentError(f"the {architecture} 3.12.16 default is missing from the configured source map")
    if (entry := found[architecture]) is None:
        raise NativeComponentError(f"the {architecture} 3.12.16 default is None (held), not enrolled")
    try:
        if type(entry) is not payload.PayloadExclusion:
            raise TypeError(f"a {type(entry).__name__}, not a PayloadExclusion")
        payload.validate_exclusion(entry, architecture)
    except (payload.PayloadRefusal, TypeError, AttributeError) as error:
        raise NativeComponentError(f"the {architecture} 3.12.16 default is malformed: {error}") from error
    if entry != payload.build_31216_exclusion(architecture, entry.baseline_imports):
        raise NativeComponentError(f"the {architecture} 3.12.16 default is foreign to the frozen native Tk spec")
    return entry


def default_states(exclusions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Pre-probe source facts for both native defaults; only ``validate_observation`` binds one to raw evidence."""
    configured = {architecture: configured_default(architecture, exclusions) for architecture in sorted(MACHINES)}
    return {**{f"{arch}_default_enrolled": True for arch in configured}, "bound_by": "raw native observation"}


def build_inner_script(payload_source: bytes, architecture: str) -> str:
    """The proven ADR 0100 probe for one native architecture: raw report first, then an explicit test-only map."""
    machine = MACHINES[platform_architecture(f"linux/{architecture}")]
    return (
        "import contextlib, io, json, pathlib, subprocess, sys, types\n"
        f"PAYLOAD, ARCH, MACHINE = {payload_source!r}, {architecture!r}, {machine!r}\n"
        "def _hook(kind, error, trace):  # one structured line for any uncaught failure, then the traceback\n"
        f"    record = {{'type': kind.__name__, 'message': str(error)[:2000]}}\n"
        f"    print({ERROR_PREFIX!r} + json.dumps(record), flush=True)\n"
        "    sys.__excepthook__(kind, error, trace)\n"
        "sys.excepthook = _hook\n"
        "assert sys.dont_write_bytecode and sys.flags.isolated == 1 and sys.flags.optimize == 0\n"
        f"assert sys.version.split()[0] == {EXPECTED_PYTHON_VERSION!r}, sys.version\n"
        "banner = subprocess.run([sys.executable, '-I', '-B', '--version'], capture_output=True, text=True,\n"
        "                        check=True).stdout.strip()\n"
        f"assert banner == {EXPECTED_PYTHON_BANNER!r}, banner\n"
        "mod = types.ModuleType('_repomap_py31216_component')\n"
        "mod.__file__ = '<python_payload>'\n"
        "sys.modules[mod.__name__] = mod\n"
        "exec(compile(PAYLOAD, mod.__file__, 'exec'), mod.__dict__)\n"
        "machine = mod.platform.machine()\n"
        "assert machine == MACHINE and mod.NATIVE.get(machine) == ARCH, machine\n"
        "before, _heads = mod._walk(pathlib.Path('/'))\n"
        "out = io.StringIO()\n"
        "with contextlib.redirect_stdout(out):\n"
        "    rc_raw = mod.main([ARCH, '--no-exclusion'])\n"
        "raw = json.loads(out.getvalue().splitlines()[-1])\n"
        f"print({RAW_PREFIX!r} + json.dumps({{'rc': rc_raw, 'report': raw}}, sort_keys=True), flush=True)\n"
        "entry = mod.build_31216_exclusion(ARCH, tuple((raw.get('baseline') or {}).get('imports') or ()))\n"
        "enrolled = ARCH in mod.PYTHON_PAYLOAD_EXCLUSIONS\n"
        "out = io.StringIO()\n"
        "with contextlib.redirect_stdout(out):\n"
        "    rc_trimmed = mod.main([ARCH], exclusions={ARCH: entry})\n"
        "trimmed = json.loads(out.getvalue().splitlines()[-1])\n"
        "after, _heads = mod._walk(pathlib.Path('/'))\n"
        f"print({INNER_PREFIX!r} + json.dumps({{\n"
        "    'python_version': sys.version.split()[0], 'python_banner': banner, 'machine': machine,\n"
        "    'rc_raw': rc_raw, 'rc_trimmed': rc_trimmed, 'default_enrolled': enrolled,\n"
        "    'default_matches': enrolled and mod.PYTHON_PAYLOAD_EXCLUSIONS[ARCH] == entry,\n"
        "    'entry_delta': len(after) - len(before), 'removed': sorted(set(before) - set(after)),\n"
        "    'modified_survivors': sorted(p for p in after if before.get(p) != after.get(p)),\n"
        "    'trimmed_report': trimmed}, sort_keys=True), flush=True)\n"
        "assert rc_raw == 1 and raw['result'] == 'refused', raw.get('reasons')\n"
        "assert rc_trimmed == 0 and trimmed['result'] == 'trimmed', trimmed.get('reasons')\n"
    )


def capture_lines(stdout: bytes) -> list[str]:
    if len(stdout) > CAPTURE_LIMIT:
        raise NativeComponentError(f"the component capture exceeds {CAPTURE_LIMIT} bytes")
    try:
        return stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise NativeComponentError("the component capture is not UTF-8") from error


def _one(lines: Sequence[str], prefix: str, what: str) -> Any:
    found = [line[len(prefix):] for line in lines if line.startswith(prefix)]
    if len(found) != 1:
        raise NativeComponentError(f"expected exactly one {what} line, found {len(found)}")
    return strict_json(found[0], limit=CAPTURE_LIMIT, what=what)


def parse_raw(lines: Sequence[str]) -> dict[str, Any]:
    raw = _one(lines, RAW_PREFIX, "raw observation")
    if not isinstance(raw, dict) or set(raw) != {"rc", "report"} or not isinstance(raw["report"], dict):
        raise NativeComponentError("the raw observation record is not exact")
    return raw


def parse_error(lines: Sequence[str]) -> dict[str, Any] | None:
    """The inner excepthook's sole record, redacted for public evidence; None when nothing was uncaught."""
    if not any(line.startswith(ERROR_PREFIX) for line in lines):
        return None
    error = _one(lines, ERROR_PREFIX, "inner error")
    if not isinstance(error, dict) or set(error) != {"type", "message"} or not all(
            isinstance(value, str) for value in error.values()):
        raise NativeComponentError("the inner error record is not exact")
    return {"type": redact(error["type"])[:100], "message": redact(error["message"])[:600]}


def parse_inner(lines: Sequence[str]) -> dict[str, Any]:
    inner = _one(lines, INNER_PREFIX, "component observation")
    if not isinstance(inner, dict) or set(inner) != INNER_KEYS:
        raise NativeComponentError("the component observation record is not exact")
    return inner


def derive_exclusion(raw_report: Mapping[str, Any], architecture: str) -> payload.PayloadExclusion:
    """The real raw native observation plus the frozen native Tk spec; never a historical or foreign tuple."""
    base, reasons = raw_report.get("baseline"), raw_report.get("reasons")
    if (set(raw_report) != REPORT_KEYS or raw_report["schema"] != payload.SCHEMA
            or raw_report["architecture"] != architecture or raw_report["result"] != "refused"
            or raw_report["exclusion"] is not None or raw_report["retained"] is not None):
        raise NativeComponentError("the raw --no-exclusion report is not an exact refusal")
    if not isinstance(reasons, list) or len(reasons) != 1 or not str(reasons[0]).startswith(
            "PayloadRefusal: no frozen exclusion applies"):
        raise NativeComponentError(f"unexpected raw refusal reasons: {str(reasons)[:300]}")
    if not isinstance(base, dict) or set(base) != BASELINE_KEYS or base["machine"] != MACHINES[architecture]:
        raise NativeComponentError("the raw baseline is malformed or not native")
    imports, failed = base["imports"], base["failed"]
    if (base["dynload_real"] != payload.DYNLOAD or not isinstance(imports, list) or not imports
            or not all(isinstance(name, str) for name in imports) or imports != sorted(set(imports))
            or not isinstance(failed, dict) or sorted(failed) != ["_tkinter"]):
        raise NativeComponentError("raw imports are malformed or another module failed besides _tkinter")
    try:
        entry = payload.build_31216_exclusion(architecture, tuple(imports))
        modules, lost = payload.lib_dynload_modules(base), payload.unresolved(base["elves"])
        payload.classify(base, entry)  # the host's independent classification of the same raw observation
    except (payload.PayloadRefusal, KeyError, TypeError, AttributeError) as error:
        raise NativeComponentError(f"the raw observation refuses the frozen native Tk spec: {error}") from error
    tk = base["elves"].get(entry.path)
    if set(modules) != {*imports, "_tkinter"} or not isinstance(tk, dict) or [
            tk.get("sha256"), tk.get("size"), tk.get("elf")] != [entry.sha256, entry.size, [2, 1, entry.elf_machine]]:
        raise NativeComponentError("the Tk bridge identity or lib-dynload names differ from the frozen spec")
    if sorted(lost) != [f"{entry.path}: {library} => not found" for library in entry.missing]:
        raise NativeComponentError(f"unresolved findings are not exactly missing Tcl and Tk: {lost[:5]}")
    return entry


def validate_observation(raw: Mapping[str, Any], inner: Mapping[str, Any], architecture: str, *,
                         exclusions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Host-side checks of the raw and trimmed contract facts, their preservation and the configured default."""
    try:
        return _validate(raw, inner, architecture, exclusions)
    except (KeyError, TypeError, AttributeError) as error:
        raise NativeComponentError(f"malformed component observation ({type(error).__name__})") from error


def _int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _validate(raw: Mapping[str, Any], inner: Mapping[str, Any], architecture: str,
              exclusions: Mapping[str, Any] | None) -> dict[str, Any]:
    entry = derive_exclusion(raw["report"], architecture)
    expected = {**entry._asdict(), "missing": list(entry.missing), "baseline_imports": len(entry.baseline_imports),
                "reason": TK_REASON}
    facts = (inner["python_version"], inner["python_banner"], inner["machine"])
    if facts != (EXPECTED_PYTHON_VERSION, EXPECTED_PYTHON_BANNER, MACHINES[architecture]):
        raise NativeComponentError(f"interpreter facts differ: {facts}")
    if not (_int(raw["rc"], 1) and _int(inner["rc_raw"], 1) and _int(inner["rc_trimmed"], 0)):
        raise NativeComponentError("the raw contract must refuse (1) and the trimmed contract must pass (0)")
    if not _int(inner["entry_delta"], -1) or inner["removed"] != [entry.path] or inner["modified_survivors"] != []:
        raise NativeComponentError("the trim is not exactly one Tk removal with unchanged survivors")
    if configured_default(architecture, exclusions) != entry:  # host state: the source map against raw facts
        raise NativeComponentError(f"the configured {architecture} default is foreign to the raw native observation")
    enrolled, matches = inner["default_enrolled"], inner["default_matches"]
    if enrolled is not True or matches is not True:
        raise NativeComponentError("an enrolled default differs from the observation: inner flags must equal the host")
    trimmed = inner["trimmed_report"]
    if (not isinstance(trimmed, dict) or set(trimmed) != REPORT_KEYS or trimmed["schema"] != payload.SCHEMA
            or trimmed["architecture"] != architecture or trimmed["result"] != "trimmed"
            or trimmed["reasons"] != [] or trimmed["exclusion"] != expected):
        raise NativeComponentError("the trimmed report is not the exact derived Tk exclusion")
    base, raw_base = trimmed["baseline"], raw["report"]["baseline"]
    if not isinstance(base, dict) or set(base) != BASELINE_KEYS or set(base["elves"]) != set(raw_base["elves"]) or any(
            base[key] != raw_base[key] for key in BASELINE_KEYS - {"elves"}):
        raise NativeComponentError("the trimmed run's baseline differs from the raw observation")
    try:
        if payload.classify(base, entry) != expected:
            raise NativeComponentError("the host classification differs from the trimmed report")
    except payload.PayloadRefusal as error:
        raise NativeComponentError(f"the host classification refuses: {error}") from error
    retained, wanted = trimmed["retained"], list(entry.baseline_imports)
    if (not isinstance(retained, dict) or retained.get("unresolved") != [] or retained.get("preserved") is not True
            or retained.get("excluded_absent") is not True or retained.get("imports") != wanted
            or retained.get("lib_dynload") != wanted or not _int(retained.get("entries"), base["entries"] - 1)
            or retained.get("elves") != {p: e["sha256"] for p, e in base["elves"].items() if p != entry.path}
            or not _int(retained.get("elf_count"), len(retained["elves"]))
            or retained.get("digest") != retained.get("expected_digest") or retained.get("digest") == base["digest"]):
        raise NativeComponentError("retained imports, digests, ELF set or linkage are not preserved")
    owners, targets = retained.get("owners"), retained.get("targets")
    if (not isinstance(owners, dict) or not isinstance(targets, dict) or not owners or set(owners) != set(targets)
            or not all(isinstance(v, str) and v.strip() for v in owners.values())
            or not all(isinstance(t, list) and len(t) == 2 and isinstance(t[0], str) for t in targets.values())):
        raise NativeComponentError("retained shared-library ownership is incomplete")
    return {"architecture": architecture, "before_entries": base["entries"], "after_entries": retained["entries"],
            "before_digest": base["digest"], "after_digest": retained["digest"], "excluded_path": entry.path,
            "excluded_sha256": entry.sha256, "excluded_size": entry.size, "excluded_elf_machine": entry.elf_machine,
            "excluded_missing": list(entry.missing), "baseline_imports": wanted,
            "baseline_import_count": len(wanted), "retained_elf_count": retained["elf_count"],
            "retained_owner_count": len(owners), "default_enrolled": enrolled, "unresolved": []}
