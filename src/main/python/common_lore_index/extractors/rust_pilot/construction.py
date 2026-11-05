"""Fresh exact-container construction, readback, probe and parse execs (spec 5.2-5.6).

Construction order is fixed: create, start, host inspection, one setup-only
UID 0 exec that receives only verified artifact/helper/notice bytes, then a
separate non-root readback that the parent verifies byte for byte together
with guest-observed confinement. No target byte exists before that passes,
and no root exec runs after sealing. Every created ID is handed to the
caller's ownership list first, so settlement never depends on success here.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any, TypeGuard

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.archive_verifier import (
    ExpectedEntry,
    expected_install_tree,
    expected_tree_digest,
)
from common_lore_index.extractors.rust_pilot.bounded_exec import ExecResult
from common_lore_index.extractors.rust_pilot.component_lock import NOTICES
from common_lore_index.extractors.rust_pilot.docker_boundary import (
    PARSER_USER,
    RUNTIME_ROOT,
    SCRATCH,
    SETUP_USER,
    DockerBoundary,
    check_container_config,
)
from common_lore_index.extractors.rust_pilot.guest_sources import GuestSources
from common_lore_index.extractors.rust_pilot.helper_protocol import MAX_OUTPUT, encode_request
from common_lore_index.extractors.rust_pilot.prepared_profile import VerifiedProfile
from common_lore_index.extractors.rust_pilot.readback import (
    MAX_READBACK,
    GuestFacts,
    decode_readback,
    verify_confinement,
    verify_install_tree,
)

SETUP_MAGIC = b"REPOMAP-RUST-SETUP-1\n"
SETUP_OK = b"REPOMAP-RUST-SETUP-OK "
MAX_SETUP_HEADER = 65_536
MAX_SETUP_PAYLOAD = 4 * 1_048_576
CONSTRUCTION_BUDGET = 30.0
PROBE_DEADLINE = 10.0
PROBE_STDOUT_LIMIT = 65_536
PARSE_DEADLINE = 5.0
PYTHON_FLAGS = ("-I", "-S", "-B")
EXPECTED_PYTHON = ("/usr/local/bin/python3.13", "3.13.12", "cpython-313")
EXPECTED_ABI_VERSION = 15
MIN_GLIBC = (2, 28)
REQUIRED_KINDS = ("mod_item", "function_item", "function_signature_item", "struct_item", "enum_item",
                  "union_item", "type_item", "trait_item", "impl_item", "macro_definition",
                  "macro_invocation", "const_item", "static_item", "use_declaration",
                  "extern_crate_declaration", "foreign_mod_item", "inner_attribute_item",
                  "attribute_item", "declaration_list", "visibility_modifier")
REQUIRED_FIELDS = ("name", "type", "trait", "body")
WheelPayload = tuple[str, bytes, str, Sequence[str], Sequence[tuple[str, int, str, int]]]


class ConstructionRefused(ContractError):
    """Construction, readback or runtime-probe refusal; the code is categorical."""


@dataclass(frozen=True)
class RuntimeMaterial:
    setup_stream: bytes
    expected: tuple[ExpectedEntry, ...]
    expected_digest: str
    sources: GuestSources


@dataclass(frozen=True)
class Constructed:
    container_id: str
    readback_digest: str
    guest: GuestFacts
    readback_bytes: int
    elapsed: float
    readback_elapsed: float
    installed_bytes: int


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_int(value: object) -> TypeGuard[int]:
    """Narrow only actual ints; bool remains refused as an int observation."""

    return type(value) is int


def load_notices() -> tuple[tuple[str, bytes], ...]:
    """Supplemental notice bytes from package data, checked against the lock."""

    package = resources.files("common_lore_index").joinpath("third_party_licenses")
    result = []
    for notice in NOTICES:
        data = package.joinpath(notice.package_file).read_bytes()
        if len(data) != notice.size or _sha(data) != notice.sha256:
            raise ConstructionRefused("notice_mismatch")
        result.append((notice.installed_name, data))
    return tuple(result)


def encode_setup_stream(wheels: Sequence[WheelPayload], helper: bytes,
                        notices: Sequence[tuple[str, bytes]]) -> bytes:
    """Magic line, one JSON header line and the payload bytes back to back."""

    payloads: list[dict[str, Any]] = []
    blobs: list[bytes] = []
    for filename, data, dist_info, top_level, members in wheels:
        payloads.append({"class": "wheel", "name": filename, "size": len(data),
                         "sha256": _sha(data), "dist_info": dist_info,
                         "top_level": list(top_level), "members": [list(member) for member in members]})
        blobs.append(data)
    payloads.append({"class": "helper", "name": "parse_helper.py", "size": len(helper),
                     "sha256": _sha(helper)})
    blobs.append(helper)
    for name, data in notices:
        payloads.append({"class": "notice", "name": name, "size": len(data), "sha256": _sha(data)})
        blobs.append(data)
    header = json.dumps({"v": 1, "payloads": payloads}, sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(header) > MAX_SETUP_HEADER or sum(len(blob) for blob in blobs) > MAX_SETUP_PAYLOAD:
        raise ConstructionRefused("setup_stream_too_large")
    return SETUP_MAGIC + header + b"\n" + b"".join(blobs)


def build_material(profile: VerifiedProfile, sources: GuestSources,
                   notices: Sequence[tuple[str, bytes]]) -> RuntimeMaterial:
    wheels = [(wheel.lock.filename, wheel.data, wheel.lock.dist_info, wheel.lock.top_level,
               [(item.name, item.size, item.sha256, item.wheel_mode) for item in wheel.lock.members]) for wheel in profile.wheels]
    expected = expected_install_tree([wheel.members for wheel in profile.wheels], sources.parse_helper, notices)
    return RuntimeMaterial(encode_setup_stream(wheels, sources.parse_helper, notices), expected,
                           expected_tree_digest(expected), sources)


def construct(boundary: DockerBoundary, *, run_id: str, seq: int, docker_arch: str, image_id: str,
              material: RuntimeMaterial, owned: list[str],
              clock: Callable[[], float] = time.monotonic) -> Constructed:
    """Construct and verify one fresh container; refuse on any deviation."""

    started = clock()
    deadline = started + CONSTRUCTION_BUDGET

    def remaining() -> float:
        left = deadline - clock()
        if left <= 0:
            raise ConstructionRefused("construction_deadline")
        return left

    container_id = boundary.create(run_id=run_id, seq=seq, docker_arch=docker_arch, image_id=image_id,
                                   hard_end=deadline, owned=owned)
    boundary.start(container_id, hard_end=deadline)
    check_container_config(boundary.inspect(container_id, hard_end=deadline), container_id=container_id, image_id=image_id,
                           run_id=run_id, seq=seq)
    setup = boundary.run_guest(container_id, user=SETUP_USER, workdir="/",
                          tail=[*PYTHON_FLAGS, "-c", material.sources.text("setup_writer")],
                          stdin=material.setup_stream, stdout_limit=4_096, deadline=remaining(), hard_end=deadline)
    if not setup.clean or not setup.stdout.startswith(SETUP_OK):
        raise ConstructionRefused("setup_failed")
    readback_started = clock()
    readback = boundary.run_guest(container_id, user=PARSER_USER,
                             tail=[*PYTHON_FLAGS, "-c", material.sources.text("install_readback")],
                             stdin=None, stdout_limit=MAX_READBACK, deadline=remaining(), hard_end=deadline)
    if not readback.clean:
        raise ConstructionRefused("readback_failed")
    decoded = decode_readback(readback.stdout)
    digest = verify_install_tree(decoded, material.expected)
    if digest != material.expected_digest:
        raise ConstructionRefused("readback_digest")
    guest = verify_confinement(decoded)
    remaining()
    finished = clock()
    return Constructed(container_id, digest, guest, len(readback.stdout), finished - started,
                       finished - readback_started,
                       sum(len(entry.data) for entry in material.expected if entry.data is not None))


def _glibc_ok(libc: object) -> bool:
    if type(libc) is not list or len(libc) != 2 or libc[0] != "glibc" or type(libc[1]) is not str:
        return False
    try:
        version = tuple(int(part) for part in libc[1].split(".")[:2])
    except ValueError:
        return False
    return version >= MIN_GLIBC


def check_runtime_facts(facts: dict[str, Any], cpu: str) -> None:
    """Spec 5.6 requirements; values are recorded observations, not pins."""

    kinds = facts.get("kind_ids") or {}
    fields = facts.get("field_ids") or {}
    low: object = facts.get("min_compatible_language_version")
    abi: object = facts.get("abi_version")
    high: object = facts.get("language_version")
    version_range_ok = (
        _strict_int(low) and _strict_int(abi) and _strict_int(high)
        and low <= abi <= high
    )
    checks = (
        facts.get("import") == "ok",
        (facts.get("executable"), facts.get("version"), facts.get("cache_tag")) == EXPECTED_PYTHON,
        facts.get("soabi") == f"cpython-313-{cpu}-linux-gnu", facts.get("abiflags") == "",
        facts.get("machine") == cpu, _glibc_ok(facts.get("libc")), facts.get("ts_version") == "0.26.0",
        version_range_ok,
        abi == EXPECTED_ABI_VERSION,
        all(type(kinds.get(kind)) is int and kinds[kind] > 0 for kind in REQUIRED_KINDS),
        all(type(fields.get(name)) is int and fields[name] > 0 for name in REQUIRED_FIELDS),
        type(facts.get("module_files")) is list and len(facts["module_files"]) == 2
        and all(type(path) is str and path.startswith(RUNTIME_ROOT + "/site/") for path in facts["module_files"]),
    )
    if not all(checks):
        raise ConstructionRefused("runtime_mismatch")


def run_runtime_probe(boundary: DockerBoundary, container_id: str, material: RuntimeMaterial,
                      cpu: str) -> dict[str, Any]:
    result = boundary.run_guest(container_id, user=PARSER_USER,
                           tail=[*PYTHON_FLAGS, "-c", material.sources.text("runtime_probe")],
                           stdin=None, stdout_limit=PROBE_STDOUT_LIMIT, deadline=PROBE_DEADLINE)
    if not result.clean:
        raise ConstructionRefused("runtime_probe_failed")
    try:
        facts = json.loads(result.stdout.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise ConstructionRefused("runtime_probe_unparseable") from None
    if type(facts) is not dict or facts.get("t") != "probe":
        raise ConstructionRefused("runtime_probe_unparseable")
    check_runtime_facts(facts, cpu)
    return facts


def parse_exec(boundary: DockerBoundary, container_id: str, data: bytes, nonce: str) -> ExecResult:
    """The fixed non-root parse exec with bounded stdin, stdout and stderr."""

    return boundary.run_guest(container_id, user=PARSER_USER, workdir=SCRATCH,
                         tail=[*PYTHON_FLAGS, "-X", "utf8", f"{RUNTIME_ROOT}/helper/parse_helper.py"],
                         stdin=encode_request(data, nonce), stdout_limit=MAX_OUTPUT, deadline=PARSE_DEADLINE)


def container_state(boundary: DockerBoundary, container_id: str, *,
                    hard_end: float | None = None) -> tuple[bool, bool]:
    """(running, oom_killed) from host inspection after a parse exec."""

    state = boundary.inspect(container_id, hard_end=hard_end).get("State") or {}
    return state.get("Running") is True, state.get("OOMKilled") is True


def resource_facts(boundary: DockerBoundary, container_id: str, material: RuntimeMaterial,
                   *, hard_end: float) -> tuple[int | None, str | None]:
    """Read only guest-reported cgroup memory inside the existing settlement budget."""

    try:
        result = boundary.observe_cost(container_id, material.sources.text("runtime_probe"), hard_end=hard_end)
        if not result.clean:
            return None, "cost_unobservable"
        value = json.loads(result.stdout.decode("ascii"))
        if type(value) is not dict or value.get("t") != "cost":
            return None, "cost_unobservable"
        peak = value.get("memory_peak_bytes")
        if type(peak) is int and peak >= 0 and value.get("unavailable_reason") is None:
            return peak, None
        if peak is None and value.get("unavailable_reason") == "cgroup_peak_unavailable":
            return None, "cgroup_peak_unavailable"
    except (ContractError, UnicodeDecodeError, ValueError):
        pass
    return None, "cost_unobservable"
