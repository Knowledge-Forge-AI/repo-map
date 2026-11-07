"""T1-only AMD report-envelope proof; no acquisition, native call or build."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

_PROGRAM = r'''
from contextlib import ExitStack
import json
from pathlib import Path
import sys
from unittest.mock import patch

root, base = (Path(value) for value in sys.argv[1:])
sys.path[:0] = [str(root/'tools'),str(root/'src/main/python'),str(root/'src/test/support/python')]
from ci import qualification_rust_acquisition as acquisition
from ci import rust_pilot_qualification as command
from ci.qualification_rust_accounting import AccountingGap
from common_lore_index.extractors.rust_pilot import prepared_profile

manifest_path = root/'tools/ci/rust_pilot_qualification_manifest.json'
manifest = json.loads(manifest_path.read_bytes())
native = json.loads((base/'t1-native.json').read_bytes())
state = base/'d12';state.mkdir(mode=0o700)
sealed = state/'sealed.json';sealed.write_text('{}',encoding='ascii')
args = ['amd64','--repo-root',str(root),'--d12-state-dir',str(state),
        '--d12-sealed-json',str(sealed),'--manifest',str(manifest_path),
        '--work-dir',str(base/'work'),'--report-dir',str(base/'report')]
wheels = tuple({key:row[key] for key in ('name','bytes','sha256')}
               for row in manifest['wheels'] if row['architecture']=='amd64')
assert len(wheels)==2
with ExitStack() as patches:
    patches.enter_context(patch.object(command,'_positive_d12',return_value=(
        'a'*40,'b'*40,'sha256:'+'a'*64,manifest['sdk']['recipe_sha256'])))
    patches.enter_context(patch.object(command,'_bind_candidate',return_value=None))
    patches.enter_context(patch.object(command,'_verify_sdk',return_value=None))
    patches.enter_context(patch.object(acquisition,'acquire_exact_amd_wheels',return_value=wheels))
    patches.enter_context(patch.object(prepared_profile,'prepare_profile',return_value=manifest['sdk']['profile_sha256']))
    call=patches.enter_context(patch.object(command,'run_native_component',return_value=native))
    code=command.main(args)
    call.assert_called_once()
    call.reset_mock()
    overflow=list(args)
    overflow[overflow.index('--work-dir')+1]=str(base/'overflow-work')
    overflow[overflow.index('--report-dir')+1]=str(base/'overflow-report')
    with patch.object(command,'MAX_REPORT_BYTES',4096):
        try:
            command.main(overflow)
        except RuntimeError as error:
            assert str(error)=='report_bound_exceeded'
        else:
            raise AssertionError('report overflow returned success')
    call.assert_called_once()
    failed_raw=(base/'overflow-report/rust-pilot-qualification.json').read_bytes()
    failed=json.loads(failed_raw)
    assert len(failed_raw)<=4096 and failed['qualified'] is False
    assert failed['reason']=='report_bound_exceeded'
    assert all(row['value'] is None and row['cross_checked'] is False
               for row in failed['counters'].values())
    assert not (base/'overflow-work').exists()
    call.reset_mock()
    late=list(args)
    late[late.index('--work-dir')+1]=str(base/'late-work')
    late[late.index('--report-dir')+1]=str(base/'late-report')
    with patch.object(command,'require_component_accounting',side_effect=AccountingGap({'t1_injected':True})):
        assert command.main(late)==1
    call.assert_called_once()
    refused=json.loads((base/'late-report/rust-pilot-qualification.json').read_bytes())
    assert refused['qualified'] is False and refused['reason']=='aggregate_accounting_unproven'
    completed=refused['failure_evidence']['completed_gold']
    assert completed['comparison_complete'] is True and len(completed['comparisons'])==13
    assert completed['item_claims']==420 and not (base/'late-work').exists()
raw=(base/'report/rust-pilot-qualification.json').read_bytes()
report=json.loads(raw)
assert code==0,{key:report.get(key) for key in ('result','reason','exception_type')}
assert len(raw)<=command.MAX_REPORT_BYTES==1_048_576
assert (report['qualified'],report['result'])==(True,'passed')
assert len(report['evidence']['gold']['comparisons'])==13
assert report['evidence']['gold']['item_claims']==420
assert not (base/'work').exists()
print(len(raw))
'''


def assert_t1_amd_report_fits(root: Path, scratch: Path, native: dict[str, Any]) -> int:
    """Exercise real main/serialization in a fresh interpreter with only T1 facts."""
    base = scratch / "amd-report-envelope"
    base.mkdir(mode=0o700)
    (base / "t1-native.json").write_text(json.dumps(native), encoding="ascii")
    done = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _PROGRAM, str(root), str(base)],
        env={"PATH": os.environ.get("PATH", ""), "TMPDIR": str(base)},
        text=True, capture_output=True, check=False, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    return int(done.stdout.strip())
