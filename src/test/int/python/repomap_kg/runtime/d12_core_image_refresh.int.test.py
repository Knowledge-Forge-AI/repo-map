"""ADR 0087 D12-A candidate round trip on the actual release recipe (ADR 0089, ADR 0091)."""

from __future__ import annotations

import re
import secrets
import subprocess
import uuid
from pathlib import Path
import pytest
from common_lore_index.runtime.release import (
    GO_RELEASE_IMAGE,
    POSTGRES_RELEASE_IMAGE,
    PSYCOPG_LIBPQ_VERSION,
    PYTHON_RELEASE_IMAGE,
)
from repomap_test_support import d12_core_image as d12
from repomap_test_support.d12_core_image_cleanup import run_candidate_cleanup
from repomap_test_support.d12_image_probes import (
    ADVISORIES as _EXTRACTED_ADVISORIES,
    CLIENTS as _EXTRACTED_CLIENTS,
    FIXED_IN as _EXTRACTED_FIXED_IN,
    HASH_SH as _EXTRACTED_HASH_SH,
    INVENTORY_SH as _EXTRACTED_INVENTORY_SH,
    LIBPQ_ADVISORY as _EXTRACTED_LIBPQ_ADVISORY,
    LIBPQ_FIXED as _EXTRACTED_LIBPQ_FIXED,
    NOTICES as _EXTRACTED_NOTICES,
    PACKAGING_PY as _EXTRACTED_PACKAGING_PY,
    ROUND_TRIP_PY as _EXTRACTED_ROUND_TRIP_PY,
    SERVER as _EXTRACTED_SERVER,
    _classify as _extracted_classify,
    _create as _extracted_create,
    _hashes as _extracted_hashes,
    _inventory as _extracted_inventory,
    _libpq_findings as _extracted_libpq_findings,
    _run_once as _extracted_run_once,
    _start_server as _extracted_start_server,
    _tmpfs as _extracted_tmpfs,
    _version as _extracted_version,
)
from repomap_test_support.resource_docker import ownership_labels
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.test_scratch import establish_run

pytestmark = pytest.mark.requires_d12_core_image_profile
REPO_ROOT = Path(__file__).resolve().parents[6]
SERVER = _EXTRACTED_SERVER
CLIENTS = _EXTRACTED_CLIENTS
ADVISORIES = _EXTRACTED_ADVISORIES
FIXED_IN = _EXTRACTED_FIXED_IN
LIBPQ_ADVISORY, LIBPQ_FIXED = _EXTRACTED_LIBPQ_ADVISORY, _EXTRACTED_LIBPQ_FIXED
NOTICES = _EXTRACTED_NOTICES
INVENTORY_SH = _EXTRACTED_INVENTORY_SH
HASH_SH = _EXTRACTED_HASH_SH
PACKAGING_PY = _EXTRACTED_PACKAGING_PY
ROUND_TRIP_PY = _EXTRACTED_ROUND_TRIP_PY

_tmpfs = _extracted_tmpfs
_create = _extracted_create
_run_once = _extracted_run_once
_start_server = _extracted_start_server
_hashes = _extracted_hashes
_inventory = _extracted_inventory
_version = _extracted_version
_classify = _extracted_classify
_libpq_findings = _extracted_libpq_findings


def _build_authority(admission: d12.D12Admission | None) -> d12.D12Admission:
    if admission is None or admission is not d12.current_admission():  # the accessor refuses throughout E1
        raise d12.D12ProfileError("build refused: admission is not the current build admission")
    return admission


