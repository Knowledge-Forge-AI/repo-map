"""Private runtime-materialization claim parsing."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from repomap_test_support.resource_ledger import ResourceLedgerError, RunIdentity
from repomap_test_support.resource_ledger_io import PrivateJsonError, read_private_json
from repomap_test_support.resource_test_image_base import TestImageError


MATERIALIZATION_MANIFEST_SCHEMA = "repomap-runtime-materialization-claim-v3"
MATERIALIZATION_ROLE = "test-runtime-image-materialization"
_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


def read_materialization_claim(path: Path) -> dict[str, Any]:
    try:
        if path.stat(follow_symlinks=False).st_uid != os.getuid():
            raise TestImageError("materialization manifest owner differs")
        payload = read_private_json(path)
    except (OSError, PrivateJsonError) as error:
        raise TestImageError("materialization manifest is unsafe") from error
    expected = {
        "schema", "project", "phase", "run_id", "role", "name",
        "base_image_id", "container_id", "network_mode", "network_id", "ledger_path",
    }
    if (
        set(payload) != expected
        or payload.get("schema") != MATERIALIZATION_MANIFEST_SCHEMA
    ):
        raise TestImageError("materialization manifest fields differ")
    if payload.get("role") != MATERIALIZATION_ROLE:
        raise TestImageError("materialization manifest authority differs")
    try:
        RunIdentity(payload["project"], payload["phase"], payload["run_id"])
    except ResourceLedgerError as error:
        raise TestImageError("materialization manifest run identity differs") from error
    if not re.fullmatch(
        r"repomap-test-materialization-[0-9a-f]{24}",
        str(payload.get("name") or ""),
    ):
        raise TestImageError("materialization manifest name differs")
    if payload.get("network_mode") not in {"none", "bridge"}:
        raise TestImageError("materialization manifest network mode differs")
    network_id = payload.get("network_id")
    if payload["network_mode"] == "bridge":
        if not re.fullmatch(r"[0-9a-f]{64}", str(network_id or "")):
            raise TestImageError("materialization manifest network identity differs")
    elif network_id is not None:
        raise TestImageError("materialization manifest network identity differs")
    if not _SHA256_ID.fullmatch(str(payload.get("base_image_id") or "")):
        raise TestImageError("image identity is not exact")
    container_id = payload.get("container_id")
    if container_id is not None and not re.fullmatch(
        r"[0-9a-f]{64}", str(container_id)
    ):
        raise TestImageError("materialization manifest container ID differs")
    ledger_path = Path(str(payload.get("ledger_path") or ""))
    if not ledger_path.is_absolute() or ledger_path.is_symlink():
        raise TestImageError("materialization manifest ledger path differs")
    return payload
