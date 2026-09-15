from __future__ import annotations

import test_sandbox as sandbox_owner





from pathlib import Path

import subprocess


import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture(autouse=True)
def _capacity_boundary(monkeypatch):
    # Lifecycle owners isolate capacity IO; the capacity suite owns its contract.
    monkeypatch.setattr(sandbox_owner, "bind_backing_capacity", lambda *_args, **_kwargs: None)



def completed(command, status=0, stdout=""):
    return subprocess.CompletedProcess(command, status, stdout=stdout, stderr="")



class FinishedFollower:
    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0



def finished_follower(_command):
    return FinishedFollower()

