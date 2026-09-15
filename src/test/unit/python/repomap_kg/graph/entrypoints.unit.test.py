import unittest

from repomap_kg.graph.readback.entrypoints import (
    entrypoint_records_from_file_records,
    entrypoint_records_from_observations,
    entrypoints_to_jsonable,
    format_entrypoint_table,
)
from repomap_kg.graph.readback.files import FileRecord
from repomap_kg.observations.raw import RawObservation


class EntrypointsUnitTests(unittest.TestCase):
    def test_entrypoint_records_select_only_entrypoint_files(self):
        observations = [
            file_observation("bin/tool", role="entrypoint", executable=True),
            file_observation("scripts/helper.sh", role="script", executable=True),
            RawObservation(
                kind="shell.command",
                source_id="scripts/helper.sh#call:echo",
                path="scripts/helper.sh",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                target="tool:echo",
            ),
        ]

        records = entrypoint_records_from_observations(observations)

        self.assertEqual([record.path for record in records], ["bin/tool"])
        self.assertEqual(records[0].role, "entrypoint")
        self.assertTrue(records[0].executable)

    def test_entrypoint_records_from_file_records_select_only_entrypoints(self):
        records = (
            FileRecord(
                path="bin/tool",
                language="shell",
                role="entrypoint",
                confidence="manual",
                generated=False,
                executable=True,
            ),
            FileRecord(
                path="scripts/helper.sh",
                language="shell",
                role="script",
                confidence="extracted",
                generated=False,
                executable=True,
            ),
        )

        entrypoints = entrypoint_records_from_file_records(records)

        self.assertEqual([record.path for record in entrypoints], ["bin/tool"])

    def test_format_entrypoint_table_uses_file_columns(self):
        records = entrypoint_records_from_observations(
            [
                file_observation(
                    "ops/ship",
                    role="entrypoint",
                    confidence="manual",
                    executable=True,
                )
            ]
        )

        table = format_entrypoint_table(records)

        self.assertEqual(
            table,
            "\n".join(
                [
                    "path      language  role        confidence  generated  executable",
                    "ops/ship  shell     entrypoint  manual      false      true",
                ]
            ),
        )

    def test_entrypoints_to_jsonable_preserves_file_fields(self):
        records = entrypoint_records_from_observations(
            [file_observation("bin/tool", role="entrypoint", executable=True)]
        )

        self.assertEqual(
            entrypoints_to_jsonable(records),
            [
                {
                    "path": "bin/tool",
                    "language": "shell",
                    "role": "entrypoint",
                    "confidence": "extracted",
                    "generated": False,
                    "executable": True,
                }
            ],
        )


def file_observation(
    path,
    *,
    role,
    confidence="extracted",
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
            "language": "shell",
            "role": role,
            "content_hash": "0" * 64,
            "generated": False,
            "executable": executable,
        },
    )


if __name__ == "__main__":
    unittest.main()
