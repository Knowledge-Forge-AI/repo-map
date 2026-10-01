"""Child process coverage bootstrap template and installation helper."""

from __future__ import annotations

from pathlib import Path

BOOTSTRAP_TEMPLATE = r'''# Runner-owned bootstrap: no product authority hooks are replaced.
import atexit
import os
import hashlib

_manifest = os.environ.get('COVERAGE_CHILD_MANIFEST_DIR')
_config = os.environ.get('COVERAGE_PROCESS_START')
_token = os.environ.get('COVERAGE_CHILD_REGISTRATION_TOKEN', '')
_invocation = os.environ.get('COVERAGE_SESSION_INVOCATION_ID', '')
_suite = os.environ.get('COVERAGE_SESSION_SUITE', '')
_revision = os.environ.get('COVERAGE_SESSION_REVISION', '')
_pid = os.getpid()
_collector = None
_terminals = {}
_bootstrap_error = ''
_role = os.environ.get('COVERAGE_CHILD_LAUNCH_ROLE', 'inherited-python')
if _role not in {'portable', 'conformance', 'conformance-abrupt', 'inherited-python', 'intentional-victim'}:
    _role = 'unknown'
import sys
_raw_argv = getattr(sys, 'orig_argv', None) or getattr(sys, 'argv', [])
_is_tracker = False
_launch_shape = 'unknown'
for _i, _a in enumerate(_raw_argv):
    if _a == '-c' and _i + 1 < len(_raw_argv):
        _cmd = _raw_argv[_i + 1]
        _prefix = 'from multiprocessing.resource_tracker import main;main('
        if _i + 2 == len(_raw_argv) and _cmd.startswith(_prefix) and _cmd.endswith(')'):
            _inner = _cmd[len(_prefix):-1].strip()
            if _inner.isdigit():
                _is_tracker = True
        if _is_tracker:
            _launch_shape = 'cpython:resource_tracker'
        else:
            _launch_shape = 'cpython:-c'
        break
    elif _a == '-m' and _i + 1 < len(_raw_argv):
        _launch_shape = f"-m:{_raw_argv[_i + 1][:24]}"
        break
    elif _a.endswith('.py'):
        _launch_shape = f"script:{os.path.basename(_a)[:24]}"
        break
if _launch_shape == 'unknown' and getattr(sys, 'argv', []):
    _a0 = sys.argv[0]
    if _a0 == '-c':
        _launch_shape = 'cpython:-c'
    elif _a0 == '-m':
        _launch_shape = '-m'
    elif _a0:
        _launch_shape = f"script:{os.path.basename(_a0)[:24]}"
if _role == 'inherited-python' and _is_tracker:
    _role = 'auxiliary-runtime'
if _is_tracker:
    _pause_fifo = os.environ.get('COVERAGE_CHILD_BOOTSTRAP_PAUSE_FIFO')
    if _pause_fifo and os.path.exists(_pause_fifo):
        try:
            with open(_pause_fifo, 'r', encoding='utf-8') as _pf:
                _pf.readline()
        except Exception:
            pass
_ppid = os.getppid()
_owner = os.environ.get('COVERAGE_CHILD_TEST_OWNER', '')
if len(_owner) != 64 or any(c not in '0123456789abcdef' for c in _owner):
    _owner = ''
if not _owner and os.environ.get('PYTEST_CURRENT_TEST'):
    _owner = hashlib.sha256(os.environ['PYTEST_CURRENT_TEST'].encode()).hexdigest()
_identity = (f'pid={_pid}\ninvocation={_invocation}\nsuite={_suite}\n'
             f'token={_token}\nrevision={_revision}\nrole={_role}\nowner={_owner}\n'
             f'ppid={_ppid}\nlaunch_shape={_launch_shape}\n')


def _disarm_coverage():
    try:
        import coverage
        _cov = getattr(coverage.process_startup, 'coverage', None)
        if _cov is None and hasattr(coverage, 'Coverage'):
            _cov = coverage.Coverage.current()
        if _cov is not None:
            try:
                _cov._auto_save = False
            except Exception:
                pass
            try:
                _cov.stop()
            except Exception:
                pass
        if hasattr(coverage.process_startup, 'coverage'):
            try:
                delattr(coverage.process_startup, 'coverage')
            except Exception:
                pass
    except Exception:
        pass
    for _v in (
        'COVERAGE_PROCESS_START', 'COVERAGE_PROCESS_CONFIG', 'COVERAGE_FILE',
        'COVERAGE_CHILD_MANIFEST_DIR', 'COVERAGE_CHILD_REGISTRATION_TOKEN',
        'COVERAGE_CHILD_LAUNCH_ROLE', 'COVERAGE_CHILD_TEST_OWNER',
        'COVERAGE_SESSION_INVOCATION_ID', 'COVERAGE_SESSION_SUITE',
        'COVERAGE_SESSION_REVISION',
    ):
        try:
            os.environ.pop(_v, None)
        except Exception:
            pass
    if globals().get('_config'):
        _sess = os.path.dirname(globals()['_config'])
        import sys
        if _sess in sys.path:
            try:
                sys.path.remove(_sess)
            except Exception:
                pass


def _write_reg_fail(target_dir, stage, fclass, freason, has_manifest):
    try:
        fpath = os.path.join(target_dir, f'{_pid}.registration_failure')
        with open(fpath, 'w', encoding='utf-8') as _df:
            _df.write(
                f'pid={_pid}\nppid={_ppid}\ninvocation={_invocation}\n'
                f'suite={_suite}\nrevision={_revision}\nrole={_role}\n'
                f'owner={_owner}\nlaunch_shape={_launch_shape}\n'
                f'has_config={int(bool(_config))}\nhas_manifest={int(has_manifest)}\n'
                f'has_token={int(bool(_token))}\n'
                f'token_hash={hashlib.sha256(_token.encode()).hexdigest() if _token else ""}\n'
                f'bootstrap_stage={stage}\nfailure_class={fclass}\n'
                f'failure_reason={freason}\n'
            )
    except Exception:
        pass


if _config:
    _manifest_valid = bool(_manifest and os.path.isdir(_manifest))
    if not _manifest_valid:
        _disarm_coverage()
        if _role != 'auxiliary-runtime':
            _fail_dir = os.path.join(os.path.dirname(_config), 'child_procs')
            if not os.path.isdir(_fail_dir):
                _fail_dir = os.path.dirname(_config)
            _write_reg_fail(_fail_dir, 'manifest_validation', 'missing_manifest_authority', 'manifest_not_found', False)
        _collector = None
    else:
        _keys = [str(_pid), _token] if _token else [str(_pid)]
        _reg_ok = False
        try:
            for _k in _keys:
                with open(os.path.join(_manifest, f'{_k}.start'), 'x', encoding='utf-8') as _sf:
                    _sf.write(_identity + 'cov_start=pending\nbootstrap_error=\n')
                for _suffix in ('exit', 'shard'):
                    _terminals[(_k, _suffix)] = open(
                        os.path.join(_manifest, f'{_k}.{_suffix}'), 'x', encoding='utf-8')
            _reg_ok = True
        except (FileExistsError, OSError) as _exc:
            _disarm_coverage()
            for _h in _terminals.values():
                try:
                    _h.close()
                except Exception:
                    pass
            _terminals = {}
            if _role != 'auxiliary-runtime':
                _fclass = 'token_reuse' if (_token and _k == _token) else 'marker_collision'
                _write_reg_fail(_manifest, 'marker_creation', _fclass, type(_exc).__name__, True)
            _collector = None

        if _reg_ok:
            try:
                import coverage
                if _token:
                    _early = getattr(coverage.process_startup, 'coverage', None)
                    if _early is not None:
                        try:
                            _early._auto_save = False
                            _early.stop()
                        except Exception:
                            pass
                    _collector = coverage.Coverage(config_file=_config,
                        data_file=os.environ['COVERAGE_FILE'], data_suffix=False)
                    _collector.set_option('run:parallel', False)
                    _collector.start()
                else:
                    _collector = coverage.process_startup()
                if _collector is None:
                    _collector = coverage.Coverage.current()
                if _collector is not None and _token:
                    # Initialize only this collector's SQLite schema before the product
                    # installs its audit guard; keep its owned data handle/lifetime.
                    _collector.get_data()
            except Exception as exc:
                _bootstrap_error = type(exc).__name__
                _disarm_coverage()
                _collector = None

            if _token:
                try:
                    os.environ.pop('COVERAGE_CHILD_REGISTRATION_TOKEN', None)
                    os.environ.pop('COVERAGE_FILE', None)
                    if _role in ('portable', 'conformance', 'conformance-abrupt'):
                        os.environ.pop('COVERAGE_CHILD_LAUNCH_ROLE', None)
                except Exception:
                    pass

            for _k in _keys:
                try:
                    with open(os.path.join(_manifest, f'{_k}.start'), 'w', encoding='utf-8') as _sf:
                        _sf.write(_identity + f'cov_start={int(_collector is not None)}\n'
                                  + f'bootstrap_error={_bootstrap_error}\n')
                except Exception:
                    pass

        if _is_tracker:
            _handshake_fifo = os.environ.get('COVERAGE_CHILD_HANDSHAKE_FIFO')
            if _handshake_fifo and os.path.exists(_handshake_fifo):
                try:
                    with open(_handshake_fifo, 'w', encoding='utf-8') as _hf:
                        _hf.write(f'{_pid}:{_role}\n')
                        _hf.flush()
                except Exception:
                    pass
            _release_fifo = os.environ.get('COVERAGE_CHILD_RELEASE_FIFO')
            if _release_fifo and os.path.exists(_release_fifo):
                try:
                    with open(_release_fifo, 'r', encoding='utf-8') as _rf:
                        _rf.readline()
                except Exception:
                    pass


def _finish(_collector=_collector, _terminals=_terminals, _identity=_identity):
    shard = ''
    error = ''
    measurement = 'unavailable'
    try:
        if _collector is not None:
            _collector.stop()
            _collector.save()
            data = _collector.get_data()
            shard = data.data_filename()
            measurement = ('selected_hits' if any(data.lines(f) for f in data.measured_files())
                           else 'no_selected_hits')
    except Exception as exc:
        error = type(exc).__name__
    for (_, suffix), handle in _terminals.items():
        try:
            handle.write((_identity + f'shard={shard}\nerror={error}\ncomplete=1\n'
                          + f'measurement={measurement}\n')
                         if suffix == 'exit' else shard)
            handle.flush()
        finally:
            handle.close()


atexit.register(_finish)
'''

RUNNER_BOOTSTRAP_MARKER = "# Runner-owned bootstrap: no product authority hooks are replaced."


def generate_bootstrap_source() -> str:
    """Return the source code for the child process sitecustomize bootstrap."""
    return BOOTSTRAP_TEMPLATE


def install_bootstrap_directory(bootstrap_dir: Path) -> Path:
    """Install sitecustomize.py in the specified bootstrap directory."""
    target_dir = Path(bootstrap_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    sitecustomize_path = target_dir / "sitecustomize.py"
    sitecustomize_path.write_text(BOOTSTRAP_TEMPLATE, encoding="utf-8")
    return sitecustomize_path


__all__ = (
    "BOOTSTRAP_TEMPLATE",
    "RUNNER_BOOTSTRAP_MARKER",
    "generate_bootstrap_source",
    "install_bootstrap_directory",
)
