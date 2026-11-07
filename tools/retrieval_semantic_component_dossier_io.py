"""Structural read and exclusive write for inert W5 dossier files."""

from __future__ import annotations

import os

from retrieval_semantic_component_dossier_contract import MAX_DOSSIER_BYTES, validate_component_dossier
from retrieval_semantic_experiment_contracts import canonical_json_bytes
from retrieval_semantic_pair_artifacts import digest_bytes, parse_json_object, refuse
from retrieval_semantic_raw_component_io import capture_file, owned_path


def read_component_dossier(path: object) -> dict[str, object]:
    """Structural validation only; sources and live stores are not authenticated."""
    snapshot = capture_file(path, limit=MAX_DOSSIER_BYTES)
    report = parse_json_object(snapshot.raw, code_prefix="dossier")
    validate_component_dossier(report)
    return report


def write_component_dossier(path: object, report: dict[str, object]) -> str:
    """Create one complete output, refusing existing files and symlinks."""
    validate_component_dossier(report)
    destination = owned_path(path)
    raw = canonical_json_bytes(report) + b"\n"
    descriptor = None
    created = None
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        info = os.fstat(descriptor)
        created = info.st_dev, info.st_ino
        remaining = memoryview(raw)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise OSError("incomplete dossier output")
            remaining = remaining[count:]
        os.fsync(descriptor)
    except OSError:
        if created is not None:
            try:
                info = destination.lstat()
                if (info.st_dev, info.st_ino) == created:
                    destination.unlink()
            except OSError:
                raise refuse("dossier_output_cleanup") from None
        raise refuse("dossier_output") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return digest_bytes(raw)


__all__ = ["read_component_dossier", "write_component_dossier"]
