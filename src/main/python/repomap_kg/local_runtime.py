"""Compatibility facade for :mod:`repomap_kg.runtime.local`."""

import sys

from repomap_kg.runtime import local as _impl

sys.modules[__name__] = _impl
