"""Container-side command control scripts, argv and settlement parsing for D9-B extension_v2.

Every new extension_v2 container command runs by immutable container ID under a POSIX
``sh`` supervisor. The supervisor exclusively creates a private 0700 control directory
and a 0600 ``pid starttime token`` record, sets a unique PostgreSQL ``application_name``
and then ``exec``s the command, so the recorded process identity is the command itself.
A separate settlement exec observes every process that carries the exported invocation
token, but may signal only that exact recorded leader, and removes only that control path;
correlated sessions are settled by exact ``application_name``. The postmaster is PID 1 and
treats any reaped exit other than 0 or 1 as a crash. Settlement therefore never signals another
invocation process, nor a leader with any child, one that could fork, or one whose parent is not
the qualified Docker exec runtime's shim (PPid 0 inside the container), which reaps it; PID 1 and
any in-container parent are refused. It gives no atomic-PID or hostile-host guarantee.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from common_lore_index.runtime.local import LocalRuntimePlan

EXEC_INVOCATION_ENV = "REPOMAP_EXT_INVOCATION"
EXEC_APPLICATION_PREFIX = "repomap-ext-"
EXEC_CONTROL_PREFIX = "/tmp/repomap-ext-exec-"
EXEC_SETTLE_TIMEOUT_SECONDS = 10.0
EXEC_CONTROL_OUTPUT_MAX_BYTES = 4096
SESSION_STATEMENT_TIMEOUT_MS = 5000
SESSION_TERMINATE_WAIT_MS = 2000

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_REMOTE_STATES = frozenset(
    {"exited", "killed", "not-started", "alive", "mismatch", "unknown"}
)
_CONTROL_STATES = frozenset({"removed", "retained", "fence-retained"})
_DESCENDANT_STATES = frozenset({"none", "remaining", "unreaped", "unknown"})

# Exit status 125 means the command was never executed. The record is written before
# ``exec``, so the PID and start time it names belong to the command that replaces sh.
SUPERVISOR_SH = r"""
c="$1"; shift
start_of() { s="${1##*) }"; set -- $s; printf '%s' "${20}"; }
mkdir -m 0700 "$c" 2>/dev/null || { echo "repomap: exec control path collision" >&2; exit 125; }
read -r s < "/proc/$$/stat" || exit 125
( umask 0177; set -C; printf '%s %s %s\n' "$$" "$(start_of "$s")" "$REPOMAP_EXT_INVOCATION" > "$c/proc" ) 2>/dev/null \
  || { echo "repomap: exec control record collision" >&2; exit 125; }
PGAPPNAME="repomap-ext-$REPOMAP_EXT_INVOCATION"; export PGAPPNAME
exec "$@"
""".strip()

# Reports exactly one REMOTE, one CONTROL and one DESCENDANTS line, or one UNAVAILABLE
# line. Every invocation process inherits the token. The census reads every process, counting
# zombies by PPid, and only observes: for at most 2 s it waits for token-bearing non-leader
# processes to finish and for zombie children to be reaped, then reports them ``remaining`` or
# ``unreaped``. A live untokened child of an owned process is ``unknown``; a token-bearing process
# whose parent is PID 1, the recorded leader included, is ``remaining`` and outranks both. None of
# them, and no other non-leader, is ever sent a signal. Only the exact recorded leader (PID, start
# time and token) with a clean census and PPid 0, the exec shim, is stopped, an introduced stop
# first named exclusively in "$c/halt". It is killed only once seen stopped, then found childless by a
# census that it cannot invalidate by forking, then re-read with the same start time and PPid. A
# child found there is left alone; settlement resumes only its own stop, under that identity and
# parent, and removes "$c/halt" only once the kill or the resume is seen. An existing "$c/halt"
# prevents every signal. It fences an absent control directory so that a late supervisor start
# cannot run, and it never writes into or removes an existing directory that lacks a matching record.
SETTLE_PROCESS_SH = r"""
c="$1"; k="$2"
for u in rm rmdir sleep tr grep; do
  command -v "$u" >/dev/null 2>&1 || { echo "UNAVAILABLE $u"; exit 0; }
