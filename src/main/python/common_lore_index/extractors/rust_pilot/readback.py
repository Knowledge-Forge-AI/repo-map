"""Strict decoding and parent verification of the install readback (spec 5.4).

The parent requires the read-back path set, bytes, modes, owners and link
counts to equal its own in-memory expected tree. Mount, credential, scratch
and interface lines are guest-reported; they are labelled ``guest_observed``
and cross-checked against host-side container inspection by the caller.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from common_lore_index.extractors.contracts.vocabulary import ContractError
from common_lore_index.extractors.rust_pilot.archive_verifier import ExpectedEntry, tree_digest
from common_lore_index.extractors.rust_pilot.docker_boundary import RUNTIME_ROOT, SCRATCH

MAX_READBACK = 8 * 1_048_576
MAX_HEADER = 4_096
PARSER_ID = "10001"
_ENTRY_KEYS = frozenset({"t", "path", "type", "mode", "uid", "gid", "nlink", "size"})


class ReadbackRefused(ContractError):
    """Install readback or confinement refusal; the message is the closed code only."""


@dataclass(frozen=True)
class ReadEntry:
    path: str
    kind: str
    mode: int
    uid: int
    gid: int
    nlink: int
    data: bytes | None


@dataclass(frozen=True)
class Readback:
    entries: tuple[ReadEntry, ...]
    mounts: tuple[str, ...]
    status: tuple[str, ...]
    scratch: tuple[str, ...] | None
    ifaces: tuple[str, ...]
    network: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class GuestFacts:
    """Guest-reported confinement facts, labelled as such."""

    label: str
    uid: str
    gid: str
    no_new_privs: str
    seccomp: str | None


def _header(stdout: bytes, offset: int) -> tuple[dict[str, Any], int]:
    end = stdout.find(b"\n", offset, offset + MAX_HEADER)
    if end < 0:
        raise ReadbackRefused("readback_framing")
    try:
        value = json.loads(stdout[offset:end].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise ReadbackRefused("readback_framing") from None
    if type(value) is not dict:
        raise ReadbackRefused("readback_framing")
    return value, end + 1


def _int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ReadbackRefused("readback_framing")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise ReadbackRefused("readback_framing")
    return tuple(value)


def decode_readback(stdout: bytes) -> Readback:
    """Decode the complete readback stream or refuse."""

    if type(stdout) is not bytes or len(stdout) > MAX_READBACK:
        raise ReadbackRefused("readback_too_large")
    offset = 0
    entries: list[ReadEntry] = []
    sections: dict[str, Any] = {}
    while True:
        value, offset = _header(stdout, offset)
        tag = value.get("t")
        if tag == "entry":
            if set(value) != _ENTRY_KEYS or value["type"] not in ("d", "f") or sections:
                raise ReadbackRefused("readback_framing")
            size = _int(value["size"])
            data = None
            if value["type"] == "f":
                data = stdout[offset:offset + size]
                if len(data) != size:
                    raise ReadbackRefused("readback_framing")
                offset += size
            elif size:
                raise ReadbackRefused("readback_framing")
            entries.append(ReadEntry(value["path"] if type(value["path"]) is str else "\x00", value["type"],
                                     _int(value["mode"]), _int(value["uid"]), _int(value["gid"]),
                                     _int(value["nlink"]), data))
        elif tag in ("mounts", "status", "scratch", "ifaces") and tag not in sections:
            sections[tag] = value
        elif tag == "end":
            break
        else:
            raise ReadbackRefused("readback_framing")
    if offset != len(stdout) or set(value) != {"t", "entries"} or _int(value["entries"]) != len(entries):
        raise ReadbackRefused("readback_framing")
    if set(sections) != {"mounts", "status", "scratch", "ifaces"}:
        raise ReadbackRefused("readback_framing")
    scratch = sections["scratch"].get("names")
    network = sections["ifaces"].get("facts", [])
    if type(network) is not list or len(network) > 4 or any(type(item) is not dict for item in network):
        raise ReadbackRefused("readback_framing")
    return Readback(tuple(entries), _strings(sections["mounts"].get("lines")),
                    _strings(sections["status"].get("lines")),
                    None if scratch is None else _strings(scratch), _strings(sections["ifaces"].get("names")),
                    tuple(network))


def verify_install_tree(readback: Readback, expected: Sequence[ExpectedEntry], *,
                        owner: tuple[int, int] = (0, 0)) -> str:
    """Require exact equality with the parent's tree; return the read-back tree digest."""

    paths = [entry.path for entry in readback.entries]
    if len(paths) != len(set(paths)) or set(paths) != {entry.path for entry in expected}:
        raise ReadbackRefused("install_path_set")
    actual = {entry.path: entry for entry in readback.entries}
    for wanted in expected:
        got = actual[wanted.path]
        if got.kind != wanted.kind or got.mode != wanted.mode:
            raise ReadbackRefused("install_mode")
        if (got.uid, got.gid) != owner:
            raise ReadbackRefused("install_owner")
        if wanted.kind == "f" and (got.nlink != 1 or got.data != wanted.data):
            raise ReadbackRefused("install_bytes")
    return tree_digest((entry.path, entry.kind, entry.mode, entry.data) for entry in readback.entries)


