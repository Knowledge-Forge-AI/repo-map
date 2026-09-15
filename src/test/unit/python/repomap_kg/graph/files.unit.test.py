import unittest

from repomap_kg.graph.readback.files import (
    FileFilters,
    FileRecord,
    file_records_from_observations,
    filter_file_records,
    format_file_table,
    records_to_jsonable,
)
from repomap_kg.observations.raw import RawObservation


class FilesUnitTests(unittest.TestCase):
    def test_file_records_are_derived_from_normalized_file_observations(self):
        observations = [
            file_observation(
                "src/main/python/app.py",
                language="python",
                role="source",
                confidence="extracted",
            ),
            RawObservation(
                kind="shell.command",
                source_id="scripts/build.sh#call:nix",
                path="scripts/build.sh",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                target="tool:nix",
            ),
            file_observation(
                "README.md",
                language="markdown",
                role="documentation",
                confidence="manual",
                executable=True,
            ),
        ]

        records = file_records_from_observations(observations)

        self.assertEqual(
            [record.path for record in records],
            ["README.md", "src/main/python/app.py"],
        )
        self.assertEqual(records[0].language, "markdown")
        self.assertEqual(records[0].role, "documentation")
        self.assertEqual(records[0].confidence, "manual")
        self.assertTrue(records[0].executable)
        self.assertFalse(records[0].generated)

    def test_file_records_filter_by_role_language_and_generated_state(self):
        records = (
            FileRecord(
                path="generated/report.json",
                language="json",
                role="generated",
                confidence="extracted",
                generated=True,
                executable=False,
            ),
            FileRecord(
                path="src/main/python/app.py",
                language="python",
                role="source",
                confidence="extracted",
                generated=False,
                executable=False,
            ),
            FileRecord(
                path="src/test/python/app.test.py",
                language="python",
                role="test",
                confidence="extracted",
                generated=False,
                executable=False,
            ),
        )

        filtered = filter_file_records(
            records,
            FileFilters(role="source", language="python", generated="exclude"),
        )
        generated_only = filter_file_records(records, FileFilters(generated="only"))

        self.assertEqual(
            [record.path for record in filtered],
            ["src/main/python/app.py"],
        )
        self.assertEqual(
            [record.path for record in generated_only],
            ["generated/report.json"],
        )

    def test_format_file_table_uses_stable_columns(self):
        records = (
            FileRecord(
                path="README.md",
                language="markdown",
                role="documentation",
                confidence="manual",
                generated=False,
                executable=False,
            ),
            FileRecord(
                path="bin/tool",
                language="shell",
                role="entrypoint",
                confidence="extracted",
                generated=False,
                executable=True,
            ),
        )

        table = format_file_table(records)

        self.assertEqual(
            table,
            "\n".join(
                [
                    "path       language  role           confidence  generated  executable",
                    "README.md  markdown  documentation  manual      false      false",
                    "bin/tool   shell     entrypoint     extracted   false      true",
                ]
            ),
        )

    def test_records_to_jsonable_preserves_public_fields(self):
        records = (
            FileRecord(
                path="README.md",
                language="markdown",
                role="documentation",
                confidence="manual",
                generated=False,
                executable=False,
            ),
        )

        self.assertEqual(
            records_to_jsonable(records),
            [
                {
                    "path": "README.md",
                    "language": "markdown",
                    "role": "documentation",
                    "confidence": "manual",
                    "generated": False,
                    "executable": False,
                }
            ],
        )


def file_observation(
    path,
    *,
    language,
    role,
    confidence,
    generated=False,
    executable=False,
):
    return RawObservation(
        kind="file",
        source_id=path,
        path=path,
        confidence=confidence,
        extractor="fixture-discovery",
        extractor_version="0.1.0",
        metadata={
            "language": language,
            "role": role,
            "content_hash": "0" * 64,
            "generated": generated,
            "executable": executable,
        },
    )


if __name__ == "__main__":
    unittest.main()
