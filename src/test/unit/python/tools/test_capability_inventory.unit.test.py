from __future__ import annotations

import json
from pathlib import Path

import test_capability_inventory as capability_inventory

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_inventory_module():
    return capability_inventory


def write(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_inventory_classifies_direct_inherited_and_simulated_capabilities(tmp_path):
    write(
        tmp_path,
        "src/test/int/python/conftest.py",
        "postgres_container_session(runtime='docker', port=55433)\n",
    )
    write(
        tmp_path,
        "src/test/int/python/pkg/live.int.test.py",
        """\
import docker
from repomap_test_support.postgres_harness import temporary_postgres

def test_live():
    client = docker.from_env()
    subprocess.run(["docker", "volume", "create", "owned"])
    subprocess.run(["docker", "run", "--volume", "/scratch/a:/scratch/a", "image"])
    with temporary_postgres():
        pass
""",
    )
    write(
        tmp_path,
        "src/test/int/python/pkg/contracts.int.test.py",
        """\
def test_cli_contract():
    runner(["podman", "network", "inspect", "owned"])
    assert "REPOMAP_GO_HELPER" in env
    assert "/proc/1/status"
    assert "ipcrm" in cleanup_command
""",
    )
    write(
        tmp_path,
        "src/test/unit/python/pkg/fake.unit.test.py",
        """\
def test_fake_runner():
    fake_runner(["docker", "pull", "example.invalid/image"])
""",
    )
    write(
        tmp_path,
        "src/test/unit/python/pkg/violation.unit.test.py",
        """\
import docker

def test_live_client():
    docker.from_env()
""",
    )

    inventory = load_inventory_module().build_inventory(tmp_path)
    module_entries = {entry["path"]: entry for entry in inventory["modules"]}

    live = module_entries["src/test/int/python/pkg/live.int.test.py"]
    assert live["capabilities"]["temporary_postgres"]["classification"] == "actual_live_resource"
    assert live["capabilities"]["docker_sdk"]["classification"] == "actual_live_resource"
    assert live["capabilities"]["volume_lifecycle"]["classification"] == "actual_live_resource"
    assert live["capabilities"]["bind_mounts"]["classification"] == "actual_live_resource"
    assert live["capabilities"]["source_scratch_mounts"]["classification"] == "actual_live_resource"

    contracts = module_entries["src/test/int/python/pkg/contracts.int.test.py"]
    assert contracts["capabilities"]["temporary_postgres"]["origin"] == "suite_fixture"
    assert contracts["capabilities"]["host_port"]["origin"] == "suite_fixture"
    assert contracts["capabilities"]["docker_cli"]["classification"] == "integration_only_behavior"
    assert contracts["capabilities"]["network_lifecycle"]["classification"] == "integration_only_behavior"
    assert contracts["capabilities"]["native_toolchain"]["classification"] == "integration_only_behavior"
    assert contracts["capabilities"]["proc_inspection"]["classification"] == "integration_only_behavior"
    assert contracts["capabilities"]["ipc"]["classification"] == "integration_only_behavior"

    fake = module_entries["src/test/unit/python/pkg/fake.unit.test.py"]
    assert fake["capabilities"]["docker_cli"]["classification"] == "simulated_unit_contract"
    violation = module_entries["src/test/unit/python/pkg/violation.unit.test.py"]
    assert violation["capabilities"]["docker_sdk"]["classification"] == "actual_live_resource"
    assert inventory["unit_live_resource_violations"] == [
        {
            "capability": "docker_sdk",
            "path": "src/test/unit/python/pkg/violation.unit.test.py",
        }
    ]


def test_inventory_json_is_deterministic_and_repository_relative(tmp_path):
    write(tmp_path, "src/test/int/python/conftest.py", "postgres_container_session()\n")
    write(tmp_path, "src/test/int/python/z.int.test.py", "def test_z(): pass\n")
    write(tmp_path, "src/test/unit/python/a.unit.test.py", "def test_a(): pass\n")

    module = load_inventory_module()
    first = module.inventory_json(module.build_inventory(tmp_path))
    second = module.inventory_json(module.build_inventory(tmp_path))

    assert first == second
    assert str(tmp_path) not in first
    parsed = json.loads(first)
    assert [entry["path"] for entry in parsed["modules"]] == [
        "src/test/int/python/z.int.test.py",
        "src/test/unit/python/a.unit.test.py",
    ]
    assert parsed["schema"] == "repomap-test-capability-inventory-v1"
