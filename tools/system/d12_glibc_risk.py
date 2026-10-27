"""ADR 0101 finite Trixie glibc risk disposition: exact record verification and per-image libc assessment.

Stdlib-only. ``accepted_unresolved`` is returned only for the exact approved record together with complete native
libc6 evidence from each named image. Risk acceptance never waives missing, unknown or conflicting identity, byte,
owner, version or notice evidence, and never qualifies an image or relabels a finding.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

RECORD_RELPATH = "tools/ci/d12_glibc_risk_disposition.json"
RECORD_PATH = Path(__file__).resolve().parents[1] / "ci" / "d12_glibc_risk_disposition.json"
APPROVED_RECORD_SHA256 = "5ed32d84313cadab05514c0372b53c0e9e3081de9d2df072cde4bf989e2b0231"
MAX_RECORD_BYTES = 65_536
RECORD_SCHEMA = "repomap-d12-glibc-disposition-v1"
RESULT_SCHEMA = "repomap-d12-glibc-assessment-v1"
ACCEPTED, REFUSED = "accepted_unresolved", "refused"
SOURCE_VERSION = "2.41-12+deb13u4"
OWNER = "Samuel Leighton Lair"
POSTGRES_INDEX = "sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97"
PYTHON_INDEX = "sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e"
BASE_REFERENCES = (f"postgres:16.15-trixie@{POSTGRES_INDEX}", f"python:3.12-slim-trixie@{PYTHON_INDEX}")
# platform -> (dpkg architecture, uname -m, Debian multiarch triplet)
PLATFORMS = {
    "linux/amd64": ("amd64", "x86_64", "x86_64-linux-gnu"),
    "linux/arm64": ("arm64", "aarch64", "aarch64-linux-gnu"),
}
OS_PRETTY_NAME = "Debian GNU/Linux 13 (trixie)"
LIBC_PACKAGE, LIBC_SONAME, LIBC_NOTICE = "libc6", "libc.so.6", "/usr/share/doc/libc6/copyright"
GLIBC_PACKAGES = (LIBC_PACKAGE, "libc-bin")  # the essential glibc-source pair (loaded libc and ldd/ldconfig)
FINDING_IDS = (
    "CVE-2010-4756", "CVE-2018-20796", "CVE-2019-1010022", "CVE-2019-1010023", "CVE-2019-1010024",
    "CVE-2019-1010025", "CVE-2019-9192", "CVE-2026-18374", "CVE-2026-19499", "CVE-2026-19542", "CVE-2026-5435",
    "CVE-2026-6238", "CVE-2026-6368", "CVE-2026-6791", "CVE-2026-77117", "CVE-2026-80489", "CVE-2026-8674",
    "CVE-2026-86805", "CVE-2026-89092", "CVE-2026-95818", "CVE-2026-97399",
)
FIXED_RECORD_VALUES: dict[str, object] = {
    "accepts_image_or_other_findings": False, "component": "glibc", "decision": "accept_unresolved",
    "decision_date": "2026-10-27", "distribution": "debian-trixie",
    "operator_statement": "Stick with Debian Trixie and accept the glibc risk.", "owner": OWNER,
    "phase": "REPOMAP-PRODUCT6-NAVIGATION47-CI73TRIXIE1", "platforms": sorted(PLATFORMS),
    "postgres_index": POSTGRES_INDEX, "python_index": PYTHON_INDEX,
    "retained_catalogue_sha256": "b7be264228c3ab778074c27171cd0e7da7a7ae25adf7e2056e1e14e297feee6d",
    "schema": RECORD_SCHEMA, "source_version": SOURCE_VERSION,
}
RECORD_FIELDS = frozenset({*FIXED_RECORD_VALUES, "advisories"})
FINDING_FIELDS = frozenset({
    "class", "disposition", "highest_reported_band", "highest_reported_score", "id", "owner", "primary",
    "secondary", "secondary_sha256",
})
RECORDED_CLASSES = ("affected", "unknown")  # never fixed, outside_affected_range or image-qualified
BANDS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_CVE = re.compile(r"CVE-(\d{4})-(\d{4,})")
_TEXT_LIMIT = 600


class GlibcRiskError(ValueError):
    """Raised when the glibc disposition record or libc evidence cannot support accepted_unresolved."""


def _need(condition: object, message: str) -> None:
    if not condition:
        raise GlibcRiskError(message)


def _short(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _TEXT_LIMIT else text[:_TEXT_LIMIT] + "...<truncated>"


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        _need(key not in out, f"duplicate JSON key {key!r} in glibc disposition record")
        out[key] = value
    return out


def _no_constant(name: str) -> Any:
    raise GlibcRiskError(f"non-finite JSON constant {name} in glibc disposition record")


def strict_json_loads(raw: bytes) -> Any:
    """Bounded strict UTF-8 JSON: duplicate keys and non-finite constants refuse."""
    _need(isinstance(raw, bytes), "glibc disposition record must be bytes")
    _need(0 < len(raw) <= MAX_RECORD_BYTES, f"glibc disposition record size {len(raw)} outside 1..{MAX_RECORD_BYTES}")
    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GlibcRiskError(f"glibc disposition record is not strict UTF-8 JSON: {exc}") from exc


def read_record_bytes(path: Path = RECORD_PATH) -> bytes:
    """Read at most MAX_RECORD_BYTES + 1 bytes from a regular file; larger files refuse."""
    _need(path.is_file(), f"glibc disposition record is not a regular file: {RECORD_RELPATH}")
    with path.open("rb") as handle:
        raw = handle.read(MAX_RECORD_BYTES + 1)
    _need(len(raw) <= MAX_RECORD_BYTES, f"glibc disposition record exceeds {MAX_RECORD_BYTES} bytes")
    return raw


def _secondary_url(finding_id: str) -> str:
    if (match := _CVE.fullmatch(finding_id)) is None:
        raise GlibcRiskError(f"malformed finding id {finding_id!r}")
    year, number = match.group(1), int(match.group(2))
    return (f"https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/{year}/{number // 1000}xxx/"
            f"{finding_id}.json")


def _validate_finding(item: object, expected_id: str) -> None:
    if not isinstance(item, Mapping):
        raise GlibcRiskError(f"glibc finding is not an object: {_short(item)}")
    keys = set(item)
    _need(keys == FINDING_FIELDS, f"glibc finding {item.get('id')!r} fields missing "
          f"{sorted(FINDING_FIELDS - keys)} extra {sorted(keys - FINDING_FIELDS)}")
    finding_id = item["id"]
    _need(finding_id == expected_id, f"glibc finding {finding_id!r} is not the approved {expected_id!r}")
    _need(item["class"] in RECORDED_CLASSES, f"{finding_id} class {item['class']!r} is not affected/unknown")
    _need(item["disposition"] == ACCEPTED, f"{finding_id} disposition {item['disposition']!r} != {ACCEPTED!r}")
    _need(item["owner"] == OWNER, f"{finding_id} owner {item['owner']!r} != {OWNER!r}")
    _need(item["highest_reported_band"] in BANDS, f"{finding_id} band {item['highest_reported_band']!r}")
    score = item["highest_reported_score"]
    _need(type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 10, f"{finding_id} score {score!r}")
    _need(item["primary"] == f"https://security-tracker.debian.org/tracker/{finding_id}",
          f"{finding_id} primary URL {item['primary']!r}")
    _need(item["secondary"] == _secondary_url(finding_id), f"{finding_id} secondary URL {item['secondary']!r}")
    sha = item["secondary_sha256"]
    _need(isinstance(sha, str) and _SHA256.fullmatch(sha), f"{finding_id} secondary_sha256 {sha!r}")


def validate_record(data: object) -> dict[str, Any]:
    """Validate the closed record shape: fixed decision fields and exactly the finite 21 findings in order."""
    if not isinstance(data, Mapping):
        raise GlibcRiskError("glibc disposition record is not a JSON object")
    keys = set(data)
    _need(keys == RECORD_FIELDS,
          f"glibc disposition fields missing {sorted(RECORD_FIELDS - keys)} extra {sorted(keys - RECORD_FIELDS)}")
    for key, expected in FIXED_RECORD_VALUES.items():
        value = data[key]
        _need(type(value) is type(expected) and value == expected,
              f"glibc disposition {key} {_short(value)} != approved {_short(expected)}")
    advisories = data["advisories"]
    _need(isinstance(advisories, list), "glibc disposition advisories must be a list")
    ids = [item.get("id") if isinstance(item, Mapping) else None for item in advisories]
    if not all(isinstance(i, str) for i in ids):
        raise GlibcRiskError(f"glibc finding ids must be strings: {_short(ids)}")
    finding_ids = {str(i) for i in ids}
    _need(len(ids) == len(set(ids)), f"duplicate glibc finding ids: {_short(ids)}")
    _need(finding_ids == set(FINDING_IDS), f"glibc findings missing {sorted(set(FINDING_IDS) - finding_ids)} "
          f"foreign/future {sorted(finding_ids - set(FINDING_IDS))}")
    _need(tuple(ids) == FINDING_IDS, "glibc findings are not in the approved order")
    for item, expected_id in zip(advisories, FINDING_IDS, strict=True):
        _validate_finding(item, expected_id)
    return dict(data)


def load_approved_record(raw: bytes | None = None) -> dict[str, Any]:
    """Return the record only when its exact bytes hash to the approved SHA-256 and the closed shape validates."""
    record_bytes = read_record_bytes() if raw is None else raw
    _need(isinstance(record_bytes, bytes), "glibc disposition record must be bytes")
    digest = hashlib.sha256(record_bytes).hexdigest()
    _need(digest == APPROVED_RECORD_SHA256,
          f"glibc disposition record SHA-256 {digest} != approved {APPROVED_RECORD_SHA256}")
    return validate_record(strict_json_loads(record_bytes))


def _rows(inventory: Mapping[str, Any], key: str) -> list[Any]:
    rows = inventory.get(key)
    if not isinstance(rows, list):
        raise GlibcRiskError(f"inventory {key} must be a list, got {_short(rows)}")
    return rows


def _libc_file(row: object) -> bool:
    if not isinstance(row, Mapping):
        return False
    return any(str(row.get(field) or "").rsplit("/", 1)[-1] == LIBC_SONAME for field in ("invoked", "resolved"))


def assess_libc_inventory(
    *, label: object, base_reference: object, image_id: object, platform: object, execution: object,
    inventory: object,
) -> dict[str, Any]:
    """Assess one image's ``_inventory``-shaped observation of the real loaded libc6 file."""
    _need(isinstance(label, str) and label.strip(), f"image label {_short(label)} must be a non-empty string")
    _need(base_reference in BASE_REFERENCES, f"{label}: base {_short(base_reference)} is not an approved index")
    _need(isinstance(image_id, str) and _IMAGE_ID.fullmatch(image_id),
          f"{label}: image identity {_short(image_id)} is not an observed sha256 image ID")
    _need(image_id not in (POSTGRES_INDEX, PYTHON_INDEX), f"{label}: an index digest is not an image identity")
    _need(isinstance(platform, str) and platform in PLATFORMS,
          f"{label}: platform {_short(platform)} is not an approved native platform")
    _need(execution == "native", f"{label}: {platform} execution {_short(execution)} is not native")
    if not isinstance(inventory, Mapping):
        raise GlibcRiskError(f"{label}: inventory is not an object")
    dpkg_arch, machine, triplet = PLATFORMS[str(platform)]
    os_row = inventory.get("os")
    if not isinstance(os_row, list) or os_row != [OS_PRETTY_NAME, machine, dpkg_arch]:
        raise GlibcRiskError(
            f"{label}: os/architecture {_short(os_row)} != {[OS_PRETTY_NAME, machine, dpkg_arch]}")
    packages = _rows(inventory, "packages")
    for name in GLIBC_PACKAGES:
        found = [row for row in packages if isinstance(row, list) and row[:1] == [name]]
        _need(found == [[name, SOURCE_VERSION, dpkg_arch]],
              f"{label}: {name} package rows {_short(found)} != one native {SOURCE_VERSION} {dpkg_arch} row")
    files = [row for row in _rows(inventory, "files") if _libc_file(row)]
    _need(files, f"{label}: no observed {LIBC_SONAME} file evidence")
    fields = ("resolved", "kind", "sha256", "interpreter", "owner", "md5")
    _need(all(isinstance(row.get(field), str) for row in files for field in ("invoked", *fields)),
          f"{label}: incomplete {LIBC_SONAME} observation {_short(files)}")
    distinct = {tuple(row.get(field) for field in fields) for row in files}
    _need(len(distinct) == 1, f"{label}: conflicting {LIBC_SONAME} observations {_short(sorted(map(str, distinct)))}")
    resolved, kind, sha256, interpreter, owner, md5 = next(iter(distinct))
    expected_path = f"/usr/lib/{triplet}/{LIBC_SONAME}"
    _need(resolved == expected_path, f"{label}: libc resolved path {_short(resolved)} != {expected_path}")
    _need(kind == "elf" and interpreter == "-", f"{label}: libc kind {_short(kind)}/{_short(interpreter)} != elf")
    _need(isinstance(sha256, str) and _SHA256.fullmatch(sha256), f"{label}: libc SHA-256 {_short(sha256)} unknown")
    _need(owner == LIBC_PACKAGE, f"{label}: libc owner {_short(owner)} != {LIBC_PACKAGE}")
    _need(md5 == "match", f"{label}: libc dpkg md5 {_short(md5)} != match")
    invoked = {row.get("invoked") for row in files}
    links = [row for row in _rows(inventory, "links") if isinstance(row, list) and row[1:2] == [LIBC_SONAME]]
    _need(links, f"{label}: no ldd observation loads {LIBC_SONAME}")
    _need(all(len(row) == 3 and isinstance(row[2], str) and row[2] in invoked for row in links),
          f"{label}: ldd {LIBC_SONAME} mappings {_short(links)} do not resolve to the observed file")
    notices = inventory.get("notices")
    notice = notices.get(LIBC_NOTICE) if isinstance(notices, Mapping) else None
    _need(isinstance(notice, str) and _SHA256.fullmatch(notice), f"{label}: libc notice {_short(notice)} unknown")
    return {
        "label": label, "base_reference": base_reference, "image_id": image_id, "platform": platform,
        "execution": "native", "os": list(os_row), "package": [LIBC_PACKAGE, SOURCE_VERSION, dpkg_arch],
        "glibc_packages": [[name, SOURCE_VERSION, dpkg_arch] for name in GLIBC_PACKAGES],
        "libc": {"path": resolved, "sha256": sha256, "owner": owner, "md5": md5, "file_observations": len(files),
                 "ldd_observations": len(links)},
        "notice": {"path": LIBC_NOTICE, "sha256": notice},
    }


