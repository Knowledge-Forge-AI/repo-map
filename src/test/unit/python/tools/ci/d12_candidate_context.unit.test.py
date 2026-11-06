"""The committed grant and candidate bind the actual unpatched build context."""

from __future__ import annotations

import json
from pathlib import Path

from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH,
    DEFAULT_GRANT_RELPATH,
    validate_system_build_grant,
)
from repomap_test_support.d12_recipe import frozen_identity


def test_current_candidate_and_grant_bind_the_actual_build_context() -> None:
    root = Path(__file__).resolve().parents[6]
    grant = json.loads((root / DEFAULT_GRANT_RELPATH).read_bytes())
    candidate = json.loads((root / DEFAULT_CANDIDATE_RELPATH).read_bytes())
    identity = frozen_identity(root, "linux/amd64")
    assert identity == grant["d12_context"] == candidate["d12_context"]
    validate_system_build_grant(grant, frozen_identity=identity)
