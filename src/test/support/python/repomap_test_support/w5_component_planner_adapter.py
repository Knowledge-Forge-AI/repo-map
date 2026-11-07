"""Test-only, exact-byte ANN transport control; no SQL or role rewriting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


MAX_SQL_BYTES = 1024 * 1024
MAX_LOG_BYTES = 64 * 1024
ROUTES = frozenset({"ann_explain", "ann_candidates"})
PLANNER_OPTION = "-c enable_seqscan=off -c enable_sort=off"


class FunctionalAdapterRefusal(ValueError):
    """The disposable diagnostic adapter cannot preserve its exact contract."""


def sql_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def selected_options(
    sql: bytes, inherited: str | None, allowed: Mapping[str, Sequence[str]],
) -> tuple[str, str | None]:
    """Select only exact precomputed SQL digests; every other call is unchanged."""
    if set(allowed) != ROUTES or any(
        type(values) not in (list,tuple) or not 1 <= len(values) <= 2
        for values in allowed.values()
    ):
        raise FunctionalAdapterRefusal("adapter_route_configuration")
    values = [value for group in allowed.values() for value in group]
    if any(type(value) is not str or len(value) != 71 or not value.startswith("sha256:")
           or any(char not in "0123456789abcdef" for char in value[7:]) for value in values):
        raise FunctionalAdapterRefusal("adapter_route_configuration")
    if len(set(values)) != len(values):
        raise FunctionalAdapterRefusal("adapter_route_configuration")
    digest = sql_digest(sql)
    route = next((name for name, group in allowed.items() if digest in group), "unchanged")
    if route == "unchanged":
        return route, inherited
    if inherited is not None and any(option in inherited for option in ("enable_seqscan","enable_sort")):
        raise FunctionalAdapterRefusal("adapter_planner_option_preexisting")
    return route, (inherited + " " if inherited else "") + PLANNER_OPTION


def _append_receipt(path: Path, record: Mapping[str, object]) -> None:
    raw = (json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n").encode()
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_size + len(raw) > MAX_LOG_BYTES:
            raise FunctionalAdapterRefusal("adapter_receipt_boundary")
        if os.write(descriptor, raw) != len(raw):
            raise FunctionalAdapterRefusal("adapter_receipt_short_write")
    finally:
        os.close(descriptor)


def _check_argv(argv: Sequence[str]) -> None:
    # These maintained transport routes all send SQL on stdin. Command/file
    # options could execute a second, unclassified payload and must refuse.
    if any(value in {"-c", "--command", "-f", "--file"} or value.startswith(
        ("--command=", "--file=", "-c", "-f")
    ) or (value.startswith("-") and not value.startswith("--") and
          any(option in value[1:] for option in ("c","f"))) for value in argv):
        raise FunctionalAdapterRefusal("adapter_non_stdin_sql")


def command_main(config_path: Path, argv: Sequence[str]) -> int:
    """Invoke the same fixture psql with unchanged SQL, arguments and outputs."""
    try:
        config = json.loads(config_path.read_bytes())
        if set(config) != {"command", "allowed"}:
            raise FunctionalAdapterRefusal("adapter_configuration")
        _check_argv(argv)
        sql = sys.stdin.buffer.read(MAX_SQL_BYTES + 1)
        if not sql or len(sql) > MAX_SQL_BYTES:
            raise FunctionalAdapterRefusal("adapter_sql_size")
        inherited = os.environ.get("PGOPTIONS")
        route, options = selected_options(sql, inherited, config["allowed"])
        environment = os.environ.copy()
        if options is not None:
            environment["PGOPTIONS"] = options
        completed = subprocess.run([config["command"], *argv], input=sql, env=environment, check=False)
        _append_receipt(config_path.parent / "invocations.jsonl", {
            "route": route,
            "sql_sha256": sql_digest(sql),
            "planner_option_appended": route != "unchanged",
            "inherited_pgoptions_sha256": None if inherited is None else sql_digest(inherited.encode()),
            "effective_pgoptions_sha256": None if options is None else sql_digest(options.encode()),
            "inherited_options_preserved": options == inherited if route == "unchanged" else (
                options == (inherited + " " if inherited else "") + PLANNER_OPTION
            ),
            "psql_exit": completed.returncode,
        })
        return completed.returncode
    except (FunctionalAdapterRefusal, OSError, ValueError, TypeError, KeyError):
        print("functional planner adapter refused", file=sys.stderr)
        return 3


@dataclass(frozen=True)
class FunctionalAdapter:
    command: Path
    receipt: Path
    allowed: tuple[tuple[str, tuple[str, ...]], ...]

    def read_receipts(self) -> tuple[dict[str, object], ...]:
        raw = self.receipt.read_bytes()
        if len(raw) > MAX_LOG_BYTES:
            raise FunctionalAdapterRefusal("adapter_receipt_boundary")
        return tuple(json.loads(line) for line in raw.splitlines())


def make_functional_adapter(
    directory: Path, command: str, allowed_sql: Mapping[str, Sequence[str]],
) -> FunctionalAdapter:
    """Create one test-owned adapter; paths/configuration never enter public proof."""
    if set(allowed_sql) != ROUTES or any(type(group) not in (tuple,list)
        or not 1 <= len(group) <= 2 for group in allowed_sql.values()):
        raise FunctionalAdapterRefusal("adapter_route_configuration")
    if any(type(value) is not str or not 0 < len(value.encode()) <= MAX_SQL_BYTES
           for group in allowed_sql.values() for value in group):
        raise FunctionalAdapterRefusal("adapter_route_configuration")
    allowed = {name:tuple(sql_digest(value.encode()) for value in group) for name,group in allowed_sql.items()}
    selected_options(b"configuration validation", None, allowed)
    directory.mkdir(mode=0o700)
    receipt = directory / "invocations.jsonl"
    with receipt.open("xb"):
        pass
    config_path = directory / "config.json"
    with config_path.open("x") as stream:
        json.dump({"command": command, "allowed": allowed}, stream)
    os.chmod(config_path, 0o600)
    os.chmod(receipt, 0o600)
    adapter_path = directory / "psql-adapter"
    # This points only to maintained test support, never an artifact archive.
    support_root = Path(__file__).resolve().parents[1]
    script = (
        f"#!{sys.executable}\n"
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(support_root)!r})\n"
        "from repomap_test_support.w5_component_planner_adapter import command_main\n"
        f"raise SystemExit(command_main(Path({str(config_path)!r}), sys.argv[1:]))\n"
    )
    with adapter_path.open("x") as stream:
        stream.write(script)
    os.chmod(adapter_path, 0o700)
    return FunctionalAdapter(adapter_path, receipt, tuple(sorted(allowed.items())))


__all__ = [
    "FunctionalAdapter", "FunctionalAdapterRefusal", "MAX_SQL_BYTES",
    "PLANNER_OPTION", "make_functional_adapter", "selected_options", "sql_digest",
]
