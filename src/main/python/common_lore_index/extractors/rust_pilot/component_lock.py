"""Exact component lock for the two pinned native packages (spec section 2).

The lock is Python source: filenames, URLs, sizes, SHA-256 digests, closed
member manifests, inert ELF facts and the supplemental notice digests. Its
identity is the SHA-256 of the canonical JSON of these constants. Nothing
here downloads, imports or executes the locked artifacts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

LOCK_SCHEMA = "cloe-rust-pilot-component-lock-v1"
LOCK_ID = "rust-pilot-lock-1"
SELECTION_RULE = "rust-pilot-selection-v1"
DIALECT = "rust/tree-sitter-rust-0.24.2"
CPUS = ("aarch64", "x86_64")
DOCKER_ARCH_BY_CPU = {"aarch64": "arm64", "x86_64": "amd64"}
CPU_BY_DOCKER_ARCH = {"arm64": "aarch64", "aarch64": "aarch64", "amd64": "x86_64", "x86_64": "x86_64"}
MAX_ARCHIVE_UNCOMPRESSED = 8 * 1_048_576
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_URL_PREFIX = "https://files.pythonhosted.org/packages/"


@dataclass(frozen=True)
class MemberLock:
    """One closed archive member; ``wheel_mode`` is the archive's recorded mode."""

    name: str
    size: int
    sha256: str
    wheel_mode: int


@dataclass(frozen=True)
class ElfFacts:
    """Static ELF observations from inert inspection; not runtime pairing."""

    machine: int
    needed: tuple[str, ...]
    glibc_versions: tuple[str, ...]
    nx_stack: bool = True
    relro: bool = True


@dataclass(frozen=True)
class WheelLock:
    package: str
    version: str
    cpu: str
    filename: str
    url: str
    size: int
    sha256: str
    dist_info: str
    top_level: tuple[str, ...]
    extension: str
    elf: ElfFacts
    members: tuple[MemberLock, ...]

    @property
    def record_name(self) -> str:
        return f"{self.dist_info}/RECORD"

    def member(self, name: str) -> MemberLock:
        for item in self.members:
            if item.name == name:
                return item
        raise KeyError(name)


@dataclass(frozen=True)
class NoticeLock:
    """A supplemental notice shipped as package data and injected under notices/."""

    package_file: str
    installed_name: str
    size: int
    sha256: str


def _m(name: str, size: int, digest: str, mode: int = 0o644) -> MemberLock:
    return MemberLock(name, size, digest, mode)


_TS = "tree_sitter-0.26.0.dist-info"
_TSR = "tree_sitter_rust-0.24.2.dist-info"
_TS_COMMON = (
    _m("tree_sitter/__init__.py", 1504, "0754ef728b311cfb8eb64de361390cbe1344f280c7f40fded08161a6e650268f"),
    _m("tree_sitter/__init__.pyi", 13390, "54ccd48b1aeafc791928b17e4ec6a7134603e78f7ed7b1e554111144139570dc"),
    _m("tree_sitter/py.typed", 0, EMPTY_SHA256),
    _m(f"{_TS}/METADATA", 10026, "40c7146e3b9830f27317e68803d3ea0ecec75af69c957044a976b143a4f94ba4"),
    _m(f"{_TS}/top_level.txt", 12, "a0d28314078b8ba8b7f447134d6ef90cbd12139b0c064817d1344ca497b72ebb"),
    _m(f"{_TS}/licenses/LICENSE", 1088, "1af0790543fffac99dd3bd290bf83ca963f4f8029065eb6f35638f4df863ae8e"),
)
_TSR_COMMON = (
    _m("tree_sitter_rust/__init__.py", 942, "39c6727968787212fab8a02b9df0891af4bfa4cdee83fa7f6dc21772324f7550"),
    _m("tree_sitter_rust/__init__.pyi", 138, "c58d914a565a66885029b46c5356709734ac94177a3777c99acf62cc9de2ef93"),
    _m("tree_sitter_rust/binding.c", 679, "cdfd53e3ec5fd19076a26af1c5b4fb951adb4d262c2b1e9f800674832b9cf7d2"),
    _m("tree_sitter_rust/py.typed", 0, EMPTY_SHA256),
    _m("tree_sitter_rust/queries/highlights.scm", 3527, "0f0343107f14a7690157f51090a979eb8f8bfe4eada7c61763ddb4c54b1311d1"),
    _m("tree_sitter_rust/queries/injections.scm", 247, "723146f179bc0edfba2f51731c99afce8bed3b677dfb4435c303859fae299ba5"),
    _m("tree_sitter_rust/queries/tags.scm", 1194, "f22867fdebde5cb091861c08d34690dc2540f4318068bf81be9f6b0d348ab8c1"),
    _m(f"{_TSR}/METADATA", 2793, "218755ae51a30173dd771ef9caa5ead8b51f6883add5c777433128f9b406bf9d"),
    _m(f"{_TSR}/top_level.txt", 26, "ea9d18a4910dcaf1c23b5c0ebbc0df725a4f60fa4b71dfde7c43353dc19d5a04"),
    _m(f"{_TSR}/licenses/LICENSE", 1080, "31d5b6f4243d5c7c6e1c4ebbbb9f6407bd1457a08bcc4f706521710341acba36"),
)
_NEEDED = ("libc.so.6", "libpthread.so.0")


