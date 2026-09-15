import os
import sys
import tempfile
import textwrap
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from repomap_kg.extractors.languages.go_protocol import GoHelperUnavailableError
from repomap_kg.extractors.languages.golang import (
    extract_go_repository_observations,
)


@dataclass(frozen=True)
class FileStub:
    path: str
    language: str


class GolangRepositoryExtractionUnitTests(unittest.TestCase):
    def test_extracts_only_sorted_go_files_with_explicit_helper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            helper = self.write_helper(root)
            file_infos = (
                FileStub("z/last.go", "go"),
                FileStub("go.mod", "go-module"),
                FileStub("a/first.go", "go"),
                FileStub("tool.py", "python"),
            )
            with patch.dict(os.environ, {"REPOMAP_GO_HELPER": str(helper)}):
                observations = extract_go_repository_observations(root, file_infos)

        self.assertEqual(
            [(item.kind, item.path) for item in observations],
            [("go.package", "a/first.go"), ("go.package", "z/last.go")],
        )

    def test_skips_helper_resolution_when_repository_has_no_go_files(self):
        with patch.dict(
            os.environ,
            {"REPOMAP_GO_HELPER": "/missing/repomap-go-extract"},
        ):
            observations = extract_go_repository_observations(
                Path("/tmp/repository"),
                (FileStub("go.mod", "go-module"),),
            )

        self.assertEqual(observations, ())

    def test_missing_helper_fails_without_lexical_fallback(self):
        with patch.dict(
            os.environ,
            {"REPOMAP_GO_HELPER": "/missing/repomap-go-extract"},
        ):
            with self.assertRaises(GoHelperUnavailableError):
                extract_go_repository_observations(
                    Path("/tmp/repository"),
                    (FileStub("file.go", "go"),),
                )

    def write_helper(self, root: Path) -> Path:
        helper = root / "repomap-go-extract"
        helper.write_text(
            "#!" + sys.executable + "\n" + textwrap.dedent(
                r'''
                import json
                import sys

                for line in sys.stdin:
                    request = json.loads(line)
                    path = request["path"]
                    observation = {
                        "schema_version": 1,
                        "kind": "go.package",
                        "source_id": path + "#go.package:0:1:0",
                        "path": path,
                        "confidence": "extracted",
                        "extractor": "repo-go-ast",
                        "extractor_version": "0.1.0",
                        "start_line": 1,
                        "end_line": 1,
                        "name": "sample",
                        "metadata": {"static_only": True},
                    }
                    print(json.dumps({"protocol_version": 1, "type": "observation", "sequence": request["sequence"], "path": path, "observation": observation}), flush=True)
                    print(json.dumps({"protocol_version": 1, "type": "file_end", "sequence": request["sequence"], "path": path, "observation_count": 1, "diagnostic_count": 0, "truncated": False}), flush=True)
                '''
            )
        )
        helper.chmod(0o755)
        return helper


if __name__ == "__main__":
    unittest.main()
