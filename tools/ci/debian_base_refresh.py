#!/usr/bin/env python3
"""Read-only current Debian slim/official derivative check before publication (ADR0105)."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
import urllib.parse
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT / "src/main/python"))

from common_lore_index.runtime.release import POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE

ACCEPT = ", ".join(("application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json"))
CATALOGUE_URL = "https://raw.githubusercontent.com/docker-library/official-images/master/library/debian"
MAX_METADATA_BYTES = 2_000_000
Fetch = Callable[[str, Mapping[str, str]], bytes]


class BaseRefreshError(ValueError):
    """Official metadata or a pin cannot establish current stable-slim provenance."""


def fetch(url: str, headers: Mapping[str, str]) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=dict(headers)), timeout=60) as response:
        data = response.read(MAX_METADATA_BYTES + 1)
    if not data or len(data) > MAX_METADATA_BYTES:
        raise BaseRefreshError("official metadata is empty or exceeds the byte bound")
    return data


def stable_version(catalogue: str, suite: str = "trixie") -> str:
    versions = dict(re.findall(r"^# (stable|" + re.escape(suite) + r") -- Debian ([0-9.]+) Released .+$",
                              catalogue, re.MULTILINE))
    if versions.get("stable") is None or versions.get("stable") != versions.get(suite):
        raise BaseRefreshError("the selected Debian suite is no longer current stable; compatibility refresh required")
    if not re.search(r"^Tags: .*\b" + re.escape(suite) + r"-slim(?:,|$)", catalogue, re.MULTILINE):
        raise BaseRefreshError("official stable suite has no slim variant")
    return versions["stable"]


class Registry:
    """Metadata only: bearer tokens stay in memory; no layer acquisition or image execution."""

    def __init__(self, fetch_fn: Fetch = fetch):
        self.fetch = fetch_fn
        self._headers: dict[str, dict[str, str]] = {}

    def read(self, repository: str, kind: str, reference: str) -> tuple[dict[str, Any], str]:
        if repository not in ("debian", "python", "postgres") or kind not in ("manifests", "blobs"):
            raise BaseRefreshError("unsupported official repository or metadata type")
        if repository not in self._headers:
            query = urllib.parse.urlencode({"service": "registry.docker.io", "scope": f"repository:library/{repository}:pull"})
            auth = json.loads(self.fetch("https://auth.docker.io/token?" + query, {}))
            self._headers[repository] = {"Authorization": "Bearer " + auth["token"], "Accept": ACCEPT}
        raw = self.fetch(f"https://registry-1.docker.io/v2/library/{repository}/{kind}/{reference}",
                         self._headers[repository])
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if reference.startswith("sha256:") and reference != digest:
            raise BaseRefreshError("registry metadata digest differs from its descriptor")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise BaseRefreshError("registry metadata must be an object")
        return document, digest

    def image(self, repository: str, tag: str) -> dict[str, Any]:
        index, digest = self.read(repository, "manifests", tag)
        children = {}
        for item in index.get("manifests", []):
            platform = item.get("platform") or {}
            architecture = platform.get("architecture")
            if platform.get("os") != "linux" or architecture not in ("amd64", "arm64"):
                continue
            if architecture in children:
                raise BaseRefreshError("duplicate native platform in official index")
            manifest, _ = self.read(repository, "manifests", item["digest"])
            config, config_digest = self.read(repository, "blobs", manifest["config"]["digest"])
            if config.get("os") != "linux" or config.get("architecture") != architecture:
                raise BaseRefreshError("image configuration platform disagrees with its index")
            children[architecture] = {"manifest": item["digest"], "config": config_digest,
                "created": config.get("created"), "rootfs": config["rootfs"]["diff_ids"]}
        if set(children) != {"amd64", "arm64"}:
            raise BaseRefreshError("official index is missing a required native platform")
        return {"index": digest, "platforms": children}


def verify_observation(
    base: Mapping[str, Any], derivatives: Mapping[str, Any], pins: Mapping[str, str],
) -> bool:
    """Every derivative must inherit the currently observed stable-slim root layer; pins stay immutable."""
    current = True
    for name, observed in derivatives.items():
        current = current and observed["index"] == pins[name]
        for architecture in ("amd64", "arm64"):
            roots = observed["platforms"][architecture]["rootfs"]
            if not roots or roots[0] != base["platforms"][architecture]["rootfs"][0]:
                raise BaseRefreshError("official derivative has not incorporated the current stable-slim base")
    return current


def observe(*, registry: Registry | None = None, fetch_fn: Fetch = fetch) -> dict[str, Any]:
    catalogue = fetch_fn(CATALOGUE_URL, {})
    version = stable_version(catalogue.decode("utf-8"))
    registry = registry or Registry(fetch_fn)
    base = registry.image("debian", "trixie-slim")
    derivatives, pins = {}, {}
    for reference in (POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE):
        name, digest = reference.split("@", 1)
        repository, tag = name.split(":", 1)
        derivatives[name] = registry.image(repository, tag)
        pins[name] = digest
    current = verify_observation(base, derivatives, pins)
    return {"schema": "repomap-debian-base-freshness-v1", "observed_at": datetime.now(UTC).isoformat(),
            "stable_suite": "trixie", "debian_version": version, "official_catalogue_sha256": hashlib.sha256(catalogue).hexdigest(),
            "slim_base": base, "derivatives": derivatives, "pinned_indexes": pins, "pins_current": current,
            "upstream_debian_findings": "informational", "layers_pulled": 0, "images_executed": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    result = observe()
    raw = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        with args.output_json.open("x", encoding="utf-8") as stream:
            stream.write(raw)
    else:
        print(raw, end="")
    return 0 if result["pins_current"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
