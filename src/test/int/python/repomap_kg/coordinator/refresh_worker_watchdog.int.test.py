import json
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Mapping

import pytest

from repomap_test_support.executable_authority import controlled_psql_copy
from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.ops.config import load_ops_config
from repomap_kg.runtime.postgres_route import effective_postgres_route
from repomap_kg.graph.multi_source_pipeline import scan_multi_source_generations
from repomap_kg.ops.generations import (
    canonicalizer_generation,
    configured_graph,
    extractor_generation,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.coordinator.protocol import run_refresh_worker
from repomap_kg.coordinator.refresh_adapter import (
    RefreshCapability,
    create_refresh_capability,
    execute_refresh,
    load_refresh_capability,
)


def search_path():
    psql = shutil.which("psql")
    assert psql is not None
    return (Path(psql).parent,)


def worker_limits():
    return {
        "process_deadline_seconds": 60, "refresh_attempt_deadline_seconds": 120,
        "heartbeat_seconds": 30, "hello_deadline_seconds": 30,
        "cancellation_after_seconds": 5, "cancel_deadline_seconds": 5,
        "process_termination_grace_seconds": 5, "max_diagnostic_bytes": 4096,
        "max_protocol_line_bytes": 1024 * 1024, "max_array_items": 32,
    }


def _write_config(config_path: Path, repository: Path, postgres: Any = None) -> None:
    host = postgres.socket_dir if postgres else "/tmp"
    port = postgres.port if postgres else 5432
    db = "repomap_test" if postgres else "dummy"
    user = postgres.user if postgres else "repomap_refresh_publication"
    config_path.write_text(
        f'schema_version = 1\n[service]\nmode = "local"\nmcp_transport = "stdio"\nlog_level = "info"\n'
        f'[postgres]\nhost = "{host}"\nport = {port}\ndatabase = "{db}"\nuser = "{user}"\npassword_env = "REPOMAP_PG_PASSWORD"\n'
        f'[[graphs]]\nid = "synthetic-refresh"\nname = "Synthetic Refresh"\nroot_path = "{repository}"\n'
        f'repository_name = "synthetic-refresh"\nprivacy = "public-dev"\nenabled = true\nmcp_visible = false\n'
        f'extractor_profile = "default"\nrefresh_policy = "manual"\n[server_memory]\nenabled = false\npath = "disabled"\nmode = "read_only"\n',
        encoding="utf-8",
    )


def _route_fields(config: Any) -> dict[str, Any]:
    route = effective_postgres_route(config)
    return {"postgres_host": route.host, "postgres_port": route.port, "postgres_route_kind": route.kind}


def test_refresh_worker_timeout_before_publication_records_not_started(monkeypatch):
    with short_test_directory("async4-", "repository/README.md") as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
        config_path = root / "ops.toml"
        _write_config(config_path, repository)
        loaded_config = load_ops_config(config_path)
        configured = configured_graph(loaded_config, "synthetic-refresh")
        scan = scan_multi_source_generations(configured)
        psql_path = controlled_psql_copy(root)
        capability = RefreshCapability(
            schema_version=1, job_id="job-refresh-prepub-timeout", attempt=1,
            graph_id="synthetic-refresh", config_path=config_path, psql_path=psql_path,
            postgres_user="repomap_refresh_publication", postgres_password="test-only", **_route_fields(loaded_config),
            executable_search_path=(psql_path.parent,), source_generation=scan.source_generation,
            config_generation=scan.config_generation, extractor_generation=extractor_generation(configured),
            canonicalizer_generation=canonicalizer_generation(), coordinator_instance_id="worker-refresh-timeout",
            singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        path = create_refresh_capability(root, capability)

        pause_dir = root / "pause_dir"
        pause_dir.mkdir(mode=0o700)
        pause_file = pause_dir / "pause.trigger"
        ready_file = pause_dir / "pause.trigger.ready"
        pause_file.touch()
        monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", str(pause_file))

        timeout_trigger = pause_dir / "timeout.trigger"
        monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER", str(timeout_trigger))

        ready_observed = threading.Event()

        def inject_timeout_on_ready():
            deadline = time.monotonic() + 30.0
            while not ready_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not ready_file.exists():
                raise TimeoutError("pre-publication pause ready marker never appeared")
            ready_observed.set()
            timeout_trigger.touch()

        injector = threading.Thread(target=inject_timeout_on_ready)
        injector.start()

        limits = {
            **worker_limits(),
            "process_deadline_seconds": 60,
            "refresh_attempt_deadline_seconds": 120,
            "heartbeat_seconds": 30,
            "hello_deadline_seconds": 30,
        }
        result = run_refresh_worker(
            path, {"job_id": capability.job_id, "attempt": capability.attempt}, limits,
            job_context={"graph_id": capability.graph_id, "source_generation": capability.source_generation, "config_generation": capability.config_generation},
        )
        injector.join()

        assert ready_observed.is_set()
        assert result.process_timed_out is True
        assert result.heartbeat_timed_out is False
        assert result.terminal["status"] == "failed"
        assert result.terminal["publication_state"] == "not_started"
        assert result.process_group_cleaned is True
        assert not path.exists()


def test_refresh_worker_timeout_after_publication_records_commit_unknown(monkeypatch):
    require_postgres_binaries()
    with short_test_directory("async4-", "repository/README.md") as directory:
        root = Path(directory)
        repository = root / "repository"
        repository.mkdir()
        (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
        with temporary_postgres() as postgres:
            apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
            config_path = root / "ops.toml"
            _write_config(config_path, repository, postgres)
            loaded_config = load_ops_config(config_path)
            configured = configured_graph(loaded_config, "synthetic-refresh")
            scan = scan_multi_source_generations(configured)
            capability = RefreshCapability(
                schema_version=1, job_id="job-refresh-postpub-timeout", attempt=1,
                graph_id="synthetic-refresh", config_path=config_path, psql_path=Path(postgres.psql_command),
                postgres_user=postgres.user, postgres_password=postgres.password, executable_search_path=search_path(),
                **_route_fields(loaded_config),
                source_generation=scan.source_generation, config_generation=scan.config_generation,
                extractor_generation=extractor_generation(configured), canonicalizer_generation=canonicalizer_generation(),
                coordinator_instance_id="worker-refresh-postpub-timeout", singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
            )
            path = create_refresh_capability(root, capability)

            pause_dir = root / "pause_dir"
            pause_dir.mkdir(mode=0o700)
            pause_file = pause_dir / "pause_post.trigger"
            ready_file = pause_dir / "pause_post.trigger.ready"
            pause_file.touch()
            monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH", str(pause_file))

            timeout_trigger = pause_dir / "timeout.trigger"
            monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_TIMEOUT_TRIGGER", str(timeout_trigger))

            ready_observed = threading.Event()

            def inject_timeout_on_ready():
                deadline = time.monotonic() + 30.0
                while not ready_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not ready_file.exists():
                    raise TimeoutError("post-publication pause ready marker never appeared")
                ready_observed.set()
                timeout_trigger.touch()

            injector = threading.Thread(target=inject_timeout_on_ready)
            injector.start()

            limits = {
                **worker_limits(),
                "process_deadline_seconds": 60,
                "refresh_attempt_deadline_seconds": 120,
                "heartbeat_seconds": 30,
                "hello_deadline_seconds": 30,
            }
            result = run_refresh_worker(
                path, {"job_id": capability.job_id, "attempt": capability.attempt}, limits,
                job_context={"graph_id": capability.graph_id, "source_generation": capability.source_generation, "config_generation": capability.config_generation},
            )
            injector.join()

            assert ready_observed.is_set()
            assert result.process_timed_out is True
            assert result.heartbeat_timed_out is False
            assert result.terminal["status"] == "failed"
            assert result.terminal.get("publication_state") == "commit_unknown"
            assert result.terminal.get("error_category") == "worker_timeout"
            assert result.process_group_cleaned is True
            assert not path.exists()


def test_refresh_worker_leaf_and_outer_deadlines_observed_distinct_in_single_attempt(monkeypatch):
    """Verify configured outer supervision and nested leaf process deadlines are observed directly

    at their production boundaries in a single attempt driven by build_refresh_worker_runner.

    Controlled boundary note: The test exercises build_refresh_worker_runner(resolve_authority, root, limits)
    with a validated CoordinatorLimits instance. Outer subprocess execution is substituted with controlled
    routing to execute_refresh while executing real portable worker ingestion and real publication (~4s in
    containerized postgres); the test proves production mapping and value propagation through capability to
    nested leaf without replacement.
    """
    require_postgres_binaries()
    leaf_deadline = 20
    outer_deadline = 120

    with short_test_directory("async4-leafspy-", "repository/README.md") as d, temporary_postgres() as pg:
        root, repo = Path(d), Path(d) / "repository"
        repo.mkdir()
        (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
        apply_migrations(default_rdbms_root(), pg.psql_args, psql_command=pg.psql_command)
        cfg_path = root / "ops.toml"
        _write_config(cfg_path, repo, pg)
        cfg = configured_graph(load_ops_config(cfg_path), "synthetic-refresh")
        scan = scan_multi_source_generations(cfg)

        from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
        from repomap_kg.coordinator.refresh_adapter import build_refresh_worker_runner
        from repomap_kg.coordinator.limits import CoordinatorLimits, HARD_MAX_LIMITS
        from types import SimpleNamespace

        resolver = ConfiguredRefreshResolver(
            cfg_path, Path(pg.psql_command), postgres_user=pg.user, postgres_password=pg.password,
        )
        limits = CoordinatorLimits(
            process_deadline_seconds=leaf_deadline, refresh_attempt_deadline_seconds=outer_deadline, cancel_deadline_seconds=10,
        )
        limits.validate(hard_maxima=HARD_MAX_LIMITS)

        captured_outer_limits: dict[str, Any] = {}
        captured_leaf_limits: dict[str, Any] = {}
        outer_spy_calls: list[dict[str, Any]] = []
        leaf_spy_calls: list[dict[str, Any]] = []

        import repomap_kg.coordinator.refresh_adapter as ra
        import repomap_kg.ops.portable_refresh as pr
        from repomap_kg.coordinator._protocol_execution import SyntheticWorkerResult
        from repomap_kg.coordinator import _publication_phase

        orig_run_portable = pr.run_portable_worker

        def spy_run_portable(cap_path: Any, ident: Any, lim: Any, *args: Any, **kwargs: Any) -> Any:
            leaf_spy_calls.append({"cap_path": cap_path, "identity": dict(ident) if hasattr(ident, "__getitem__") else ident, "limits": lim})
            if hasattr(lim, "process_deadline_seconds"):
                captured_leaf_limits["process_deadline_seconds"] = lim.process_deadline_seconds
            elif isinstance(lim, Mapping):
                captured_leaf_limits["process_deadline_seconds"] = lim.get("process_deadline_seconds")
            return orig_run_portable(cap_path, ident, lim, *args, **kwargs)

        monkeypatch.setattr(pr, "run_portable_worker", spy_run_portable)

        def spy_run_protocol_worker(
            argv: tuple[str, ...], env: Any, work_dir: Path, auto_cancel: bool, identity: Any, supervision_limits: Any, *args: Any, **kwargs: Any
        ) -> SyntheticWorkerResult:
            outer_spy_calls.append({"argv": argv, "identity": dict(identity) if hasattr(identity, "__getitem__") else identity, "supervision_limits": supervision_limits})
            if hasattr(supervision_limits, "process_deadline_seconds"):
                captured_outer_limits["process_deadline_seconds"] = supervision_limits.process_deadline_seconds
            elif isinstance(supervision_limits, Mapping):
                captured_outer_limits["process_deadline_seconds"] = supervision_limits.get("process_deadline_seconds")

            cap_idx = argv.index("--capability")
            p = Path(argv[cap_idx + 1])
            loaded_cap = load_refresh_capability(p)
            refresh_result = execute_refresh(
                loaded_cap, before_publication=lambda: _publication_phase.before_publication(p.parent, loaded_cap)
            )
            terminal = ra.refresh_terminal(loaded_cap, refresh_result)

            return SyntheticWorkerResult(
                argv=argv, messages=(), terminal=terminal, stderr="", stderr_total_bytes=0,
                stderr_truncated=False, returncode=0, process_timed_out=False, heartbeat_timed_out=False,
                hello_timed_out=False, terminated=False, killed=False, process_group_cleaned=True,
                supervision_kind="managed_process", waited=True, protocol_error=None, synthesized_terminal=False,
            )

        monkeypatch.setattr(ra, "_run_protocol_worker", spy_run_protocol_worker)

        runner = build_refresh_worker_runner(resolver.resolve_authority, root, limits)
        claim = SimpleNamespace(
            job_id="job-refresh-leafspy", attempt=1, graph_id="synthetic-refresh",
            source_generation=scan.source_generation, config_generation=scan.config_generation,
            extractor_generation=extractor_generation(cfg), canonicalizer_generation=canonicalizer_generation(),
            instance_id="worker-leafspy", fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        res = runner(claim, threading.Event())

        # 1. Exactly one invocation for each boundary in this single attempt
        assert len(outer_spy_calls) == 1 and len(leaf_spy_calls) == 1

        # 2. Both boundaries witnessed the exact same job and attempt
        assert outer_spy_calls[0]["identity"]["job_id"] == claim.job_id == leaf_spy_calls[0]["identity"]["job_id"]
        assert outer_spy_calls[0]["identity"]["attempt"] == claim.attempt == leaf_spy_calls[0]["identity"]["attempt"]

        # 3. Outer supervisor received configured outer attempt deadline (120s)
        assert captured_outer_limits.get("process_deadline_seconds") == outer_deadline

        # 4. Nested leaf worker received configured leaf process deadline (20s)
        assert captured_leaf_limits.get("process_deadline_seconds") == leaf_deadline

        # 5. Anti-aliasing proof: inner leaf and outer attempt deadlines are distinct
        assert captured_leaf_limits["process_deadline_seconds"] != captured_outer_limits["process_deadline_seconds"]

        # 6. Real publication and terminal state checks
        assert res.get("status") == "succeeded" and res.get("publication_state") == "committed"

        # 7. Durable production signal: retained portable result lifecycle status is terminal-accepted
        retained = tuple((root / "state" / "portable-publication" / "attempts").glob("*/portable-result.json"))
        assert len(retained) == 1
        retention = json.loads(retained[0].read_text(encoding="utf-8"))
        assert retention.get("retention_class") == "terminal-accepted"



def test_refresh_worker_anti_aliasing_and_cancellation():
    with short_test_directory("async4-", "repository/README.md") as directory:
        root = Path(directory)
        config_path = root / "ops.toml"
        config_path.write_text("version = 1\n", encoding="utf-8")
        psql_path = controlled_psql_copy(root)
        capability = RefreshCapability(
            schema_version=1, job_id="job-refresh-cancel", attempt=1,
            graph_id="synthetic-refresh", config_path=config_path, psql_path=psql_path,
            postgres_user="repomap_refresh_publication", postgres_password="test-only",
            executable_search_path=(psql_path.parent,), source_generation="sg1:source",
            config_generation="cg1:config", extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer", coordinator_instance_id="worker-refresh-cancel",
            singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        path = create_refresh_capability(root, capability)

        aliased_limits = {
            "process_deadline_seconds": 10,
            "heartbeat_seconds": 10,
            "hello_deadline_seconds": 2,
        }
        with pytest.raises(ValueError, match="refresh_attempt_deadline_seconds is required"):
            run_refresh_worker(
                path, {"job_id": capability.job_id, "attempt": capability.attempt}, aliased_limits,
                job_context={"graph_id": capability.graph_id, "source_generation": capability.source_generation, "config_generation": capability.config_generation},
            )

        aliased_equal_limits = {
            **worker_limits(),
            "process_deadline_seconds": 10,
            "refresh_attempt_deadline_seconds": 10,
        }
        with pytest.raises(ValueError, match="refresh_attempt_deadline_seconds must be greater than process_deadline_seconds"):
            run_refresh_worker(
                path, {"job_id": capability.job_id, "attempt": capability.attempt}, aliased_equal_limits,
                job_context={"graph_id": capability.graph_id, "source_generation": capability.source_generation, "config_generation": capability.config_generation},
            )

        cancel_event = threading.Event()
        cancel_event.set()
        result = run_refresh_worker(
            path, {"job_id": capability.job_id, "attempt": capability.attempt}, worker_limits(),
            job_context={"graph_id": capability.graph_id, "source_generation": capability.source_generation, "config_generation": capability.config_generation},
            cancel_event=cancel_event,
        )
        assert result.terminal["status"] in {"failed", "cancelled"}
        assert result.terminal["publication_state"] == "not_started"
        assert result.process_group_cleaned is True
        assert not path.exists()
