#!/usr/bin/env python3
"""Read-only operator inventory for ambiguous legacy RepoMap images."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
if str(TEST_SUPPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_SUPPORT_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory legacy unclassified RepoMap image tags without mutation."
    )
    parser.add_argument("command", choices=("legacy-inventory",))
    args = parser.parse_args(argv)
    del args

    import docker

    from repomap_test_support.resource_test_images import TestImageManager

    client = docker.from_env()
    try:
        records = TestImageManager.legacy_inventory(client)
    finally:
        client.close()
    print(
        json.dumps(
            {
                "schema": "repomap-test-image-legacy-inventory-v1",
                "classification": "legacy_unclassified",
                "images": [
                    {
                        "tags": list(record.tags),
                        "image_id": record.image_id,
                        "created": record.created,
                        "size": record.size,
                        "container_references": list(record.container_references),
                    }
                    for record in records
                ],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