def _identity(image: object) -> dict[str, Any]:
    if not isinstance(image, Mapping):
        return {"label": _short(image)}
    return {key: str(image.get(key))[:_TEXT_LIMIT] for key in ("label", "base_reference", "image_id", "platform")}


def assess_glibc_disposition(images: Sequence[object], *, record_bytes: bytes | None = None) -> dict[str, Any]:
    """Raise unless the exact record and every image's libc6 evidence support accepted_unresolved."""
    record = load_approved_record(record_bytes)
    _need(len(images) > 0, "glibc assessment requires at least one image")
    observed: list[dict[str, Any]] = []
    for img in images:
        if not isinstance(img, Mapping):
            raise GlibcRiskError(f"image entry is not an object: {_short(img)}")
        observed.append(assess_libc_inventory(
            label=img.get("label"), base_reference=img.get("base_reference"), image_id=img.get("image_id"),
            platform=img.get("platform"), execution=img.get("execution"), inventory=img.get("inventory")))
    labels, ids = [o["label"] for o in observed], [o["image_id"] for o in observed]
    _need(len(set(labels)) == len(labels), f"glibc image labels are not distinct: {labels}")
    _need(len(set(ids)) == len(ids), f"glibc per-image identities are not distinct: {ids}")
    for platform in {o["platform"] for o in observed}:
        same = {(o["libc"]["sha256"], o["notice"]["sha256"]) for o in observed if o["platform"] == platform}
        _need(len(same) == 1, f"conflicting libc6 {SOURCE_VERSION} bytes or notices on {platform}: {sorted(same)}")
    return {
        "schema": RESULT_SCHEMA, "status": ACCEPTED, "component": "glibc", "source_version": SOURCE_VERSION,
        "owner": OWNER, "decision": record["decision"], "record_path": RECORD_RELPATH,
        "record_sha256": APPROVED_RECORD_SHA256, "retained_catalogue_sha256": record["retained_catalogue_sha256"],
        "images": observed, "findings": [dict(item) for item in record["advisories"]],
        "accepts_image_or_other_findings": False, "image_qualified": False,
    }


