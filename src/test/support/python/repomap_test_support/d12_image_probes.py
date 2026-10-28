"""Shared D12 image probe constants, scripts, and post-build assessment helpers (ADR 0095)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import re
import time
from typing import Any

from repomap_kg.runtime.release import (
    PACKAGED_PG_DUMP,
    PACKAGED_PG_RESTORE,
    PACKAGED_PSQL,
    POSTGRES_RELEASE_IMAGE,
)

REPORT_PART_LIMIT, REPORT_TOTAL_LIMIT, REPORT_CLEANUP_RESERVE = 1_500_000, 5_000_000, 100_000

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


def _tmpfs(client: Any, image: str) -> dict[str, str]:
    return {path: "" for path in client.images.get(image).attrs["Config"].get("Volumes") or {}}


def _create(owner: Any, client: Any, image: str, command: Any, **options: Any) -> tuple[str, Any]:
    identity = owner.create(image, command, tmpfs=_tmpfs(client, image), **options)
    container = client.containers.get(identity)
    mounts = [m for m in container.attrs.get("Mounts") or [] if m.get("Type") in ("bind", "volume")]
    assert not mounts, f"tested runtime must have no bind or volume mounts: {mounts}"
    return identity, container


def _run_once(owner: Any, client: Any, image: str, command: Any, *, role: str, entrypoint: Any,
              environment: Mapping[str, str] | None = None, network: str = "none",
              platform: str | None = None, deadline: Any | None = None,
              create_fn: Callable[..., tuple[str, Any]] = _create) -> str:
    if deadline is not None and hasattr(deadline, "check_test_budget"):
        deadline.check_test_budget(role)
    elif deadline is not None and hasattr(deadline, "check_budget"):
        deadline.check_budget()
    wait_timeout = max(1, int(deadline.clamp_timeout(900.0))) if deadline is not None else 900
    identity, container = create_fn(owner, client, image, command, role=role, entrypoint=entrypoint,
                                    environment=dict(environment or {}), network_mode=network, platform=platform)
    primary: BaseException | None = None
    try:
        container.start()
        status = container.wait(timeout=wait_timeout).get("StatusCode", 1)
        output = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
        errors = container.logs(stdout=False, stderr=True).decode("utf-8", "replace")
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            owner.cleanup(identity)
        except BaseException as cleanup_exc:
            if primary is None:
                raise
            primary.add_note(
                f"D12 container {identity} cleanup also failed ({type(cleanup_exc).__name__}: {cleanup_exc})"
            )
    assert status == 0, f"{role} failed with {status}: {errors[-4000:]}"
    return output


def _start_server(owner: Any, client: Any, environment: Mapping[str, str], platform: str | None, *,
                  deadline: Any | None = None, create_fn: Callable[..., tuple[str, Any]] = _create) -> tuple[str, Any]:
    identity, container = create_fn(owner, client, POSTGRES_RELEASE_IMAGE, None, role="d12-server",
                                    environment=dict(environment), network_mode="none", platform=platform)
    try:
        container.start()
        probe = ["pg_isready", "-h", "127.0.0.1", "-U", environment["POSTGRES_USER"], "-d", environment["POSTGRES_DB"]]
        window = float(deadline.clamp_timeout(90.0)) if deadline is not None else 90.0
        stop_at = time.monotonic() + window
        while container.exec_run(probe).exit_code != 0:
            if deadline is not None and hasattr(deadline, "check_test_budget"):
                deadline.check_test_budget("d12 server readiness")
            elif deadline is not None and hasattr(deadline, "check_budget"):
                deadline.check_budget()
            container.reload()
            assert container.status == "running" and time.monotonic() < stop_at, "16.15 server never became ready"
            time.sleep(1)
    except BaseException as primary:
        try:
            owner.cleanup(identity)
        except BaseException as cleanup_exc:
            primary.add_note(
                f"D12 server container {identity} cleanup also failed ({type(cleanup_exc).__name__}: {cleanup_exc})"
            )
        raise
    return identity, container


def _hashes(owner: Any, client: Any, image: str, paths: Sequence[str], platform: str | None, role: str, *,
            deadline: Any | None = None, create_fn: Callable[..., tuple[str, Any]] = _create,
            run_once_fn: Callable[..., str] = _run_once) -> dict[str, str]:
    text = run_once_fn(owner, client, image, ["-c", HASH_SH, "sh", *paths], role=role, entrypoint=["sh"],
                       platform=platform, deadline=deadline, create_fn=create_fn)
    return {r.split("\t")[1]: r.split("\t")[2] for r in text.splitlines() if r.startswith("H\t")}


def _inventory(owner: Any, client: Any, image: str, platform: str | None, role: str, *,
               deadline: Any | None = None, create_fn: Callable[..., tuple[str, Any]] = _create,
               run_once_fn: Callable[..., str] = _run_once) -> dict[str, Any]:
    script = INVENTORY_SH.replace("$NOTICES", " ".join(NOTICES))
    text = run_once_fn(owner, client, image, ["-c", script, "sh", SERVER, *CLIENTS, "/usr/bin/psql",
                                              "/usr/local/bin/python3"], role=role, entrypoint=["sh"],
                       platform=platform, deadline=deadline, create_fn=create_fn)
    rows = [line.split("\t") for line in text.splitlines() if "\t" in line]
    files = [dict(zip(("role", "invoked", "resolved", "kind", "sha256", "interpreter", "owner", "md5"), r[1:]))
             for r in rows if r[0] == "F"]
    return {"files": files, "links": [r[1:] for r in rows if r[0] == "L"],
            "packages": [r[1:] for r in rows if r[0] == "P"], "verify_mismatches": [r[1:] for r in rows if r[0] == "V"],
            "verify_count": int(next((r[1] for r in rows if r[0] == "VC"), "-1")),
            "unowned_usr_lib": [r[1] for r in rows if r[0] == "U"],
            "unowned_count": int(next((r[1] for r in rows if r[0] == "UC"), "-1")),
            "notices": {r[1]: r[2] for r in rows if r[0] == "C"}, "os": next((r[1:] for r in rows if r[0] == "O"), [])}


def _version(text: str | None) -> tuple[int, int] | None:
    match = re.search(r"\(PostgreSQL\) (\d+)\.(\d+)", text or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def _classify(observed: tuple[int, int] | None) -> str:
    if observed is None:
        return "unknown"
    return "outside_affected_range" if observed[0] == 16 and observed >= FIXED_IN else "affected"


def _libpq_findings(packaging: Mapping[str, Any], inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    loaded = divmod(int(packaging["libpq"]), 10000)
    system = [row[1] for row in inventory["packages"] if row[0] == "libpq5"]
    found = re.match(r"(\d+)\.(\d+)", system[0]) if system else None
    copies = (("loaded_by_psycopg", loaded), ("system_libpq5", (int(found[1]), int(found[2])) if found else None))
    return [{"advisory": LIBPQ_ADVISORY, "copy": name, "observed": observed,
             "class": "unknown" if observed is None or observed[0] not in LIBPQ_FIXED else
             "outside_affected_range" if observed[1] >= LIBPQ_FIXED[observed[0]] else "affected"}
            for name, observed in copies]
