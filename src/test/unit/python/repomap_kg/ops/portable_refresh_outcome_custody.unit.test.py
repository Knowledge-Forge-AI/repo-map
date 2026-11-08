from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from repomap_test_support.ops_refresh import OpsRefreshUnitTestCase

from common_lore_index.ops import portable_refresh
from common_lore_index.ops.portable_refresh import execute_portable_refresh
from common_lore_index.storage.main import LoadSummary
from common_lore_index.storage.publication_phase_witness import PublicationPhase, PublicationPhaseWitness
from common_lore_index.ops._portable_refresh_custody import prepare_server_publication_root, settle_after_publisher_error
from common_lore_index.ops._server_retention_lock import RetentionLockError, ServerRetentionLock


class _CleanupFault(BaseException):
    """A cleanup failure that must not replace the publication primary."""


class _PrimaryError(RuntimeError):
    """A primary whose note sink also fails, exercising BaseException custody."""

    def __init__(self, annotation_fault: BaseException):
        super().__init__("primary publication failure")
        self.annotation_fault = annotation_fault
        self.annotation_attempts = 0

    def add_note(self, note: str) -> None:
        self.annotation_attempts += 1
        raise self.annotation_fault


class _Capture:
    authority = object()

    def __init__(self, terminal_errors: dict[bool, BaseException] | None = None):
        self.terminal_errors = terminal_errors or {}
        self.terminal_calls: list[bool] = []
        self.retention_class = "publication-reconciliation"
        self.annotation_calls: list[tuple[object, object]] = []

    def mark_terminal(self, *, accepted: bool, **_kwargs: object) -> None:
        self.terminal_calls.append(accepted)
        self.retention_class = "terminal-accepted" if accepted else "terminal-failed"
        error = self.terminal_errors.get(accepted)
        if error is not None:
            raise error

    def annotate(self, key: object, value: object, **_kwargs: object) -> None:
        self.annotation_calls.append((key, value))


