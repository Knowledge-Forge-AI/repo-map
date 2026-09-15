"""Shared helpers for config extractor tests."""

from __future__ import annotations


def observations_format(observations):
    return observations[0].metadata["format"]
