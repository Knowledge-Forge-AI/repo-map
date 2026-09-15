"""Test-owned synthetic worker modes."""

ALLOWED_SYNTHETIC_WORKER_MODES = frozenset(
    {
        "success",
        "delay",
        "transient_failure",
        "permanent_failure",
        "cooperative_cancellation",
        "non_cooperative_cancellation",
        "pre_publication_crash",
        "transaction_crash",
        "transaction_rollback",
        "transaction_commit",
        "before_commit_connection_loss",
        "after_commit_connection_loss",
        "conflicting_marker",
        "malformed_hello",
        "malformed_json",
        "oversized_line",
        "out_of_order_message",
        "duplicate_terminal",
        "heartbeat_loss",
        "stderr_flood",
    }
)