def test_d12_core_image_refresh_candidate_round_trip() -> None:
    import d12_dependency_preflight as inner  # ADR 0089 D9 E1 support, from the canonical runner's tools path
    from tools.system.d12_system_evidence import observe_and_assess_candidate

    exploration = inner.current_exploration()
    admission: d12.D12Admission | None = None  # build authority only; stays None throughout E1
    if exploration is None:
        frozen = admission = d12.current_admission()
    elif d12._ADMISSION is not None:
        raise d12.D12ProfileError("mixed build and exploration admission")
    else:
        frozen = exploration  # E1 platform, source, recipe, context and report binding; never build authority
    boundary = d12.locate_run_boundary()
    run = active_resource_run()
    assert run is not None, "the admitted D12 owner requires the canonical resource run"
    client = boundary.client
    platform = frozen.platform
    inspected = subprocess.run(["docker", "buildx", "inspect"], capture_output=True, text=True, check=False)
    builder = inspected.stdout
    availability = d12.platform_availability(platform, client.info().get("Architecture", ""),
                                             d12.offered_platforms(builder))
    bases = d12.verify_bases(client, platform, (POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE, GO_RELEASE_IMAGE))
    server_image_id = bases[POSTGRES_RELEASE_IMAGE]["id"]
    assert isinstance(server_image_id, str)
    scratch = establish_run().tmp / f"d12-{uuid.uuid4().hex[:12]}"
    context = d12.stage_context(REPO_ROOT, scratch / "context", frozen)
    dockerfile = scratch / "Dockerfile"
    dockerfile.write_text(d12.recipe_text(), encoding="utf-8")
    run_tag = re.sub(r"[^a-z0-9_.-]", "-", run.ledger.identity.run_id.lower())[:24]
    tag = f"repomap-d12-core-candidate:{run_tag}-{platform.split('/')[1]}"
    assert not d12.image_present(client, tag), "stale candidate tag exists before the build"
    labels = {**ownership_labels(run.ledger.identity, role="d12-core-candidate", retained=False),
              d12.CANDIDATE_LABEL: "true", "org.repomap.d12.platform": platform,
              "org.repomap.d12.source_sha256": frozen.source_sha256,
              "org.repomap.d12.recipe_sha256": frozen.recipe_sha256}
    d12.write_report("freeze", {"admission": vars(frozen), "availability": availability, "bases": bases,
                                "tag": tag, "labels": labels, "budget": boundary.projection()})
    owner = CurrentRunDockerContainers(run, client)
    image_id, server_id, primary = None, None, None
    try:
        # Everything that needs no candidate runs first, so its defects cannot spend the build.
        server_env = {"POSTGRES_USER": "d12", "POSTGRES_DB": "d12", "POSTGRES_PASSWORD": secrets.token_hex(16)}
        server_id, server_container = _start_server(owner, client, server_env, platform)
        assert server_container.attrs["Image"] == server_image_id
        server_side = {
            p: server_container.exec_run([p, "--version"]).output.decode().strip() for p in (SERVER, *CLIENTS)}
        server_inventory = _inventory(
            owner, client, server_image_id, platform, "d12-inventory-server")
        _hashes(owner, client, PYTHON_RELEASE_IMAGE, ["/usr/local/bin/python3"], platform, "d12-hash-preflight")
        if exploration is not None:  # E1: observe and report, then return before the build; custody still runs
            b_map = {"run_id": run.ledger.identity.run_id, "sdk_image": "unobserved in the sandbox"}
            steps = inner.explore(
                owner, client, exploration, bases=bases, availability=availability, inspected=inspected,
                server_inventory=server_inventory, create=_create, bindings=b_map)["steps"]
            api, library = steps["libpq_runtime"]["api"], steps["libpq_runtime"]["library"]
            srv_libs = {(f["resolved"], f["sha256"]) for f in server_inventory["files"]
                        if f["role"] == "libpq" and f["owner"] == "libpq5"}
            assert srv_libs == {(library["path"], library["sha256"])} and api == steps["candidate"]["libpq_version"]
            srv_vers = [tuple(map(int, m)) for r in server_inventory["packages"]
                        if r[0] == "libpq5" for m in re.findall(r"^(\d+)\.(\d+)", r[1])]
            assert [divmod(api, 10000)] == srv_vers, (api, server_inventory["packages"])
            return
        image_id, log = d12.build_candidate(boundary=boundary, admission=_build_authority(admission),
                                            context=context, dockerfile=dockerfile, tag=tag, labels=labels)
        run.ledger.register(ResourceKind.DOCKER_IMAGE, image_id, creation_owner="d12-core-image-owner",
                            created_before_run=False, creation_observed=True, cleanup_required=True)
        attrs = client.images.get(image_id).attrs
        d12.write_report("build", {"image_id": image_id, "os": attrs["Os"], "architecture": attrs["Architecture"],
                                   "labels": attrs["Config"]["Labels"], "log_tail": log})
        assert f"{attrs['Os']}/{attrs['Architecture']}" == platform
        assert {k: attrs["Config"]["Labels"].get(k) for k in labels} == labels
        assert attrs["Config"]["Entrypoint"] == ["python", "-m", "common_lore_index"]
        observe_and_assess_candidate(
            owner, client, image_id=image_id, platform=platform, server_id=server_id,
            server_env=server_env, server_side=server_side, server_inventory=server_inventory,
            availability=availability, expected_libpq_version=PSYCOPG_LIBPQ_VERSION,
            tls_header=inner.HEADER, write_report=d12.write_report,
            server_image_id=server_image_id,
            run_once_fn=_run_once, inventory_fn=_inventory, hashes_fn=_hashes,
        )
    except BaseException as error:
        primary = error
        raise
    finally:
        def custody(cleanup):
            cleanup["candidate_image_id"] = image_id
            if server_id is not None:
                owner.cleanup(server_id)
                cleanup["server"] = "removed"
            owner.verify_baseline()
            cleanup["containers"] = "baseline_verified"
            if image_id is not None:
                cleanup["image"] = d12.remove_candidate_image(client, run.ledger, image_id, tag)
            elif d12.image_present(client, tag):
                # Exact custody evidence for the operator; an unledgered image is never removed here.
                cleanup["unledgered_tag_image_id"] = client.images.get(tag).id
                raise d12.D12ProfileError(f"candidate tag {tag} has no exact ledgered image ID; left for operator")
            budget = cleanup["budget"] = boundary.projection()
            if exploration is not None:  # E1 builds and pulls nothing: all four counts must be zero
                cleanup["zero_build"] = inner.require_zero_builds(budget)
                return
            counts = [budget[k] for k in ("managed_system_candidate_image_build_count",
                      "product_or_build_profile_build_count", "unmanaged_build_count", "unmanaged_pull_count")]
            assert counts[1:] == [0, 0, 0] and counts[0] <= 1 and (primary is not None or counts[0] == 1), budget

        run_candidate_cleanup(primary, custody, d12.write_report)
