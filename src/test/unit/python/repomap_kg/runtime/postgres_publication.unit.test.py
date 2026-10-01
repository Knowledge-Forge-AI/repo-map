import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.runtime._container_inspection import inspect_container
from repomap_kg.runtime.local import setup_local_runtime, up_local_runtime
from repomap_kg.runtime.plan import LocalRuntimeError, build_local_runtime_plan


def plan_for(tmp_path, enabled=True):
    setup_local_runtime(tmp_path)
    path = tmp_path / "repomap.rpl.toml"
    if enabled:
        path.write_text(path.read_text().replace("direct_host_port_enabled = false", "direct_host_port_enabled = true"))
    return build_local_runtime_plan(tmp_path)


def record_for(plan, bindings):
    return {"Config": {"Labels": plan.identity.labels("postgres")},
            "State": {"Status": "running", "ExitCode": 0},
            "NetworkSettings": {"Ports": {"5432/tcp": bindings}}}


def observe(plan, record):
    result = SimpleNamespace(returncode=0, stdout=json.dumps([record]), stderr="")
    with patch("repomap_kg.runtime._container_inspection.subprocess.run", return_value=result):
        return inspect_container(plan, "postgres", plan.identity.postgres_container)


@pytest.mark.parametrize("bindings", [None, [], [{"HostIp": "0.0.0.0", "HostPort": "55432"}],
    [{"HostIp": "127.0.0.1", "HostPort": "55433"}],
    [{"HostIp": "::1", "HostPort": "55432"}],
    [{"HostIp": "127.0.0.1", "HostPort": "55432"}] * 2, {}, "invalid"])
def test_rejects_missing_wrong_public_multiple_bindings(tmp_path, bindings):
    plan = plan_for(tmp_path)
    status = observe(plan, record_for(plan, bindings))
    assert status.postgres_host_port_checked
    assert not status.postgres_host_port_published
    assert not status.postgres_host_binding_valid


@pytest.mark.parametrize("enabled", [False, True])
def test_owned_exact_binding_is_observed(tmp_path, enabled):
    plan = plan_for(tmp_path, enabled)
    binding = [{"HostIp": "127.0.0.1", "HostPort": "55432"}] if enabled else None
    status = observe(plan, record_for(plan, binding))
    assert status.postgres_host_binding_valid
    assert status.postgres_host_port_published == enabled
    with patch("repomap_kg.runtime.local.is_local_port_open", return_value=False):
        unchecked = up_local_runtime(tmp_path, dry_run=True).to_jsonable()["runtime"]
    assert unchecked["direct_db_host_port_enabled"] == enabled
    assert not unchecked["postgres_host_port_checked"]
    assert not unchecked["postgres_host_port_published"]


@pytest.mark.parametrize("defect", ["foreign", "stopped", "missing-ports", "malformed-state", "extra-port"])
def test_ownership_and_structure_are_required(tmp_path, defect):
    plan = plan_for(tmp_path)
    record = record_for(plan, [{"HostIp": "127.0.0.1", "HostPort": "55432"}])
    if defect == "foreign": record["Config"]["Labels"]["org.repomap.home_hash"] = "foreign"
    elif defect == "stopped": record["State"]["Status"] = "exited"
    elif defect == "missing-ports": del record["NetworkSettings"]
    elif defect == "malformed-state": record["State"] = []
    else: record["NetworkSettings"]["Ports"]["1234/tcp"] = [{"HostIp": "127.0.0.1", "HostPort": "55555"}]
    assert not observe(plan, record).postgres_host_binding_valid


def test_up_verification_failure_runs_supported_teardown(tmp_path):
    plan = plan_for(tmp_path)
    bad = observe(plan, record_for(plan, None))
    with (patch("repomap_kg.runtime.local.shutil.which", return_value="docker"),
          patch("repomap_kg.runtime.local.is_local_port_open", return_value=False),
          patch("repomap_kg.runtime.local.inspect_container", return_value=bad),
          patch("repomap_kg.runtime.local.inspect_compose_coordinator", return_value="absent"),
          patch("repomap_kg.runtime.local._run_container_runtime") as run):
        with pytest.raises(LocalRuntimeError, match="publication"):
            up_local_runtime(tmp_path)
    assert run.call_args_list[0].args[0][-4:] == ("up", "-d", "--build", "--remove-orphans")
    assert run.call_args_list[1].args[0][-2:] == ("down", "--remove-orphans")


def test_up_published_output_is_engine_derived(tmp_path):
    plan = plan_for(tmp_path)
    good = observe(plan, record_for(plan, [{"HostIp": "127.0.0.1", "HostPort": "55432"}]))
    with (patch("repomap_kg.runtime.local.shutil.which", return_value="docker"),
          patch("repomap_kg.runtime.local.is_local_port_open", return_value=False),
          patch("repomap_kg.runtime.local.inspect_container", return_value=good),
          patch("repomap_kg.runtime.local.inspect_compose_coordinator", return_value="absent"),
          patch("repomap_kg.runtime.local._run_container_runtime")):
        runtime = up_local_runtime(tmp_path).to_jsonable()["runtime"]
    assert runtime["postgres_host_port_checked"]
    assert runtime["postgres_host_port_published"]


def test_disabled_exposure_rejects_an_actual_binding(tmp_path):
    plan = plan_for(tmp_path, enabled=False)
    status = observe(plan, record_for(plan, [{"HostIp": "127.0.0.1", "HostPort": "55432"}]))
    assert status.postgres_host_port_checked
    assert not status.postgres_host_port_published
    assert not status.postgres_host_binding_valid
