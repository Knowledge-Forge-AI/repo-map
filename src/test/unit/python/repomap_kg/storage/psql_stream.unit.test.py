from repomap_kg.storage._psql_stream import _PsqlStreamFailure
import io
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

from repomap_kg.storage._psql_stream import (
    _BoundedTextCapture,
    _terminate_process,
    _write_chunks,
    run_psql_stream,
)
from repomap_kg.storage.errors import StorageSchemaError


class PsqlStreamUnitTests(unittest.TestCase):
    def test_capture_discards_only_oldest_bytes_across_chunks(self):
        capture = _BoundedTextCapture(5)
        capture.append(b"ab")
        capture.append(b"cd")
        capture.append(b"efgh")
        self.assertEqual(capture.text(), "defgh")
        capture.append(b"ijklmnop")
        self.assertEqual(capture.text(), "lmnop")

    def test_capture_decodes_truncated_multibyte_tail_without_failure(self):
        capture = _BoundedTextCapture(3)
        capture.append("éabc".encode())
        self.assertEqual(capture.text(), "abc")
        capture.append("é".encode())
        self.assertEqual(capture.text(), "cé")

    def test_invalid_capture_limit_refuses_before_launch(self):
        with patch("repomap_kg.storage._psql_stream.subprocess.Popen") as launch:
            with self.assertRaisesRegex(ValueError, "capture limit must be positive"):
                run_psql_stream(["fixture-psql"], (), capture_limit=0)
        launch.assert_not_called()

    def test_invalid_batch_size_refuses_before_consuming_chunks(self):
        chunks = _OneShotIterable(("BEGIN;",))
        sink = _RecordingBinarySink()
        with self.assertRaisesRegex(ValueError, "batch size must be positive"):
            _write_chunks(sink, chunks, batch_size=0)
        self.assertEqual(chunks.iterations, 0)
        self.assertEqual(sink.value, b"")
        self.assertEqual(sink.flushes, 0)

    def test_missing_pipe_terminates_child_before_consuming_input(self):
        process = MagicMock(spec=subprocess.Popen)
        process.stdin = None
        process.poll.return_value = None
        process.wait.return_value = -15
        chunks = _OneShotIterable(("BEGIN;",))
        with patch(
            "repomap_kg.storage._psql_stream.subprocess.Popen", return_value=process
        ):
            with self.assertRaisesRegex(StorageSchemaError, "pipes are unavailable"):
                run_psql_stream(["fixture-psql"], chunks)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
        self.assertEqual(chunks.iterations, 0)

    def test_termination_escalates_only_after_timeout_and_reaps_child(self):
        process = MagicMock(spec=subprocess.Popen)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("fixture-psql", 5), -9]
        self.assertEqual(_terminate_process(process), -9)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 2)
        self.assertEqual(process.wait.call_args_list[0].kwargs, {"timeout": 5})
        self.assertEqual(process.wait.call_args_list[1].kwargs, {})

    def test_termination_preserves_already_reaped_exit_status(self):
        process = MagicMock(spec=subprocess.Popen)
        process.poll.return_value = 7
        process.returncode = 7
        self.assertEqual(_terminate_process(process), 7)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        process.wait.assert_not_called()

    def test_write_chunks_flushes_at_bounded_batch_boundaries(self):
        cases = (
            ((), 0),
            (("one\n",), 1),
            (("one\n", "two\n"), 1),
            (("one\n", "two\n", "three\n"), 2),
        )
        for chunks, expected_flushes in cases:
            with self.subTest(chunks=len(chunks)):
                sink = _RecordingBinarySink()

                written = _write_chunks(sink, iter(chunks), batch_size=2)

                self.assertEqual(written, len(chunks))
                self.assertEqual(sink.value, "".join(chunks).encode("utf-8"))
                self.assertEqual(sink.flushes, expected_flushes)

    def test_write_chunks_does_not_double_iterate(self):
        chunks = _OneShotIterable(("one\n", "two\n", "three\n"))
        sink = _RecordingBinarySink()

        _write_chunks(sink, chunks, batch_size=2)

        self.assertEqual(chunks.iterations, 1)

    def test_subprocess_transfer_returns_bounded_summary_output(self):
        completed = run_psql_stream(
            [
                sys.executable,
                "-c",
                (
                    "import sys; data=sys.stdin.read(); "
                    "print('{\"bytes\": %d}' % len(data.encode()))"
                ),
            ],
            iter(("alpha\n", "beta\n")),
            batch_size=1,
            capture_limit=1024,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), '{"bytes": 11}')
        self.assertEqual(completed.stderr, "")

    def test_connector_failure_is_bounded_and_sanitized(self):
        private_sentinel = "source-derived-private-sentinel"
        with self.assertRaisesRegex(StorageSchemaError, "psql failed") as raised:
            run_psql_stream(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; data=sys.stdin.read(); "
                        "sys.stderr.write(data); sys.exit(7)"
                    ),
                ],
                (f"{private_sentinel}\n" for _ in range(1000)),
                batch_size=2,
                capture_limit=128,
            )

        self.assertLessEqual(len(str(raised.exception)), 256)
        self.assertNotIn(private_sentinel, str(raised.exception))

    def test_write_chunks_rejects_unpaired_surrogate_without_output(self):
        sink = _RecordingBinarySink()

        with self.assertRaises(UnicodeEncodeError):
            _write_chunks(sink, iter(("\ud800",)), batch_size=1)

        self.assertEqual(sink.value, b"")
        with self.assertRaises(UnicodeEncodeError):
            run_psql_stream(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                iter(("\ud800",)),
                batch_size=1,
            )

    def test_connection_failure_category_does_not_expose_details(self):
        private_sentinel = "private-connection-detail"

        with self.assertRaises(StorageSchemaError) as raised:
            run_psql_stream(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; sys.stdin.read(); "
                        f"sys.stderr.write('connection refused {private_sentinel}'); "
                        "sys.exit(2)"
                    ),
                ],
                iter(("BEGIN;\n",)),
            )

        assert isinstance(raised.exception, _PsqlStreamFailure)
        self.assertTrue(raised.exception.supports_container_fallback)
        self.assertNotIn(private_sentinel, str(raised.exception))
        self.assertEqual(str(raised.exception), "psql failed with exit code 2")

    def test_serialization_failure_terminates_the_child(self):
        def failing_chunks():
            yield "BEGIN;\n"
            raise ValueError("synthetic serialization failure")

        with self.assertRaisesRegex(ValueError, "synthetic serialization failure"):
            run_psql_stream(
                [sys.executable, "-c", "import sys; sys.stdin.read()"],
                failing_chunks(),
                batch_size=1,
            )

    def test_cancellation_terminates_the_child_with_bounded_diagnostic(self):
        def interrupted_chunks():
            yield "BEGIN;\n"
            raise KeyboardInterrupt

        with self.assertRaisesRegex(
            StorageSchemaError,
            "psql streaming interrupted",
        ):
            run_psql_stream(
                [sys.executable, "-c", "import sys; sys.stdin.read()"],
                interrupted_chunks(),
                batch_size=1,
            )


class _RecordingBinarySink(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0

    @property
    def value(self):
        return self.getvalue()

    def flush(self):
        self.flushes += 1
        super().flush()


class _OneShotIterable:
    def __init__(self, chunks):
        self._chunks = chunks
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("chunks were iterated twice")
        return iter(self._chunks)


if __name__ == "__main__":
    unittest.main()