done
report() { echo "REMOTE $1"; echo "CONTROL $2"; echo "DESCENDANTS $3"; exit 0; }
pause() { sleep 0.1 2>/dev/null || { sleep 1; w=$((w + 9)); }; w=$((w + 1)); }
probe() {
  if read -r s 2>/dev/null < "/proc/$1/stat"; then s="${s##*) }"; set -- $s; echo "$1 ${20} $2"
  else echo "gone - -"; fi
}
live() { set -- "$1" "$2" $(probe "$1"); [ "$4" = "$2" ] && [ "$3" != Z ] && [ "$3" != X ] && [ "$3" != gone ]; }
fence() { ( umask 0177; set -C; printf 'fence %s\n' "$k" > "$c/proc" ) 2>/dev/null; }
owned() {
  for e in /proc/[0-9]*/environ; do
    q="${e#/proc/}"; q="${q%/environ}"
    [ "$q" = "$$" ] && continue
    set -- $(probe "$q")
    case "$1" in gone) continue ;; Z|X) echo "Z $q $2 $3 $1"; continue ;; esac
    if tr '\0' '\n' 2>/dev/null < "$e" | grep -Fqx "REPOMAP_EXT_INVOCATION=$k"; then echo "T $q $2 $3 $1"
    else echo "N $q $2 $3 $1"; fi
  done
}
held() {
  y="$1"; set -- $(owned)
  while [ "$#" -ge 5 ]; do [ "$1:$4" = T:1 ] && report "$y" retained remaining; shift 5; done
  report "$y" retained unknown
}
tree() {
  w=0
  while :; do
    m="$(owned)"; ts=" "; x=""; z=""; o=""; u=""; d=none
    set -- $m
    while [ "$#" -ge 5 ]; do [ "$1" = T ] && ts="$ts$2 "; shift 5; done
    set -- $m
    while [ "$#" -ge 5 ]; do
      [ "$1:$4" = T:1 ] && o=1
      [ "$1" = T ] && [ "$2" != "$L" ] && x=1
      case "$ts" in *" $4 "*) case "$1" in N) u=1 ;; Z) z=1 ;; esac ;; esac
      shift 5
    done
    [ -n "$o" ] && { d=remaining; return 0; }
    [ -n "$u" ] && { d=unknown; return 0; }
    [ -n "$x$z" ] || return 0
    if [ "$w" -ge 20 ]; then d=unreaped; [ -n "$x" ] && d=remaining; return 0; fi
    pause
  done
}
kids() {
  for f in /proc/[0-9]*/stat; do
    read -r s 2>/dev/null < "$f" || continue; s="${s##*) }"; set -- $s; [ "$2" = "$p" ] && return 0
  done
  return 1
}
retire() {
  a=""; kf=""; n=0
  [ -e "$c/halt" ] && return 1
  set -- $(probe "$p"); [ "$2" = "$t" ] && [ "$3" = 0 ] || return 1
  pq="$3"
  case "$1" in
    T) ;;
    Z|X|t|gone) return 1 ;;
    *) ( umask 0177; set -C; printf '%s %s\n' "$p" "$t" > "$c/halt" ) 2>/dev/null || return 1
       a=1; kill -STOP "$p" 2>/dev/null ;;
  esac
  while set -- $(probe "$p"); [ "$1" != T ] && [ "$2" = "$t" ] && [ "$n" -lt 10 ]; do n=$((n + 1)); sleep 0.1 2>/dev/null || n=10; done
  if [ "$1:$2:$3" = "T:$t:$pq" ]; then
    if kids; then kf=1
    else set -- $(probe "$p"); [ "$1:$2:$3" = "T:$t:$pq" ] && kill -9 "$p" 2>/dev/null && return 0
    fi
  fi
  [ -n "$a" ] || return 1
  set -- $(probe "$p"); [ "$2:$3" = "$t:$pq" ] && kill -CONT "$p" 2>/dev/null || return 1
  n=0
  while set -- $(probe "$p"); [ "$1:$2:$3" = "T:$t:$pq" ] && [ "$n" -lt 10 ]; do n=$((n + 1)); sleep 0.1 2>/dev/null || n=10; done
  case "$1" in T|t|Z|X|gone) ;; *) [ "$2:$3" = "$t:$pq" ] && rm -f "$c/halt" && a="" ;; esac
  return 1
}
d=none; L=""; a=""
if mkdir -m 0700 "$c" 2>/dev/null; then
  if fence; then tree; report not-started fence-retained "$d"; fi
  held unknown
fi
{ [ -d "$c" ] && [ ! -L "$c" ]; } || held unknown
[ -L "$c/proc" ] && held unknown
w=0; p=""; t=""; tok=""
while [ "$w" -lt 20 ]; do
  read -r p t tok 2>/dev/null < "$c/proc"
  { [ -n "$tok" ] || [ "$p" = fence ]; } && break
  pause
done
[ -L "$c/proc" ] && held unknown
[ "$p" = fence ] && { tree; report not-started retained "$d"; }
[ "$tok" = "$k" ] || held unknown
case "$p:$t" in *[!0-9:]*|:*|*:) held unknown ;; esac
r=exited
if live "$p" "$t"; then
  tr '\0' '\n' 2>/dev/null < "/proc/$p/environ" | grep -Fqx "REPOMAP_EXT_INVOCATION=$k" || held mismatch
  L="$p"; n2=0
  while :; do
    tree
    if [ "$d" != none ]; then live "$p" "$t" && report alive retained "$d"; report exited retained "$d"; fi
    live "$p" "$t" || break
    retire && { r=killed; break; }
    if [ -n "$kf" ] || [ -e "$c/halt" ]; then
      y=unknown; live "$p" "$t" && y=alive
      tree; [ "$d" = none ] && { d=unknown; [ -n "$kf" ] && d=remaining; }
      report "$y" retained "$d"
    fi
    n2=$((n2 + 1)); [ "$n2" -lt 3 ] || report alive retained unknown
  done
  w=0
  while live "$p" "$t"; do
    [ "$w" -ge 20 ] && report alive retained unknown
    pause
  done
  [ -n "$a" ] && { rm -f "$c/halt" || report "$r" retained unknown; }
