"""Ledger reconciliation helpers for the tiny public installed-experience fixture."""

from __future__ import annotations


class LedgerWindow:
    """A closed window of labelled ledger amounts."""

    def __init__(self, entries):
        self.entries = list(entries)

    def total(self):
        return sum(amount for _label, amount in self.entries)


def reconcile_ledger_totals(entries):
    """Return the reconciled total of one ledger window."""
    return LedgerWindow(entries).total()