def _ts(cpu: str, filename: str, url: str, size: int, digest: str, so: tuple[int, str],
        wheel: tuple[int, str], record: tuple[int, str], elf: ElfFacts) -> WheelLock:
    extension = f"tree_sitter/_binding.cpython-313-{cpu}-linux-gnu.so"
    members = (*_TS_COMMON, _m(extension, so[0], so[1], 0o755), _m(f"{_TS}/WHEEL", *wheel),
               _m(f"{_TS}/RECORD", *record, 0o664))
    return WheelLock("tree-sitter", "0.26.0", cpu, filename, _URL_PREFIX + url, size, digest, _TS,
                     ("tree_sitter", _TS), extension, elf, members)


def _tsr(cpu: str, filename: str, url: str, size: int, digest: str, so: tuple[int, str],
         wheel: tuple[int, str], record: tuple[int, str], elf: ElfFacts) -> WheelLock:
    extension = "tree_sitter_rust/_binding.abi3.so"
    members = (*_TSR_COMMON, _m(extension, so[0], so[1], 0o755), _m(f"{_TSR}/WHEEL", *wheel),
               _m(f"{_TSR}/RECORD", *record, 0o664))
    return WheelLock("tree-sitter-rust", "0.24.2", cpu, filename, _URL_PREFIX + url, size, digest,
                     _TSR, ("tree_sitter_rust", _TSR), extension, elf, members)


