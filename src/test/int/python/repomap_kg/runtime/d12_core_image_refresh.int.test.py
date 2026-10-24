"""ADR 0087 D12-A candidate round trip on the actual release recipe (ADR 0089, ADR 0091)."""

from __future__ import annotations

import json, re, secrets, subprocess, time, uuid
from pathlib import Path
import pytest
from repomap_kg.runtime.release import (
    GO_RELEASE_IMAGE, PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE, PACKAGED_PSQL, POSTGRES_RELEASE_IMAGE,
    POSTGRES_RELEASE_VERSION, PSYCOPG_LIBPQ_VERSION, PSYCOPG_RELEASE_VERSION, PYTHON_RELEASE_IMAGE,
    PYTHON_RELEASE_VERSION)
from repomap_test_support import d12_core_image as d12, d12_dynamic_linkage as linkage
from repomap_test_support.d12_core_image_cleanup import run_candidate_cleanup
from repomap_test_support.resource_docker import ownership_labels
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_ledger import ResourceKind
from repomap_test_support.resource_run import active_resource_run
from repomap_test_support.test_scratch import establish_run

pytestmark = pytest.mark.requires_d12_core_image_profile
REPO_ROOT = Path(__file__).resolve().parents[6]
SERVER = "/usr/lib/postgresql/16/bin/postgres"
CLIENTS = (PACKAGED_PSQL, PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE, "/usr/bin/pg_isready")
ADVISORIES = {"CVE-2026-16239": SERVER, "CVE-2026-19385": PACKAGED_PG_DUMP}
FIXED_IN = (16, 15)
LIBPQ_ADVISORY, LIBPQ_FIXED = "CVE-2026-6477", {16: 14, 17: 10, 18: 4}
NOTICES = (
    "/usr/share/doc/postgresql-16/copyright", "/usr/share/doc/postgresql-client-16/copyright",
    "/usr/share/doc/libpq5/copyright", "/usr/share/doc/postgresql-common/copyright",
    "/usr/share/doc/libssl3t64/copyright", "/usr/share/doc/libc6/copyright",  # ADR 0091 TLS and glibc notices
    "/usr/share/doc/repomap-kg/go/LICENSE", "/usr/share/doc/repomap-kg/go/PATENTS",
    "/usr/local/lib/python3.12/LICENSE.txt", "/usr/share/doc/repomap-kg/psycopg/psycopg-source.json",
    "/usr/share/doc/repomap-kg/psycopg/psycopg-LICENSE.txt", "/usr/share/doc/repomap-kg/psycopg/GPL-3.0.txt")
