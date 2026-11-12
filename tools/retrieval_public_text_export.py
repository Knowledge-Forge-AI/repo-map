"""Fixed private stdout sidecar for public-text evaluator evidence."""
from __future__ import annotations
from collections.abc import Mapping
import base64
import binascii
import hashlib
import io
import json
import math
import re
import sys
import tarfile
from pathlib import PurePosixPath, PureWindowsPath
from typing import cast, IO, TextIO

PHASE = "REPOMAP-CLOE-PUBLIC-TEXT1"
PREFIX = "CLOE_PUBLICTEXT_PRIVATE_EVIDENCE_V1 "
SCHEMA = "cloe-publictext-private-evidence-v1"
MAX_JOURNAL_BYTES = 64 * 1024 * 1024
MAX_TAR_BYTES, MAX_STDOUT_BYTES = 72 * 1024 * 1024, 96 * 1024 * 1024
MAX_PUBLIC_REPORT_BYTES, MAX_METADATA_BYTES = 32 * 1024 * 1024, 64 * 1024
MAX_RAW_GROUP_BYTES = 32 * 1024 * 1024
RAW_MEMBERS = ("declaration.json", "report.json", "source-manifest.json", "sources.zip", "terminal.json")
RAW_LIMITS = {member: MAX_RAW_GROUP_BYTES for member in RAW_MEMBERS}
EXTRA_LIMITS = {"public-text-calibration-report.json": MAX_PUBLIC_REPORT_BYTES, "public-text-study-failure.json": MAX_METADATA_BYTES, "functional-transition-observation.json": MAX_METADATA_BYTES, "functional-transition-gate.json": MAX_METADATA_BYTES}
EXTRA_NAMES = tuple(EXTRA_LIMITS)
ALL_NAMES = frozenset(EXTRA_NAMES) | frozenset(f"raw-components/w5-semantic-g{generation}/{member}" for generation in (1, 2) for member in RAW_MEMBERS)
JSON_NAMES = frozenset(EXTRA_NAMES)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_META_FIELDS = frozenset({"schema", "phase", "kind", "functional_only", "journal_decoded_bytes", "archive_b64", "archive_length", "archive_sha256", "manifest", "manifest_sha256"})

class ExportRefusal(ValueError):
    """Closed sidecar refusal without raw payloads or private paths."""
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ExportRefusal(code)

