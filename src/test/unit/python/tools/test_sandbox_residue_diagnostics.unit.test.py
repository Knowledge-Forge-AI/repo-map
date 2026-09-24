import hashlib
import json
import subprocess

import pytest
import test_sandbox as sandbox


def snapshot(**changes):
    return sandbox.HostSnapshot(**{
        kind: frozenset(changes.get(kind, ()))
        for kind in ("containers", "images", "volumes", "networks")
    })


@pytest.mark.parametrize("labels,ownership", [
    ({"org.repomap.test.resource.run_id": "private-run"}, "repomap_metadata"),
    ({"com.docker.compose.project": "explicit-other-owner"}, "unattributed"),
    ({"secret-key": "private-secret"}, "unattributed"),
    ({}, "unattributed"),
    (None, "unattributed"),
])
def test_new_volume_is_identified_inspected_and_never_excused(labels, ownership, capsys):
    calls = []
    identity = "private-volume-name"

    def runner(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] <= 2
        return subprocess.CompletedProcess(command, 0, json.dumps(labels), "private-stderr")

    with pytest.raises(RuntimeError, match="volumes=1"):
        sandbox.verify_host_snapshot(snapshot(), snapshot(volumes=[identity]), runner=runner)
    assert calls == [["docker", "volume", "inspect", "--format", "{{json .Labels}}", "--", identity]]
    output = capsys.readouterr().err
    record, summary = map(json.loads, output.splitlines())
    assert record["identity_sha256"] == hashlib.sha256(identity.encode()).hexdigest()
    assert record["engine_id"] is None
    assert record["inspection"] == "inspected" and record["ownership"] == ownership
    if labels and "com.docker.compose.project" in labels:
        assert record["owner_label_sha256"]["com.docker.compose.project"] == hashlib.sha256(
            b"explicit-other-owner").hexdigest()
    assert summary["decision"] == "failed" and summary["omitted"] == 0
    for private in (identity, "private-run", "explicit-other-owner", "secret-key", "private-secret", "private-stderr"):
        assert private not in output


@pytest.mark.parametrize("failure,expected", [
    ("timeout", "TimeoutExpired"), ("os-error", "OSError"),
    ("nonzero", "unavailable"), ("malformed", "JSONDecodeError"),
    ("wrong-type", "malformed"), ("oversized", "oversized"),
])
def test_inspection_failure_retains_primary_residue_failure(failure, expected, capsys):
    def runner(command, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 2, stderr="private-error")
        if failure == "os-error":
            raise OSError("private-error")
        payload = {"malformed": "private-error", "wrong-type": "[]", "oversized": "x" * 16385}.get(failure, "{}")
        return subprocess.CompletedProcess(command, 1 if failure == "nonzero" else 0, payload, "private-error")

    with pytest.raises(RuntimeError, match="unexpected host Docker residue.*volumes=1"):
        sandbox.verify_host_snapshot(snapshot(), snapshot(volumes=["a" * 64]), runner=runner)
    output = capsys.readouterr().err
    record = json.loads(output.splitlines()[0])
    assert record["inspection"] == expected and record["engine_id"] == "a" * 64
    assert "private-error" not in output


def test_diagnostics_are_bounded_and_all_resource_kinds_remain_fatal(capsys):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    after = snapshot(containers=["a" * 64], images=["sha256:" + "b" * 64],
                     networks=["c" * 64], volumes=[f"volume-{i:02}" for i in range(20)])
    with pytest.raises(RuntimeError, match="containers=1, images=1, networks=1, volumes=20"):
        sandbox.verify_host_snapshot(snapshot(), after, runner=runner)
    assert len(calls) == 16 and all(c[2] == "inspect" for c in calls)
    assert [c[4] for c in calls[:4]] == ["{{json .Config.Labels}}", "{{json .Config.Labels}}",
                                       "{{json .Labels}}", "{{json .Labels}}"]
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert len(records) == 17 and records[-1]["omitted"] == 7


def test_unchanged_snapshot_never_inspects_or_emits(capsys):
    def runner(*args, **kwargs):
        raise AssertionError("unchanged resources must not be inspected")

    before = snapshot(volumes=["baseline-private"])
    sandbox.verify_host_snapshot(before, before, runner=runner)
    assert not capsys.readouterr().err