INVENTORY_SH = r"""
set -u
probe() { r=$(readlink -f "$2" 2>/dev/null || true)
  if [ -z "$r" ] || [ ! -f "$r" ]; then printf 'F\t%s\t%s\t-\tmissing\t-\t-\t-\t-\n' "$1" "$2"; return; fi
  magic=$(head -c 4 "$r" | od -An -tx1 | tr -d ' \n'); interp=-
  case "$magic" in
    7f454c46) kind=elf;;
    2321*) kind=script; interp=$(head -n1 "$r" | cut -c3- | cut -d' ' -f1);;
    *) kind=other;;
  esac
  owner=$(dpkg -S "$r" 2>/dev/null | head -n1 | cut -d: -f1)
  [ -n "$owner" ] || owner=$(dpkg -S "/${r#/usr/}" 2>/dev/null | head -n1 | cut -d: -f1)
  md5=-; if [ -n "$owner" ]; then
    sums=$(ls /var/lib/dpkg/info/"$owner".md5sums /var/lib/dpkg/info/"$owner":*.md5sums 2>/dev/null | head -n1)
    want=$(grep -E "  (${r#/}|${r#/usr/})\$" "$sums" 2>/dev/null | head -n1 | cut -d' ' -f1)
    have=$(md5sum "$r" | cut -d' ' -f1)
    if [ -z "$want" ]; then md5=unlisted; elif [ "$want" = "$have" ]; then md5=match; else md5=mismatch; fi
  else owner=-; fi
  sha=$(sha256sum "$r" | cut -d' ' -f1)
  printf 'F\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$r" "$kind" "$sha" "$interp" "$owner" "$md5"
  if [ "$kind" = elf ]; then ldd "$r" 2>&1 | awk -v p="$2" \
    '/=>/ {print "L\t" p "\t" $1 "\t" $3; next} $1 ~ /^\// {print "L\t" p "\t" $1 "\t" $1}'; fi
  if [ "$kind" = script ] && [ "$1" != interpreter ]; then probe interpreter "$interp"; fi; }
for p in "$@"; do probe invoked "$p"; done > /tmp/inv
grep '^L' /tmp/inv | cut -f4 | grep '^/' | sort -u | while read -r lib; do probe library "$lib"; done >> /tmp/inv
if grep -q 'perl' /tmp/inv; then perl -e 'require PgCommon; print "$_\n" for sort values %INC' 2>/dev/null \
  | while read -r m; do probe module "$m"; done >> /tmp/inv; fi
find / -xdev -name 'libpq*.so*' 2>/dev/null | sort | while read -r f; do probe libpq "$f"; done >> /tmp/inv
cat /tmp/inv
dpkg-query -W -f='P\t${Package}\t${Version}\t${Architecture}\n'
dpkg --verify 2>/dev/null > /tmp/verify; printf 'VC\t%s\n' "$(wc -l < /tmp/verify)"
head -n 1500 /tmp/verify | awk '{print "V\t" $1 "\t" $NF}'
cat /var/lib/dpkg/info/*.list 2>/dev/null | sed 's#^/lib/#/usr/lib/#' | sort -u > /tmp/owned
find /usr/lib -xdev \( -type f -o -type l \) 2>/dev/null | sort -u | comm -23 - /tmp/owned > /tmp/unowned
printf 'UC\t%s\n' "$(wc -l < /tmp/unowned)"; head -n 1500 /tmp/unowned | sed 's/^/U\t/'
for f in $NOTICES; do
  if [ -s "$f" ]; then printf 'C\t%s\t%s\n' "$f" "$(sha256sum "$f" | cut -d' ' -f1)"
  else printf 'C\t%s\tabsent\n' "$f"; fi
done
. /etc/os-release; printf 'O\t%s\t%s\t%s\n' "$PRETTY_NAME" "$(uname -m)" "$(dpkg --print-architecture)"
"""
HASH_SH = (
    r'for f in "$@"; do if [ -f "$f" ]; then '
    r'printf "H\t%s\t%s\n" "$f" "$(sha256sum "$f" | cut -d" " -f1)"; '
    r'else printf "H\t%s\t-\n" "$f"; fi; done')
