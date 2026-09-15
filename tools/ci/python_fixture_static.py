"""Static-only syntax, token, and execution-use checks for fixture authority."""

from __future__ import annotations

import ast
import io
from pathlib import Path
import tokenize
from typing import Mapping, Sequence


class FixtureAuthorityError(ValueError):
    """Static fixture evidence is unreadable or contradictory."""


EXECUTION_CALLS = frozenset({
    "compile", "eval", "exec", "__import__",
    "importlib.import_module", "importlib.util.module_from_spec",
    "importlib.util.spec_from_file_location", "os.popen", "os.spawnl", "os.system",
    "pytest.main", "runpy.run_module", "runpy.run_path", "subprocess.call",
    "subprocess.check_call", "subprocess.check_output", "subprocess.Popen", "subprocess.run",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "os.execl", "os.execle", "os.execlp", "os.execlpe",
    "os.execv", "os.execve", "os.execvp", "os.execvpe", "os.fork", "os.forkpty",
    "os.spawnle", "os.spawnlp", "os.spawnlpe", "os.spawnv", "os.spawnve",
    "os.spawnvp", "os.spawnvpe", "os.posix_spawn", "os.posix_spawnp",
    "multiprocessing.Process", "multiprocessing.Pool", "multiprocessing.pool.Pool",
    "multiprocessing.get_context", "multiprocessing.managers.BaseManager",
    "ctypes.CDLL", "ctypes.PyDLL", "ctypes.WinDLL", "ctypes.OleDLL",
    "ctypes.cdll.LoadLibrary", "ctypes.pydll.LoadLibrary", "ctypes.windll.LoadLibrary",
    "ctypes.oledll.LoadLibrary", "pty.spawn", "pty.fork",
})


