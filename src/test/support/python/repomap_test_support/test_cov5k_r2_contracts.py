"""Acyclic callable identity and explicitly supplied evidence construction."""

from __future__ import annotations

import hashlib
import inspect
import shutil
import sys
from pathlib import Path
from types import CodeType
from typing import Callable, Protocol, TypeVar




T = TypeVar("T")
Evidence = TypeVar("Evidence", covariant=True)


class OwnerEvidenceFactory(Protocol[Evidence]):
    """Construct evidence without importing its orchestration-owned record."""

    def __call__(
        self, *, module_source_digest: str, qualified_symbol: str,
        code_object_identity: str, executor_source_digest: str,
        owner_entry_count: int, scenario_seam_active: bool,
        owner_source_path: str, owner_module: str,
        executor_source_path: str, executor_module: str,
        executor_qualified_symbol: str, owner_entry_during_operation: bool,
    ) -> Evidence: ...


class OwnerBindingError(RuntimeError):
    """Raised when exact runtime owner reachability is not proved."""


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def callable_source_digest(callable_owner: Callable[..., object]) -> str:
    try:
        source = inspect.getsource(callable_owner).encode("utf-8")
    except (OSError, TypeError) as error:
        raise OwnerBindingError("callable source is unavailable") from error
    return _digest_bytes(source)


def code_object_identity(code: CodeType) -> str:
    return _digest_bytes(
        b"\0".join(
            (
                str(Path(code.co_filename).resolve()).encode("utf-8"),
                code.co_qualname.encode("utf-8"),
                code.co_code,
            )
        )
    )


def external_owner_evidence(
    *,
    evidence_factory: OwnerEvidenceFactory[Evidence],
    executor: Callable[..., object],
    executable: str,
    owner_entry_count: int,
    scenario_seam_active: bool,
) -> Evidence:
    logical_name = Path(executable).name
    resolved = shutil.which(executable)
    if resolved is None:
        raise OwnerBindingError("registered external executable is unavailable")
    path = Path(resolved).resolve()
    stat = path.stat()
    identity = _digest_bytes(
        f"{path.name}:{stat.st_dev}:{stat.st_ino}:{stat.st_size}".encode("utf-8")
    )
    return evidence_factory(
        module_source_digest=_digest_bytes(path.read_bytes()),
        qualified_symbol=f"external:{path.name}",
        code_object_identity=identity,
        executor_source_digest=callable_source_digest(executor),
        owner_entry_count=owner_entry_count,
        scenario_seam_active=scenario_seam_active,
        # Logical tool authority is the requested invocation name, not the
        # resolved target: a launcher symlink may resolve to a different
        # basename. Physical binding stays on the resolved artifact above.
        owner_source_path=f"tool:{logical_name}",
        owner_module="external",
        executor_source_path=str(
            Path(inspect.getsourcefile(executor) or "").resolve().relative_to(
                Path(__file__).resolve().parents[5]
            )
        ),
        executor_module=executor.__module__,
        executor_qualified_symbol=f"{executor.__module__}.{executor.__qualname__}",
        owner_entry_during_operation=True,
    )


def exact_callable_matches(
    callable_owner: Callable[..., object],
    *,
    source_path: Path,
    symbol: str,
) -> bool:
    """Reject runtime insertion and same-module symbol substitution."""

    code = getattr(callable_owner, "__code__", None)
    if code is None:
        return False
    if Path(code.co_filename).resolve() != source_path.resolve():
        return False
    source = source_path.read_text(encoding="utf-8")
    declared = _declared_callable_source(source, symbol)
    if declared is None:
        return False
    expected_name, expected_source = declared
    if callable_owner.__name__ != expected_name:
        return False
    return callable_source_digest(callable_owner) == _digest_bytes(
        expected_source.encode("utf-8")
    )


def _declared_callable_source(source: str, symbol: str) -> tuple[str, str] | None:
    import ast

    module = ast.parse(source)
    lines = source.splitlines(keepends=True)
    functions = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    target_name = symbol
    if target_name not in functions:
        for node in module.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Name):
                continue
            if any(isinstance(target, ast.Name) and target.id == symbol for target in node.targets):
                target_name = node.value.id
                break
    func = functions.get(target_name)
    if func is not None:
        return target_name, "".join(lines[func.lineno - 1 : func.end_lineno])
    return None


def invoke_bound_owner(
    *,
    evidence_factory: OwnerEvidenceFactory[Evidence],
    executor: Callable[..., object],
    owner: Callable[..., object],
    scenario_seam_active: bool,
    operation: Callable[[], T],
    expected_owner_entries: int = 1,
) -> tuple[T, Evidence, tuple[dict[str, object], ...]]:
    """Invoke an operation while tracing the exact owner code object."""

    owner_code = getattr(owner, "__code__", None)
    executor_code = getattr(executor, "__code__", None)
    if owner_code is None or executor_code is None:
        raise OwnerBindingError("owner or executor has no Python code object")
    entries: list[dict[str, object]] = []
    prior = sys.getprofile()

    def profile(frame, event, _arg):
        if event != "call" or frame.f_code is not owner_code:
            return
        caller = frame.f_back
        while caller is not None and caller.f_code is not executor_code:
            caller = caller.f_back
        if caller is None:
            return
        entries.append(dict(frame.f_locals))
        if len(entries) >= expected_owner_entries:
            sys.setprofile(prior)

    sys.setprofile(profile)
    try:
        result = operation()
    finally:
        sys.setprofile(prior)
    if not entries:
        raise OwnerBindingError("registered owner code object was not entered by executor")
    source_path = Path(inspect.getsourcefile(owner) or "").resolve()
    evidence = evidence_factory(
        module_source_digest=_digest_bytes(source_path.read_bytes()),
        qualified_symbol=f"{owner.__module__}.{owner.__qualname__}",
        code_object_identity=code_object_identity(owner_code),
        executor_source_digest=callable_source_digest(executor),
        owner_entry_count=len(entries),
        scenario_seam_active=scenario_seam_active,
        owner_source_path=str(
            source_path.relative_to(Path(__file__).resolve().parents[5])
        ),
        owner_module=owner.__module__,
        executor_source_path=str(
            Path(inspect.getsourcefile(executor) or "")
            .resolve()
            .relative_to(Path(__file__).resolve().parents[5])
        ),
        executor_module=executor.__module__,
        executor_qualified_symbol=f"{executor.__module__}.{executor.__qualname__}",
        owner_entry_during_operation=True,
    )
    return result, evidence, tuple(entries)
