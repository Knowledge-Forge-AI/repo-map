"""Bounded owned-container inspection and exact PostgreSQL publication proof."""

from __future__ import annotations

import json
import subprocess

from repomap_kg.runtime._plan_records import LocalContainerStatus, LocalRuntimePlan


def inspect_container(plan: LocalRuntimePlan, component: str, name: str) -> LocalContainerStatus:
    try:
        result = subprocess.run(
            [plan.container_runtime, "inspect", name], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return LocalContainerStatus(name, component, checked=True, diagnostic="container inspection unavailable")
    if result.returncode != 0:
        return LocalContainerStatus(name, component, checked=True, diagnostic="container unavailable")
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, list) or len(payload) != 1:
            raise ValueError
        record = payload[0]
        labels = record["Config"]["Labels"]
        state = record["State"]
        if not isinstance(labels, dict) or not isinstance(state, dict) or not isinstance(state.get("Status"), str):
            raise ValueError
        owned = all(labels.get(key) == value for key, value in plan.identity.labels(
            "http" if component == "server" else component
        ).items())
        binding_valid = False
        published = False
        diagnostic = None
        if component == "postgres":
            ports = record["NetworkSettings"]["Ports"]
            if not isinstance(ports, dict) or "5432/tcp" not in ports:
                raise ValueError
            bindings = ports["5432/tcp"]
            expected = [{"HostIp": "127.0.0.1", "HostPort": str(plan.postgres_host_port)}]
            no_extra_bindings = all(value in (None, []) for key, value in ports.items() if key != "5432/tcp")
            binding_valid = owned and state["Status"] == "running" and no_extra_bindings and (
                bindings == expected if plan.direct_db_host_port_enabled else bindings in (None, [])
            )
            published = binding_valid and plan.direct_db_host_port_enabled
            if not binding_valid:
                diagnostic = "PostgreSQL ownership, state, or host binding does not match the runtime plan"
        health = state.get("Health")
        host_binding_valid = binding_valid
        if component == "server":
            ports = record["NetworkSettings"]["Ports"]
            internal_port = f"{plan.server_host_port}/tcp"
            host_binding_valid = (
                owned and state["Status"] == "running"
                and isinstance(ports, dict)
                and ports.get(internal_port) == [{"HostIp": plan.bind_host, "HostPort": str(plan.server_host_port)}]
                and all(value in (None, []) for key, value in ports.items() if key != internal_port)
            )
        return LocalContainerStatus(
            name, component, checked=True, exists=True, owned=owned,
            status=state["Status"],
            exit_code=state.get("ExitCode") if type(state.get("ExitCode")) is int else None,
            health=health.get("Status") if isinstance(health, dict) else None,
            diagnostic=diagnostic,
            postgres_host_port_checked=component == "postgres",
            postgres_host_port_published=published,
            postgres_host_binding_valid=binding_valid,
            host_binding_valid=host_binding_valid,
        )
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return LocalContainerStatus(
            name, component, checked=True, exists=True,
            postgres_host_port_checked=component == "postgres",
            diagnostic="container inspection structure is invalid",
        )


def inspect_compose_coordinator(plan: LocalRuntimePlan) -> str:
    """Successful exact-project inventory is required to prove absence."""
    try:
        result = subprocess.run(
            [plan.container_runtime, "ps", "-aq", "--filter",
             f"label=com.docker.compose.project={plan.identity.project_name}",
             "--filter", "label=com.docker.compose.service=coordinator"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode != 0:
            return "unknown"
        ids = result.stdout.split()
        if not ids:
            return "absent"
        if len(ids) != 1:
            return "unknown"
        status = inspect_container(plan, "coordinator", ids[0])
        if not status.owned or not status.exists:
            return "unknown"
        return "running" if status.status == "running" else "stopped"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