def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
def _canonical(value: object, *, newline: bool = False) -> bytes:
    def ready(item: object) -> object:
        if item is None or isinstance(item, (str, bool)) or type(item) is int:
            return item
        if isinstance(item, Mapping):
            if any(type(key) is not str for key in item):
                raise ValueError("json_key")
            return {key: ready(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [ready(val) for val in item]
        raise ValueError("json_value")
    try:
        raw = json.dumps(
            ready(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, ValueError, UnicodeError):
        raise ExportRefusal("export_noncanonical_json") from None
    return raw + b"\n" if newline else raw

def _strict_json(data: bytes) -> None:
    _require(type(data) is bytes and bool(data), "export_json_member")
    try:
        json.loads(data, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant, parse_float=_finite_float)
    except ExportRefusal:
        raise
    except (RecursionError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        raise ExportRefusal("export_json_member") from None

def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExportRefusal("export_duplicate_json_field")
        result[key] = value
    return result

def _reject_constant(_value: str) -> object:
    raise ExportRefusal("export_nonfinite_json")

def _finite_float(value: str) -> float:
    number = float(value)
    _require(math.isfinite(number), "export_nonfinite_json")
    return number

def _digest(value: object) -> str:
    _require(type(value) is str and _DIGEST.fullmatch(value) is not None, "export_digest")
    return cast(str, value)

def _name(value: object) -> str:
    if type(value) is not str or not value:
        raise ExportRefusal("export_name")
    if value in EXTRA_NAMES:
        return value
    parts = value.split("/")
    if (
        "\\" in value
        or value.startswith("/")
        or len(parts) < 2
        or any(part in {"", ".", ".."} for part in parts)
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or value not in ALL_NAMES
    ):
        raise ExportRefusal("export_name")
    return value

def _member_limit(name: str) -> int:
    member = name.rsplit("/", 1)[-1]
    return EXTRA_LIMITS[member] if member in EXTRA_LIMITS else RAW_LIMITS[member]

def _files(extras: Mapping[str, bytes]) -> dict[str, bytes]:
    _require(isinstance(extras, Mapping), "export_files")
    values: dict[str, bytes] = {}
    for raw_name, data in extras.items():
        name = _name(raw_name)
        if name in values or type(data) is not bytes:
            raise ExportRefusal("export_files")
        _require(len(data) <= _member_limit(name), "export_member_size")
        if name in JSON_NAMES:
            _strict_json(data)
        values[name] = data
    _require(
        "public-text-calibration-report.json" in values
        or "public-text-study-failure.json" in values,
        "export_report_or_failure",
    )
    functional = {
        name for name in (
            "functional-transition-observation.json", "functional-transition-gate.json"
        ) if name in values
    }
    if functional and functional != {
        "functional-transition-observation.json", "functional-transition-gate.json"
    }:
        raise ExportRefusal("export_functional_pair")
    for generation in (1, 2):
        names = {
            f"raw-components/w5-semantic-g{generation}/{member}" for member in RAW_MEMBERS
        } & values.keys()
        if names and names != {
            f"raw-components/w5-semantic-g{generation}/{member}" for member in RAW_MEMBERS
        }:
            raise ExportRefusal("export_raw_group")
        _require(
            sum(len(values[name]) for name in names) <= MAX_RAW_GROUP_BYTES,
            "export_raw_group_size",
        )
    return values

def _mode_check(files: Mapping[str, bytes], functional_only: bool) -> None:
    transition = {
        name for name in (
            "functional-transition-observation.json", "functional-transition-gate.json"
        ) if name in files
    }
    if functional_only and "public-text-calibration-report.json" in files and transition != {
        "functional-transition-observation.json", "functional-transition-gate.json"
    }:
        raise ExportRefusal("export_functional_pair")
    if not functional_only and transition:
        raise ExportRefusal("export_native_functional_payload")

def _tar(files: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    try:
        with tarfile.open(
            fileobj=output, mode="w:", format=tarfile.USTAR_FORMAT
        ) as bundle:
            for name in sorted(files, key=lambda value: value.encode("ascii")):
                data = files[name]
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o600
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                info.type = tarfile.REGTYPE
                info.linkname = ""
                info.pax_headers = {}
                bundle.addfile(info, io.BytesIO(data))
    except (OSError, tarfile.TarError, ValueError):
        raise ExportRefusal("export_tar_write") from None
    archive = output.getvalue()
    _require(len(archive) <= MAX_TAR_BYTES, "export_tar_size")
    return archive

def _manifest(files: Mapping[str, bytes]) -> list[dict[str, object]]:
    return [
        {"name": name, "length": len(files[name]), "sha256": _sha(files[name])}
        for name in sorted(files, key=lambda value: value.encode("ascii"))
    ]

def emit_study_evidence(extras: Mapping[str, bytes], *, journal_decoded_bytes: int,
                        functional_only: bool, stream: TextIO | None = None) -> str:
    _require(
        type(journal_decoded_bytes) is int
        and not isinstance(journal_decoded_bytes, bool)
        and 0 <= journal_decoded_bytes <= MAX_JOURNAL_BYTES,
        "export_journal_size",
    )
    _require(type(functional_only) is bool, "export_functional_flag")
    files = _files(extras)
    _mode_check(files, functional_only)
    archive = _tar(files)
    manifest = _manifest(files)
    manifest_raw = _canonical(manifest)
    _require(
        journal_decoded_bytes + sum(len(data) for data in files.values()) <= MAX_JOURNAL_BYTES,
        "export_content_size",
    )
    manifest_digest = _sha(manifest_raw)
    document = {
        "schema": SCHEMA,
        "phase": PHASE,
        "kind": "sidecar",
        "functional_only": functional_only,
        "journal_decoded_bytes": journal_decoded_bytes,
        "archive_b64": base64.b64encode(archive).decode("ascii"),
        "archive_length": len(archive),
        "archive_sha256": _sha(archive),
        "manifest": manifest,
        "manifest_sha256": manifest_digest,
    }
    line = "\n" + PREFIX + _canonical(document, newline=True).decode("ascii")
    _require(
        journal_decoded_bytes + len(line.encode("ascii")) <= MAX_STDOUT_BYTES,
        "export_stdout_size",
    )
    output = sys.stdout if stream is None else stream
    output.write(line)
    flush = getattr(output, "flush", None)
    if callable(flush):
        flush()
    return manifest_digest

def _parse_tar(archive: bytes) -> dict[str, bytes]:
    _require(
        type(archive) is bytes
        and len(archive) <= MAX_TAR_BYTES
        and len(archive) >= 1024
        and len(archive) % 512 == 0,
        "export_tar_bounds",
    )
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:", errorlevel=2) as bundle:
            for index in range(len(ALL_NAMES) + 1):
                member = bundle.next()
                if member is None:
                    break
                _require(index < len(ALL_NAMES), "export_tar_member_count")
                _require(
                    member.type == tarfile.REGTYPE and member.isfile(),
                    "export_tar_special_file",
                )
                name = _name(member.name)
                _require(name not in files, "export_tar_member")
                _require(
                    member.mode == 0o600 and member.uid == 0 and member.gid == 0
                    and member.mtime == 0 and member.uname == ""
                    and member.gname == "" and member.linkname == ""
                    and member.devmajor == 0 and member.devminor == 0
                    and not member.pax_headers and member.sparse is None,
                    "export_tar_metadata",
                )
                _require(
                    type(member.size) is int
                    and 0 <= member.size <= _member_limit(name),
                    "export_member_size",
                )
                _require(
                    type(member.offset_data) is int and member.offset_data >= 0
                    and member.offset_data + member.size <= len(archive),
                    "export_tar_bounds",
                )
                reader = bundle.extractfile(member)
                _require(reader is not None, "export_tar_member")
                data = cast(IO[bytes], reader).read(member.size + 1)
                _require(
                    type(data) is bytes and len(data) == member.size,
                    "export_tar_member",
                )
                files[name] = data
            else:
                raise ExportRefusal("export_tar_member_count")
    except ExportRefusal:
        raise
    except (AttributeError, EOFError, KeyError, OSError, RecursionError, tarfile.TarError, ValueError):
        raise ExportRefusal("export_tar_read") from None
    _require(_tar(files) == archive, "export_tar_noncanonical")
    return files

def decode_study_evidence(raw_log: bytes, *, journal_decoded_bytes: int,
                          expected_functional_only: bool) -> dict[str, bytes]:
    _require(type(raw_log) is bytes and len(raw_log) <= MAX_STDOUT_BYTES, "export_input_size")
    _require(
        type(journal_decoded_bytes) is int
        and not isinstance(journal_decoded_bytes, bool)
        and 0 <= journal_decoded_bytes <= MAX_JOURNAL_BYTES,
        "export_journal_size",
    )
    _require(type(expected_functional_only) is bool, "export_functional_flag")
    lines = [line for line in raw_log.split(b"\n") if line.startswith(PREFIX.encode("ascii"))]
    _require(len(lines) == 1 and raw_log.endswith(b"\n"), "export_frame_count")
    payload = lines[0][len(PREFIX):]
    try:
        document = json.loads(
            payload.decode("ascii"), object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except ExportRefusal:
        raise
    except (RecursionError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        raise ExportRefusal("export_frame_json") from None
    _require(
        type(document) is dict and set(document) == _META_FIELDS
        and _canonical(document) == payload,
        "export_frame_json",
    )
    _require(
        type(document["functional_only"]) is bool
        and (
            document["schema"], document["phase"], document["kind"],
            document["functional_only"],
        ) == (SCHEMA, PHASE, "sidecar", expected_functional_only),
        "export_frame_header",
    )
    _require(
        type(document["journal_decoded_bytes"]) is int
        and not isinstance(document["journal_decoded_bytes"], bool)
        and document["journal_decoded_bytes"] == journal_decoded_bytes,
        "export_journal_size",
    )
    archive_b64 = document["archive_b64"]
    _require(
        type(archive_b64) is str
        and len(archive_b64) <= 4 * ((MAX_TAR_BYTES + 2) // 3),
        "export_archive_encoding",
    )
    try:
        archive = base64.b64decode(archive_b64.encode("ascii"), validate=True)
    except (ValueError, UnicodeError, binascii.Error):
        raise ExportRefusal("export_archive_encoding") from None
    _require(base64.b64encode(archive).decode("ascii") == archive_b64, "export_archive_encoding")
    _require(
        type(document["archive_length"]) is int
        and not isinstance(document["archive_length"], bool)
        and document["archive_length"] >= 0
        and len(archive) == document["archive_length"]
        and len(archive) <= MAX_TAR_BYTES
        and _sha(archive) == _digest(document["archive_sha256"]),
        "export_archive_digest",
    )
    manifest = document["manifest"]
    _require(type(manifest) is list and len(manifest) <= len(ALL_NAMES), "export_manifest")
    _require(
        _sha(_canonical(manifest)) == _digest(document["manifest_sha256"]),
        "export_manifest_digest",
    )
    expected: dict[str, dict[str, object]] = {}
    for entry in manifest:
        if type(entry) is not dict or set(entry) != {"name", "length", "sha256"}:
            raise ExportRefusal("export_manifest")
        name = _name(entry["name"])
        length = entry["length"]
        if (
            type(length) is not int or isinstance(length, bool)
            or length < 0 or length > _member_limit(name)
        ):
            raise ExportRefusal("export_manifest")
        if name in expected or not _digest(entry["sha256"]):
            raise ExportRefusal("export_manifest")
        expected[name] = entry
    if list(expected) != sorted(expected, key=lambda value: value.encode("ascii")):
        raise ExportRefusal("export_manifest_order")
    files = _parse_tar(archive)
    if set(files) != set(expected) or _tar(files) != archive:
        raise ExportRefusal("export_manifest_mismatch")
    for name, data in files.items():
        entry = expected[name]
        if len(data) != entry["length"] or _sha(data) != entry["sha256"]:
            raise ExportRefusal("export_member_digest")
        if name in JSON_NAMES:
            _strict_json(data)
    _files(files)
    _mode_check(files, expected_functional_only)
    if journal_decoded_bytes + sum(len(data) for data in files.values()) > MAX_JOURNAL_BYTES:
        raise ExportRefusal("export_content_size")
    return files

__all__ = ["ALL_NAMES", "ExportRefusal", "MAX_JOURNAL_BYTES", "MAX_STDOUT_BYTES", "MAX_TAR_BYTES", "PREFIX", "decode_study_evidence", "emit_study_evidence"]
