"""Unit contracts for the fixed public-text stdout sidecar."""
from __future__ import annotations
import base64
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from typing import cast
from retrieval_public_text_export import (
    MAX_JOURNAL_BYTES, PREFIX, ExportRefusal,
    decode_study_evidence, emit_study_evidence,
)


RAW_MEMBERS = ("declaration.json", "report.json", "source-manifest.json", "sources.zip", "terminal.json")


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii") + b"\n"


def _extras(*, report: bool = True, failure: bool = False, functional: bool = False,
            raw_generation: int | None = None) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    if report:
        values["public-text-calibration-report.json"] = _json({"status": "observed"})
    if failure:
        values["public-text-study-failure.json"] = _json({"status": "failed"})
    if functional:
        values["functional-transition-observation.json"] = _json({"status": "observed"})
        values["functional-transition-gate.json"] = _json({"status": "observed"})
    if raw_generation is not None:
        for member in RAW_MEMBERS:
            name = f"raw-components/w5-semantic-g{raw_generation}/{member}"
            values[name] = b"{}\n" if member != "sources.zip" else b"zip-bytes"
    return values


def _emit(values: dict[str, bytes], *, journal: int = 7,
          functional_only: bool = True) -> bytes:
    stream = io.StringIO()
    emit_study_evidence(values, journal_decoded_bytes=journal,
                        functional_only=functional_only, stream=stream)
    return stream.getvalue().encode("ascii")


def _document(raw: bytes) -> dict[str, object]:
    line = next(item for item in raw.split(b"\n") if item.startswith(PREFIX.encode("ascii")))
    return json.loads(line[len(PREFIX):])


def _reline(document: dict[str, object]) -> bytes:
    return b"\n" + PREFIX.encode("ascii") + _json(document)


