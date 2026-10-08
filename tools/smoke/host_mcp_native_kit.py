"""Operator kit for the host MCP native qualification runner.

The kit mirrors the repository layout (``cli_in_process`` and the fixture
helpers resolve siblings through fixed parent offsets) and contains the runner,
the AST-computed import closure under ``tools`` and ``src/test/support/python``,
the two offline fixture inputs, ``run.sh`` and the operator README. The
interpreter, the ``repomap-kg`` console script and the editable ``repomap_kg``
package (with its migrations and installed dependencies) still come from the
pinned checkout; the kit manifest records the checkout product bytes it was
built against so a mismatched checkout is refused before any resource exists.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from .host_mcp_native_evidence import deterministic_zip

KIT_DIR = "repomap-host-mcp-native-kit"
KIT_ZIP = f"{KIT_DIR}.zip"
MANIFEST = "KIT-MANIFEST.json"
MANIFEST_SCHEMA = "repomap-host-mcp-native-kit-v1"
IMPORT_ROOTS = ("tools", "src/test/support/python")
SEEDS = (
    "tools/host_mcp_native_qualify.py",
    "tools/smoke/host_mcp_native.py",
    "tools/smoke/host_mcp_native_scenario.py",
)
FIXTURE_INPUTS = (
    "src/test/fixtures/discovery/feed_static_basic/rss.xml",
    "src/test/fixtures/source_ingestion/feed_sources/allowed-rss.toml",
)
RENAMED = {"tools/smoke/host_mcp_native_kit_run.sh": "run.sh",
           "docs/ops/host-mcp-native-qualification.md": "README.md"}
PRODUCT_PATHS = ("src/main/python/repomap_kg", "src/main/resources", "pyproject.toml")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def import_closure(repo: Path, seeds: Iterable[str] = SEEDS) -> list[str]:
    """Repository-relative files reachable by any import (including lazy ones) under IMPORT_ROOTS."""
    seen: set[str] = set()
    pending = [repo / seed for seed in seeds]
    while pending:
        path = pending.pop()
        relative = path.relative_to(repo).as_posix()
        if relative in seen:
            continue
        seen.add(relative)
        package = _module_name(relative).rpartition(".")[0] if path.name != "__init__.py" else _module_name(relative)
        for name in _imported_modules(ast.parse(path.read_bytes(), filename=relative), package):
            parts = name.split(".")
            for depth in range(1, len(parts) + 1):
                resolved = _resolve(repo, parts[:depth])
                if resolved is not None:
                    pending.append(resolved)
    return sorted(seen)


def _module_name(relative: str) -> str:
    for root in IMPORT_ROOTS:
        if relative.startswith(root + "/"):
            module = relative[len(root) + 1:].removesuffix(".py").replace("/", ".")
            return module.removesuffix(".__init__")
    raise ValueError(f"{relative} is outside the kit import roots")


def _imported_modules(tree: ast.AST, package: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*anchor, base] if base else anchor)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return {name for name in names if name}


def _resolve(repo: Path, parts: list[str]) -> Path | None:
    for root in IMPORT_ROOTS:
        candidate = repo.joinpath(root, *parts)
        if (candidate / "__init__.py").is_file():
            return candidate / "__init__.py"
        if candidate.with_suffix(".py").is_file():
            return candidate.with_suffix(".py")
    return None


def product_manifest(checkout: Path, *, runner: Runner = subprocess.run) -> dict[str, str]:
    """SHA-256 of every git-listed product file (never a filesystem walk, so caches are ignored)."""
    listed = runner(["git", "-C", str(checkout), "ls-files", "-z", "--", *PRODUCT_PATHS],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, timeout=60,
                    env=_git_env())
    return {path: hashlib.sha256((checkout / path).read_bytes()).hexdigest()
            for path in sorted(filter(None, listed.stdout.split("\0")))}


def _git_env() -> dict[str, str]:
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}


def kit_files(repo: Path) -> dict[str, tuple[bytes, int]]:
    """Kit-relative path -> (bytes, mode) for every shipped file except the manifest."""
    files = {relative: ((repo / relative).read_bytes(), 0o644) for relative in (*import_closure(repo),
                                                                                 *FIXTURE_INPUTS)}
    for source, target in RENAMED.items():
        files[target] = ((repo / source).read_bytes(), 0o755 if target.endswith(".sh") else 0o644)
    return files


def build_kit(repo: Path, out_dir: Path, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Write the kit ZIP plus a sidecar receipt and the operator command; never overwrite."""
    files = kit_files(repo)
    head = runner(["git", "-C", str(repo), "rev-parse", "HEAD", "HEAD^{tree}"], stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, text=True, check=True, timeout=60, env=_git_env()).stdout.split()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "mode": oct(mode)}
                  for name, (data, mode) in sorted(files.items())},
        "renamed_from": {target: source for source, target in RENAMED.items()},
        "product": product_manifest(repo, runner=runner),
        "build_checkout": {"head": head[0], "tree": head[1], "role": "evidence only; not a gate"},
        "from_checkout": ["<checkout>/.venv/bin/python (parent and child interpreter)",
                          "<checkout>/.venv/bin/repomap-kg (the MCP acceptance process)",
                          "editable repomap_kg under <checkout>/src/main/python with src/main/resources",
                          "installed psycopg and pytest in <checkout>/.venv"],
    }
    files[MANIFEST] = ((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), 0o644)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / KIT_ZIP
    if zip_path.exists():
        raise FileExistsError(f"refusing to overwrite an existing kit: {zip_path}")
    data = deterministic_zip({f"{KIT_DIR}/{name}": value for name, value in files.items()})
    zip_path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    receipt = {"schema": "repomap-host-mcp-native-kit-receipt-v1", "zip": KIT_ZIP, "sha256": digest,
               "bytes": len(data), "members": len(files), "build_checkout": manifest["build_checkout"]}
    (out_dir / "kit-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                                              encoding="utf-8")
    (out_dir / "OPERATOR-COMMAND.zsh").write_text(operator_command(digest, out_dir), encoding="utf-8")
    return receipt


def operator_command(kit_sha256: str, kit_dir: Path, checkout: str = "$HOME/projs/repo-map_dev") -> str:
    """The complete zsh command: verify the exact delivered kit in place, extract it fresh, check, then execute."""
    return f"""(
  set -eu
  kit_sha={kit_sha256}
  zip={_shell_path(kit_dir.expanduser().absolute())}/{KIT_ZIP}
  [[ -f "$zip" && "$(shasum -a 256 "$zip" | cut -d' ' -f1)" == "$kit_sha" ]] || {{
    print -u2 "NOT RUN: $zip is absent or its SHA-256 is not $kit_sha"; exit 2; }}
  dest=$(mktemp -d "${{TMPDIR:-/tmp}}/repomap-native-kit.XXXXXX")
  ditto -x -k "$zip" "$dest"
  sh "$dest/{KIT_DIR}/run.sh" --check --checkout "{checkout}"
  sh "$dest/{KIT_DIR}/run.sh" --execute --checkout "{checkout}"
)
"""


def _shell_path(path: Path) -> str:
    """``"$HOME"/…`` when under the home folder and plainly quotable, otherwise an exact single-quoted path."""
    text, home = str(path), str(Path.home())
    if text.startswith(home + "/") and not any(char in text for char in "$`\"\\\n"):
        return f'"$HOME{text[len(home):]}"'
    return shlex.quote(text)


def verify_kit(kit_root: Path) -> tuple[bool, dict[str, Any]]:
    """Manifest integrity of an extracted kit (every listed file present with its recorded bytes)."""
    manifest_path = kit_root / MANIFEST
    if not manifest_path.is_file():
        return False, {"error": "not running from an extracted kit (KIT-MANIFEST.json is absent)"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        return False, {"error": "unsupported kit manifest schema"}
    bad = sorted(name for name, entry in manifest["files"].items()
                 if not (kit_root / name).is_file()
                 or hashlib.sha256((kit_root / name).read_bytes()).hexdigest() != entry["sha256"])
    return not bad, {"files": len(manifest["files"]), "mismatched": bad,
                     "build_checkout": manifest.get("build_checkout")}


def compare_checkout(kit_root: Path, checkout: Path, *, runner: Runner = subprocess.run) -> list[str]:
    """Problems that make this checkout differ from the one the kit was built from."""
    manifest = json.loads((kit_root / MANIFEST).read_text(encoding="utf-8"))
    sources = {**{name: name for name in manifest["files"] if name.startswith(("tools/", "src/"))},
               **manifest.get("renamed_from", {})}
    problems = [f"checkout differs from kit: {source}" for target, source in sorted(sources.items())
                if not (checkout / source).is_file()
                or (checkout / source).read_bytes() != (kit_root / target).read_bytes()]
    actual = product_manifest(checkout, runner=runner)
    expected = manifest["product"]
    problems.extend(f"product file differs: {path}" for path in sorted(set(actual) | set(expected))
                    if actual.get(path) != expected.get(path))
    return problems