def read_source(
    path: Path, label: str, *, allow_tokenization_error: bool = False,
) -> tuple[str, tuple[tokenize.TokenInfo, ...]]:
    """Read UTF-8 source and tokenize it without importing or executing it."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise FixtureAuthorityError(f"{label} source is unreadable") from error
    tokens: list[tokenize.TokenInfo] = []
    try:
        tokens.extend(tokenize.generate_tokens(io.StringIO(source).readline))
    except (IndentationError, tokenize.TokenError) as error:
        if not allow_tokenization_error:
            raise FixtureAuthorityError(f"{label} tokenization failed") from error
    return source, tuple(tokens)


def parse_source(source: str, *, shape: str, label: str) -> ast.Module | None:
    """Parse a declared valid or malformed source shape with the AST only."""
    try:
        tree = ast.parse(source, filename=label)
    except SyntaxError as error:
        if shape == "malformed":
            return None
        raise FixtureAuthorityError(f"valid fixture declaration does not parse: {label}") from error
    if shape == "malformed":
        raise FixtureAuthorityError(f"malformed fixture declaration parses successfully: {label}")
    return tree


def qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def execution_api_aliases(tree: ast.AST) -> dict[str, str]:
    """Resolve imported execution APIs without importing their modules."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local = item.asname or item.name.split(".")[0]
                aliases[local] = item.name if item.asname else local
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name != "*":
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def resolved_call_name(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    """Return the canonical execution API name for an imported call."""
    name = qualified_name(node)
    if name is None:
        return None
    if name in aliases:
        name = aliases[name]
    else:
        prefix, separator, suffix = name.partition(".")
        if separator and prefix in aliases:
            name = f"{aliases[prefix]}.{suffix}"
    return name.removeprefix("builtins.")


def execution_calls(tree: ast.AST) -> tuple[str, ...]:
    aliases = execution_api_aliases(tree)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = resolved_call_name(node.func, aliases)
            if name in EXECUTION_CALLS:
                names.append(name)
    return tuple(sorted(set(names)))


def mentions_family(node: ast.AST, family: str, aliases: set[str]) -> bool:
    return any(
        (isinstance(child, ast.Constant) and isinstance(child.value, str) and family in child.value)
        or (isinstance(child, ast.Name) and child.id in aliases)
        for child in ast.walk(node)
    )


def _fixture_helper_names(family: str) -> set[str]:
    family_name = family.casefold()
    names = {f"{family_name}_fixture", f"{family_name}_fixture_root"}
    if family_name == "python_package":
        names.add("discovery_fixture")
    if family_name == "mixed_corpus":
        names.add("bulk_fixture_root")
    return names


def _fixture_seed(node: ast.AST, family: str, aliases: set[str]) -> bool:
    """Recognize a fixture path/helper without matching product module names."""
    strings = [
        child.value.casefold()
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]
    if any("fixtures" in value for value in strings):
        return True
    if any(isinstance(child, ast.Name) and child.id in aliases for child in ast.walk(node)):
        return True
    return any(
        isinstance(child, ast.Call)
        and qualified_name(child.func) in _fixture_helper_names(family)
        for child in ast.walk(node)
    )


def _fixture_reference_node(node: ast.AST, family: str, aliases: set[str]) -> bool:
    if not mentions_family(node, family, aliases):
        return False
    return _fixture_seed(node, family, aliases)


def path_aliases(tree: ast.AST, family: str) -> set[str]:
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            value: ast.expr | None
            targets: Sequence[ast.expr]
            if isinstance(node, ast.Assign):
                value, targets = node.value, node.targets
            elif isinstance(node, ast.AnnAssign):
                value, targets = node.value, (node.target,)
            elif isinstance(node, ast.NamedExpr):
                value, targets = node.value, (node.target,)
            else:
                continue
            family_value = mentions_family(value, family, set()) if value is not None else False
            family_target = any(
                isinstance(target, ast.Name)
                and target.id.casefold() in {"family", "fixture_family", "fixture_name"}
                for target in targets
            )
            if value is None or (not _fixture_seed(value, family, aliases) and not (family_value and family_target)):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
        if _fixture_seed(tree, family, aliases):
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                for argument in arguments:
                    name = argument.arg.casefold()
                    if "fixture" in name or name in {"family", "path", "root"}:
                        if argument.arg not in aliases:
                            aliases.add(argument.arg)
                            changed = True
        if not aliases:
            break
    return aliases


def consumer_execution_calls(tree: ast.AST, family: str) -> tuple[str, ...]:
    aliases = path_aliases(tree, family)
    execution_aliases = execution_api_aliases(tree)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = resolved_call_name(node.func, execution_aliases)
        if name in EXECUTION_CALLS and _fixture_reference_node(node, family, aliases):
            calls.append(name)
    return tuple(sorted(set(calls)))


def imports_fixture_family(tree: ast.AST, family: str) -> bool:
    """Detect a static import whose module path is visibly a fixture path."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
            if any("fixtures" in name.split(".") and family in name.split(".") for name in names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if "fixtures" in parts and family in parts:
                return True
    return False


def fixture_reference_present(tokens: Sequence[tokenize.TokenInfo], family: str) -> bool:
    """Require a fixture anchor before treating a family name as a reference.

    Product modules often contain names such as ``python_web`` that happen to
    match a fixture family.  A fixture reference needs either a literal fixture
    path or an explicitly named fixture helper, together with the family name.
    Import statements are checked separately from the AST because their dotted
    module path is represented as several NAME tokens.
    """
    family_name = family.casefold()
    relevant = [
        token.string.casefold()
        for token in tokens
        if token.type in {tokenize.NAME, tokenize.STRING}
    ]
    has_family = any(family_name in value for value in relevant)
    if not has_family:
        return False
    has_path_literal = any(
        token.type == tokenize.STRING and "fixtures" in token.string.casefold()
        for token in tokens
    )
    helper_names = _fixture_helper_names(family)
    has_fixture_helper = any(
        token.type == tokenize.NAME and token.string.casefold() in helper_names
        for token in tokens
    )
    return has_path_literal or has_fixture_helper


def candidate_consumer_paths(repo_root: Path, fixture_root: str) -> tuple[Path, ...]:
    """Return maintained Python source outside the fixture data boundary."""
    paths: set[Path] = set()
    for relative_root in ("src/main/python", "src/test", "tools"):
        source_root = repo_root / relative_root
        if not source_root.is_dir():
            continue
        for path in source_root.rglob("*.py"):
            if path.is_file() and not path.is_symlink() and not path.is_relative_to(repo_root / fixture_root):
                paths.add(path)
    return tuple(sorted(paths))


def validate_consumer(
    consumer_path: Path,
    repo_root: Path,
    fixture_path: str,
    family: str,
    role: str,
) -> dict[str, object]:
    """Return static evidence for one declared fixture consumer."""
    source, tokens = read_source(consumer_path, f"consumer {consumer_path}")
    try:
        tree = ast.parse(source, filename=str(consumer_path))
    except SyntaxError as error:
        raise FixtureAuthorityError(f"consumer source does not parse: {consumer_path}") from error
    fixture_import = imports_fixture_family(tree, family)
    if not fixture_reference_present(tokens, family) and not fixture_import:
        raise FixtureAuthorityError(
            f"consumer does not statically name fixture family {family}: {fixture_path}"
        )
    calls = consumer_execution_calls(tree, family)
    if role == "inert_data" and (calls or fixture_import):
        detail = ", ".join(calls) or "fixture import"
        raise FixtureAuthorityError(f"inert fixture has executable consumer use ({detail}): {fixture_path}")
    if role == "executable_first_party" and not (calls or fixture_import):
        raise FixtureAuthorityError(
            f"executable fixture lacks a statically verified execution consumer: {fixture_path}"
        )
    return {
        "path": consumer_path.relative_to(repo_root).as_posix(),
        "family": family,
        "tokens_checked": len(tokens),
        "ast_parsed": True,
        "execution_calls": list(calls),
        "fixture_import": fixture_import,
    }


def scan_unlisted_consumers(
    repo_root: Path,
    fixture_root: str,
    inert_families: Sequence[str],
    declared: set[str],
    ignored_paths: Sequence[str] = (),
) -> dict[str, list[str]]:
    """Find undeclared static references and reject hidden executable use."""
    families = tuple(sorted(set(inert_families)))
    ignored = set(ignored_paths)
    references: dict[str, list[str]] = {family: [] for family in families}
    for path in candidate_consumer_paths(repo_root, fixture_root):
        relative = path.relative_to(repo_root).as_posix()
        if relative in ignored:
            continue
        source, tokens = read_source(path, f"candidate consumer {relative}")
        for family in families:
            if not token_mentions_family(tokens, family):
                continue
            try:
                tree = ast.parse(source, filename=relative)
            except SyntaxError as error:
                raise FixtureAuthorityError(
                    f"candidate consumer with fixture reference does not parse: {relative}"
                ) from error
            fixture_import = imports_fixture_family(tree, family)
            if not fixture_reference_present(tokens, family) and not fixture_import:
                continue
            calls = consumer_execution_calls(tree, family)
            if calls or fixture_import:
                detail = ", ".join(calls) or "fixture import"
                raise FixtureAuthorityError(
                    f"unlisted executable use of inert fixture ({detail}): {relative}"
                )
            if relative not in declared:
                references[family].append(relative)
    return references


def token_mentions_family(tokens: Sequence[tokenize.TokenInfo], family: str) -> bool:
    return any(
        family in token.string
        for token in tokens
        if token.type in {tokenize.NAME, tokenize.STRING}
    )