PACKAGING_PY = r"""
import hashlib, importlib.metadata as md, importlib.util as iu, json, os, pathlib, platform, re, shutil, subprocess
import psycopg
from psycopg import pq
from repomap_kg.storage import discover_migrations
from repomap_kg.coordinator._control_schema import discover_control_migrations
from repomap_kg.extractors.languages.go_helper import resolve_go_helper_command
run = lambda *c: subprocess.run(list(c), capture_output=True, text=True, check=False)
paths = json.loads(os.environ["D12_PATHS"]) + [w for w in map(shutil.which, ("psql", "pg_dump", "pg_restore")) if w]
root = pathlib.Path(psycopg.__file__).parent.parent
# Libraries only (ADR 0089 D2): psycopg-c installs its Cython declaration psycopg_c/pq/libpq.pxd.
libs = sorted(p for p in root.rglob("*") if re.search(os.environ["D12_LIBRARY_FILE"], p.name))
helper = resolve_go_helper_command()[0]
print(json.dumps({"versions": {p: run(p, "--version").stdout.strip() for p in paths},
  "python": platform.python_version(), "psycopg": psycopg.__version__, "libpq": pq.version(),
  "implementation": pq.__impl__, "libpq_build": pq.__build_version__,
  "has_cancel_safe": psycopg.capabilities.has_cancel_safe(),
  "bundled_libpq": [
      {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in libs if p.is_file()],
  "pip_absent": iu.find_spec("pip") is None, "setuptools_absent": iu.find_spec("setuptools") is None,
  "ensurepip_absent": not pathlib.Path("/usr/local/lib/python3.12/ensurepip").exists(),
  "go_absent": shutil.which("go") is None,
  "migrations": [len(discover_migrations()), len(discover_control_migrations())],
  "go_helper": helper, "go_helper_protocol": run(helper, "--protocol-version").stdout.strip(),
  "distributions": sorted({
      (d.metadata["Name"], d.version, d.metadata.get("License-Expression") or d.metadata.get("License") or "")
      for d in md.distributions()})}))
"""
ROUND_TRIP_PY = r"""
import hashlib, json, os, subprocess
import psycopg
from repomap_kg.storage import apply_migrations, graph_schema_readiness
env_keys = ("REPOMAP_PACKAGED_PSQL", "REPOMAP_PACKAGED_PG_DUMP", "REPOMAP_PACKAGED_PG_RESTORE")
psql, dump, restore = (os.environ[k] for k in env_keys)
base = ["-h", "127.0.0.1", "-p", "5432", "-U", os.environ["PGUSER"]]
def sql(db, text):
    cmd = [psql, *base, "-d", db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]
    return subprocess.run(cmd, input=text, capture_output=True, text=True, check=True).stdout
for db in ("d12_source", "d12_restore"):
    sql(os.environ["PGDATABASE"],
        f"CREATE DATABASE {db} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C';")
apply_migrations(None, [*base, "-d", "d12_source"], psql_command=psql)
sql("d12_source",
    "CREATE SCHEMA d12_fixture; CREATE TABLE d12_fixture.parent(id bigint PRIMARY KEY, label text NOT NULL);"
    " CREATE TABLE d12_fixture.child(id bigint PRIMARY KEY,"
    " parent_id bigint NOT NULL REFERENCES d12_fixture.parent(id), payload jsonb NOT NULL);"
    " CREATE INDEX child_parent ON d12_fixture.child(parent_id);"
    " CREATE VIEW d12_fixture.joined AS SELECT p.label, c.payload"
    " FROM d12_fixture.child c JOIN d12_fixture.parent p ON p.id = c.parent_id;"
    " INSERT INTO d12_fixture.parent SELECT g, 'label-' || g FROM generate_series(1, 200) g;"
    " INSERT INTO d12_fixture.child SELECT g, 1 + g % 200,"
    " jsonb_build_object('n', g, 'text', repeat('x', g % 17)) FROM generate_series(1, 2000) g;")
archive = "/tmp/d12-source.dump"
subprocess.run([dump, *base, "-d", "d12_source", "-Fc", "-f", archive], check=True, capture_output=True)
before = hashlib.sha256(open(archive, "rb").read()).hexdigest()
toc = subprocess.run([restore, "-l", archive], check=True, capture_output=True, text=True).stdout
r_cmd = [restore, *base, "-d", "d12_restore", "--exit-on-error", "--single-transaction", archive]
subprocess.run(r_cmd, check=True, capture_output=True)
after = hashlib.sha256(open(archive, "rb").read()).hexdigest()
AM_Q = (
    "SELECT DISTINCT am.amname FROM pg_class c JOIN pg_am am ON am.oid = c.relam "
    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind = 'i' "
    "AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')")
MD5_Q = (
    "SELECT md5(string_agg(label || ':' || payload::text, ',' ORDER BY label, payload::text)) "
    "FROM d12_fixture.joined")
def observe(db):
    with psycopg.connect(host="127.0.0.1", port=5432, user=os.environ["PGUSER"], dbname=db) as conn:
        one = lambda q: conn.execute(q).fetchone()[0]
        return {"server_version": one("SHOW server_version"), "server_version_num": one("SHOW server_version_num"),
          "extensions": [r[0] for r in conn.execute("SELECT extname FROM pg_extension ORDER BY 1")],
          "replication_slots": one("SELECT count(*) FROM pg_replication_slots"),
          "index_access_methods": sorted({r[0] for r in conn.execute(AM_Q)}),
          "fixture_md5": one(MD5_Q),
          "fixture_rows": one("SELECT count(*) FROM d12_fixture.child"),
          "graph_schema": graph_schema_readiness(None, [*base, "-d", db], psql_command=psql).status.name}
toc_n = sum(1 for l in toc.splitlines() if l and not l.startswith(";"))
print(json.dumps({"source": observe("d12_source"), "restored": observe("d12_restore"), "archive_sha256_before": before,
  "archive_sha256_after": after, "archive_toc_entries": toc_n}))
"""

