"""CLI compatibility facade and package namespace."""

from importlib import import_module
from typing import Any

_impl = import_module("repomap_kg.cli.main")

_MODULE_DUNDER_NAMES = {
    "__builtins__",
    "__cached__",
    "__dir__",
    "__doc__",
    "__file__",
    "__getattr__",
    "__loader__",
    "__name__",
    "__package__",
    "__spec__",
}

# Copy the realized names only: ``dir(_impl)`` would list, and ``getattr``
# would import, the deferred PostgreSQL-implementation names.
globals().update(
    {name: value for name, value in vars(_impl).items() if name not in _MODULE_DUNDER_NAMES}
)


def __getattr__(name: str) -> Any:
    # Deferred PostgreSQL-implementation names, resolved on each access. Only
    # names without a module global reach here: an assigned global (including
    # a restored monkeypatch value) shadows this until it is deleted.
    if name in _impl.POSTGRES_FACADE_NAMES:
        return getattr(_impl, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _impl.POSTGRES_FACADE_NAMES)


# Keep the entry-point callable explicit for static consumers; the assignment
# preserves identity with ``repomap_kg.cli.main.main`` and the facade exports.
from repomap_kg.cli.main import main as main
