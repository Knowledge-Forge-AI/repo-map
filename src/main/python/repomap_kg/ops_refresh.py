"""Compatibility facade for :mod:`repomap_kg.ops.refresh`."""

import sys

from repomap_kg.ops import refresh as _impl

sys.modules[__name__] = _impl
