"""ADR 0089 D2/D6 probe of the dependency-only Python 3.12 runtime image.

The repository-owned ``TestImageManager`` materializes its canonical
dependency-only image (a managed, non-ledger test-runtime cache, never a D12
candidate build). That image builds psycopg-c 3.3.6 from the hash-bound sdist
against the base distribution's ``libpq-dev`` and keeps only its ``libpq5``.
One network-less probe container then runs this repository's stdlib probe with
``PSYCOPG_IMPL`` unset. Passing proves the C implementation, header/runtime
equality, ``DT_NEEDED`` dynamic linkage and the single loaded, verified,
``dpkg``-owned libpq of this test image only; it is not release-image or
assembled-product evidence, whose libpq owner is the PostgreSQL base.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from repomap_kg.runtime.release import (
    PSYCOPG_RELEASE_VERSION,
    RELEASE_FINAL_PACKAGE_CHECK_PY,
    RELEASE_PROBE_HELPERS_PY,
)
from repomap_test_support import d12_core_image as d12
from repomap_test_support import d12_dynamic_linkage as linkage
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.resource_test_images import ensure_canonical_runtime_image

REPO_ROOT = Path(__file__).resolve().parents[6]
VERSIONS = "REPOMAP_DEPENDENCY_VERSIONS="
CUSTODY = "REPOMAP_APT_PREREQUISITES="


def _materialized_versions(run_root: Path, prefix: str = VERSIONS) -> dict[str, object] | None:
    """One materializer result line from this run's retained runtime evidence, if it built."""
    def strings(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    for path in sorted(run_root.glob("test-runtime-*.evidence.json")):
        for text in strings(json.loads(path.read_text(encoding="utf-8"))):
            for line in text.splitlines():
                if line.startswith(prefix):
                    return dict(json.loads(line.removeprefix(prefix)))
    return None


def test_dependency_only_runtime_links_system_libpq_dynamically() -> None:
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "the dependency-only probe requires the canonical resource run"
    client = boundary.client
    image_id = ensure_canonical_runtime_image(
        repo_root=REPO_ROOT, resource_run=run, client=client, boundary=boundary
    )
    owner = CurrentRunDockerContainers(run, client)
    identity = owner.create(
        image_id,
        ["-I", "-c", linkage.probe_source(), "probe"],
        role="d12-dynamic-linkage-probe",
        entrypoint=["python"],
        network_mode="none",
    )
    try:
        container = client.containers.get(identity)
        container.start()
        status = container.wait(timeout=300).get("StatusCode", 1)
        output = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        errors = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(identity)
    owner.verify_baseline()
    assert status == 0, f"linkage probe failed with {status}: {errors[-4000:]}"
    report = json.loads(output.splitlines()[-1])
    print("D12_DYNAMIC_LINKAGE=" + json.dumps(report, sort_keys=True))
    failures = linkage.assess(report, psycopg_version=PSYCOPG_RELEASE_VERSION)
    assert not failures, failures
    versions = _materialized_versions(Path(run.layout.run_root))
    print(VERSIONS + json.dumps(versions, sort_keys=True))
    if versions is not None:  # built in this run: build-time and loaded facts must agree
        assert versions["implementation"] == "c" and versions["libpq"] == report["libpq_runtime"], versions
        assert versions["libpq5"] == versions["libpq_dev"] == report["loaded_libpq"][0]["owner_version"], versions
        # ADR 0089: native prerequisites came only from the frozen, hash-bound manifest.
        custody = _materialized_versions(Path(run.layout.run_root), CUSTODY)
        assert custody is not None and custody["manifest_sha256"] == versions["apt_manifest_sha256"], custody
        added, executable = custody["added"], versions["pg_config_executable"]
        assert isinstance(added, list) and isinstance(executable, dict), (custody, versions)
        assert any(str(item).startswith("libpq5:") and str(item).endswith(f"={versions['libpq5']}") for item in added)
        assert versions["owners"] == {"pg_config": executable["package"], "libpq-fe.h": "libpq-dev",
                                      "libpq.so.5": "libpq5"}, versions
    loaded = report["loaded_libpq"][0]
    assert loaded["real_path"].startswith("/usr/lib/"), loaded
    assert {Path(item["path"]).name.split(".")[0] for item in report["extensions"]} >= {"_psycopg", "pq"}
    # ADR 0096 Decision 3: execute the shared final package classifier against the connected
    # dependency-only runtime image (observing its own container files) and exported SDK package
    # names under an explicitly unqualified root (proving compiler-name refusal only, not SDK
    # payload qualification). Positive native amd64 qualification of gcc-14-base on the assembled
    # PostgreSQL image remains hosted-only; arm64 runtime or compiler/dev names refuse without skip.
    assert Path("/usr/bin/dpkg-query").is_file()
    sdk_rows = [
        line.split("\t")
        for line in subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}\t${db:Status-Abbrev}\n"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    ]
    sdk_package_names = [name for name, st in sdk_rows if st.startswith("ii")]
    pkg_script = (
        RELEASE_PROBE_HELPERS_PY
        + RELEASE_FINAL_PACKAGE_CHECK_PY
        + "import json\n"
        "arch = run('dpkg', '--print-architecture')[1]\n"
        "q = run('dpkg-query', '-W', '-f=${Package}\\t${db:Status-Abbrev}\\n')[1].splitlines()\n"
        "pkgs = [r.split('\\t')[0] for r in q if r.split('\\t')[1].startswith('ii')]\n"
        f"sdk_package_names = {sdk_package_names!r}\n"
        "print(json.dumps({'arch': arch, 'runtime_live': forbidden_packages(pkgs), "
        "'unqualified': forbidden_packages(pkgs, root='/nonexistent'), "
        "'with_tooling': forbidden_packages([*pkgs, 'gcc', 'binutils', 'cpp', 'libpq-dev']), "
        "'sdk_compiler_names_refused': forbidden_packages(sdk_package_names, root='/nonexistent')}))\n"
    )
    pkg_cid = owner.create(
        image_id,
        ["-I", "-c", pkg_script],
        role="d12-dynamic-linkage-pkg-probe",
        entrypoint=["python"],
        network_mode="none",
    )
    try:
        pkg_container = client.containers.get(pkg_cid)
        pkg_container.start()
        pkg_status = pkg_container.wait(timeout=120).get("StatusCode", 1)
        pkg_stdout = pkg_container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        pkg_stderr = pkg_container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(pkg_cid)
    owner.verify_baseline()
    assert pkg_status == 0, f"package classifier probe failed with {pkg_status}: {pkg_stderr[-2000:]}"
    pkg_report = json.loads(pkg_stdout.splitlines()[-1])
    print("D12_PACKAGE_CLASSIFIER=" + json.dumps(pkg_report, sort_keys=True))
    assert isinstance(pkg_report["runtime_live"], list)
    assert {"gcc", "binutils", "cpp", "libpq-dev"} <= set(pkg_report["with_tooling"])
    assert {"gcc", "binutils", "cpp", "libpq-dev"} <= set(pkg_report["sdk_compiler_names_refused"])
    assert "gcc-14-base" in pkg_report["unqualified"]
    if pkg_report["arch"] != "amd64":
        assert pkg_report["runtime_live"] == ["gcc-14-base"]
