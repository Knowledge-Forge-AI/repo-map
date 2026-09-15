"""TEST-RUNNER-SAFETY1 canonical runner dependency-flow contracts."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import Mock, call, patch

import pytest
import run_tests
from test_runner_entry import RunnerDependencies, run_test_runner

from repomap_test_support.resource_hygiene_policy import HygieneConfig, HygieneProfile


EXACT_IMAGE = "sha256:" + "a" * 64


def test_entrypoint_uses_its_own_globals_after_module_registry_replacement():
    class ReachedPatchedScratch(Exception):
        pass

    with (
        patch.dict(sys.modules, {"run_tests": ModuleType("run_tests")}),
        patch.object(run_tests, "establish_test_scratch", side_effect=ReachedPatchedScratch) as scratch,
    ):
        with pytest.raises(ReachedPatchedScratch):
            run_tests.main(["--suite", "unit"])
    scratch.assert_called_once()


def _zero_docker_projection():
    return {
        "product_or_build_profile_build_count": 0,
        "managed_test_runtime_image_build_count": 0,
        "managed_runtime_build_intermediate_created_count": 0,
        "managed_runtime_build_intermediate_removed_count": 0,
        "managed_runtime_build_intermediate_residue_count": 0,
        "managed_external_base_pull_count": 0,
        "unmanaged_build_count": 0,
        "unmanaged_pull_count": 0,
        "new_managed_external_test_base_images": 0,
        "new_managed_test_runtime_cache_images": 0,
        "new_unattributed_images": 0,
        "new_unattributed_volumes": 0,
        "current_run_ephemeral_image_residue": 0,
        "current_run_image_residue": 0,
        "current_run_volume_residue": 0,
    }


def _layout(tmp_path, *, allocated=True):
    root = tmp_path / "run"
    root.mkdir()
    return SimpleNamespace(run_root=root, allocated=allocated)


def test_docker_projection_reports_managed_cache_and_ephemeral_classes(capsys):
    run_tests.report_docker_projection(_zero_docker_projection(), boundary="terminal")

    output = capsys.readouterr().out
    assert "managed_test_runtime_image_build_count: 0" in output
    assert "managed_runtime_build_intermediate_created_count: 0" in output
    assert "managed_runtime_build_intermediate_removed_count: 0" in output
    assert "managed_runtime_build_intermediate_residue_count: 0" in output
    assert "managed_external_base_pull_count: 0" in output
    assert "new_managed_external_test_base_images: 0" in output
    assert "new_managed_test_runtime_cache_images: 0" in output
    assert "current_run_ephemeral_image_residue: 0" in output


def test_missing_smoke_override_uses_managed_default_path(tmp_path):
    del tmp_path
    class ReachedManagedRun(Exception):
        pass

    with patch.object(
        run_tests,
        "establish_test_scratch",
        side_effect=ReachedManagedRun,
    ) as scratch:
        with pytest.raises(ReachedManagedRun):
            run_tests.main(["--suite", "smoke"])

    scratch.assert_called_once()


def test_mutable_smoke_image_tag_is_rejected_before_scratch():
    with patch.object(run_tests, "establish_test_scratch") as scratch:
        result = run_tests.main(
            ["--suite", "smoke", "--smoke-image-reference", "python:3.13-slim"]
        )

    assert result == 2
    scratch.assert_not_called()


def test_staging_passes_the_exact_allocating_resource_run_into_smoke(tmp_path):
    layout = _layout(tmp_path)
    resource_run = Mock()
    resource_run.quota_exceeded = False
    resource_run.bounded_subprocess.return_value = nullcontext()
    boundary = Mock()
    boundary.verify_terminal.return_value = _zero_docker_projection()
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(
            run_tests,
            "load_hygiene_config",
            return_value=HygieneConfig(requested_profile=HygieneProfile.HEAVY),
        ),
        patch.object(run_tests.TestResourceRun, "start", return_value=resource_run),
        patch.object(
            run_tests,
            "start_runwide_docker_boundary",
            return_value=boundary,
        ),
        patch.object(run_tests, "prepare_go_test_environment"),
        patch.object(run_tests, "require_integration_sandbox"),
        patch.object(run_tests, "integration_sandbox_dispatch", return_value=None),
        patch.object(run_tests, "run_pytest_suites", return_value=0),
        patch.object(run_tests, "run_smoke_suite", return_value=0) as smoke,
        patch.object(run_tests, "finalize_run"),
    ):
        result = run_tests.main(
            [
                "--suite",
                "staging",
                "--hygiene-profile",
                "heavy",
                "--declared-complete-gates",
                "1",
                "--smoke-image-reference",
                EXACT_IMAGE,
            ]
        )

    assert result == 0
    assert smoke.call_args.args[1] is resource_run
    assert smoke.call_args.args[2] is boundary
    assert boundary.verify_terminal.call_count == 3
    boundary.close.assert_called_once_with(resource_run)


def test_smoke_receives_exact_image_id_from_repository_manager():
    args = SimpleNamespace(
        smoke_image_reference=None,
        smoke_timeout=5,
        pg_container_port=55433,
    )
    resource_run = Mock()
    boundary = Mock()
    with (
        patch(
            "repomap_test_support.resource_test_images.ensure_canonical_runtime_image",
            return_value=EXACT_IMAGE,
        ) as ensure_image,
        patch("smoke.container_smoke.run_container_smoke", return_value=0) as smoke,
    ):
        result = run_tests.run_smoke_suite(args, resource_run, boundary)

    assert result == 0
    ensure_image.assert_called_once_with(
        repo_root=run_tests.REPO_ROOT,
        resource_run=resource_run,
        client=boundary.client,
        boundary=boundary,
    )
    assert smoke.call_args.args[0].image_reference == EXACT_IMAGE
    assert smoke.call_args.kwargs["resource_run"] is resource_run


def test_smoke_refuses_inherited_run_before_any_suite_work(tmp_path):
    layout = _layout(tmp_path, allocated=False)
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(run_tests, "load_hygiene_config", return_value=HygieneConfig()),
        patch.object(run_tests.TestResourceRun, "start", return_value=None),
        patch.object(run_tests, "integration_sandbox_dispatch", return_value=None),
        patch.object(run_tests, "run_selected_suites") as work,
        patch.object(run_tests, "finalize_run"),
    ):
        result = run_tests.main(
            ["--suite", "smoke", "--smoke-image-reference", EXACT_IMAGE]
        )

    assert result == 2
    work.assert_not_called()


def test_int_refuses_inherited_run_before_any_container_work(tmp_path):
    layout = _layout(tmp_path, allocated=False)
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(run_tests, "load_hygiene_config", return_value=HygieneConfig()),
        patch.object(run_tests.TestResourceRun, "start", return_value=None),
        patch.object(run_tests, "integration_sandbox_dispatch", return_value=None),
        patch.object(run_tests, "run_selected_suites") as work,
        patch.object(run_tests, "finalize_run"),
    ):
        result = run_tests.main(["--suite", "int"])

    assert result == 2
    work.assert_not_called()


def test_staging_refuses_inherited_run_before_any_suite_work(tmp_path):
    layout = _layout(tmp_path, allocated=False)
    with (
        patch.object(run_tests, "establish_test_scratch", return_value=layout),
        patch.object(run_tests, "load_hygiene_config", return_value=HygieneConfig()),
        patch.object(run_tests.TestResourceRun, "start", return_value=None),
        patch.object(run_tests, "run_selected_suites") as work,
        patch.object(run_tests, "finalize_run"),
    ):
        result = run_tests.main(["--suite", "staging"])

    assert result == 2
    work.assert_not_called()


def test_runwide_boundary_refuses_non_exact_managed_run() -> None:
    args = SimpleNamespace(suite="int", pg_container_runtime="docker")

    with (
        patch.object(run_tests, "require_integration_sandbox"),
        pytest.raises(RuntimeError, match="exact managed run"),
    ):
        run_tests.start_runwide_docker_boundary(args, Mock())


def test_removed_smoke_runtime_option_cannot_represent_podman_as_qualified():
    with pytest.raises(SystemExit):
        run_tests.main(
            [
                "--suite",
                "smoke",
                "--smoke-image-reference",
                EXACT_IMAGE,
                "--smoke-container-runtime",
                "podman",
            ]
        )


def test_invalid_smoke_timeout_refuses_before_scratch_or_work():
    with (
        patch.object(run_tests, "establish_test_scratch") as scratch,
        patch.object(run_tests, "run_selected_suites") as work,
    ):
        result = run_tests.main(
            [
                "--suite",
                "staging",
                "--smoke-image-reference",
                EXACT_IMAGE,
                "--smoke-timeout",
                "0",
            ]
        )

    assert result == 2
    scratch.assert_not_called()
    work.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "work_status", "expected_status", "residue"),
    [
        ("none", 0, 0, False),
        ("none", 5, 5, False),
        ("admission", 0, 2, False),
        ("admission_cleanup", 0, 2, True),
        ("docker_verify", 0, 2, True),
        ("docker_close", 5, 2, True),
        ("resource_close", 0, 2, True),
    ],
)
def test_runner_capabilities_isolate_work_and_preserve_terminal_precedence(
    tmp_path: Path, failure: str, work_status: int, expected_status: int, residue: bool,
) -> None:
    capabilities = Mock()
    resource = capabilities.resource
    resource.quota_exceeded = False
    resource.bounded_subprocess.return_value = nullcontext()
    boundary = capabilities.boundary
    boundary.verify_terminal.return_value = {"current_run_image_residue": 0}
    layout = Mock(run_root=tmp_path / "unallocated", allocated=True)
    capabilities.split.return_value = (["--suite", "unit", "--no-coverage"], ["owner.unit.test.py"])
    capabilities.dispatch.return_value = None
    capabilities.scratch.return_value = layout
    capabilities.config.return_value = HygieneConfig()
    capabilities.resource_type.start.return_value = resource
    capabilities.start_boundary.return_value = boundary
    capabilities.work.return_value = work_status
    dependencies = RunnerDependencies(
        repo_root=tmp_path, default_report_root=tmp_path / "reports",
        split_forwarded_args=capabilities.split, parse_jobs=capabilities.parse_jobs,
        validate_sandbox_admission_options=capabilities.validate,
        integration_sandbox_dispatch=capabilities.dispatch,
        establish_test_scratch=capabilities.scratch, load_hygiene_config=capabilities.config,
        resolve_runner_profile=capabilities.profile, resource_run_type=capabilities.resource_type,
        cleanup_unadmitted_layout=capabilities.cleanup, finalize_run=capabilities.finalize,
        start_runwide_docker_boundary=capabilities.start_boundary,
        run_selected_suites=capabilities.work, report_docker_projection=capabilities.projection,
        terminal_outcome_type=capabilities.outcome,
    )
    if failure.startswith("admission"):
        capabilities.resource_type.start.side_effect = RuntimeError("admission refused")
    if failure == "admission_cleanup":
        capabilities.cleanup.side_effect = RuntimeError("scratch cleanup refused")
    if failure == "docker_verify":
        boundary.verify_terminal.side_effect = RuntimeError("terminal residue")
    if failure == "docker_close":
        boundary.close.side_effect = RuntimeError("Docker cleanup refused")
    if failure == "resource_close":
        resource.close.side_effect = RuntimeError("resource cleanup refused")

    with (
        patch.object(Path, "mkdir", side_effect=AssertionError("real scratch allocation")),
        patch("subprocess.Popen", side_effect=AssertionError("real child execution")),
        patch.object(run_tests.TestResourceRun, "start", side_effect=AssertionError("real admission")),
    ):
        result = run_test_runner(["supplied arguments"], dependencies=dependencies)

    assert result == expected_status
    capabilities.split.assert_called_once_with(["supplied arguments"])
    capabilities.scratch.assert_called_once()
    capabilities.finalize.assert_called_once_with(
        layout, "passed" if expected_status == 0 else "failed",
        exit_status=expected_status, live_runtime_residue=residue,
    )
    if failure.startswith("admission"):
        capabilities.cleanup.assert_called_once_with(layout)
        capabilities.work.assert_not_called()
        capabilities.start_boundary.assert_not_called()
        resource.close.assert_not_called()
        assert capabilities.mock_calls[-2:] == [
            call.cleanup(layout),
            call.finalize(layout, "failed", exit_status=2, live_runtime_residue=residue),
        ]
    else:
        capabilities.cleanup.assert_not_called()
        capabilities.work.assert_called_once_with(
            capabilities.scratch.call_args.args[0], ["owner.unit.test.py"], resource, boundary,
        )
        boundary.verify_terminal.assert_called_once_with()
        boundary.close.assert_called_once_with(resource)
        passed_before_close = work_status == 0 and failure not in {"docker_verify", "docker_close"}
        outcome = capabilities.outcome.PASSED if passed_before_close else capabilities.outcome.FAILED
        resource.close.assert_called_once_with(outcome)
        names = [entry[0] for entry in capabilities.mock_calls]
        assert names.index("boundary.close") < names.index("resource.close") < names.index("finalize")
    assert not layout.run_root.exists()
