import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.awk import (
    FAKE_SECRET_MARKERS,
    FIXTURE_ROOT,
    first_observation,
    observations_by_kind,
)

from repomap_kg.ops.ingestion.bulk import classify_bulk_route
from repomap_kg.graph.discovery import classify_path, discover_observations
from repomap_kg.ops.ingestion.source import _archive_extractor_route
from repomap_kg.extractors.shell.awk import extract_awk_file_observations


class AwkExtractorUnitTests(unittest.TestCase):
    def test_classifies_awk_extension_and_shebang_without_reclassifying_shell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(root / "filters" / "report.awk", "# static fixture\n")
            self.write(root / "bin" / "filter", "#!/usr/bin/env awk -f\n")
            os.chmod(root / "bin" / "filter", 0o755)
            self.write(root / "bin" / "gawk-filter", "#!/usr/bin/env gawk -f\n")
            os.chmod(root / "bin" / "gawk-filter", 0o755)
            self.write(root / "scripts" / "inline.sh", "#!/bin/sh\nawk '{ print $1 }' input.txt\n")
            self.write(root / "Makefile", "report:\n\tawk '{ print $$1 }' input.txt\n")

            infos = {
                relative: classify_path(root, root / relative)
                for relative in (
                    "filters/report.awk",
                    "bin/filter",
                    "bin/gawk-filter",
                    "scripts/inline.sh",
                    "Makefile",
                )
            }

        self.assertEqual(infos["filters/report.awk"].language, "awk")
        self.assertEqual(infos["filters/report.awk"].role, "source")
        self.assertEqual(infos["bin/filter"].language, "awk")
        self.assertEqual(infos["bin/filter"].role, "entrypoint")
        self.assertEqual(infos["bin/gawk-filter"].language, "awk")
        self.assertEqual(infos["scripts/inline.sh"].language, "shell")
        self.assertNotEqual(infos["Makefile"].language, "awk")

    def test_program_begin_end_and_pattern_action_observations(self):
        content = (FIXTURE_ROOT / "basic.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/basic.awk", content)

        by_kind = observations_by_kind(observations)
        program = by_kind["awk.program"][0]
        self.assertEqual(program.path, "filters/basic.awk")
        self.assertEqual(program.confidence, "extracted")
        self.assertEqual(program.metadata["language"], "awk")
        self.assertEqual(program.metadata["dialect"], "awk")
        self.assertEqual(program.metadata["file_type"], "awk")
        self.assertEqual(program.metadata["shebang"], "#!/usr/bin/env awk -f")
        self.assertEqual(program.metadata["classification_evidence"], ["extension", "shebang"])
        self.assertEqual(program.metadata["parser"], "stdlib-static-scanner")
        self.assertTrue(program.metadata["static_only"])
        self.assertFalse(program.metadata["awk_executed"])
        self.assertFalse(program.metadata["shell_executed"])

        begin = by_kind["awk.begin"][0]
        self.assertEqual(begin.metadata["block_kind"], "begin")
        self.assertTrue(begin.metadata["action_present"])
        self.assertFalse(begin.metadata["action_modeled"])
        self.assertFalse(begin.metadata["awk_executed"])

        end = by_kind["awk.end"][0]
        self.assertEqual(end.metadata["block_kind"], "end")
        self.assertTrue(end.metadata["action_present"])
        self.assertFalse(end.metadata["awk_executed"])

        pattern_kinds = {item.metadata["pattern_kind"] for item in by_kind["awk.pattern_action"]}
        self.assertTrue({"regex", "expression"}.issubset(pattern_kinds))
        self.assertTrue(all(item.metadata["action_modeled"] is False for item in by_kind["awk.pattern_action"]))

    def test_extracts_regex_expression_range_and_empty_pattern_actions(self):
        content = (FIXTURE_ROOT / "patterns-and-actions.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/patterns-and-actions.awk", content)

        by_kind = observations_by_kind(observations)
        pattern_kinds = {
            item.metadata["pattern_kind"]
            for item in by_kind["awk.pattern_action"]
        }
        self.assertTrue({"regex", "expression", "range", "empty"}.issubset(pattern_kinds))
        expression_without_action = first_observation(
            by_kind["awk.pattern_action"],
            kind="awk.pattern_action",
            predicate=lambda item: item.metadata["pattern_kind"] == "expression"
            and item.metadata["action_present"] is False,
        )
        self.assertEqual(expression_without_action.metadata["pattern_summary"], "NR == 1")

    def test_extracts_functions_with_parameters_and_local_parameter_convention(self):
        content = (FIXTURE_ROOT / "functions.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/functions.awk", content)

        functions = observations_by_kind(observations)["awk.function"]
        normalize = first_observation(functions, kind="awk.function", name="normalize")
        self.assertEqual(normalize.metadata["function_name"], "normalize")
        self.assertEqual(normalize.metadata["parameters"], ["value"])
        self.assertEqual(normalize.metadata["local_parameters"], ["trimmed", "suffix"])
        self.assertFalse(normalize.metadata["body_modeled"])
        passthrough = first_observation(functions, kind="awk.function", name="passthrough")
        self.assertEqual(passthrough.metadata["parameters"], ["value"])
        self.assertEqual(passthrough.metadata["local_parameters"], [])

    def test_extracts_assignments_fields_records_and_special_variables(self):
        content = (FIXTURE_ROOT / "basic.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/basic.awk", content)

        by_kind = observations_by_kind(observations)
        assignments = {item.name: item.metadata for item in by_kind["awk.variable_assignment"]}
        self.assertEqual(assignments["FS"]["operation"], "assign")
        self.assertTrue(assignments["FS"]["special_variable"])
        self.assertEqual(assignments["FS"]["value_kind"], "string")
        self.assertEqual(assignments["count"]["operation"], "add_assign")
        self.assertEqual(assignments["name"]["value_kind"], "field")

        field_refs = {
            (item.metadata["reference_kind"], item.metadata.get("field_number"), item.metadata.get("field_name"))
            for item in by_kind["awk.field_reference"]
        }
        self.assertIn(("field", 1, None), field_refs)
        self.assertIn(("field", 3, None), field_refs)
        self.assertIn(("field", None, "NF"), field_refs)

        record_refs = {
            (item.metadata["reference_kind"], item.name)
            for item in by_kind["awk.record_reference"]
        }
        self.assertIn(("record", "$0"), record_refs)
        self.assertIn(("special_variable", "FS"), record_refs)
        self.assertIn(("special_variable", "OFS"), record_refs)
        self.assertIn(("special_variable", "NF"), record_refs)

    def test_dynamic_expressions_are_bounded_without_fabricating_targets(self):
        content = (FIXTURE_ROOT / "dynamic.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/dynamic.awk", content)

        by_kind = observations_by_kind(observations)
        dynamic_reasons = {
            item.metadata["dynamic_reason"] for item in by_kind["awk.dynamic_expression"]
        }
        self.assertTrue(
            {
                "dynamic_regex",
                "dynamic_field",
                "string_concatenation",
                "computed_target",
            }.issubset(dynamic_reasons)
        )
        dynamic_field = first_observation(
            by_kind["awk.field_reference"],
            kind="awk.field_reference",
            predicate=lambda item: item.metadata["reference_kind"] == "dynamic_field",
        )
        self.assertEqual(dynamic_field.metadata["resolution"], "dynamic")
        self.assertEqual(dynamic_field.metadata["dynamic_reason"], "dynamic_field")
        self.assertIsNone(dynamic_field.target)

    def test_gawk_dialect_evidence_is_explicit_and_include_extraction_is_static(self):
        content = (FIXTURE_ROOT / "gawk-extensions.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/gawk-extensions.awk", content)

        by_kind = observations_by_kind(observations)
        program = by_kind["awk.program"][0]
        self.assertEqual(program.metadata["dialect"], "gawk")
        self.assertIn("shebang:gawk", program.metadata["classification_evidence"])
        self.assertIn("gawk:@include", program.metadata["classification_evidence"])
        self.assertIn("gawk:BEGINFILE", program.metadata["classification_evidence"])
        self.assertIn("gawk:gensub", program.metadata["classification_evidence"])
        include = by_kind["awk.include"][0]
        self.assertEqual(include.metadata["include_target"], "lib.awk")
        self.assertFalse(include.metadata["include_loaded"])
        self.assertNotIn("awk.extension", by_kind)
        dynamic_reasons = {
            item.metadata["dynamic_reason"] for item in by_kind["awk.dynamic_expression"]
        }
        self.assertIn("unsupported_gawk_extension", dynamic_reasons)

    def test_secret_like_assignments_are_redacted_and_fake_values_are_absent(self):
        content = (FIXTURE_ROOT / "redaction.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/redaction.awk", content)

        payload = json.dumps([item.to_dict() for item in observations], sort_keys=True)
        by_kind = observations_by_kind(observations)
        assignments = {item.name: item.metadata for item in by_kind["awk.variable_assignment"]}
        self.assertTrue(assignments["api_token"]["redacted"])
        self.assertFalse(assignments["api_token"]["raw_value_stored"])
        self.assertTrue(assignments["password"]["redacted"])
        self.assertFalse(assignments["password"]["raw_value_stored"])
        self.assertFalse(assignments["public_value"]["redacted"])
        for marker in FAKE_SECRET_MARKERS:
            self.assertNotIn(marker, payload)

    def test_false_positive_boundaries_skip_comments_strings_and_division(self):
        content = (FIXTURE_ROOT / "false-positives.awk").read_text(encoding="utf-8")

        observations = extract_awk_file_observations("filters/false-positives.awk", content)

        by_kind = observations_by_kind(observations)
        function_names = {item.name for item in by_kind.get("awk.function", [])}
        self.assertNotIn("hidden", function_names)
        self.assertEqual(len(by_kind.get("awk.begin", [])), 1)
        self.assertNotIn("awk.system_call", by_kind)
        self.assertNotIn("awk.file_read", by_kind)
        self.assertNotIn("awk.file_write", by_kind)
        self.assertNotIn("awk.pipe_read", by_kind)
        self.assertNotIn("awk.pipe_write", by_kind)
        self.assertNotIn("awk.include", by_kind)
        self.assertNotIn("awk.extension", by_kind)
        dynamic_reasons = {
            item.metadata["dynamic_reason"] for item in by_kind.get("awk.dynamic_expression", [])
        }
        self.assertNotIn("ambiguous_regex_or_division", dynamic_reasons)

    def test_discovery_routes_awk_files_through_awk_extractor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "filters" / "basic.awk",
                (FIXTURE_ROOT / "basic.awk").read_text(encoding="utf-8"),
            )
            self.write(root / "scripts" / "inline.sh", "#!/bin/sh\nawk '{ print $1 }' input.txt\n")

            observations = discover_observations(root)

        by_kind = observations_by_kind(observations)
        self.assertIn("awk.program", by_kind)
        self.assertIn("awk.begin", by_kind)
        self.assertEqual(
            next(
                item for item in observations
                if item.path == "filters/basic.awk" and item.kind == "file"
            ).metadata["language"],
            "awk",
        )
        self.assertFalse(
            any(item.path == "filters/basic.awk" and item.metadata.get("dialect") == "bash" for item in observations)
        )
        self.assertFalse(
            any(item.path == "scripts/inline.sh" and item.kind.startswith("awk.") for item in observations)
        )

    def test_local_ingestion_route_tables_include_awk(self):
        self.assertEqual(classify_bulk_route(Path("filters/basic.awk")), "awk")
        self.assertEqual(_archive_extractor_route(Path("filters/basic.awk")), "awk")
        self.assertEqual(classify_bulk_route(Path("scripts/inline.sh")), "shell")

    def test_extractor_does_not_invoke_subprocess_or_shells(self):
        content = (FIXTURE_ROOT / "basic.awk").read_text(encoding="utf-8")

        with patch.object(subprocess, "run", side_effect=AssertionError("subprocess invoked")):
            observations = extract_awk_file_observations("filters/basic.awk", content)

        self.assertIn("awk.program", {item.kind for item in observations})

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
