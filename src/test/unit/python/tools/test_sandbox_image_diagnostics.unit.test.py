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


@pytest.mark.parametrize("detail,expected", [
    ("CERTIFICATE_VERIFY_FAILED at https://private.invalid/token", ["tls"]),
    ("Temporary failure resolving private.invalid", ["dns"]),
    ("connection timed out", ["timeout"]),
    ("HTTP Error 429: Too Many Requests", ["http_rate_limit"]),
    ("HTTP Error 503: Service Unavailable", ["http_service"]),
    ("apt prerequisites refused: transaction changes installed private:amd64 1 -> 2", ["apt_prerequisite_refused", "apt_preservation_refused"]),
    ("hash sum mismatch for private.deb", ["archive_identity"]),
    ("No matching distribution found for private", ["package_resolution"]),
    ("no space left on device at /private/operator", ["storage_exhausted"]),
    ("unknown secret-token and /private/operator path", []),
])
@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_failure_reasons_are_closed_codes_across_both_build_channels(capsys, detail, expected, channel):
    streams = {"stdout": "", "stderr": ""}
    streams[channel] = detail
    result = subprocess.CompletedProcess(["private-command"], 23, **streams)
    sandbox_owner._images._image_diagnostic("build", result, "build_failed")
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["failure_reasons"] == expected
    for name, value in streams.items():
        assert diagnostic[name + "_bytes"] == len(value.encode())
        assert diagnostic[name + "_sha256"] == hashlib.sha256(value.encode()).hexdigest()
    serialized = json.dumps(diagnostic)
    for private in ("private.invalid", "private-command", "secret-token", "private.deb", "/private/operator"):
        assert private not in serialized


def test_success_does_not_report_reason_codes_from_echoed_build_text(capsys):
    result = subprocess.CompletedProcess([], 0, "HTTP Error 503: Service Unavailable", "")
    sandbox_owner._images._image_diagnostic("build", result, "built")
    assert json.loads(capsys.readouterr().err)["failure_reasons"] == []


@pytest.mark.parametrize("progress", ["", "#12 8.125 ", "\x1b[31m#12 8.125 \x1b[0m"])
@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_canonical_apt_explanation_survives_the_outer_projection(capsys, monkeypatch, progress, channel):
    private = "fixture-sensitive-value"
    monkeypatch.setenv("CREDENTIAL_FOR_TEST", private)
    message = "apt-get install --simulate failed with exit 100; libssl-dev depends on libssl3t64 (= 3.5.5-1~deb13u1)"
    line = progress + "apt prerequisites refused: " + message + " | " + private + " at /private/operator/config https://mirror.example.invalid/path"
    streams = {"stdout": "", "stderr": ""}
    streams[channel] = line
    sandbox_owner._images._image_diagnostic("build", subprocess.CompletedProcess([], 1, **streams), "build_failed")
    diagnostic = json.loads(capsys.readouterr().err)
    detail = diagnostic["apt_failure"]
    assert "exit 100" in detail["redacted_message"]
    assert "libssl-dev" in detail["redacted_message"]
    assert "3.5.5-1~deb13u1" in detail["redacted_message"]
    assert detail["source_line_bytes"] == len(line.encode())
    assert detail["source_line_sha256"] == hashlib.sha256(line.encode()).hexdigest()
    for value in (private, "/private/operator", "mirror.example.invalid"):
        assert value not in json.dumps(diagnostic)


@pytest.mark.parametrize("text", [
    'RUN print("apt prerequisites refused: untrusted echo")',
    "ERROR apt prerequisites refused: arbitrary context",
    "#3 [stage 2/4] RUN apt prerequisites refused: echoed command",
])
def test_arbitrary_build_context_is_not_a_canonical_failure_line(text):
    assert sandbox_owner._images._apt_failure(text, "") is None


def test_apt_explanation_is_bounded_after_redaction(monkeypatch):
    private = "fixture-sensitive-" + "x" * 6000
    monkeypatch.setenv("CREDENTIAL_FOR_TEST", private)
    text = "#1 1.2 apt prerequisites refused: " + private + " | " + "public detail " * 600
    result = sandbox_owner._images._apt_failure("", text)
    assert result is not None
    message = result["redacted_message"]
    assert isinstance(message, str) and len(message) <= 4000
    assert "fixture-sensitive" not in message


def test_success_does_not_retain_echoed_apt_failure(capsys):
    line = "apt prerequisites refused: an echoed test fixture"
    sandbox_owner._images._image_diagnostic("build", subprocess.CompletedProcess([], 0, line, ""), "built")
    assert json.loads(capsys.readouterr().err)["apt_failure"] is None
