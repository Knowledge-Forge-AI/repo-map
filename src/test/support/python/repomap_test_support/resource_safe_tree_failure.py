"""Closed exceptional-progress contract for descriptor-relative deletion."""

from __future__ import annotations

from repomap_test_support.resource_validation import nonnegative_int


SAFE_TREE_FAILURE_CATEGORIES = frozenset(
    {
        "callback_error",
        "cross_device_refused",
        "directory_list_error",
        "durability_error",
        "entry_open_error",
        "entry_stat_error",
        "identity_changed",
        "interrupted",
        "post_delete_verification_error",
        "rmdir_error",
        "unexpected_safe_tree_error",
        "unlink_error",
        "unsupported_kind",
    }
)


class SafeTreeDeleteError(RuntimeError):
    """The exact tree cannot be deleted without path escape risk."""


class SafeTreeDeleteUnavailable(SafeTreeDeleteError):
    """The host lacks the required descriptor and no-follow operations."""


class SafeTreeDeleteFailure(SafeTreeDeleteError):
    """A catchable delete failure with exact already-removed progress."""

    def __init__(
        self,
        *,
        removed_allocated_bytes: int,
        removed_inode_count: int,
        failure_category: str,
    ) -> None:
        if failure_category not in SAFE_TREE_FAILURE_CATEGORIES:
            raise ValueError("safe-tree failure category is invalid")
        self.removed_allocated_bytes = nonnegative_int(
            removed_allocated_bytes, "removed allocated bytes"
        )
        self.removed_inode_count = nonnegative_int(
            removed_inode_count, "removed inode count"
        )
        self.failure_category = failure_category
        super().__init__(failure_category)


__all__ = [
    "SAFE_TREE_FAILURE_CATEGORIES",
    "SafeTreeDeleteError",
    "SafeTreeDeleteFailure",
    "SafeTreeDeleteUnavailable",
]
