#!/bin/sh
# RepoMap host-native MCP qualification kit entrypoint; see README.md beside it.
# Runs the kit's parent runner with the pinned checkout's own interpreter.
# Nothing is installed, pulled, or configured here.
set -u
KIT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P) || exit 2
CHECKOUT=""
previous=""
for argument in "$@"; do
  if [ "$previous" = "--checkout" ]; then CHECKOUT=$argument; fi
  case $argument in --checkout=*) CHECKOUT=${argument#--checkout=} ;; esac
  previous=$argument
done
if [ -z "$CHECKOUT" ]; then
  echo "NOT RUN: --checkout PATH is required (no receipt: refused before the runner started)" >&2
  exit 2
fi
PYTHON="$CHECKOUT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "NOT RUN: checkout interpreter is missing: $PYTHON (no receipt: refused before the runner started)" >&2
  exit 2
fi
exec "$PYTHON" -I -B "$KIT/tools/host_mcp_native_qualify.py" "$@"
