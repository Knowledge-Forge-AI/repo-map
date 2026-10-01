"""Operator entrypoint for the host MCP native qualification runner.

``--check`` (default) evaluates prerequisites and creates no resource.
``--execute`` runs the native proof on macOS from a verified, extracted
operator kit against the pinned checkout's own ``.venv/bin/repomap-kg``.
``--build-kit OUT`` (repository checkout only) writes the operator kit.

There is deliberately no option or environment variable that lets a non-macOS
run, an unverified kit, or a provisioned test wrapper stand in for native
execution; the Linux integration exercise reaches ``execute_run`` only through
its own test with ``qualification_class="linux-harness-exercise"``. Every
outcome is ``completed_pending_manager_review`` at best: nothing here labels a
run qualified or accepted.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from typing import Any

from .host_mcp_native_evidence import EvidenceWriter, utc_stamp
from .host_mcp_native_kit import MANIFEST, build_kit, compare_checkout, verify_kit
from .host_mcp_native_launch import ChildLayout, ConsoleEntrypoint, child_environment, console_entrypoint, import_probe

DEFAULT_PHASE = "REPOMAP-PRODUCT2-HOST-MCP-NATIVE1-HOST1"
PHASE_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9-]{2,95}")
DEFAULT_OUTBOX = Path.home() / "Documents" / "agent" / "outbox" / "repo-map_dev"
MIN_FREE_BYTES = 1 << 30
KIT_MODULE_PREFIXES = ("smoke", "repomap_test_support", "runner_", "test_sandbox", "host_mcp_native_qualify")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="host_mcp_native_qualify.py", description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="prerequisites only; creates nothing (default)")
    mode.add_argument("--execute", action="store_true", help="run the native macOS proof from an extracted kit")
    mode.add_argument("--build-kit", metavar="OUT", type=Path, help="write the operator kit (repository only)")
    parser.add_argument("--checkout", type=Path, help="pinned RepoMap checkout whose .venv console is executed")
    parser.add_argument("--phase", default=DEFAULT_PHASE, help="outbox phase directory name")
    parser.add_argument("--outbox-root", type=Path, default=DEFAULT_OUTBOX, help="evidence outbox root")
    return parser


@dataclass
class Prerequisites:
    items: list[dict[str, Any]] = field(default_factory=list)
    console: ConsoleEntrypoint | None = None
    port: int | None = None

    @property
    def ok(self) -> bool:
        return bool(self.items) and all(item["status"] == "ok" for item in self.items)

    def add(self, name: str, ok: bool, **detail: Any) -> bool:
        self.items.append({"name": name, "status": "ok" if ok else "refused", **detail})
        return ok


def check_prerequisites(checkout: Path, kit_root: Path, *, platform: str = sys.platform,
                        runner: Runner = subprocess.run) -> Prerequisites:
    """Local checks always run; Docker is probed only after every local check passed."""
    pre = Prerequisites()
    pre.add("platform", platform == "darwin", platform=platform, machine=os.uname().machine,
            note="native execution requires macOS; a Linux success is never native acceptance")
    kit_ok, kit = verify_kit(kit_root)
    pre.add("kit", kit_ok, kit_root=str(kit_root), **kit)
    _checkout(pre, checkout, kit_root, kit_ok, runner)
    console_path = checkout / ".venv" / "bin" / "repomap-kg"
    if pre.add("console-present", console_path.is_file(), path=str(console_path)):
        pre.console = console_entrypoint(console_path)
        refusal = pre.console.native_refusal(checkout)
        pre.add("console-form", refusal is None, refusal=refusal, console=pre.console.jsonable())
        if refusal is None and pre.console.interpreter:
            _probe(pre, checkout, pre.console.interpreter, platform, runner)
    _parent(pre, checkout, kit_root)
    if not pre.ok:
        pre.items.append({"name": "docker", "status": "skipped", "reason": "an earlier prerequisite was refused"})
        return pre
    _docker(pre, runner)
    free = shutil.disk_usage(tempfile.gettempdir()).free
    pre.add("disk", free >= MIN_FREE_BYTES, free_bytes=free, required_bytes=MIN_FREE_BYTES)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        pre.port = probe.getsockname()[1]
    pre.add("loopback-port", pre.port not in (5432, 55433), port=pre.port, bind="127.0.0.1")
    return pre


def _checkout(pre: Prerequisites, checkout: Path, kit_root: Path, kit_ok: bool, runner: Runner) -> None:
    git_env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return runner(["git", "-C", str(checkout), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                      text=True, check=False, timeout=60, env=git_env)

    try:
        status, head = git("status", "--porcelain"), git("rev-parse", "HEAD", "HEAD^{tree}")
    except (OSError, subprocess.SubprocessError) as error:
        pre.add("checkout-clean", False, checkout=str(checkout), error=f"{type(error).__name__}: {error}")
        return
    clean = status.returncode == 0 and not status.stdout.strip()
    pre.add("checkout-clean", clean, checkout=str(checkout), head_and_tree=head.stdout.split(),
            dirty_entries=len(status.stdout.splitlines()), git_exit=status.returncode,
            note="HEAD/tree recorded as evidence, not a gate")
    if clean and kit_ok:
        problems = compare_checkout(kit_root, checkout, runner=runner)
        pre.add("checkout-matches-kit", not problems, problems=problems[:50])


def _probe(pre: Prerequisites, checkout: Path, interpreter: str, platform: str, runner: Runner) -> None:
    scratch = Path(tempfile.mkdtemp(prefix="repomap-native-probe-")).resolve()
    try:
        layout = ChildLayout(scratch).create()
        record = import_probe(interpreter, layout, child_environment(layout, platform), runner=runner)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    result = record.get("result") or {}
    source = (checkout / "src" / "main" / "python").resolve()
    inside = bool(result.get("repomap_kg_file")) and Path(result["repomap_kg_file"]).resolve().is_relative_to(source)
    pre.add("console-imports", bool(record.get("ok")) and inside, probe=record,
            note="prerequisite probe with the child environment; a missing import is a prerequisite refusal, "
                 "never an automatic installation")


def _parent(pre: Prerequisites, checkout: Path, kit_root: Path) -> None:
    detail: dict[str, Any] = {"parent_python": sys.executable, "sys_flags_isolated": sys.flags.isolated}
    try:
        import psycopg
        import pytest
        import repomap_kg
        from . import host_mcp_native_scenario  # loads the whole parent fixture closure

        detail.update(repomap_kg=repomap_kg.__file__, psycopg=psycopg.__version__, pytest=pytest.__version__,
                      scenario=host_mcp_native_scenario.__file__)
    except Exception as error:  # a broken checkout import is a prerequisite refusal
        pre.add("parent-imports", False, error=f"{type(error).__name__}: {error}", **detail)
        return
    source = (checkout / "src" / "main" / "python").resolve()
    files = {name: getattr(module, "__file__", None) for name, module in list(sys.modules.items())
             if name.startswith(KIT_MODULE_PREFIXES)}
    outside = sorted(name for name, file in files.items()
                     if file and not Path(file).resolve().is_relative_to(kit_root.resolve()))
    pre.add("parent-imports", Path(detail["repomap_kg"]).resolve().is_relative_to(source) and not outside,
            modules_outside_kit=outside[:20], **detail)


def _docker(pre: Prerequisites, runner: Runner) -> None:
    from repomap_test_support.postgres_container import TEST_POSTGRES_IMAGE

    def docker(*args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return runner(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          check=False, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None

    server = docker("version", "--format", "{{.Server.Version}}")
    if not pre.add("docker", server is not None and server.returncode == 0,
                   server=(server.stdout.strip() if server else None)):
        return
    image = docker("image", "inspect", "--format", "{{.Id}}", TEST_POSTGRES_IMAGE)
    pre.add("postgres-image", image is not None and image.returncode == 0, image=TEST_POSTGRES_IMAGE,
            image_id=(image.stdout.strip() if image else None),
            manual_pull=f"docker pull {TEST_POSTGRES_IMAGE}", note="never pulled automatically")


def main(argv: Sequence[str] | None = None, *, kit_root: Path, runner: Runner = subprocess.run) -> int:
    args = build_parser().parse_args(argv)
    if args.build_kit is not None:
        if (kit_root / MANIFEST).exists():
            print("NOT RUN: --build-kit works only in a repository checkout", file=sys.stderr)
            return 2
        receipt = build_kit(kit_root, args.build_kit, runner=runner)
        print(f"kit {args.build_kit / receipt['zip']} sha256 {receipt['sha256']}")
        return 0
    if args.checkout is None or not PHASE_PATTERN.fullmatch(args.phase):
        print("NOT RUN: --checkout PATH is required and --phase must be an upper-case phase id", file=sys.stderr)
        return 2
    checkout = args.checkout.expanduser().absolute()
    pre = check_prerequisites(checkout, kit_root.resolve(), runner=runner)
    mode = "execute" if args.execute else "check"
    run_id = f"{'native1' if args.execute else 'check'}-{utc_stamp()}-{os.urandom(4).hex()}"
    evidence = EvidenceWriter(args.outbox_root.expanduser() / args.phase / run_id, run_id=run_id, phase=args.phase)
    evidence.write_json("prerequisites.json", {"mode": mode, "checkout": str(checkout), "items": pre.items})
    if not pre.ok or not args.execute:
        outcome = "prerequisites_ok" if pre.ok else "not_run"
        receipt = evidence.finalize(outcome=outcome, exit_code=0 if pre.ok else 2,
                                    qualification_class="none (prerequisite check)",
                                    summary={"mode": mode, "refused": [i["name"] for i in pre.items
                                                                       if i["status"] == "refused"]})
        print(f"{mode}: {outcome.upper().replace('_', ' ')}; receipt {evidence.run_dir / 'receipt.json'}",
              file=sys.stderr)
        return int(receipt["exit_code"])
    from .host_mcp_native_backend import OwnedContainerBackend
    from .host_mcp_native_run import RunContext, execute_run, new_work_root
    from .host_mcp_native_scenario import run_scenario

    assert pre.console is not None and pre.port is not None
    backend = OwnedContainerBackend(port=pre.port, run_id=f"native1{run_id.rsplit('-', 1)[1]}", runner=runner)
    context = RunContext(run_id=run_id, work=new_work_root(run_id), evidence=evidence,
                         parent_bin=checkout / ".venv" / "bin")
    return execute_run(context, backend, pre.console, qualification_class="native-macos-checkout-console",
                       scenario=run_scenario)