class PublicTextExportTest(unittest.TestCase):
    """Synthetic bytes only; no journal loading, model, native, or filesystem export."""

    def test_roundtrip_report_functional_pair_and_raw_group(self) -> None:
        values = _extras(functional=True, raw_generation=1)
        raw = _emit(values)
        self.assertTrue(raw.startswith(b"\n" + PREFIX.encode("ascii")))
        self.assertTrue(raw.endswith(b"\n"))
        decoded = decode_study_evidence(raw, journal_decoded_bytes=7,
                                        expected_functional_only=True)
        self.assertEqual(decoded, values)

    def test_raw_json_whitespace_is_preserved(self) -> None:
        values = _extras(raw_generation=2)
        values["public-text-calibration-report.json"] = (
            b'{\n  "status": "observed"\n}\n'
        )
        values["raw-components/w5-semantic-g2/report.json"] = b"opaque parser bytes"
        raw = _emit(values, functional_only=False)
        self.assertEqual(
            decode_study_evidence(raw, journal_decoded_bytes=7,
                                  expected_functional_only=False),
            values,
        )

    def test_default_stdout_emits_one_decodable_frame(self) -> None:
        capture = io.StringIO()
        values = _extras(functional=True)
        with redirect_stdout(capture):
            emit_study_evidence(values, journal_decoded_bytes=3,
                                functional_only=True)
        raw = capture.getvalue().encode("ascii")
        self.assertEqual(
            decode_study_evidence(raw, journal_decoded_bytes=3,
                                  expected_functional_only=True),
            values,
        )

    def test_failure_only_native_label_is_truthful(self) -> None:
        values = _extras(report=False, failure=True)
        raw = _emit(values, journal=11, functional_only=False)
        self.assertEqual(decode_study_evidence(raw, journal_decoded_bytes=11,
                                                expected_functional_only=False), values)
        with self.assertRaises(ExportRefusal):
            _emit(_extras(failure=True, functional=True), functional_only=False)

    def test_report_functional_pair_and_raw_group_are_closed(self) -> None:
        with self.assertRaises(ExportRefusal):
            _emit(_extras(report=True, functional=False))
        with self.assertRaises(ExportRefusal):
            _emit(cast(dict[str, bytes], _extras(report=True, functional=True).copy() | {
                "functional-transition-gate.json": None}))
        incomplete = _extras(report=True, raw_generation=1)
        del incomplete["raw-components/w5-semantic-g1/terminal.json"]
        with self.assertRaises(ExportRefusal):
            _emit(incomplete)

    def test_unknown_unsafe_noncanonical_and_type_substitutions_refuse(self) -> None:
        for unsafe in ("../escape.json", "/escape.json", "raw-components/../report.json",
                       r"raw-components\w5-semantic-g1\report.json"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ExportRefusal):
                _emit({unsafe: b"{}\n", **_extras()})
        malformed = _extras()
        malformed["public-text-calibration-report.json"] = (
            b'{"status":1,"status":2}'
        )
        with self.assertRaises(ExportRefusal):
            _emit(malformed)
        malformed["public-text-calibration-report.json"] = b'{"status":NaN}'
        with self.assertRaises(ExportRefusal):
            _emit(malformed)
        with self.assertRaises(ExportRefusal):
            emit_study_evidence(_extras(), journal_decoded_bytes=True,
                                functional_only=True)
        with self.assertRaises(ExportRefusal):
            emit_study_evidence(_extras(), journal_decoded_bytes=MAX_JOURNAL_BYTES + 1,
                                functional_only=True)

    def test_duplicate_truncated_archive_and_hash_refuse(self) -> None:
        raw = _emit(_extras(functional=True), journal=13)
        with self.assertRaises(ExportRefusal):
            decode_study_evidence(raw + raw, journal_decoded_bytes=13,
                                  expected_functional_only=True)
        with self.assertRaises(ExportRefusal):
            decode_study_evidence(raw[:-1], journal_decoded_bytes=13,
                                  expected_functional_only=True)
        document = _document(raw)
        archive = base64.b64decode(cast(str, document["archive_b64"]))
        document["archive_sha256"] = "sha256:" + hashlib.sha256(b"wrong").hexdigest()
        with self.assertRaises(ExportRefusal):
            decode_study_evidence(_reline(document), journal_decoded_bytes=13,
                                  expected_functional_only=True)
        document = _document(raw)
        special = bytearray(archive)
        special[156] = ord("5")
        special_bytes = bytes(special)
        document["archive_b64"] = base64.b64encode(special_bytes).decode("ascii")
        document["archive_length"] = len(special_bytes)
        document["archive_sha256"] = "sha256:" + hashlib.sha256(special_bytes).hexdigest()
        with self.assertRaises(ExportRefusal):
            decode_study_evidence(_reline(document), journal_decoded_bytes=13,
                                  expected_functional_only=True)
        document = _document(raw)
        document["archive_b64"] = base64.b64encode(archive + b"\0" * 512).decode("ascii")
        document["archive_length"] = len(archive) + 512
        document["archive_sha256"] = "sha256:" + hashlib.sha256(archive + b"\0" * 512).hexdigest()
        with self.assertRaises(ExportRefusal):
            decode_study_evidence(_reline(document), journal_decoded_bytes=13,
                                  expected_functional_only=True)

    def test_stdout_and_content_bounds_are_preserved(self) -> None:
        with self.assertRaises(ExportRefusal):
            emit_study_evidence(_extras(functional=True), journal_decoded_bytes=MAX_JOURNAL_BYTES,
                                functional_only=True)

    def test_base_exception_is_not_suppressed(self) -> None:
        class InterruptingMapping(dict[str, bytes]):
            def items(self):
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            emit_study_evidence(InterruptingMapping(_extras()),
                                journal_decoded_bytes=1,
                                functional_only=True)

    def test_metadata_exponent_overflow_is_refused_before_emission(self) -> None:
        values = _extras(report=False, failure=True)
        values["public-text-study-failure.json"] = b'{"elapsed":1e9999}\n'
        with self.assertRaises(ExportRefusal):
            _emit(values, functional_only=False)

    def test_decoder_ignores_other_stdout_but_never_raw_path_or_message(self) -> None:
        raw = b"ordinary stdout\n" + _emit(_extras(functional=True))
        self.assertEqual(decode_study_evidence(raw, journal_decoded_bytes=7,
                                                expected_functional_only=True), _extras(functional=True))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.log"
            with self.assertRaises(ExportRefusal) as error:
                decode_study_evidence(b"bad", journal_decoded_bytes=0,
                                      expected_functional_only=True)
            self.assertNotIn(str(path), str(error.exception))