class _Validated:
    family_counts = {"files": 1, "raw_observations": 1}

    def __init__(self, close_error: BaseException | None = None):
        self.close_error = close_error
        self.close_calls = 0

    def to_prepared_stage_rows(self) -> tuple[()]:
        return ()

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class PortableRefreshOutcomeCustodyUnitTests(OpsRefreshUnitTestCase):
    def test_server_anchor_is_private_when_new_and_never_chmods_existing_root(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "state" / "portable-publication"
            previous = os.umask(0o002)
            try:
                prepare_server_publication_root(root)
            finally:
                os.umask(previous)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            attempts = root / "attempts"
            attempts.mkdir(mode=0o700)
            root.chmod(0o755)
            prepare_server_publication_root(root)
            with ServerRetentionLock(attempts):
                self.assertEqual(root.stat().st_mode & 0o777, 0o755)
            root.chmod(0o775)
            prepare_server_publication_root(root)
            with self.assertRaises(RetentionLockError):
                with ServerRetentionLock(attempts):
                    self.fail("group-writable anchor was admitted")
            self.assertEqual(root.stat().st_mode & 0o777, 0o775)

    def test_default_route_supplies_a_witness_and_retains_post_commit_failure(self):
        capture = _Capture()
        validated = _Validated()
        primary = RuntimeError("post-commit publisher fault")

        def publish(*_args, **kwargs):
            witness = kwargs.get("publication_witness")
            self.assertIsInstance(witness, PublicationPhaseWitness)
            assert isinstance(witness, PublicationPhaseWitness)
            witness.advance(PublicationPhase.COMMITTED)
            raise primary

        with self._isolated_route(capture, validated) as publisher:
            publisher.side_effect = publish
            config = self._config()
            with self.assertRaises(RuntimeError) as caught:
                execute_portable_refresh(config, config.graphs[0], "repomap_repo_map", authority=None)
        self.assertIs(caught.exception, primary)
        self.assertEqual(capture.terminal_calls, [])
        self.assertEqual(capture.retention_class, "publication-reconciliation")
        self.assertEqual(validated.close_calls, 1)

    def test_missing_witness_cannot_prove_prepublication_failure(self):
        capture = _Capture()
        settle_after_publisher_error(
            capture, RuntimeError("unknown publisher phase"),
            publication_witness=None, publisher_returned=False,
        )
        self.assertEqual(capture.terminal_calls, [])
        self.assertEqual(capture.retention_class, "publication-reconciliation")

    @contextmanager
    def _isolated_route(
        self,
        capture: _Capture,
        validated: _Validated,
        *,
        publisher_error: BaseException | None = None,
    ):
        publisher = Mock(
            return_value=LoadSummary(repository_id=7, run_id=11, files=1),
        )
        if publisher_error is not None:
            publisher.side_effect = publisher_error
        with (
            patch.object(
                portable_refresh,
                "capture_portable_candidate",
                return_value=capture,
            ),
            patch.object(
                portable_refresh,
                "validate_portable_capture",
                return_value=(object(), validated),
            ),
            patch.object(
                portable_refresh,
                "portable_publication_binding",
                return_value=object(),
            ),
            patch.object(
                portable_refresh,
                "stage_id_for_authority",
                return_value="stage-test",
            ),
            patch.object(
                portable_refresh,
                "run_staged_portable_refresh",
                publisher,
            ),
        ):
            yield publisher

    def _config(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "repo"
        root.mkdir()
        (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
        return self.config_for_roots(root)

    def test_post_return_baseexception_keeps_accepted_retention(self):
        for error_type in (KeyboardInterrupt, SystemExit):
            with self.subTest(error_type=error_type.__name__):
                primary = error_type("post-return cleanup fault")
                capture = _Capture({True: primary})
                validated = _Validated()

                with self._isolated_route(capture, validated) as publisher:
                    try:
                        config = self._config()
                        execute_portable_refresh(
                            config,
                            config.graphs[0],
                            "repomap_repo_map",
                            authority=None,
                        )
                    except BaseException as observed:
                        self.assertIs(observed, primary)
                    else:
                        self.fail("post-return cleanup fault was swallowed")

                publisher.assert_called_once()
                self.assertEqual(capture.terminal_calls, [True])
                self.assertEqual(capture.retention_class, "terminal-accepted")
                self.assertEqual(validated.close_calls, 1)

    def test_post_return_primary_survives_close_and_annotation_faults(self):
        annotation_fault = _CleanupFault("annotation fault")
        primary = _PrimaryError(annotation_fault)
        validated = _Validated(close_error=_CleanupFault("close fault"))
        capture = _Capture({True: primary})

        with self._isolated_route(capture, validated) as publisher:
            try:
                config = self._config()
                execute_portable_refresh(
                    config,
                    config.graphs[0],
                    "repomap_repo_map",
                    authority=None,
                )
            except BaseException as observed:
                self.assertIs(observed, primary)
            else:
                self.fail("post-return primary was swallowed")

        publisher.assert_called_once()
        self.assertEqual(capture.terminal_calls, [True])
        self.assertEqual(capture.retention_class, "terminal-accepted")
        self.assertEqual(validated.close_calls, 1)
        self.assertGreaterEqual(primary.annotation_attempts, 1)

    def test_publisher_primary_survives_settlement_and_close_faults(self):
        primary = _PrimaryError(_CleanupFault("annotation fault"))
        capture = _Capture({False: _CleanupFault("terminal settlement fault")})
        validated = _Validated(close_error=_CleanupFault("close fault"))

        with self._isolated_route(
            capture,
            validated,
            publisher_error=primary,
        ) as publisher:
            try:
                config = self._config()
                execute_portable_refresh(
                    config,
                    config.graphs[0],
                    "repomap_repo_map",
                    authority=None,
                )
            except BaseException as observed:
                self.assertIs(observed, primary)
            else:
                self.fail("publisher primary was swallowed")

        publisher.assert_called_once()
        self.assertEqual(capture.terminal_calls, [False])
        self.assertEqual(validated.close_calls, 1)
        self.assertGreaterEqual(primary.annotation_attempts, 1)
