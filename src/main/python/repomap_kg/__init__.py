"""Transitional legacy namespace for CLOE through v0.1.x (ADR 0123).

Only the selected installed-identity constants and version are re-exported from
``common_lore_index``; former internal modules are not provided here.
"""

from common_lore_index import (
    DISTRIBUTION_NAME as DISTRIBUTION_NAME,
    IMPORT_PACKAGE as IMPORT_PACKAGE,
    PREFERRED_CLI as PREFERRED_CLI,
    __version__ as __version__,
)
