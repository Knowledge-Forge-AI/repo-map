import subprocess

from repomap_kg.storage.psql import psql_failure_message


def _failure(*, stderr: str = "", stdout: str = "") -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        9,
        ["psql"],
        output=stdout,
        stderr=stderr,
    )


def test_psql_failure_message_bounds_multiline_stderr() -> None:
    details = "connection refused at /private/source-derived/root\n" + (
        "additional private diagnostic\n" * 512
    )

    message = psql_failure_message(_failure(stderr=details))

    assert message.startswith("psql failed: connection refused")
    assert message.endswith(" ... [truncated]")
    assert "\n" not in message
    assert len(message) <= 525


def test_psql_failure_message_bounds_stdout_fallback() -> None:
    details = "query failed " + ("x" * 2048)

    message = psql_failure_message(_failure(stdout=details))

    assert message.startswith("psql failed: query failed")
    assert message.endswith(" ... [truncated]")
    assert len(message) <= 525


def test_psql_failure_message_preserves_short_detail() -> None:
    message = psql_failure_message(_failure(stderr="connection refused\n"))

    assert message == "psql failed: connection refused"


def test_psql_failure_message_without_detail_uses_exit_code() -> None:
    message = psql_failure_message(_failure())

    assert message == "psql failed with exit code 9"
