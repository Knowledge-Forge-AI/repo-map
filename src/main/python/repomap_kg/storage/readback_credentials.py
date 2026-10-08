"""Ephemeral credential plumbing for read-only PostgreSQL queries."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import NamedTuple

from repomap_kg.storage.errors import StorageSchemaError


class DiagnosticOptions(NamedTuple):
    options: str
    effective_timeout_ms: int


def psql_environment(password: str | None) -> dict[str, str] | None:
    """Return a private child environment without changing process globals."""

    if password is None:
        return None
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PGPASSWORD", "REPOMAP_PG_PASSWORD"}
    }
    environment["PGPASSWORD"] = password
    return environment


def psycopg_connection_params(
    params: Mapping[str, str], password: str | None
) -> dict[str, str]:
    """Copy connection parameters and add an in-memory password when supplied."""

    result = dict(params)
    if password is not None:
        result["password"] = password
    return result


def sanitized_psycopg_error(
    label: str, phase: str, error: BaseException
) -> StorageSchemaError:
    """Keep only bounded diagnostic metadata from a credentialed failure."""

    result = StorageSchemaError(f"psycopg readback failed for {label}")
    setattr(result, "_readback_phase", phase)
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
        setattr(result, "_readback_sqlstate", sqlstate)
    setattr(
        result,
        "_readback_operational",
        error.__class__.__name__ == "OperationalError"
        and error.__class__.__module__.split(".", maxsplit=1)[0] == "psycopg",
    )
    return result


def psycopg_error_details(error: BaseException) -> tuple[str | None, bool]:
    """Read diagnostic metadata without traversing credential-bearing causes."""

    sqlstate = getattr(error, "_readback_sqlstate", None)
    operational = bool(getattr(error, "_readback_operational", False))
    if isinstance(sqlstate, str) or operational:
        return sqlstate if isinstance(sqlstate, str) else None, operational
    cause = error.__cause__
    if cause is None:
        return None, False
    sqlstate = getattr(cause, "sqlstate", None)
    is_operational = (
        cause.__class__.__name__ == "OperationalError"
        and cause.__class__.__module__.split(".", maxsplit=1)[0] == "psycopg"
    )
    return sqlstate if isinstance(sqlstate, str) else None, is_operational


def _resolve_diagnostic_options(
    existing: str | None, target_ms: int
) -> DiagnosticOptions | None:
    if not existing or not existing.strip():
        return DiagnosticOptions(
            f"-c default_transaction_read_only=on -c statement_timeout={target_ms}",
            target_ms,
        )
    if any(ch in existing for ch in ('"', "'", "\\")):
        return None
    mults = {"ms": 1, "s": 1000, "min": 60_000, "h": 3_600_000, "d": 86_400_000}
    tokens, new_toks, seen = existing.strip().split(), [], set()
    has_to, has_ro, eff_to, i = False, False, target_ms, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-c" and i + 1 < len(tokens):
            is_att, pair, i = False, tokens[i + 1], i + 2
        elif tok.startswith("-c") and len(tok) > 2:
            is_att, pair, i = True, tok[2:], i + 1
        else:
            return None
        if "=" not in pair:
            return None
        k, v = (x.strip() for x in pair.split("=", 1))
        k = k.lower()
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", k) or k in seen:
            return None
        seen.add(k)
        if k == "statement_timeout":
            if not (m := re.match(r"^(\d+)(ms|s|min|h|d)?$", v.lower())):
                return None
            has_to, parsed = True, int(m.group(1)) * mults[m.group(2) or "ms"]
            eff_to = target_ms if parsed == 0 else min(target_ms, parsed)
            val = f"statement_timeout={eff_to}"
        elif k == "default_transaction_read_only":
            if v.lower() not in {"on", "off", "true", "false", "yes", "no", "1", "0"}:
                return None
            has_ro, val = True, "default_transaction_read_only=on"
        elif re.match(r"^[a-zA-Z0-9_.,:-]+$", v):
            val = f"{k}={v}"
        else:
            return None
        new_toks.append(f"-c{val}" if is_att else f"-c {val}")
    if not has_ro:
        new_toks.append("-c default_transaction_read_only=on")
    if not has_to:
        new_toks.append(f"-c statement_timeout={target_ms}")
    return DiagnosticOptions(" ".join(new_toks), eff_to)
