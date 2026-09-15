"""Closed shared layout vocabulary for the private advisory index."""

ALLOWED_PROJECT_INDEX_ENTRIES = frozenset(
    {
        "admission.lock",
        "bootstrap.json",
        "inventory.json",
        "recovery",
        "runs",
        "summary.json",
    }
)

__all__ = ["ALLOWED_PROJECT_INDEX_ENTRIES"]