def _tmpfs(client, image):
    return {path: "" for path in client.images.get(image).attrs["Config"].get("Volumes") or {}}

def _create(owner, client, image, command, **options):
    identity = owner.create(image, command, tmpfs=_tmpfs(client, image), **options)
    container = client.containers.get(identity)
    mounts = [m for m in container.attrs.get("Mounts") or [] if m.get("Type") in ("bind", "volume")]
    assert not mounts, f"tested runtime must have no bind or volume mounts: {mounts}"
    return identity, container

def _run_once(owner, client, image, command, *, role, entrypoint, environment=None, network="none", platform=None):
    identity, container = _create(owner, client, image, command, role=role, entrypoint=entrypoint,
                                  environment=environment or {}, network_mode=network, platform=platform)
    try:
        container.start()
        status = container.wait(timeout=900).get("StatusCode", 1)
        output = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        errors = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    finally:
        owner.cleanup(identity)
    assert status == 0, f"{role} failed with {status}: {errors[-4000:]}"
    return output

def _start_server(owner, client, environment, platform):
    identity, container = _create(owner, client, POSTGRES_RELEASE_IMAGE, None, role="d12-server",
                                  environment=environment, network_mode="none", platform=platform)
    container.start()
    probe = ["pg_isready", "-h", "127.0.0.1", "-U", environment["POSTGRES_USER"], "-d", environment["POSTGRES_DB"]]
    deadline = time.monotonic() + 90
    while container.exec_run(probe).exit_code != 0:
        container.reload()
        assert container.status == "running" and time.monotonic() < deadline, "16.15 server never became ready"
        time.sleep(1)
    return identity, container

def _hashes(owner, client, image, paths, platform, role):
    text = _run_once(owner, client, image, ["-c", HASH_SH, "sh", *paths], role=role, entrypoint=["sh"],
                     platform=platform)
    return {r.split("\t")[1]: r.split("\t")[2] for r in text.splitlines() if r.startswith("H\t")}

def _inventory(owner, client, image, platform, role):
    script = INVENTORY_SH.replace("$NOTICES", " ".join(NOTICES))
    text = _run_once(owner, client, image, ["-c", script, "sh", SERVER, *CLIENTS, "/usr/bin/psql",
                                            "/usr/local/bin/python3"], role=role, entrypoint=["sh"], platform=platform)
    rows = [line.split("\t") for line in text.splitlines() if "\t" in line]
    files = [dict(zip(("role", "invoked", "resolved", "kind", "sha256", "interpreter", "owner", "md5"), r[1:]))
             for r in rows if r[0] == "F"]
    return {"files": files, "links": [r[1:] for r in rows if r[0] == "L"],
            "packages": [r[1:] for r in rows if r[0] == "P"], "verify_mismatches": [r[1:] for r in rows if r[0] == "V"],
            "verify_count": int(next((r[1] for r in rows if r[0] == "VC"), "-1")),
            "unowned_usr_lib": [r[1] for r in rows if r[0] == "U"],
            "unowned_count": int(next((r[1] for r in rows if r[0] == "UC"), "-1")),
            "notices": {r[1]: r[2] for r in rows if r[0] == "C"}, "os": next((r[1:] for r in rows if r[0] == "O"), [])}

