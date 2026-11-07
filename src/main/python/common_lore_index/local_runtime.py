"""Compatibility facade for :mod:`common_lore_index.runtime.local`."""

import sys

from common_lore_index.runtime import local as _impl

sys.modules[__name__] = _impl
