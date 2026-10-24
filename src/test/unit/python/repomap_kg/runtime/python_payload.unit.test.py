"""ADR 0089 D4 payload contract: a temporary root and an injected runner; the host /usr/local is never read."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime.commands import PYTHON_PAYLOAD_SOURCE, render_server_dockerfile
from repomap_kg.runtime.release import PYTHON_RELEASE_IMAGE, DebPackage, PlatformPackages

DYN, LIBC, LICENSE = payload.DYNLOAD, "/lib/aarch64-linux-gnu/libc.so.6", "/usr/local/lib/python3.12/LICENSE.txt"
TK, SSL, MATH = (f"{DYN}/{name}.cpython-312-aarch64-linux-gnu.so" for name in ("_tkinter", "_ssl", "math"))
OK, MISSING = f"\tlibc.so.6 => {LIBC} (0x2)\n", "\tlibtcl8.6.so => not found\n\tlibtk8.6.so => not found\n"


def elf(tag: bytes, machine: int = 183) -> bytes:
    return b"\x7fELF\x02\x01\x01" + bytes(11) + machine.to_bytes(2, "little") + tag


class World:
    def __init__(self, root: Path) -> None:
        self.root, self.calls, self.broken, self.post = root, list[list[str]](), {"_tkinter"}, dict[str, Any]()
        files = {"/usr/local/bin/python3.12": elf(b"py"), SSL: elf(b"ssl"), MATH: elf(b"math"), TK: elf(b"tk"),
                 LICENSE: b"PSF", LIBC: b"libc"}
        self.ldd, self.owned = {**dict.fromkeys(files, OK), TK: OK + MISSING}, {LIBC: "libc6"}
        for path, data in files.items():
            self.path(path).parent.mkdir(parents=True, exist_ok=True)
            self.path(path).write_bytes(data)
        os.symlink("python3.12", self.path("/usr/local/bin/python3"))

    def path(self, logical: str) -> Path:
        return self.root / logical.lstrip("/")

    def run(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        post = self.post if not self.path(TK).exists() else {}  # overrides once the target is gone
        if command[0] == "ldd":
            text = {**self.ldd, **post}.get("/" + Path(command[1]).relative_to(self.root).as_posix())
            return subprocess.CompletedProcess(command, 0, text, "")
        if command[0] == "dpkg-query":
            owner = self.owned.get(command[2])
            out = f"{owner}:arm64: {command[2]}\n" * bool(owner)
            return subprocess.CompletedProcess(command, int(not owner), out, "")
        assert command[1:4] == ["-I", "-B", "-c"] and options["env"]["LD_BIND_NOW"] == "1", (command, options)
        bad = command[4].removeprefix("import ") in post.get("broken", self.broken)
        return subprocess.CompletedProcess(command, int(bad), "", "ImportError: libtk8.6.so" * bad)

    def tree(self) -> dict[str, bytes]:
        return {str(p): os.readlink(p).encode() if p.is_symlink() else p.read_bytes()
                for p in self.root.rglob("*") if p.is_file() or p.is_symlink()}


def _entry(**changes: Any) -> payload.PayloadExclusion:
    data = elf(b"tk")
    fields = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "baseline_imports": ("_ssl", "math")}
    return payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"]._replace(**{**fields, **changes})


def _main(world: World, capsys, *argv: str, machine: str = "aarch64",
          entry: payload.PayloadExclusion | None = None) -> tuple[int, dict[str, Any]]:
    code = payload.main(list(argv or ["arm64"]), run=world.run, mount=world.root, executable="py",
                        machine=lambda: machine, exclusions={"arm64": entry or _entry()})
    return code, json.loads(capsys.readouterr().out.splitlines()[-1])


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    return World(tmp_path)


# Historical Bookworm 3.12.13 E1 entry (ADR 0089 D4); superseded by the Trixie entry and never generalized.
LEGACY: dict[str, Any] = dict(python_index="sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b",
                              platform_manifest=(
                                  "sha256:c18c7a910432dde3311fc54d02e5d5220f3ebe26fec43ff15745982863dd7b3b"),
                              python_config="sha256:a0938838407c79b6ff4ea2635398c61b68a3bf58d9d71d0604ab7825086d506a",
                              sha256="e6856022061704f2b95ea01c9c12b6fa6fee36d2527a8ad7d0f18d4bacd9519f", size=70512,
                              baseline_imports=tuple(sorted((*payload.ARM64_BASELINE_IMPORTS, "nis"))))


def test_frozen_entry_is_the_static_trixie_arm64_identity_and_all_77_imports() -> None:
    entry = payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"]
    assert set(payload.PYTHON_PAYLOAD_EXCLUSIONS) == {"arm64"}, "no inferred amd64 entry"
    assert entry[1:10] == ("sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
                           "sha256:6c6ae3622772575c3ac02ecb2b02a06d05f19e1713a0cbff476ef37bca79e90f",
                           "sha256:7efd45553a98be3d940b73600550669831c0be34f30c521159e7030a91fcdee6",
                           "/usr/local/lib/python3.12/lib-dynload/_tkinter.cpython-312-aarch64-linux-gnu.so",
                           "9fe4f2c93a746b000a15ebb6fbb71ea33b3b7888efb70e3c1296fac8b30c2c96", 70584, 183, "_tkinter",
                           ("libtcl8.6.so", "libtk8.6.so")), entry
    assert PYTHON_RELEASE_IMAGE.endswith("@" + entry.python_index), "the pinned release index"
    assert len(entry.baseline_imports) == 77 and "nis" not in entry.baseline_imports
    assert hashlib.sha256(" ".join(entry.baseline_imports).encode()).hexdigest() == (
        "049267074bee42d4449e7a3ed866076d6529b44106e0e3676f41a5e1da277a1b"), "exactly the observed 77 names"
    assert hashlib.sha256(" ".join(LEGACY["baseline_imports"]).encode()).hexdigest() == (
        "96ddc6b126ca6ddaa8ad4e9d2cdbcc0dcd4d494d8afe7655478a5025eccb9c09"), "the historical 78 are the 77 plus nis"
    payload.validate_exclusion(entry, "arm64")


def _observed(*, imports: tuple[str, ...] | None = None, tk: dict[str, Any] | None = None,
              extra: str = "") -> dict[str, Any]:
    """The shape of the actual Trixie no-exclusion baseline: 77 importing modules plus the one Tk bridge."""
    entry = payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"]
    names = sorted((*entry.baseline_imports, "_tkinter") if imports is None else (*imports, "_tkinter"))
    imported = [name for name in names if name != "_tkinter"]
    elf_tk = {"sha256": entry.sha256, "size": entry.size, "elf": [2, 1, 183], "ldd_exit": 0,
              "ldd": OK + MISSING + extra, **(tk or {})}
    return {"machine": "aarch64", "dynload_real": DYN, "elves": {TK: elf_tk}, "targets": {},
            "dynload": [[f"{name}.cpython-312-aarch64-linux-gnu.so", "file"] for name in names],
            "imports": imported, "failed": {"_tkinter": {"exit": 1, "error": "ImportError: libtk8.6.so"}}}


def test_frozen_entry_classifies_the_exact_observed_trixie_baseline() -> None:
    exclusion = payload.classify(_observed(), payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"])
    assert exclusion is not None and exclusion["sha256"] == payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"].sha256
    assert exclusion["size"] == 70584 and exclusion["baseline_imports"] == 77 and exclusion["module"] == "_tkinter"


@pytest.mark.parametrize("observation, entry, message", [
    (lambda: _observed(), LEGACY, "target hash, size or ELF"),
    (lambda: _observed(), {"baseline_imports": LEGACY["baseline_imports"]}, "baseline imports differ"),
    (lambda: _observed(), {"sha256": LEGACY["sha256"]}, "target hash, size or ELF"),
    (lambda: _observed(), {"size": 70512}, "target hash, size or ELF"),
    (lambda: _observed(tk={"size": 70512}), {}, "target hash, size or ELF"),
    (lambda: _observed(tk={"sha256": "0" * 64}), {}, "target hash, size or ELF"),
    (lambda: _observed(imports=LEGACY["baseline_imports"]), {}, "baseline imports differ"),
    (lambda: _observed(imports=payload.ARM64_BASELINE_IMPORTS[1:]), {}, "baseline imports differ"),
    (lambda: _observed(extra="\tlibX11.so.6 => not found\n"), {}, "exactly the frozen missing pair"),
])
def test_legacy_or_wrong_pins_and_import_drift_refuse_the_trixie_classification(observation, entry, message) -> None:
    frozen = payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"]._replace(**entry)
    with pytest.raises(payload.PayloadRefusal, match=message):
        payload.classify(observation(), frozen)


@pytest.mark.parametrize("changes", [
    {"architecture": "amd64"}, {"sha256": "E" * 64}, {"python_config": "sha256:" + "a" * 63}, {"module": "_ssl"},
    {"path": "/usr/local/lib/python3.12/_tkinter.cpython-312-aarch64-linux-gnu.so"}, {"size": 0}, {"elf_machine": 0},
    {"missing": ("libtk8.6.so", "libtcl8.6.so")}, {"missing": ()}, {"baseline_imports": ("math", "_ssl")},
    {"baseline_imports": ("_tkinter",)}, {"baseline_imports": ("a b",)},
])
def test_inexact_entries_refuse(changes: dict[str, Any]) -> None:
    with pytest.raises(payload.PayloadRefusal, match="not exact"):
        payload.validate_exclusion(payload.PYTHON_PAYLOAD_EXCLUSIONS["arm64"]._replace(**changes), "arm64")


def test_trims_exactly_the_frozen_file_after_recording_the_raw_baseline(world: World, capsys) -> None:
    before = world.tree()
    code, report = _main(world, capsys)
    assert code == 0 and report["result"] == "trimmed" and report["reasons"] == [], report["reasons"]
    baseline, retained = report["baseline"], report["retained"]
    assert payload.unresolved(baseline["elves"]) == [
        f"{TK}: libtcl8.6.so => not found", f"{TK}: libtk8.6.so => not found"]
    assert sorted(baseline["failed"]) == ["_tkinter"] and baseline["imports"] == ["_ssl", "math"], baseline
    assert baseline["elves"][TK]["sha256"] == _entry().sha256 and baseline["entries"] == 10, baseline["entries"]
    assert report["exclusion"]["path"] == TK and report["exclusion"]["missing"] == ["libtcl8.6.so", "libtk8.6.so"]
    after = world.tree()
    assert set(before) - set(after) == {str(world.path(TK))} and all(after[p] == before[p] for p in after), "one file"
    assert retained["excluded_absent"] is True and retained["preserved"] is True and retained["unresolved"] == []
    assert retained["imports"] == retained["lib_dynload"] == ["_ssl", "math"] and retained["owners"] == {LIBC: "libc6"}
    assert retained["digest"] == retained["expected_digest"] != baseline["digest"], retained
    imports = [c[4] for c in world.calls if c[:1] == ["py"]]
    assert imports == ["import _ssl", "import _tkinter", "import math", "import _ssl", "import math"], imports


def _symlinked(world: World, _options: dict[str, Any]) -> None:
    world.path(TK).unlink()
    world.path("/usr/local/real_tk.so").write_bytes(elf(b"tk"))
    os.symlink("/usr/local/real_tk.so", world.path(TK))


def _machine62(world: World, options: dict[str, Any]) -> None:
    world.path(TK).write_bytes(elf(b"tk", 62))
    options["entry"] = _entry(sha256=hashlib.sha256(elf(b"tk", 62)).hexdigest())


@pytest.mark.parametrize("change, message", [
    (lambda w, o: o.update(entry=_entry(sha256="0" * 64)), "hash, size or ELF"),
    (lambda w, o: o.update(entry=_entry(size=1)), "hash, size or ELF"),
    (lambda w, o: o.update(entry=_entry(path=f"{DYN}/_tkinter.cpython-312-x86_64-linux-gnu.so")), "absent, dupl"),
    (lambda w, o: o.update(machine="x86_64"), "native architecture 'x86_64' is not 'arm64'"),
    (_machine62, "ELF class/machine"),
    (lambda w, o: w.broken.clear(), "non-importing modules"),
    (lambda w, o: w.broken.add("math"), "non-importing modules"),
    (lambda w, o: w.ldd.update({SSL: OK + "\tlibfoo.so.1 => not found\n"}), "missing pair"),
    (lambda w, o: w.ldd.update({TK: OK + "\tlibtcl8.6.so => not found\n"}), "missing pair"),
    (lambda w, o: w.ldd.update({TK: OK + MISSING + "\tlibX11.so.6 => not found\n"}), "missing pair"),
    (lambda w, o: w.ldd.update({MATH: ""}), "malformed empty ldd output"),
    (lambda w, o: w.ldd.update({MATH: "garbage"}), "missing pair"),
    (_symlinked, "absent, duplicated, a symlink"),
    (lambda w, o: w.path(f"{DYN}/_tkinter.abi3.so").write_bytes(b"x"), "absent, duplicated"),
    (lambda w, o: o.update(argv=("arm64", "--no-exclusion")), "no frozen exclusion applies"),
    (lambda w, o: o.update(argv=("amd64",), machine="x86_64"), "no frozen exclusion applies"),
    (lambda w, o: o.update(argv=("arm64", "--force")), "usage"),
])
def test_any_changed_observation_refuses_and_removes_nothing(world: World, capsys, change, message) -> None:
    options: dict[str, Any] = {}
    change(world, options)
    before = world.tree()
    code, report = _main(world, capsys, *options.pop("argv", ()), **options)
    assert code == 1 and report["result"] == "refused" and message in report["reasons"][0], report["reasons"]
    assert world.tree() == before and report["exclusion"] is None, "removes nothing"
    assert report["baseline"] is not None or message in ("usage", "native architecture 'x86_64' is not 'arm64'")


@pytest.mark.parametrize("post, message", [
    ({SSL: OK + "\tlibssl.so.3 => not found\n"}, "retained ELF dependencies are unresolved"),
    ({"broken": {"math"}}, "retained imports"),
    ({"hook": lambda w: w.path(LICENSE).unlink()}, "payload entries differ besides the exclusion"),
    ({"hook": lambda w: w.path(f"{DYN}/_new.so").write_bytes(b"x")}, "payload entries differ"),
    ({"hook": lambda w: w.owned.clear()}, "no CPython or dpkg owner"),
])
def test_retained_payload_must_resolve_import_stay_owned_and_unchanged(world: World, capsys, monkeypatch, post,
                                                                      message) -> None:
    post, remove = dict(post), payload.remove_exclusion
    if hook := post.pop("hook", None):  # an over-broad removal
        monkeypatch.setattr(payload, "remove_exclusion", lambda mount, entry: (remove(mount, entry), hook(world)))
    world.post.update(post)
    code, report = _main(world, capsys)
    assert code == 1 and report["result"] == "refused" and message in report["reasons"][0], report["reasons"]
    assert report["exclusion"]["path"] == TK and report["retained"] is None and not world.path(TK).exists()


def test_bytecode_writes_and_unknown_architectures_refuse_before_observing(world: World, capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    code, report = _main(world, capsys)
    assert code == 1 and "run with -B" in report["reasons"][0] and report["baseline"] is None and world.calls == []
    done = subprocess.run([sys.executable, "-I", "-B", payload.__file__, "riscv64"], capture_output=True, text=True)
    refused = json.loads(done.stdout)
    assert done.returncode == 1 and refused["schema"] == payload.SCHEMA
    assert "native architecture" in refused["reasons"][0]


def test_recipe_runs_the_same_file_on_the_unmodified_base_before_any_builder_package() -> None:
    root = Path(__file__).resolve().parents[6]
    assert (root / PYTHON_PAYLOAD_SOURCE).resolve() == Path(payload.__file__).resolve(), PYTHON_PAYLOAD_SOURCE
    deb = [DebPackage(name, "18.4-1", "arm64", hashlib.sha256(name.encode()).hexdigest())
           for name in ("libpq-dev", "libpq5")]
    item = PlatformPackages("sha256:" + "1" * 64, ("/etc/apt/sources.list.d/pgdg.list", "2" * 64),
                            ("/usr/share/keyrings/p.gpg", "3" * 64), ("A" * 40,), "/usr/lib/a/libpq.so.5.18", "4" * 64,
                            "18.4-1", tuple(deb), (deb[1],), ("_ssl",))
    recipe = render_server_dockerfile({"arm64": item}, 180004)
    stage = recipe.index(f"FROM {PYTHON_RELEASE_IMAGE} AS python-runtime\nARG TARGETARCH\nWORKDIR /build\nRUN case")
    copy = recipe.index(f"COPY {PYTHON_PAYLOAD_SOURCE} /tmp/repomap-payload/python_payload.py\n")
    run = recipe.index('RUN python -I -B /tmp/repomap-payload/python_payload.py "${TARGETARCH}" \\\n'
                       "    && rm -rf /tmp/repomap-payload\n")
    later = [recipe.index(token) for token in ("COPY --from=postgres", "apt-get", "pip download", "pip install",
                                               "COPY src/main/python ./src/main/python", "FROM postgres")]
    assert stage < recipe.index("esac\n", stage) < copy < run < min(later), (stage, copy, run, later)
    assert recipe.count("python_payload.py") == 3 and "--no-exclusion" not in recipe, "one wired, guarded run"
    assert "python_payload" not in render_server_dockerfile().split("AS runtime", 1)[1], "build stage only"
