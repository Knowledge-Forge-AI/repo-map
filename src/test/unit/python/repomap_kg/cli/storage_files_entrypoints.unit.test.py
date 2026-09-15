import io
import unittest
from contextlib import redirect_stderr
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.cli.parser import build_parser
else:
    from repomap_kg.cli import build_parser


class CliStorageFilesEntrypointsUnitTests(unittest.TestCase):
    def test_storage_file_inventory_commands_are_removed_from_public_parser(self):
        for command in ("files", "entrypoints", "file-nodes"):
            with self.subTest(command=command):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        build_parser().parse_args(
                            [
                                "storage",
                                command,
                                "--root-path",
                                "/tmp/fixture",
                            ]
                        )
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("invalid choice", stderr.getvalue())