def evaluate_glibc_disposition(images: Sequence[object], *, record_bytes: bytes | None = None) -> dict[str, Any]:
    """Non-raising form for retained sidecars: a refusal keeps image/platform identities and the record digest."""
    try:
        return assess_glibc_disposition(images, record_bytes=record_bytes)
    except (GlibcRiskError, OSError) as exc:  # an unreadable record is a retained refusal too
        refusal = (str(exc) if isinstance(exc, GlibcRiskError)
                   else f"{type(exc).__name__} reading {RECORD_RELPATH} (errno={exc.errno})")
        return {
            "schema": RESULT_SCHEMA, "status": REFUSED, "component": "glibc", "source_version": SOURCE_VERSION,
            "record_path": RECORD_RELPATH, "record_sha256": APPROVED_RECORD_SHA256,
            "refusal": refusal[:2 * _TEXT_LIMIT], "images": [_identity(img) for img in images[:8]],
            "accepts_image_or_other_findings": False, "image_qualified": False,
        }


def evaluate_d12_post_build(
    *, candidate_image_id: object, candidate_inventory: object, server_image_id: object, server_inventory: object,
    base_reference: str, platform: str, availability: Mapping[str, Any],
) -> dict[str, Any]:
    """The D12 runtime stage and pinned service both derive from the PostgreSQL base; each is assessed separately."""
    observed_platform = availability.get("platform")
    execution = availability.get("execution") if observed_platform == platform else f"for {observed_platform!r}"
    return evaluate_glibc_disposition([
        {"label": "candidate", "base_reference": base_reference, "image_id": candidate_image_id,
         "platform": platform, "execution": execution, "inventory": candidate_inventory},
        {"label": "server", "base_reference": base_reference, "image_id": server_image_id,
         "platform": platform, "execution": execution, "inventory": server_inventory},
    ])
