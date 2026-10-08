"""Compact, redacted evidence ZIP and delivery receipt for host MCP native runs.

Files are staged in memory and written only at finalization, after every
secret registered during the run (fixture admin password, every value in the
setup-owned ``runtime/.env``) has been replaced by exact value. The one
exception is ``write_early_json``: the secret-free ownership record is also
written to disk immediately so interruption recovery never depends on
finalization. Each member
records the SHA-256 of its recorded bytes; a redacted member also records the
SHA-256 of its original bytes and the redaction count. A final scan of the
recorded bytes fails closed. The receipt attests delivery only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any
import zipfile

RECEIPT_SCHEMA = "repomap-host-mcp-native-receipt-v1"
ATTESTS = "evidence delivery only; not Product step 3 acceptance"
REDACTION = "[REDACTED]"
MIN_SECRET_CHARS = 8
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class EvidenceWriter:
    """Stage members in memory; ``finalize`` writes ``evidence.zip`` and ``receipt.json`` once."""

    run_dir: Path
    run_id: str
    phase: str
    members: dict[str, bytes] = field(default_factory=dict)
    secrets: set[str] = field(default_factory=set)
    early: dict[str, str] = field(default_factory=dict)
    finalized: bool = False

    def __post_init__(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)

    def add_secret(self, value: str | None) -> None:
        if value and len(value) >= MIN_SECRET_CHARS:
            self.secrets.add(value)

    def add_env_file_secrets(self, env_file: Path) -> int:
        """Register every assigned value in a runtime env file; returns the count."""
        count = 0
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if len(value) >= MIN_SECRET_CHARS:
                    self.secrets.add(value)
                    count += 1
        return count

    def write_json(self, name: str, payload: Any) -> None:
        self.write_text(name, _json(payload))

    def write_early_json(self, name: str, payload: Any) -> Path:
        """Write one metadata-only member to disk now (0600, fsynced) and stage the same bytes.

        This is the only member written before finalization: the ownership record must exist
        before any backend resource does. It refuses any secret registered so far.
        """
        if self.finalized:
            raise RuntimeError("evidence is already finalized")
        text = _json(payload)
        if any(secret in text for secret in self.secrets):
            raise ValueError(f"{name} would contain a registered secret")
        data, path = text.encode("utf-8"), self.run_dir / name
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self.members[name], self.early[name] = data, hashlib.sha256(data).hexdigest()
        return path

    def write_text(self, name: str, text: str) -> None:
        if self.finalized:
            raise RuntimeError("evidence is already finalized")
        self.members[name] = text.encode("utf-8")

    def redact(self, text: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, REDACTION)
        return text

    def finalize(self, *, outcome: str, exit_code: int, qualification_class: str,
                 summary: dict[str, Any]) -> dict[str, Any]:
        """Redact, scan, and write the ZIP and receipt; refuses a second finalization."""
        if self.finalized:
            raise RuntimeError("evidence is already finalized")
        self.finalized = True
        recorded, index = {}, {}
        for name, original in sorted(self.members.items()):
            text = original.decode("utf-8")
            redactions = sum(text.count(secret) for secret in self.secrets)
            data = self.redact(text).encode("utf-8")
            recorded[name] = data
            index[name] = {"recorded_sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                           **({"original_sha256": hashlib.sha256(original).hexdigest(), "redactions": redactions}
                              if redactions else {}),
                           **({"early_file_sha256": self.early[name]} if name in self.early else {})}
        leaked = sorted(name for name, data in recorded.items()
                        if any(secret.encode("utf-8") in data for secret in self.secrets))
        if leaked:  # fail closed: withhold the members rather than deliver a secret
            for name in leaked:
                recorded.pop(name)
                index[name] = {"withheld": "secret scan failed after redaction"}
            outcome, exit_code = "evidence_redaction_failed", max(exit_code, 1)
        manifest = {"schema": "repomap-host-mcp-native-evidence-manifest-v1", "run_id": self.run_id,
                    "phase": self.phase, "outcome": outcome, "qualification_class": qualification_class,
                    "hash_domains": {"recorded_sha256": "bytes stored in this ZIP (after redaction)",
                                     "original_sha256": "bytes before exact-value redaction",
                                     "early_file_sha256": "the same-named file written beside evidence.zip before "
                                                          "the backend started; equals original_sha256 when the "
                                                          "member was redacted, otherwise recorded_sha256"},
                    "secret_values_registered": len(self.secrets), "members": index, "summary": summary}
        recorded["MANIFEST.json"] = self.redact(json.dumps(manifest, indent=2, sort_keys=True, default=str)
                                                + "\n").encode("utf-8")
        zip_path = self.run_dir / "evidence.zip"
        zip_bytes = deterministic_zip({f"{self.run_id}/{name}": (data, 0o644) for name, data in recorded.items()})
        zip_path.write_bytes(zip_bytes)
        receipt = {
            "schema": RECEIPT_SCHEMA, "run_id": self.run_id, "phase": self.phase, "outcome": outcome,
            "exit_code": exit_code, "qualification_class": qualification_class, "attests": ATTESTS,
            "created_utc": utc_stamp(),
            "zip": {"name": zip_path.name, "sha256": hashlib.sha256(zip_bytes).hexdigest(),
                    "bytes": len(zip_bytes), "members": len(recorded)},
        }
        (self.run_dir / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                                                   encoding="utf-8")
        return receipt


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def deterministic_zip(files: dict[str, tuple[bytes, int]]) -> bytes:
    """Sorted members, fixed timestamps, explicit POSIX modes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            data, mode = files[name]
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | mode) << 16
            info.create_system = 3
            archive.writestr(info, data)
    return buffer.getvalue()
