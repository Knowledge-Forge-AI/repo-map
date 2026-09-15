from __future__ import annotations



import test_sandbox as sandbox_owner

import io

from pathlib import Path

import subprocess


import tarfile

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



def report_archive(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in files.items():
            payload = content.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()



def special_archive(member: tarfile.TarInfo) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        archive.addfile(member)
    return output.getvalue()



class FakeArchiveProcess:
    def __init__(self, payload: bytes, *, status: int = 0):
        self.stdout = io.BytesIO(payload)
        self.status = status
        self.killed = False

    def wait(self):
        return self.status

    def poll(self):
        return None if not self.killed else -9

    def kill(self):
        self.killed = True

