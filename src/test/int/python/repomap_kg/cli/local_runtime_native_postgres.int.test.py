def test_native_mode_observes_direct_postgres_binding(tmp_path):
    """Real Engine inspection without a release-image build in the integration runner."""
    import socket
    from repomap_kg.runtime.local import setup_local_runtime, query_local_runtime_status
    from repomap_kg.runtime.plan import build_local_runtime_plan
    from repomap_kg.runtime.compose import render_compose_yaml
    from repomap_test_support.postgres_container import PostgresContainerHarness
    from repomap_test_support.postgres_container_config import PostgresContainerConfig

    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    home = tmp_path / "native-home"
    setup_local_runtime(home)
    config = home / "repomap.rpl.toml"
    config.write_text(config.read_text().replace("[runtime]", '[runtime]\ncoordinator_mode = "native"').replace(
        "direct_host_port_enabled = false", "direct_host_port_enabled = true"
    ).replace("host_port = 55432", f"host_port = {port}"))
    plan = build_local_runtime_plan(home)

    class OwnedPostgres(PostgresContainerHarness):
        @property
        def container_name(self):
            return plan.identity.postgres_container

        def labels(self):
            return {**super().labels(), **plan.identity.labels("postgres")}

    harness = OwnedPostgres(PostgresContainerConfig(host_port=port))
    try:
        harness.start()
        harness.wait_until_ready()
        status = query_local_runtime_status(home, check_containers=True).to_jsonable()
        runtime = status["runtime"]
        assert runtime["coordinator_mode"] == "native"
        assert runtime["direct_db_host_port_enabled"]
        assert runtime["postgres_host_port_checked"]
        assert runtime["postgres_host_port_published"]
        assert "  coordinator:\n" not in render_compose_yaml(plan)
        import subprocess
        inventory = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label=org.repomap.home_hash={plan.identity.home_hash}",
             "--filter", "label=org.repomap.component=coordinator"],
            capture_output=True, text=True, check=True,
        )
        assert inventory.stdout.strip() == ""
    finally:
        harness.teardown()
