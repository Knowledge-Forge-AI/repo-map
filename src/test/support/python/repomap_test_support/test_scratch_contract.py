"""Shared scratch authority constants and refusal type."""

from pathlib import Path

ENV_SCRATCH_ROOT = "REPOMAP_TEST_SCRATCH_ROOT"
ENV_RUN_ROOT = "REPOMAP_TEST_RUN_ROOT"
ENV_PROJECT = "REPOMAP_TEST_PROJECT"
ENV_PHASE = "REPOMAP_TEST_PHASE"

DEFAULT_PROJECT = "repo-map_dev"
DEFAULT_PHASE = "local"

DARWIN_SHARED_ROOT = Path("/Users/Shared/agent-scratch")
PORTABLE_ROOT_NAME = "repomap-test-scratch"

# macOS sockaddr_un.sun_path holds 104 bytes including the NUL terminator, so a
# conservative usable maximum is 103 encoded bytes.
MAX_SOCKET_PATH_BYTES = 103

MANIFEST_SCHEMA = "repomap-test-scratch-manifest-v1"
_TERMINAL_STATES = ("passed", "failed", "stopped")


class TestScratchError(RuntimeError):
    """Raised when the scratch authority cannot be established safely."""

    # Not a test class; the name only begins with "Test" because it belongs to
    # the test-scratch authority.
    __test__ = False


