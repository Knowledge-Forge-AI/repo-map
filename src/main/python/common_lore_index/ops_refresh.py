"""Compatibility facade for :mod:`common_lore_index.ops.refresh`."""

import sys

from common_lore_index.ops import refresh as _impl

sys.modules[__name__] = _impl
