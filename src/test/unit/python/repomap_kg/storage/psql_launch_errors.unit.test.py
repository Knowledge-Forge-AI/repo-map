import subprocess
from unittest.mock import patch

import pytest

from repomap_kg.storage._psql_stream import run_psql_stream
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.psql import run_psql


PRIVATE_EXECUTABLE = "/private/source-derived/bin/psql"


@pytest.mark.parametrize("input_text", [None, "", "select 1;\n"])
@pytest.mark.parametrize("environment", [None, {}, {"PGAPPNAME": "fixture"}])
def test_run_psql_preserves_optional_inputs_and_result_identity(
    input_text: str | None, environment: dict[str, str] | None
) -> None:
    command = ("fixture-psql", "-qAt")
    completed = subprocess.CompletedProcess(command, 0, "1\n", "")
    with patch(
        "repomap_kg.storage.psql.subprocess.run", return_value=completed
    ) as run:
        result = run_psql(command, input_text=input_text, env=environment)

    assert result is completed
    assert run.call_args.args == (list(command),)
    options = run.call_args.kwargs
    assert options["check"] is True
    assert options["text"] is True
    assert options["stdout"] == options["stderr"] == subprocess.PIPE
    assert ("input" in options) is (input_text is not None)
    assert ("env" in options) is (environment is not None)
    if input_text is not None:
        assert options["input"] == input_text
    if environment is not None:
        assert options["env"] is environment


def test_run_psql_failure_keeps_original_process_cause() -> None:
    failure = subprocess.CalledProcessError(7, ["fixture-psql"], stderr="refused\n")
    with patch("repomap_kg.storage.psql.subprocess.run", side_effect=failure):
        with pytest.raises(StorageSchemaError, match="^psql failed: refused$") as raised:
            run_psql(["fixture-psql"], input_text="BEGIN;", env={})

    assert raised.value.__cause__ is failure


def test_run_psql_sanitizes_executable_launch_failure() -> None:
    with patch(
        "repomap_kg.storage.psql.subprocess.run",
        side_effect=FileNotFoundError(PRIVATE_EXECUTABLE),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            run_psql([PRIVATE_EXECUTABLE, "-qAt"])

    assert str(raised.value) == "unable to launch psql command"
    assert PRIVATE_EXECUTABLE not in str(raised.value)


def test_run_psql_translates_interruption_to_bounded_storage_error() -> None:
    with patch(
        "repomap_kg.storage.psql.subprocess.run",
        side_effect=KeyboardInterrupt,
    ):
        try:
            run_psql([PRIVATE_EXECUTABLE, "-qAt"])
        except BaseException as caught:
            raised = caught
        else:
            pytest.fail("run_psql did not raise")

    assert isinstance(raised, StorageSchemaError)
    assert str(raised) == "psql command interrupted"
    assert raised.__cause__ is None
    assert raised.__suppress_context__ is True
    assert PRIVATE_EXECUTABLE not in str(raised)


def test_run_psql_stream_sanitizes_executable_launch_failure() -> None:
    with patch(
        "repomap_kg.storage._psql_stream.subprocess.Popen",
        side_effect=FileNotFoundError(PRIVATE_EXECUTABLE),
    ):
        with pytest.raises(StorageSchemaError) as raised:
            run_psql_stream([PRIVATE_EXECUTABLE, "-qAt"], iter(()))

    assert str(raised.value) == "unable to launch psql command"
    assert PRIVATE_EXECUTABLE not in str(raised.value)
