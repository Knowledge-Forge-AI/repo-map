"""Bounded PostgreSQL matching with the current reader's ASCII-only fold."""
from __future__ import annotations

from common_lore_index.storage.sqlite_local.raw_payload import ascii_lower
from common_lore_index.storage.sql_core import sql_literal
from retrieval_evaluation_correspondence_observation_records import MAX_QUERY_LENGTH

_OBSERVATION_FIELDS = ("ro.kind", "ro.source_id", "ro.path", "ro.payload_json::text")
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LOWER = "abcdefghijklmnopqrstuvwxyz"


def postgres_literal_observation_match(query: str) -> str:
    """Use fixed expressions; user text selects neither SQL nor a collation.

    ASCII translation equals ``raw_payload.ascii_lower``. C collation makes
    substring matching deterministic even if the database uses an ICU locale.
    SQL and the Python recheck therefore select the same rows before LIMIT.
    Percent, underscore and backslash are ordinary substring characters.
    """
    if type(query) is not str or not query or "\x00" in query or len(query) > MAX_QUERY_LENGTH:
        raise ValueError("current observation query is required")
    needle = sql_literal(ascii_lower(query))
    clauses = (
        f"strpos(translate({field}, '{_UPPER}', '{_LOWER}') COLLATE \"C\", {needle}) > 0"
        for field in _OBSERVATION_FIELDS
    )
    return "(" + " OR ".join(clauses) + ")"
