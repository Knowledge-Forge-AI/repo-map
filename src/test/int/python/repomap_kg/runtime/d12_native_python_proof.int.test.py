"""ADR 0102 local native ARM proof of the shared Python 3.12.16 component observer (B3, B4).

This owner runs the exact observer E1 hooks after native engine facts, on the passive preloaded raw ARM base:
no pull, build, dependency-runtime materialization or image acceptance. It is a local native ARM proof only. On a
native AMD (or any non-ARM) daemon it proves the ARM refusal before image access and prints a distinct
non-qualification record; the admitted E1 path is this campaign's sole AMD component observer. The older ADR 0100
ARM owner observes the same base; these overlapping observations are not independent image qualification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import d12_native_python_observer as observer
from common_lore_index.runtime import python_payload as payload
from repomap_test_support import d12_core_image as d12
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run

REPO_ROOT = Path(__file__).resolve().parents[6]
ARM_PLATFORM = "linux/arm64"
RECORD_PREFIX = "PY31216_COMPONENT_JSON:"
REFUSAL_PREFIX = "PY31216_COMPONENT_ARM_REFUSAL_JSON:"


def test_native_python31216_component(capsys: pytest.CaptureFixture[str]) -> None:
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "the component proof requires the canonical resource run"
    client = boundary.client
    owner = CurrentRunDockerContainers(run, client)
    record = observer.new_record(ARM_PLATFORM)  # the request names the platform; the daemon only confirms it
    # The ordinary ARM population selects the dependency runtime, so the override is recorded here, not required;
    # identity comes from the observed image attributes. E1 requires the exact override.
    observer.observe_component(record, client=client, owner=owner, run=run, boundary=boundary,
                               platform=ARM_PLATFORM, environ=os.environ, require_override=False,
                               repo_root=REPO_ROOT)
    amd64 = payload.build_31216_exclusion("amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
    assert payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"] == amd64, "ADR 0103 admitted AMD default; never qualified here"
    daemon = str(client.info().get("Architecture") or "").strip().lower()
    if daemon not in ("aarch64", "arm64"):
        with capsys.disabled():
            print(REFUSAL_PREFIX + json.dumps({
                "schema": record["schema"], "daemon_arch": daemon, "result": "arm64_component_refused",
                "stage": record["stage"], "amd64_qualified": False, "amd64_default_enrolled": True,
                "operations_delta": record["operations"].get("delta"), "cleanup": record["cleanup"],
                "qualification": record["qualification"],
            }, sort_keys=True, separators=(",", ":")), flush=True)
        assert record["status"] == "refused" and record["stage"] == "daemon", record["reasons"]
        assert "provenance" not in record and "container" not in record, "refusal precedes any image access"
        assert record["cleanup"] == {"verified": True, "container_created": False, "ledger_containers": 0,
                                     "removed": 0, "engine_absent": True, "baseline_verified": True}
        assert record["operations"].get("delta") == {}, record["reasons"]
        return
    with capsys.disabled():  # one bounded record; pytest would otherwise discard captured stdout on a pass
        print(RECORD_PREFIX + json.dumps(record, sort_keys=True, separators=(",", ":")), flush=True)
    assert record["status"] == "observed", record["reasons"]
    assert record["provenance"]["config"] == payload.PYTHON_31216_ARM64_CONFIG
    assert record["summary"]["default_enrolled"] is True and record["defaults"]["amd64_default_enrolled"] is True
    assert record["cleanup"]["verified"] is True and record["operations"]["delta"] == {}
    assert record["qualification"] == {"image": False, "p3": False, "whole_preflight": False,
                                       "default_enrollment": False}
