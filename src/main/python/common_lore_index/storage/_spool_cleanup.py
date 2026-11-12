"""Complete the known family-spool cleanup chain without losing a primary."""
from __future__ import annotations

from collections.abc import Iterable

from common_lore_index.storage.row_spool import RowSpool


def close_spooled_rows(
    families: Iterable[Iterable[dict[str, object]]], *, preserve_primary: bool = False,
) -> None:
    first_error: BaseException | None = None
    for rows in families:
        if isinstance(rows, RowSpool):
            try:
                rows.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
    if not preserve_primary and first_error is not None:
        raise first_error
