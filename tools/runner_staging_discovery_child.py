"""Fixed child entrypoint: collect test identities without executing bodies."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import sys

# -I prevents inherited PYTHONPATH/user-site bootstrap before request validation.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv: list[str] | None = None) -> int:
    from runner_staging_discovery_contract import (
        DISCOVERY_RECEIPT_SCHEMA, digest, read_document, validate_request, write_document,
    )

    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        return 2
    request_path, receipt_path = map(Path, arguments)
    request = read_document(request_path)
    validate_request(request)
    # The installed interpreter/macOS runtime can inject these two startup
    # fields; they are not test inputs or measurement bootstrap authority.
    actual_environment = {key: value for key, value in os.environ.items()
                          if key not in {"PYTHONNOUSERSITE", "__CF_USER_TEXT_ENCODING"}}
    if Path.cwd() != Path(request["cwd"]) or actual_environment != request["environment"]:
        return 2
    sys.path[:] = request["python_paths"]
    from runner_integration_obligations import MAINTAINED_ABRUPT_DECLARATIONS
    # The declaration bytes bind source even though partitioning occurs only
    # after the parent validates this child's ordered collection result.
    if request["declarations"] != [asdict(item) for item in MAINTAINED_ABRUPT_DECLARATIONS]:
        return 2
    import pytest
    from runner_integration_population import ItemCollectorPlugin

    collector = ItemCollectorPlugin(suite=request["suite"], full_population=not request["scoped"])
    error_name = None
    try:
        code = int(pytest.main(["--collect-only", "-q", *request["pytest_args"]], plugins=[collector]))
    except BaseException as error:
        code, error_name = 2, type(error).__name__
    receipt = {
        "schema": DISCOVERY_RECEIPT_SCHEMA, "request_sha256": digest(request),
        "exit_code": code, "error": error_name,
        "collected": list(collector.collected_nodeids),
        "eligible": list(collector.eligible_nodeids), "deferred": list(collector.deferred_nodeids),
    }
    receipt["sha256"] = digest(receipt)
    write_document(receipt_path, receipt)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
