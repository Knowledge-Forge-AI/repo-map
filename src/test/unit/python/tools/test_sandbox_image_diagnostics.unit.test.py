import hashlib
import json
import subprocess

import pytest
import test_sandbox as sandbox_owner


@pytest.mark.parametrize("stderr,category", [
    ("Cannot connect to the Docker daemon at unix:///private/operator.sock", "endpoint_unavailable"),
    ("permission denied for secret-token", "endpoint_unavailable"),
    ("unexpected inspector failure secret-token", "inspection_failed"),
    ("", "inspection_failed"),
])
def test_inspection_failure_does_not_authorize_build(tmp_path, capsys, stderr, category):
    recipe = tmp_path / "Dockerfile"
    recipe.write_text("FROM scratch\n")
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 17, "private configuration", stderr)

    with pytest.raises(RuntimeError, match=category):
        sandbox_owner.ensure_sandbox_image(dockerfile=recipe, runner=runner)
    assert len(calls) == 1 and calls[0][:3] == ["docker", "image", "inspect"]
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["stage"] == "inspect" and diagnostic["returncode"] == 17
    assert diagnostic["category"] == category
    assert diagnostic["stderr_bytes"] == len(stderr.encode())
    assert diagnostic["stderr_sha256"] == hashlib.sha256(stderr.encode()).hexdigest()
    assert "secret-token" not in str(diagnostic)
    assert "operator.sock" not in str(diagnostic)
    assert "private configuration" not in str(diagnostic)


def test_failed_build_retains_sanitized_status_without_retry(tmp_path, capsys):
    recipe = tmp_path / "Dockerfile"
    recipe.write_text("FROM scratch\n")
    calls = []
    stderr = "failed to solve: secret-token at /private/operator/config"

    def runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 1, "", f"Error response from daemon: No such image: {sandbox_owner.IMAGE_TAG}")
        return subprocess.CompletedProcess(command, 23, "private build output", stderr)

    with pytest.raises(RuntimeError, match="build failed: exit=23"):
        sandbox_owner.ensure_sandbox_image(dockerfile=recipe, runner=runner)
    assert [c[:2] for c in calls] == [["docker", "image"], ["docker", "build"]]
    diagnostics = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [d["category"] for d in diagnostics] == ["cache_absent", "build_failed"]
    assert diagnostics[1]["returncode"] == 23
    assert diagnostics[1]["stderr"] == "failed to solve"
    assert diagnostics[1]["stderr_sha256"] == hashlib.sha256(stderr.encode()).hexdigest()
    assert "secret-token" not in str(diagnostics)
    assert "private build output" not in str(diagnostics)


@pytest.mark.parametrize("prefix,suffix", [
    ("WARNING: experimental client setting\n", ""),
    ("", "\nWARNING: unrelated client warning"),
    ("WARNING: client setting\n", "\n"),
])
def test_missing_image_with_warnings_is_cache_absence(prefix, suffix, capsys):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", prefix +
            f"Error response from daemon: No such image: {sandbox_owner.IMAGE_TAG}" + suffix)

    status, image_id = sandbox_owner._inspect_managed_image(runner, "fixture-recipe")
    assert status == 1 and image_id is None
    assert json.loads(capsys.readouterr().err)["category"] == "cache_absent"


def test_endpoint_failure_takes_precedence_over_missing_image(capsys):
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "",
            f"Error: No such image: {sandbox_owner.IMAGE_TAG}\npermission denied")

    with pytest.raises(RuntimeError, match="endpoint_unavailable"):
        sandbox_owner._inspect_managed_image(runner, "fixture-recipe")
    assert json.loads(capsys.readouterr().err)["category"] == "endpoint_unavailable"
