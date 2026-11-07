"""Fixed child entrypoint: collect test identities without executing bodies."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import sys
from typing import Any

# -I prevents inherited PYTHONPATH/user-site bootstrap before request validation.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _retain_error(record: dict[str, Any], receipt_path: Path) -> None:
    from runner_failure_evidence import CHILD_SCHEMA, error_record, persist_diagnostic, print_diagnostic
    try:
        persist_diagnostic(receipt_path.with_name("child_error.json"), {"schema": CHILD_SCHEMA, "error": record})
    except Exception as persistence_error:
        print_diagnostic(error_record(persistence_error, "diagnostic_persistence"), primary=False)


def _collect(request_path: Path, receipt_path: Path) -> int:
    from runner_staging_discovery_contract import (
        DISCOVERY_RECEIPT_SCHEMA, digest, read_document, validate_request, write_document,
    )

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

    from repomap_test_support.d12_core_image import POPULATION_ATTR

    class OptionalPopulation:
        """Rebase the conftest's optional-owner record onto the collector-visible population.

        The root conftest records indices over pytest's whole collection, but profile plugins
        (pgvector) deselect visibly before the collector records ``collected``. The persisted
        record therefore indexes the collector's population plus the optional exclusions.
        """
        record = None
        whole: list[str] = []

        @pytest.hookimpl(hookwrapper=True)
        def pytest_collection_modifyitems(self, session, config, items):
            self.whole = [item.nodeid for item in items]
            yield

        def pytest_collection_finish(self, session) -> None:
            record = getattr(session.config, POPULATION_ATTR, None)
            if record is None:
                return
            excluded = {entry["nodeid"] for entry in record["excluded"]}
            visible = excluded | set(collector.collected_nodeids)
            raw = [nodeid for nodeid in self.whole if nodeid in visible]
            if [nodeid for nodeid in raw if nodeid not in excluded] != list(collector.collected_nodeids):
                raise RuntimeError("optional-owner exclusion does not rebase onto the collected population")
            self.record = {**record, "raw_count": len(raw), "excluded": [
                {"nodeid": nodeid, "raw_index": index} for index, nodeid in enumerate(raw) if nodeid in excluded]}

    collector = ItemCollectorPlugin(suite=request["suite"], full_population=not request["scoped"])
    optional = OptionalPopulation()
    error_name = None
    try:
        code = int(pytest.main(["--collect-only", "-q", *request["pytest_args"]],
                               plugins=[collector, optional]))
    except BaseException as error:
        from runner_failure_evidence import error_record
        record = error_record(error, "child_collection")
        _retain_error(record, receipt_path)
        code, error_name = 2, record["type"]
    receipt = {
        "schema": DISCOVERY_RECEIPT_SCHEMA, "request_sha256": digest(request),
        "exit_code": code, "error": error_name,
        "collected": list(collector.collected_nodeids),
        "eligible": list(collector.eligible_nodeids), "deferred": list(collector.deferred_nodeids),
        "optional": optional.record,
    }
    receipt["sha256"] = digest(receipt)
    write_document(receipt_path, receipt)
    return code


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        return 2
    request_path, receipt_path = map(Path, arguments)
    try:
        return _collect(request_path, receipt_path)
    except BaseException as error:
        # Normal startup validates the request before importing the diagnostic helper.
        from runner_failure_evidence import error_record
        _retain_error(error_record(error, "child_startup"), receipt_path)
        if not isinstance(error, Exception):
            raise
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