def _version(text):
    match = re.search(r"\(PostgreSQL\) (\d+)\.(\d+)", text or "")
    return (int(match.group(1)), int(match.group(2))) if match else None

def _classify(observed):
    if observed is None:
        return "unknown"
    return "outside_affected_range" if observed[0] == 16 and observed >= FIXED_IN else "affected"

def _libpq_findings(packaging, inventory):
    loaded = divmod(int(packaging["libpq"]), 10000)
    system = [row[1] for row in inventory["packages"] if row[0] == "libpq5"]
    found = re.match(r"(\d+)\.(\d+)", system[0]) if system else None
    copies = (("loaded_by_psycopg", loaded), ("system_libpq5", (int(found[1]), int(found[2])) if found else None))
    return [{"advisory": LIBPQ_ADVISORY, "copy": name, "observed": observed,
             "class": "unknown" if observed is None or observed[0] not in LIBPQ_FIXED else
             "outside_affected_range" if observed[1] >= LIBPQ_FIXED[observed[0]] else "affected"}
            for name, observed in copies]

def _build_authority(admission: d12.D12Admission | None) -> d12.D12Admission:
    if admission is None or admission is not d12.current_admission():  # the accessor refuses throughout E1
        raise d12.D12ProfileError("build refused: admission is not the current build admission")
    return admission