def _mount(lines: Sequence[str], point: str) -> tuple[set[str], str, set[str]]:
    matches = [line.split(" ") for line in lines if len(line.split(" ")) > 5 and line.split(" ")[4] == point]
    if len(matches) != 1 or "-" not in matches[0]:
        raise ReadbackRefused("guest_mount_" + point.strip("/").replace("/", "_"))
    fields = matches[0]
    separator = fields.index("-")
    if len(fields) < separator + 4:
        raise ReadbackRefused("guest_mount_shape")
    return set(fields[5].split(",")), fields[separator + 1], set(fields[separator + 3].split(","))


def _status(lines: Sequence[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for line in lines:
        key, _, rest = line.partition(":")
        result[key] = rest.split()
    return result


def verify_confinement(readback: Readback) -> GuestFacts:
    """Check the guest-observed mounts, credentials, scratch and interfaces."""

    root_options, _, _ = _mount(readback.mounts, "/")
    runtime_options, runtime_type, _ = _mount(readback.mounts, RUNTIME_ROOT)
    scratch_options, scratch_type, _ = _mount(readback.mounts, SCRATCH)
    if "ro" not in root_options:
        raise ReadbackRefused("guest_root_writable")
    if runtime_type != "tmpfs" or not {"nosuid", "nodev"} <= runtime_options or "noexec" in runtime_options:
        raise ReadbackRefused("guest_runtime_mount")
    if scratch_type != "tmpfs" or not {"noexec", "nosuid", "nodev"} <= scratch_options:
        raise ReadbackRefused("guest_scratch_mount")
    status = _status(readback.status)
    if status.get("Uid") != [PARSER_ID] * 4 or status.get("Gid") != [PARSER_ID] * 4:
        raise ReadbackRefused("guest_credentials")
    for key in ("CapEff", "CapPrm", "CapAmb"):
        values = status.get(key)
        if values is None or len(values) != 1 or values[0].strip("0") != "":
            raise ReadbackRefused("guest_capabilities")
    if status.get("NoNewPrivs") != ["1"]:
        raise ReadbackRefused("guest_no_new_privs")
    if readback.scratch != ():
        raise ReadbackRefused("guest_scratch_not_empty")
    if not confined_network(readback.ifaces, readback.network):
        raise ReadbackRefused("guest_network")
    seccomp = status.get("Seccomp")
    return GuestFacts("guest_observed", PARSER_ID, PARSER_ID, "1", seccomp[0] if seccomp else None)


def confined_network(names: tuple[str, ...], facts: Sequence[dict[str, Any]]) -> bool:
    """Only loopback plus known, observed DOWN and unaddressed fallback devices."""

    if names == ("lo",):
        return True
    if (len(set(names)) != len(names) or "lo" not in names
            or not set(names) <= {"lo", "tunl0", "ip6tnl0"}):
        return False
    by_name = {item.get("name"): item for item in facts if type(item.get("name")) is str}
    if len(by_name) != len(facts) or set(by_name) != set(names):
        return False
    return all(by_name[name] == {"name": name, "up": False, "ipv4": False,
                                "ipv6": False, "observable": True}
               for name in names if name != "lo")
