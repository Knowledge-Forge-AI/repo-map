"""Portable mixed-language worker on the pinned native Python supplier; no application build."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
import textwrap

import typing_extensions

from repomap_kg.runtime import python_payload, release
from repomap_test_support import d12_core_image as d12
from repomap_test_support.portable_worker_scenarios import package_worker_code
from repomap_test_support.resource_docker_current import CurrentRunDockerContainers
from repomap_test_support.resource_run import active_resource_run

PROGRAM = textwrap.dedent('''
    import json, os, pathlib, re, sys
    sys.path[:0] = ['/probe/code/src/main/python', '/probe/support']
    from repomap_kg.artifacts.store import FileSystemArtifactStore
    from repomap_kg.coordinator._portable_capability import create_portable_capability
    from repomap_kg.coordinator._portable_worker_launch import run_portable_worker
    from repomap_test_support.portable_worker_scenarios import create_test_sealed_capability, coordinator_test_limits
    from repomap_kg.extractors.languages import go_helper
    tag = go_helper.platform_tag()
    binaries = pathlib.Path(go_helper.__file__).resolve().parents[2] / '_bin'
    executable = binaries / tag / go_helper.HELPER_NAME
    root = pathlib.Path('/probe/work'); root.mkdir(mode=0o700)
    workspace = root / 'workspace'; workspace.mkdir(mode=0o700)
    store = FileSystemArtifactStore(root / 'store')
    seed = root / 'sup_seed_src_job-probe'; seed.mkdir()
    (seed / 'main.py').write_text('VALUE = 1\\n')
    (seed / 'helper.go').write_text('package main\\nfunc Greet() string { return "hello" }\\n')
    capability = create_test_sealed_capability(root, store, workspace, job_id='job-probe')
    result = run_portable_worker(create_portable_capability(root, capability),
                                {'job_id': capability.job_id, 'attempt': 1}, coordinator_test_limits())
    record = {'python': sys.version.split()[0], 'status': result.terminal.get('status'),
              'category': result.terminal.get('error_category'), 'cleaned': result.process_group_cleaned,
              'audit': re.findall(r'AUDIT_DENIED:[A-Za-z0-9_.:-]+', result.stderr),
              'helper_tag': tag, 'helper_present': executable.is_file(),
              'helper_executable': os.access(executable, os.X_OK),
              'helper_entries': sorted(str(p.relative_to(binaries)) for p in binaries.rglob('*')),
              'cause': re.findall(r'refresh-failure:[A-Za-z0-9_:-]+', result.stderr)}
    print(json.dumps(record), flush=True)
    assert record['status'] == 'succeeded' and record['cleaned'], record
    assert not list(workspace.iterdir())
''')

# Test-only observation preserves every real refusal; it grants no additional authority.
TRACE = textwrap.dedent('''
    import os, sys
    from repomap_kg.coordinator import _portable_authority as authority
    original = authority._validate_audit_event
    def observed(event, args, *rest):
        try:
            return original(event, args, *rest)
        except PermissionError:
            os.write(2, ('AUDIT_DENIED:' + event + ':' + sys._getframe(2).f_code.co_name + '\\n').encode())
            raise
    authority._validate_audit_event = observed
''')


def _archive(code: Path) -> bytes:
    support = Path(__file__).resolve().parents[6] / 'src/test/support/python/repomap_test_support'
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        archive.add(code, arcname='probe/code', filter=lambda item: None if '__pycache__' in item.name else item)
        archive.add(support, arcname='probe/support/repomap_test_support',
                    filter=lambda item: None if '__pycache__' in item.name else item)
        archive.add(typing_extensions.__file__, arcname='probe/code/src/main/python/typing_extensions.py')
        raw = TRACE.encode(); member = tarfile.TarInfo('probe/code/src/main/python/sitecustomize.py')
        member.size = len(raw); member.mode = 0o644; archive.addfile(member, io.BytesIO(raw))
    assert buffer.tell() < 20_000_000
    return buffer.getvalue()


def test_packaged_mixed_worker_on_native_python_supplier(tmp_path, capsys) -> None:
    run = active_resource_run(); assert run is not None
    client = d12.locate_run_boundary().client
    machine = str(client.info().get('Architecture') or '').lower()
    assert machine in ('arm64', 'aarch64', 'amd64', 'x86_64')
    platform = 'linux/arm64' if machine in ('arm64', 'aarch64') else 'linux/amd64'
    base = d12.verify_bases(client, platform, (release.PYTHON_RELEASE_IMAGE,))[release.PYTHON_RELEASE_IMAGE]
    expected = (python_payload.PYTHON_31216_ARM64_CONFIG if platform == 'linux/arm64'
                else python_payload.PYTHON_31216_AMD64_CONFIG)
    assert base['id'] == expected
    code = tmp_path / 'code'
    package_worker_code(code)
    owner = CurrentRunDockerContainers(run, client)
    identity = owner.create(str(base['id']), ['-I', '-B', '-c', PROGRAM],
                            role='packaged-native-worker', entrypoint=['python3'], network_mode='none')
    try:
        container = client.containers.get(identity)
        assert container.put_archive('/', _archive(code))
        container.start()
        result = container.wait(timeout=60)
        output = container.logs(stdout=True, stderr=False).decode()
        error = container.logs(stdout=False, stderr=True).decode()[-4000:]
        with capsys.disabled():
            print('NATIVE_PACKAGED_WORKER_JSON:' + output.strip(), flush=True)
        assert result['StatusCode'] == 0, (output, error)
        assert json.loads(output)['python'] == release.PYTHON_RELEASE_VERSION
    finally:
        owner.cleanup(identity)
    owner.verify_baseline()
