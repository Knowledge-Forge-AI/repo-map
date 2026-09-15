from __future__ import annotations

import subprocess
import time
from typing import Callable
from unittest.mock import patch
import scale28_runtime_identity as runtime_identity_module
from scale28_runtime_identity import Scale28RuntimeIdentity
from repomap_test_support.test_cov5k_r2_fix2_catalog import CatalogEntry
from repomap_test_support.test_cov5k_r2_fix2_evidence import ExecutorEvidence, bind_executor_evidence
from repomap_test_support.test_cov5k_r2_fix2_encoding import canonical_digest
from repomap_test_support.test_cov5k_r2_fix3_owner_binding import invoke_bound_owner
from repomap_test_support.test_cov5k_r2_fix3_scenarios import scenario_program, integer_parameter as _integer_parameter
from dataclasses import dataclass

import docker


@dataclass(slots=True)
class DeterministicEngineClient:
    container_name: str
    rss_bytes: int
    api_version: str = "1.47"
    closed: bool = False
    stats_calls: int = 0

    def version(self):
        return {
            "Version": "29.0.0",
            "ApiVersion": self.api_version,
            "Components": [
                {
                    "Name": "Engine",
                    "Version": "29.0.0",
                    "Details": {"ApiVersion": self.api_version, "GitCommit": "public"},
                }
            ],
        }

    def info(self):
        return {
            "OperatingSystem": "Public Engine",
            "OSType": "linux",
            "Architecture": "aarch64",
            "CgroupVersion": "2",
        }

    def inspect_container(self, container):
        assert container == self.container_name
        return {"Image": "sha256:" + "a" * 64}

    def stats(self, container, *, stream, one_shot):
        assert (container, stream, one_shot) == (self.container_name, False, True)
        self.stats_calls += 1
        return {
            "memory_stats": {
                "usage": self.rss_bytes,
                "stats": {"inactive_file": 0},
            }
        }

    def close(self):
        self.closed = True


class RuntimeIdentityScenarioError(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


def deterministic_engine_factory(container_name: str, rss_bytes: int):
    client = DeterministicEngineClient(container_name, rss_bytes)
    return client, lambda _runtime: (client, "deterministic_engine_api")


def categorized_engine_factory(container_name: str, category: str):
    if category == "success":
        return deterministic_engine_factory(container_name, 10_000)[1]
    if category == "unavailable":
        return lambda _runtime: None
    if category in {"transport", "semantic_schema"}:
        def fail(_runtime: str):
            raise RuntimeIdentityScenarioError(category)

        return fail
    raise ValueError(f"unsupported runtime identity category: {category}")


def engine_api_rss_reader(container_name: str) -> int:
    client = docker.from_env()
    try:
        payload = client.api.stats(container_name, stream=False, one_shot=True)
    finally:
        client.close()
    memory = payload.get("memory_stats", {})
    stats = memory.get("stats", {})
    return int(memory.get("usage", 0)) - int(stats.get("inactive_file", 0))


def docker_stats_rss_reader(container_name: str) -> int:
    completed = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container_name],
        shell=False,
        check=True,
        timeout=5,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip().split("/", 1)[0].strip()
    units = (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024), ("B", 1))
    for suffix, multiplier in units:
        if value.endswith(suffix):
            return round(float(value[: -len(suffix)].strip()) * multiplier)
    raise ValueError("docker stats memory value is unsupported")


def enact_container_rss(
    entry: CatalogEntry,
    *,
    executor: Callable[..., ExecutorEvidence],
    capture_runtime_identity: Callable[..., Scale28RuntimeIdentity | None],
    runtime: str,
    container_name: str,
    runtime_source_commit: str,
    postgresql_server_version: str,
    capture: Callable[..., object],
) -> ExecutorEvidence:
    """Capture D container authority through one exact typed owner seam."""

    if capture is not capture_runtime_identity:
        raise ValueError("substituted runtime identity owner is prohibited")
    requested_category = str(dict(entry.parameter_values)["category"])
    program = scenario_program(
        owner_identity="capture_runtime_identity",
        seam_identity="fix3.container_rss.engine_factory",
        input_action=(
            ("category_effect", requested_category),
            ("stream", False),
            ("one_shot", True),
        ),
        expected_product_event_classes=("runtime_identity_result",),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )
    factory = categorized_engine_factory(container_name, requested_category)

    def operation():
        try:
            with patch.object(runtime_identity_module, "_create_docker_api_client", factory):
                identity = capture_runtime_identity(
                    runtime=runtime,
                    container_name=container_name,
                    repomap_commit=runtime_source_commit,
                    postgresql_server_version=postgresql_server_version,
                )
        except Exception as error:
            return None, str(getattr(error, "category", type(error).__name__))
        return identity, "unavailable" if identity is None else "success"

    (identity, category), owner_evidence, _frames = invoke_bound_owner(
        executor=executor,
        owner=capture_runtime_identity,
        scenario_seam_active=True,
        operation=operation,
    )
    observed = (
        ("primary_result_category", category),
        ("runtime_source_commit", runtime_source_commit),
        ("stream", False),
        ("one_shot", True),
        ("automatic_fallback", False),
    )
    return bind_executor_evidence(
        entry,
        enacted_parameters=(
            ("category", category),
            ("stream", False),
            ("one_shot", True),
        ),
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=(("runtime_identity_result", (category, identity is not None)),),
    )


