"""Actual isolated tool subprocesses with runtime/archive imports prohibited."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
import sys


def run_component_cli(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[5]
    code = f'''import importlib.abc, runpy, sys
root={str(root)!r}
sys.path[:0]=[root+'/tools',root+'/src/main/python',root+'/src/test/support/python']
class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {{'numpy','onnxruntime','tokenizers','fixture_worker'}}:
            raise AssertionError('forbidden runtime or archived-source import')
sys.meta_path.insert(0,RejectRuntime())
def assert_absent():
    assert not any(name.split('.')[0] in {{'numpy','onnxruntime','tokenizers','fixture_worker'}} for name in sys.modules)
assert_absent()
import retrieval_semantic_raw_component
import retrieval_semantic_component_dossier
sys.argv=['retrieval_semantic_component_dossier',*{list(argv)!r}]
try:
    runpy.run_path(root+'/tools/retrieval_semantic_component_dossier.py',run_name='__main__')
finally:
    assert_absent()
'''
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT"):
        environment.pop(key, None)
    return subprocess.run(
        [sys.executable,"-I","-B","-c",code], env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )


def build_argv(sources, output: Path, *, models: bool = True) -> list[str]:
    args = ["build", "--paired-report",str(sources.paired),"--output",str(output)]
    for generation in (1,2):
        args += [f"--journal-{generation}",str(sources.journals[generation]),
                 f"--result-{generation}",str(sources.results[generation])]
        if models:
            args += [f"--model-{generation}",str(sources.models[generation])]
    return args


__all__ = ["build_argv", "run_component_cli"]
