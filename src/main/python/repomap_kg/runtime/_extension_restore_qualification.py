"""Exact artifact, server and client qualification facts for D9-B extension_v2."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

_SHA256_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


_REPO_DIGEST_RE = re.compile(r"^[a-z0-9][a-z0-9._/:-]{0,254}@(sha256:[0-9a-f]{64})$")


SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")


TARGET_TEMPLATE = "template1"


SOURCE_CLIENT_KEYS = ("pg_dump_version", "pg_restore_version")


TARGET_CLIENT_KEYS = ("pg_restore_version", "psql_version")


def engine_image_content_id(value: object) -> str | None:
    """Return an exact Engine image content ID (``sha256:<64hex>``); never parse a reference or tag."""
    return value if isinstance(value, str) and _SHA256_IMAGE_DIGEST_RE.match(value) else None


def registry_manifest_digest(repo_digest: object) -> str | None:
    """Return the manifest digest from an observed ``name@sha256:<64hex>`` RepoDigest entry."""
    match = _REPO_DIGEST_RE.match(repo_digest) if isinstance(repo_digest, str) else None
    return match.group(1) if match else None


@dataclass(frozen=True)
class TrustedArtifactQualification:
    """Trusted source/target server, client, ABI, Engine image and template-baseline qualification."""

    allowed_server_majors: tuple[int, ...] = (16,)
    allowed_server_versions: tuple[str, ...] = ()
    allowed_client_majors: tuple[int, ...] = (16,)
    allowed_client_versions: tuple[str, ...] = ()
    allowed_os_arch_abis: tuple[str, ...] = ()
    allowed_engine_image_ids: tuple[str, ...] = ()
    allowed_registry_manifest_digests: tuple[str, ...] = ()
    require_exact_abi_match: bool = True
    target_template: str = TARGET_TEMPLATE
    template_baselines: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for majors in (self.allowed_server_majors, self.allowed_client_majors):
            if not majors or any(
                isinstance(m, bool) or not isinstance(m, int) or m <= 0 for m in majors
            ):
                raise ValueError(
                    "allowed_server_majors and allowed_client_majors must be non-empty positive ints"
                )
        if any(
            not isinstance(v, str) or not SAFE_VERSION_RE.match(v)
            for v in (*self.allowed_server_versions, *self.allowed_client_versions)
        ):
            raise ValueError(
                "allowed_server_versions and allowed_client_versions entries must be exact version strings"
            )
        if any(
            not isinstance(a, str) or not a.strip() or a == "unavailable"
            for a in self.allowed_os_arch_abis
        ):
            raise ValueError("allowed_os_arch_abis entries must be non-empty ABI strings")
        if any(
            engine_image_content_id(d) is None
            for d in (*self.allowed_engine_image_ids, *self.allowed_registry_manifest_digests)
        ):
            raise ValueError(
                "allowed_engine_image_ids and allowed_registry_manifest_digests entries must be sha256:<64hex> digests"
            )
        if self.target_template != TARGET_TEMPLATE:
            raise ValueError(
                "target_template must be 'template1'; template0 cannot be logically observed without mutation"
            )
        seen: set[str] = set()
        for entry in self.template_baselines:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 2
                or engine_image_content_id(entry[0]) is None
                or not isinstance(entry[1], str)
                or not SHA256_HEX_RE.match(entry[1])
                or entry[0] in seen
            ):
                raise ValueError(
                    "template_baselines entries must be unique (engine image ID, 64-hex logical baseline digest) pairs"
                )
            seen.add(entry[0])

    def template_baseline_for(self, image_id: str | None) -> str | None:
        return next(
            (
                digest
                for img, digest in self.template_baselines
                if image_id is not None and img == image_id
            ),
            None,
        )


def parse_client_version(version_text: object) -> str | None:
    """Return the exact version token of a ``<client> (PostgreSQL) <version>`` identity line."""
    if not isinstance(version_text, str) or version_text in {"unavailable", "unused"}:
        return None
    match = re.fullmatch(
        r"(?:pg_dump|pg_restore|psql) \(PostgreSQL\) ([0-9]+(?:\.[0-9]+)*)(?: .*)?",
        version_text.strip(),
    )
    return match.group(1) if match else None


def client_identities_qualified(
    clients: object, qual: TrustedArtifactQualification, *, keys: tuple[str, ...]
) -> bool:
    """Require every named client to be observed with an exact admitted version and major."""
    if not isinstance(clients, Mapping) or not qual.allowed_client_versions:
        return False
    for key in keys:
        ver = parse_client_version(clients.get(key))
        if (
            ver is None
            or ver not in qual.allowed_client_versions
            or int(ver.split(".", 1)[0]) not in qual.allowed_client_majors
        ):
            return False
    return True


def qualify_server_provenance(
    server_provenance: Mapping[str, object] | None,
    qual: TrustedArtifactQualification,
    *,
    client_keys: tuple[str, ...] = SOURCE_CLIENT_KEYS,
) -> set[str]:
    if not isinstance(server_provenance, Mapping):
        return {"extension-target-incompatible"}
    ver_num, ver_str = (
        server_provenance.get("server_version_num"),
        server_provenance.get("server_version"),
    )
    os_arch, comp_abi = server_provenance.get("os_arch_abi"), server_provenance.get("compile_abi")
    if (
        isinstance(ver_num, bool)
        or not isinstance(ver_num, int)
        or ver_num <= 0
        or (ver_num // 10000) not in qual.allowed_server_majors
        or not qual.allowed_server_versions
        or not isinstance(ver_str, str)
        or ver_str not in qual.allowed_server_versions
        or not qual.allowed_os_arch_abis
        or not isinstance(os_arch, str)
        or not os_arch
        or os_arch == "unavailable"
        or os_arch not in qual.allowed_os_arch_abis
        or not isinstance(comp_abi, Mapping)
        or not client_identities_qualified(
            server_provenance.get("client_identities"), qual, keys=client_keys
        )
    ):
        return {"extension-target-incompatible"}
    return set()


def source_creation_semantics_complete(creation_semantics: object) -> bool:
    """Require observed source locale facts; the historical template stays an unknown observation."""
    if not isinstance(creation_semantics, Mapping):
        return False
    provider, icu = creation_semantics.get("datlocprovider"), creation_semantics.get("daticulocale")
    return (
        all(
            isinstance(creation_semantics.get(k), str) and creation_semantics.get(k)
            for k in ("encoding", "datcollate", "datctype")
        )
        and provider in ("c", "i")
        and (provider != "i" or (isinstance(icu, str) and bool(icu)))
    )