WHEELS: tuple[WheelLock, ...] = (
    _ts("aarch64",
        "tree_sitter-0.26.0-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl",
        "9b/ee/87e74671ed63a837e7a1f17ab94aa3913871e033b27523d8e7b83d6f7ad0/"
        "tree_sitter-0.26.0-cp313-cp313-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl",
        639334, "8ff2e0750b7daa722302838356d7b65e303829b7eb73c915df127ddba115e1d1",
        (2032984, "7e14540f82cfb53809f47bc816447afc5778b442919559e00c8307b6a1eadde3"),
        (193, "4c0e41a9931cc4aec087c54e6f09b32a313b21a27193bc1a65df1116a05540a9"),
        (780, "b0739118fb01cce1098f82fa57ac0a92ed77ba022e4d5c0b28652c21ded288f6"),
        ElfFacts(183, _NEEDED, ("GLIBC_2.17",))),
    _ts("x86_64",
        "tree_sitter-0.26.0-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl",
        "66/e7/f7e04cd9dff6b6ac0adf23922796fbc76accd4cf4bcda50542748d485679/"
        "tree_sitter-0.26.0-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl",
        668102, "7075ef857ef86f327dbb72d1e2574dda78db5754b3a1fca6506acd7fe5d561a7",
        (2062280, "92d8e6c46ccd676779179ea0958231532410640587a6f1ceb455aa51f8dabfd4"),
        (190, "e13ee8386091b8755d481f8daeda04027441cf81502616778c469827a311a797"),
        (779, "4ce4a101e2676e6b6cd745682a64097ce9781c305baf2f76f4fbef3fadcb63af"),
        ElfFacts(62, _NEEDED, ("GLIBC_2.14", "GLIBC_2.2.5", "GLIBC_2.3"))),
    _tsr("aarch64",
         "tree_sitter_rust-0.24.2-cp39-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl",
         "b5/f6/a5a146df5c0a5daea3ffcd5d7245775fe7f084357770d5a313dd6245ae78/"
         "tree_sitter_rust-0.24.2-cp39-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl",
         170310, "9d76d1208c3638b871236090759dfc13d478921320653a6c9da5336e7c58f65a",
         (1389144, "d09117328b7f3e069e56202647f62812f1435aacae64360eb04a78de63b7fea7"),
         (187, "0f94b7b52e20f0cdd2b5d655f6a1bee5b664cae6686297052f611d34c99a16c9"),
         (1163, "4403d3c91aa300f0a6d616080754f47b777e5d99a6daaafe310c312911884cfd"),
         ElfFacts(183, _NEEDED, ("GLIBC_2.17",))),
    _tsr("x86_64",
         "tree_sitter_rust-0.24.2-cp39-abi3-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl",
         "ca/45/a051bbd3045a61182dde25b93ae9a33d2677c935b16952283e12eaf46051/"
         "tree_sitter_rust-0.24.2-cp39-abi3-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl",
         164706, "e033c5a93b57c88e0a835880de39fc802909ff69f57aaff6000211c196ea5190",
         (1266544, "a965112037009c8264531395977cfa236f8e8486d3d0af841f0145d22b43affa"),
         (180, "3e551b29b4473328f28a39ad8adbdcf98c6161890b4feffb29e72ee8dddc161b"),
         (1163, "56399f28703bd76308c5337d78b25240abff6e0240f0f762e4964c6341d69325"),
         ElfFacts(62, _NEEDED, ("GLIBC_2.2.5",))),
)
UNIQUE_ARTIFACT_BYTES = 1_642_452

NOTICES: tuple[NoticeLock, ...] = (
    NoticeLock("tree-sitter-core-LICENSE.txt", "tree-sitter-core-LICENSE", 1080,
               "c5cfb43042b6b72045f4ba997834d0a7786d2793d91680868b5815b39f14fc78"),
    NoticeLock("tree-sitter-unicode-LICENSE.txt", "tree-sitter-unicode-LICENSE", 21001,
               "6a18c5fac70d7860b57f5b72b4e2c9a1ba6b3d2741eef7ff9767c5379364f10d"),
)
CORE_COMMIT = "7f534862c3ec939c3a6ee147f7600ef5c1bf900f"


def wheels_for_cpu(cpu: str) -> tuple[WheelLock, WheelLock]:
    """Return the exact (binding, grammar) pair for one CPU or raise ``KeyError``."""

    pair = tuple(wheel for wheel in WHEELS if wheel.cpu == cpu)
    if cpu not in CPUS or len(pair) != 2:
        raise KeyError(cpu)
    return pair[0], pair[1]


def canonical_json(value: Any) -> bytes:
    """Sorted-key, compact, ASCII JSON used for every pilot identity digest."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def lock_document() -> dict[str, Any]:
    """Return the lock constants as plain JSON-compatible data."""

    return {
        "schema": LOCK_SCHEMA, "lock_id": LOCK_ID, "selection_rule": SELECTION_RULE,
        "dialect": DIALECT, "core_commit": CORE_COMMIT,
        "max_archive_uncompressed": MAX_ARCHIVE_UNCOMPRESSED,
        "wheels": [
            {"package": wheel.package, "version": wheel.version, "cpu": wheel.cpu,
             "filename": wheel.filename, "url": wheel.url, "size": wheel.size,
             "sha256": wheel.sha256, "dist_info": wheel.dist_info,
             "top_level": list(wheel.top_level), "extension": wheel.extension,
             "elf": {"machine": wheel.elf.machine, "needed": list(wheel.elf.needed),
                     "glibc_versions": list(wheel.elf.glibc_versions),
                     "nx_stack": wheel.elf.nx_stack, "relro": wheel.elf.relro},
             "members": [[item.name, item.size, item.sha256, item.wheel_mode]
                         for item in wheel.members]}
            for wheel in WHEELS
        ],
        "notices": [[item.package_file, item.installed_name, item.size, item.sha256]
                    for item in NOTICES],
    }


LOCK_SHA256 = digest_json(lock_document())
