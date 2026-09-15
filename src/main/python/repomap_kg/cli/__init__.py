"""CLI compatibility facade and package namespace."""

from importlib import import_module

_impl = import_module("repomap_kg.cli.main")

_MODULE_DUNDER_NAMES = {
    "__builtins__",
    "__cached__",
    "__doc__",
    "__file__",
    "__loader__",
    "__name__",
    "__package__",
    "__spec__",
}

globals().update(
    {name: getattr(_impl, name) for name in dir(_impl) if name not in _MODULE_DUNDER_NAMES}
)

# Keep the entry-point callable explicit for static consumers; the assignment
# preserves identity with ``repomap_kg.cli.main.main`` and the facade exports.
from repomap_kg.cli.main import main as main
