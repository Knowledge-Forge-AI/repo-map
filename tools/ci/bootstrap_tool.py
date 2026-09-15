#!/usr/bin/env python3
"""Install one exact pre-review tool from the closed RepoMap manifest."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import stat
import tarfile
from urllib.request import urlopen


MANIFEST_PATH = Path(__file__).with_name("pre_review_tools.json")


def host_platform() -> str:
    system = {"darwin": "darwin", "linux": "linux"}.get(platform.system().lower())
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64"}.get(
        platform.machine().lower()
    )
    if system is None or machine is None:
        raise RuntimeError("host platform has no closed pre-review tool asset")
    return f"{system}-{machine}"


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "repomap-pre-review-tools-v1":
        raise RuntimeError("pre-review tool manifest schema is unsupported")
    return document


def verified_payload(asset: dict, *, opener=urlopen) -> bytes:
    with opener(asset["url"], timeout=60) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != asset["sha256"]:
        raise RuntimeError(
            f"tool asset integrity mismatch: expected {asset['sha256']}, got {digest}"
        )
    return payload


def archive_binary(payload: bytes, member_name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        member = archive.getmember(member_name)
        if not member.isfile() or member.name != member_name:
            raise RuntimeError("tool archive binary member is invalid")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError("tool archive binary member is unreadable")
        return extracted.read()


def install_tool(
    name: str,
    destination: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
    platform_name: str | None = None,
    opener=urlopen,
) -> Path:
    tools = load_manifest(manifest_path).get("tools", {})
    if name not in tools:
        raise RuntimeError(f"tool {name!r} is not in the closed manifest")
    platform_name = platform_name or host_platform()
    asset = tools[name].get("assets", {}).get(platform_name)
    if asset is None:
        raise RuntimeError(f"tool {name!r} has no asset for {platform_name}")
    payload = verified_payload(asset, opener=opener)
    if asset.get("format", "tar.gz") == "raw":
        binary = payload
    else:
        binary = archive_binary(payload, asset["binary_path"])
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / name
    output.write_bytes(binary)
    output.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--bin-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    output = install_tool(args.tool, args.bin_dir)
    if os.environ.get("GITHUB_PATH"):
        with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as path_file:
            path_file.write(f"{output.parent}\n")
    print(f"installed {args.tool} from verified immutable asset: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