def enact_container_rss_equivalence(
    entry: CatalogEntry,
    *,
    executor: Callable[..., ExecutorEvidence],
    capture_runtime_identity: Callable[..., Scale28RuntimeIdentity | None],
    api_reader: Callable[[], int] | None = None,
    diagnostic_reader: Callable[[], int] | None = None,
    runtime_identity_context: dict[str, str] | None = None,
    workload_probe: Callable[[], tuple[str, object]] | None = None,
) -> ExecutorEvidence:
    """Enact one frozen D pair without collapsing pair or workload identity."""

    parameters = dict(entry.parameter_values)
    context = runtime_identity_context or {
        "runtime": "docker",
        "container_name": "fix3-disposable-pair",
        "repomap_commit": "0" * 40,
        "postgresql_server_version": "16",
    }
    container_name = context["container_name"]
    engine_client = None
    factory = None
    if api_reader is not None or diagnostic_reader is not None:
        engine_client, factory = deterministic_engine_factory(container_name, 10_000)

    def capture_owner():
        if factory is None:
            return capture_runtime_identity(**context)
        with patch.object(runtime_identity_module, "_create_docker_api_client", factory):
            return capture_runtime_identity(**context)

    identity, owner_evidence, _frames = invoke_bound_owner(
        executor=executor,
        owner=capture_runtime_identity,
        scenario_seam_active=True,
        operation=capture_owner,
    )
    exact_api_reader = api_reader or (lambda: engine_api_rss_reader(container_name))
    exact_diagnostic_reader = diagnostic_reader or (
        lambda: docker_stats_rss_reader(container_name)
    )
    api_started_ns = time.monotonic_ns()
    api_value = int(exact_api_reader())
    diagnostic_started_ns = time.monotonic_ns()
    diagnostic_value = int(exact_diagnostic_reader())
    workload_event = (
        workload_probe()
        if workload_probe is not None
        else (str(parameters["workload"]), "typed_deterministic_effect")
    )
    if workload_event[0] != parameters["workload"]:
        raise ValueError("container workload probe differs from frozen workload")
    sampling_skew_ms = (diagnostic_started_ns - api_started_ns) / 1_000_000
    tolerance = _integer_parameter(parameters["value_tolerance_bytes"])
    program = scenario_program(
        owner_identity="capture_runtime_identity",
        seam_identity="fix3.container_pair.engine_api_and_diagnostic",
        input_action=(
            ("workload", str(parameters["workload"])),
            ("pair", _integer_parameter(parameters["pair"])),
            ("stream", False),
            ("one_shot", True),
            ("value_tolerance_bytes", tolerance),
            ("sampling_skew_ms", _integer_parameter(parameters["sampling_skew_ms"])),
        ),
        expected_product_event_classes=("runtime_identity", "engine_api_sample", "diagnostic_sample"),
        cleanup_contract=entry.cleanup_contract,
        process_boundary_contract=entry.process_boundary_contract,
    )
    enacted_values = dict(program.input_action)
    enacted_values["workload"] = workload_event[0]
    enacted = tuple((name, enacted_values[name]) for name, _ in entry.parameter_values)
    image_digest = getattr(identity, "container_image_digest", "unavailable")
    container_identity_digest = canonical_digest((container_name, image_digest))
    observed = (
        ("workload", parameters["workload"]),
        ("pair", parameters["pair"]),
        ("runtime_identity_owner_entered", True),
        ("runtime_identity_available", identity is not None),
        ("api_rss_bytes", api_value),
        ("diagnostic_rss_bytes", diagnostic_value),
        ("sampling_skew_observed_ms", sampling_skew_ms),
        ("within_tolerance", abs(api_value - diagnostic_value) <= tolerance),
        ("disposable_container_identity_digest", container_identity_digest),
        ("workload_probe", workload_event[1]),
    )
    product_events = (
        ("runtime_identity", identity is not None),
        ("engine_api_sample", api_value),
        ("diagnostic_sample", diagnostic_value),
        ("workload_effect", workload_event),
        ("sampling_skew_ms", sampling_skew_ms),
    )
    return bind_executor_evidence(
        entry,
        enacted_parameters=enacted,
        observed_fields=observed,
        owner_entry_evidence=owner_evidence,
        scenario_program_identity=program.scenario_id,
        observed_product_events=product_events,
    )