def test_d12_core_image_refresh_candidate_round_trip() -> None:
    import d12_dependency_preflight as inner  # ADR 0089 D9 E1 support, from the canonical runner's tools path
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
        assert server_container.attrs["Image"] == bases[POSTGRES_RELEASE_IMAGE]["id"]
        server_side = {
            p: server_container.exec_run([p, "--version"]).output.decode().strip() for p in (SERVER, *CLIENTS)}
        server_inventory = _inventory(owner, client, POSTGRES_RELEASE_IMAGE, platform, "d12-inventory-server")
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
        assert attrs["Config"]["Entrypoint"] == ["python", "-m", "repomap_kg"]
        packaging = json.loads(_run_once(
            owner, client, image_id, ["-c", PACKAGING_PY], role="d12-packaging", entrypoint=["python"],
            environment={"D12_PATHS": json.dumps([SERVER, *CLIENTS]), "D12_LIBRARY_FILE": linkage.LIBRARY_FILE.pattern},
            platform=platform).splitlines()[-1])
        linkage_report = json.loads(_run_once(
            owner, client, image_id, ["-I", "-c", linkage.probe_source(), "probe"],
            role="d12-linkage", entrypoint=["python"], platform=platform).splitlines()[-1])
        candidate = _inventory(owner, client, image_id, platform, "d12-inventory-candidate")
        resolved = sorted({f["resolved"] for f in candidate["files"] if f["kind"] != "missing"})
        stages = {name: _hashes(owner, client, reference, resolved, platform, f"d12-hash-{name}")
                  for name, reference in (("postgres", POSTGRES_RELEASE_IMAGE), ("python", PYTHON_RELEASE_IMAGE))}
        for item in candidate["files"]:
            matches = [n for n, hashes in stages.items() if hashes.get(item["resolved"]) == item["sha256"]]
            pip = "/site-packages/" in item["resolved"] or ".libs/" in item["resolved"]
            item["stage"] = "+".join(matches) or ("python-runtime-pip" if pip else "unattributed")
        d12.write_report("inventory", {"candidate": candidate, "server": server_inventory, "packaging": packaging,
                                       "linkage": linkage_report})
        round_trip = json.loads(_run_once(
            owner, client, image_id, ["-c", ROUND_TRIP_PY], role="d12-round-trip", entrypoint=["python"],
            environment={"PGPASSWORD": server_env["POSTGRES_PASSWORD"], "PGUSER": server_env["POSTGRES_USER"],
                         "PGDATABASE": server_env["POSTGRES_DB"]},
            network=f"container:{server_id}", platform=platform).splitlines()[-1])
        observed = {"candidate": packaging["versions"], "server_image": server_side,
                    "server_process": round_trip["source"]["server_version"]}
        findings = [{"advisory": cve, "image": image, "path": path, "observed": text,
                     "class": _classify(_version(text))}
                    for cve, path in ADVISORIES.items()
                    for image, text in (("candidate", packaging["versions"].get(path)),
                                        ("server", server_side.get(path)))]
        critical_unknown = [f for f in candidate["files"] if f["kind"] == "missing"] + [
            link for link in candidate["links"] if link[-1] == "not"]
        libpq = _libpq_findings(packaging, candidate)
        stops = [f"{f['advisory']} {f['copy']} {f['class']}" for f in libpq if f["class"] != "outside_affected_range"]
        stops += ["vulnerability classification of every other package and distribution is not performed (unknown)",
                  "incumbent 16.14 application inventory is unavailable without an extra build or pull"]
        stops += [f"unattributed bytes: {f['resolved']}" for f in candidate["files"] if f["stage"] == "unattributed"]
        stops += [] if availability["execution"] == "native" else [f"{platform} ran under existing emulation"]
        tls = {name: [r for r in inv["packages"] if r[:1] == [inner.HEADER[0]]]
               for name, inv in (("server", server_inventory), ("candidate", candidate))}
        stops += [f"{name} TLS runtime is not exactly {inner.HEADER[0]}={inner.HEADER[2]} (ADR 0091): {rows}"
                  for name, rows in tls.items() if [r[1] for r in rows] != [inner.HEADER[2]]]
        d12.write_report("result", {"observed_versions": observed, "server_side": server_side, "tls_runtime": tls,
                                    "round_trip": round_trip, "findings": findings, "libpq_findings": libpq,
                                    "critical_unknown": critical_unknown, "availability": availability,
                                    "qualification": "stop_pending_disposition", "stops": stops})
        expected = f"(PostgreSQL) {POSTGRES_RELEASE_VERSION}"
        assert all(expected in packaging["versions"][p] for p in (SERVER, *CLIENTS)), packaging["versions"]
        assert all(expected in text for text in server_side.values()), server_side
        assert round_trip["source"]["server_version"].startswith(POSTGRES_RELEASE_VERSION)
        assert (packaging["python"], packaging["psycopg"], packaging["implementation"], packaging["libpq"]) == (
            PYTHON_RELEASE_VERSION, PSYCOPG_RELEASE_VERSION, "c", PSYCOPG_LIBPQ_VERSION)
        assert all(packaging[k] for k in ("pip_absent", "setuptools_absent", "ensurepip_absent", "go_absent"))
        assert packaging["has_cancel_safe"], "product libpq must keep the bounded cancel_safe (ADR 0089 D2)"
        assert all(packaging["migrations"]) and packaging["go_helper_protocol"].isdigit()
        assert not packaging["bundled_libpq"], packaging["bundled_libpq"]
        failures = linkage.assess(linkage_report, psycopg_version=PSYCOPG_RELEASE_VERSION,
                                  libpq_version=PSYCOPG_LIBPQ_VERSION)
        assert not failures, failures
        assert all(candidate["notices"][path] != "absent" for path in NOTICES[6:]), candidate["notices"]
        assert not critical_unknown, critical_unknown
        assert all(f["class"] == "outside_affected_range" for f in findings), findings
        source, restored = round_trip["source"], round_trip["restored"]
        assert round_trip["archive_sha256_before"] == round_trip["archive_sha256_after"]
        assert source["fixture_md5"] == restored["fixture_md5"] and restored["fixture_rows"] == 2000
        assert source["graph_schema"] == restored["graph_schema"] == "CURRENT"
        assert source["extensions"] == restored["extensions"] == ["plpgsql"]
        assert source["replication_slots"] == restored["replication_slots"] == 0
        assert set(source["index_access_methods"]) == set(restored["index_access_methods"]) == {"btree"}
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