fi
tree
[ "$d" = none ] || report "$r" retained "$d"
rm -f "$c/proc" && rmdir "$c" && report "$r" removed "$d"
report "$r" retained "$d"
""".strip()


def valid_container_id(container_id: object) -> bool:
    return isinstance(container_id, str) and _CONTAINER_ID_RE.match(container_id) is not None


def valid_token(token: object) -> bool:
    return isinstance(token, str) and _TOKEN_RE.match(token) is not None


def control_path(plan: LocalRuntimePlan, token: str) -> str:
    return f"{EXEC_CONTROL_PREFIX}{plan.identity.home_hash}-{token}"


def application_name(token: str) -> str:
    return f"{EXEC_APPLICATION_PREFIX}{token}"


def split_container_exec(
    plan: LocalRuntimePlan, command: Sequence[str]
) -> tuple[list[str], list[str]] | None:
    """Return (exec options, inner argv) of a planned owned-container exec, else ``None``.

    Raises ``ValueError`` for an exec of an unexpected shape, which must refuse rather
    than run without container-side custody.
    """
    if len(command) < 2 or command[0] != plan.container_runtime or command[1] != "exec":
        return None
    options: list[str] = []
    index = 2
    while index < len(command):
        token = command[index]
        if token == "-i":
            options.append(token)
            index += 1
        elif token == "-e" and tuple(command[index + 1 : index + 2]) == ("PGPASSWORD",):
            options.extend((token, "PGPASSWORD"))
            index += 2
        else:
            break
    if index + 1 >= len(command) or command[index] != plan.identity.postgres_container:
        raise ValueError("container exec does not target the owned container in a known form")
    return options, list(command[index + 1 :])


def supervised_command(
    plan: LocalRuntimePlan,
    container_id: str,
    options: Sequence[str],
    inner: Sequence[str],
    *,
    token: str,
) -> list[str]:
    return [
        plan.container_runtime,
        "exec",
        *options,
        "-e",
        f"{EXEC_INVOCATION_ENV}={token}",
        container_id,
        "sh",
        "-c",
        SUPERVISOR_SH,
        "sh",
        control_path(plan, token),
        *inner,
    ]


def settle_process_command(plan: LocalRuntimePlan, container_id: str, token: str) -> list[str]:
    return [
        plan.container_runtime,
        "exec",
        container_id,
        "sh",
        "-c",
        SETTLE_PROCESS_SH,
        "sh",
        control_path(plan, token),
        token,
    ]


def settle_sessions_command(
    plan: LocalRuntimePlan, container_id: str, token: str, psql: str
) -> list[str]:
    """Terminate only sessions of this exact invocation and role, then read back absence."""
    match = f"application_name = '{application_name(token)}' AND pid <> pg_backend_pid()"
    terminate = (
        "WITH t AS (SELECT pg_terminate_backend(pid, "
        f"{SESSION_TERMINATE_WAIT_MS}) AS ok FROM pg_stat_activity "
        f"WHERE {match} AND usename = current_user) "
        "SELECT count(*) FILTER (WHERE NOT ok) FROM t;"
    )
    return [
        plan.container_runtime,
        "exec",
        "-e",
        "PGPASSWORD",
        container_id,
        psql,
        "-X",
        "-q",
        "-t",
        "-A",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        plan.user,
        "-d",
        plan.maintenance_database,
        "-c",
        f"SET statement_timeout = {SESSION_STATEMENT_TIMEOUT_MS}",
        "-c",
        terminate,
        "-c",
        f"SELECT count(*) FROM pg_stat_activity WHERE {match};",
    ]


def parse_process_settlement(raw: str) -> tuple[str, str, str]:
    """Return (remote, control, descendants) observations; any other output is unknown."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].startswith("UNAVAILABLE "):
        return "unavailable", "retained", "unknown"
    prefixes = ("REMOTE ", "CONTROL ", "DESCENDANTS ")
    if len(lines) != 3 or not all(line.startswith(pre) for line, pre in zip(lines, prefixes)):
        return "unknown", "unknown", "unknown"
    remote, control, descendants = (line[len(pre) :] for line, pre in zip(lines, prefixes))
    return (
        remote if remote in _REMOTE_STATES else "unknown",
        control if control in _CONTROL_STATES else "unknown",
        descendants if descendants in _DESCENDANT_STATES else "unknown",
    )


def parse_session_settlement(raw: str) -> str:
    """Return ``none`` only when the final read-back proves zero correlated sessions."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 2 or not all(line.isdigit() for line in lines):
        return "unknown"
    return "none" if int(lines[1]) == 0 else "remaining"
