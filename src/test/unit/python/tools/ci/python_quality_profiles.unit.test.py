from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from ci.python_quality_profiles import (
    MAX_PHYSICAL_LINES,
    SCHEMA,
    QualityProfileError,
    check_paths,
    count_physical_lines,
    main,
)


def test_empty_paths_returns_passed_without_invoking_subprocesses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def _fail_run(*args: Any, **kwargs: Any) -> Any:
        pytest.fail('subprocess.run should not be called for empty paths')

    monkeypatch.setattr('subprocess.run', _fail_run)
    result = check_paths((), tmp_path)
    assert result['status'] == 'passed'
    assert result['schema'] == SCHEMA
    assert result['paths'] == []
    assert result['analyzed_paths'] == []
    assert result['checks']['ruff']['count'] == 0
    assert result['checks']['mypy']['count'] == 0
    assert result['checks']['file_length']['count'] == 0


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / 'outside.py'
    outside.write_text('x: int = 1\n', encoding='utf-8')

    with pytest.raises(QualityProfileError, match='escapes repository root'):
        check_paths(('../outside.py',), tmp_path)

    with pytest.raises(QualityProfileError, match='escapes repository root'):
        check_paths((str(outside),), tmp_path)


def test_path_escape_with_raise_on_error_false_returns_tool_failure(tmp_path: Path) -> None:
    result = check_paths(('../escape.py',), tmp_path, raise_on_error=False)
    assert result['status'] == 'failed'
    assert result['classification'] == 'tool-failure'
    assert result['tool_failure'] == 'QualityProfileError'


def test_nonexistent_path_raises_quality_profile_error(tmp_path: Path) -> None:
    with pytest.raises(QualityProfileError, match='not an existing file'):
        check_paths(('does_not_exist.py',), tmp_path)


def test_repeated_filenames_in_different_directories_no_mypy_collision(tmp_path: Path) -> None:
    sub1 = tmp_path / 'sub1'
    sub2 = tmp_path / 'sub2'
    sub1.mkdir()
    sub2.mkdir()
    f1 = sub1 / 'same.unit.test.py'
    f2 = sub2 / 'same.unit.test.py'
    f1.write_text('value_a: int = 10\n', encoding='utf-8')
    f2.write_text('value_b: str = "ok"\n', encoding='utf-8')

    result = check_paths(('sub1/same.unit.test.py', 'sub2/same.unit.test.py'), tmp_path)
    assert result['status'] == 'passed'
    assert result['analyzed_paths'] == ['sub1/same.unit.test.py', 'sub2/same.unit.test.py']
    assert result['checks']['mypy']['status'] == 'passed'
    assert result['checks']['ruff']['status'] == 'passed'


def test_repeated_identical_path_is_deduplicated_cleanly(tmp_path: Path) -> None:
    f = tmp_path / 'single.py'
    f.write_text('x: int = 1\n', encoding='utf-8')

    result = check_paths(('single.py', 'single.py'), tmp_path)
    assert result['status'] == 'passed'
    assert result['analyzed_paths'] == ['single.py']


def test_mypy_checks_body_of_untyped_functions(tmp_path: Path) -> None:
    f = tmp_path / 'untyped.py'
    f.write_text('def untyped_func():\n    x: int = "string assigned to int"\n', encoding='utf-8')

    result = check_paths(('untyped.py',), tmp_path)
    assert result['status'] == 'failed'
    assert result['checks']['mypy']['status'] == 'failed'
    findings = result['checks']['mypy']['findings']
    assert len(findings) >= 1
    assert any('assignment' in finding['code'] or 'Incompatible' in finding['message'] for finding in findings)


def test_ruff_full_f_detects_unused_import_and_undefined_variable(tmp_path: Path) -> None:
    f = tmp_path / 'lint_fail.py'
    f.write_text('import sys\ndef foo():\n    return missing_symbol\n', encoding='utf-8')

    result = check_paths(('lint_fail.py',), tmp_path)
    assert result['status'] == 'failed'
    assert result['checks']['ruff']['status'] == 'failed'
    codes = {finding['code'] for finding in result['checks']['ruff']['findings']}
    assert 'F401' in codes
    assert 'F821' in codes


def test_file_length_zero_debt_admission_limit_400_lines(tmp_path: Path) -> None:
    f_ok = tmp_path / 'ok.py'
    f_ok.write_bytes(b'x = 1\n' * MAX_PHYSICAL_LINES)
    assert count_physical_lines(f_ok) == 400

    result_ok = check_paths(('ok.py',), tmp_path)
    assert result_ok['status'] == 'passed'
    assert result_ok['checks']['file_length']['status'] == 'passed'

    f_long = tmp_path / 'too_long.py'
    f_long.write_bytes(b'x = 1\n' * (MAX_PHYSICAL_LINES + 1))
    assert count_physical_lines(f_long) == 401

    result_bad = check_paths(('too_long.py',), tmp_path)
    assert result_bad['status'] == 'failed'
    assert result_bad['checks']['file_length']['status'] == 'failed'
    assert result_bad['checks']['file_length']['findings'][0]['line_count'] == 401


def test_clean_file_passes_all_checks(tmp_path: Path) -> None:
    f = tmp_path / 'clean.py'
    f.write_text('from __future__ import annotations\n\ndef add(a: int, b: int) -> int:\n    return a + b\n', encoding='utf-8')

    result = check_paths(('clean.py',), tmp_path)
    assert result['status'] == 'passed'
    assert result['checks']['ruff']['status'] == 'passed'
    assert result['checks']['mypy']['status'] == 'passed'
    assert result['checks']['file_length']['status'] == 'passed'


def test_fail_closed_on_malformed_ruff_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(importlib.metadata, 'version', {'mypy': '2.1.0', 'ruff': '0.16.2'}.__getitem__)
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')

    def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if '--show-files' in cmd:
            return subprocess.CompletedProcess(cmd, 0, 'target.py\n', '')
        return subprocess.CompletedProcess(cmd, 1, 'NOT_VALID_JSON', '')

    monkeypatch.setattr('subprocess.run', mock_run)
    with pytest.raises(QualityProfileError, match='malformed JSON'):
        check_paths(('target.py',), tmp_path)


def test_fail_closed_on_ruff_tool_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(importlib.metadata, 'version', {'mypy': '2.1.0', 'ruff': '0.16.2'}.__getitem__)
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')

    def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if '--show-files' in cmd:
            return subprocess.CompletedProcess(cmd, 0, 'target.py\n', '')
        return subprocess.CompletedProcess(cmd, 2, '', 'crash')

    monkeypatch.setattr('subprocess.run', mock_run)
    with pytest.raises(QualityProfileError, match='Ruff tool failure'):
        check_paths(('target.py',), tmp_path)


def test_fail_closed_on_mypy_tool_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(importlib.metadata, 'version', {'mypy': '2.1.0', 'ruff': '0.16.2'}.__getitem__)
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')

    def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if '--show-files' in cmd:
            return subprocess.CompletedProcess(cmd, 0, 'target.py\n', '')
        if '--select' in cmd:
            return subprocess.CompletedProcess(cmd, 0, '[]', '')
        if 'mypy' in cmd:
            return subprocess.CompletedProcess(cmd, 2, '', 'crash')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr('subprocess.run', mock_run)
    with pytest.raises(QualityProfileError, match='mypy tool failure'):
        check_paths(('target.py',), tmp_path)


def test_fail_closed_on_mypy_unparseable_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(importlib.metadata, 'version', {'mypy': '2.1.0', 'ruff': '0.16.2'}.__getitem__)
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')

    def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if '--show-files' in cmd:
            return subprocess.CompletedProcess(cmd, 0, 'target.py\n', '')
        if '--select' in cmd:
            return subprocess.CompletedProcess(cmd, 0, '[]', '')
        if 'mypy' in cmd:
            return subprocess.CompletedProcess(cmd, 1, 'Unparseable error line\n', '')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr('subprocess.run', mock_run)
    with pytest.raises(QualityProfileError, match='without parseable findings'):
        check_paths(('target.py',), tmp_path)


def test_isolated_tool_absent_package_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')
    monkeypatch.setattr(importlib.metadata, 'version', lambda name: (_ for _ in ()).throw(importlib.metadata.PackageNotFoundError(name)))
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        check_paths(('target.py',), tmp_path)
    res = check_paths(('target.py',), tmp_path, raise_on_error=False)
    assert res['status'] == 'failed'
    assert res['classification'] == 'tool-failure'
    assert res['tool_failure'] == 'PackageNotFoundError'
    assert res['analyzed_paths'] == []


def test_isolated_tool_wrong_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')
    monkeypatch.setattr(importlib.metadata, 'version', lambda name: '9.9.9' if name == 'mypy' else '0.16.2')
    with pytest.raises(QualityProfileError, match='unexpected mypy version'):
        check_paths(('target.py',), tmp_path)
    res = check_paths(('target.py',), tmp_path, raise_on_error=False)
    assert res['status'] == 'failed'
    assert res['classification'] == 'tool-failure'
    assert res['tool_failure'] == 'QualityProfileError'
    assert res['analyzed_paths'] == []


def test_preserve_completed_evidence_when_mypy_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(importlib.metadata, 'version', {'mypy': '2.1.0', 'ruff': '0.16.2'}.__getitem__)
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')

    def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if '--show-files' in cmd:
            return subprocess.CompletedProcess(cmd, 0, 'target.py\n', '')
        if '--select' in cmd:
            return subprocess.CompletedProcess(cmd, 0, '[]', '')
        if 'mypy' in cmd:
            return subprocess.CompletedProcess(cmd, 2, '', 'crash')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    monkeypatch.setattr('subprocess.run', mock_run)
    res = check_paths(('target.py',), tmp_path, raise_on_error=False)
    assert res['status'] == 'failed'
    assert res['classification'] == 'tool-failure'
    assert res['tool_failure'] == 'QualityProfileError'
    assert res['analyzed_paths'] == []
    assert res['checks']['file_length']['status'] == 'passed'
    assert res['checks']['ruff']['status'] == 'passed'
    assert res['checks']['mypy']['status'] == 'failed'


def test_preserve_completed_evidence_when_ruff_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / 'target.py'
    f.write_text('x: int = 1\n', encoding='utf-8')

    def mock_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        if '--show-files' in cmd:
            return subprocess.CompletedProcess(cmd, 0, 'target.py\n', '')
        return subprocess.CompletedProcess(cmd, 2, '', 'crash')

    monkeypatch.setattr('subprocess.run', mock_run)
    res = check_paths(('target.py',), tmp_path, raise_on_error=False)
    assert res['status'] == 'failed'
    assert res['classification'] == 'tool-failure'
    assert res['checks']['file_length']['status'] == 'passed'
    assert res['checks']['ruff']['status'] == 'failed'
    assert res['analyzed_paths'] == []


def test_code_findings_distinct_from_tool_failure(tmp_path: Path) -> None:
    f = tmp_path / 'bad_type.py'
    f.write_text('def f() -> int:\n    return "string"\n', encoding='utf-8')
    res = check_paths(('bad_type.py',), tmp_path, raise_on_error=False)
    assert res['status'] == 'failed'
    assert 'tool_failure' not in res
    assert res.get('classification') != 'tool-failure'
    assert res['checks']['mypy']['status'] == 'failed'
    assert len(res['checks']['mypy']['findings']) >= 1
    assert res['analyzed_paths'] == ['bad_type.py']


def test_real_tools_repeated_package_basenames_and_reexports(tmp_path: Path) -> None:
    pa = tmp_path / 'pkg_a' / 'common'
    pb = tmp_path / 'pkg_b' / 'common'
    pa.mkdir(parents=True)
    pb.mkdir(parents=True)
    (pa / 'mod.py').write_text('val_a: int = 1\n', encoding='utf-8')
    (pb / 'mod.py').write_text('val_b: str = "ok"\n', encoding='utf-8')
    (tmp_path / 'pkg_a' / '__init__.py').write_text('from .common.mod import val_a as val_a\n', encoding='utf-8')
    targets = ('pkg_a/__init__.py', 'pkg_a/common/mod.py', 'pkg_b/common/mod.py')
    res = check_paths(targets, tmp_path)
    assert res['status'] == 'passed'
    assert set(res['analyzed_paths']) == set(targets)


def test_real_tools_direct_and_imported_same_file(tmp_path: Path) -> None:
    (tmp_path / 'dep.py').write_text('def add(a: int, b: int) -> int:\n    return a + b\n', encoding='utf-8')
    (tmp_path / 'caller.py').write_text('import dep\nx: int = dep.add(1, 2)\n', encoding='utf-8')
    res = check_paths(('dep.py', 'caller.py'), tmp_path)
    assert res['status'] == 'passed'
    assert set(res['analyzed_paths']) == {'dep.py', 'caller.py'}


def test_real_tools_dependency_diagnostics_reported(tmp_path: Path) -> None:
    (tmp_path / 'dep_err.py').write_text('bad: int = "type error"\n', encoding='utf-8')
    (tmp_path / 'target_app.py').write_text('import dep_err\n', encoding='utf-8')
    res = check_paths(('target_app.py',), tmp_path)
    assert res['status'] == 'failed'
    assert res['checks']['mypy']['status'] == 'failed'
    findings = res['checks']['mypy']['findings']
    assert any('dep_err.py' in f['path'] and f.get('dependency') is True for f in findings)


def test_real_tools_spaces_and_dotted_owner_names(tmp_path: Path) -> None:
    folder = tmp_path / 'folder with spaces'
    folder.mkdir()
    f = folder / 'special.unit.test.py'
    f.write_text('from __future__ import annotations\nx: int = 10\n', encoding='utf-8')
    rel = 'folder with spaces/special.unit.test.py'
    res = check_paths((rel,), tmp_path)
    assert res['status'] == 'passed'
    assert res['analyzed_paths'] == [rel]


def test_duration_measured(tmp_path: Path) -> None:
    res = check_paths((), tmp_path)
    assert 'duration_seconds' in res
    assert isinstance(res['duration_seconds'], (int, float))
    assert res['duration_seconds'] >= 0


def test_cli_main_exit_codes_and_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['--repo-root', str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['status'] == 'passed'

    clean_file = tmp_path / 'clean.py'
    clean_file.write_text('x: int = 1\n', encoding='utf-8')
    assert main(['--repo-root', str(tmp_path), '--format', 'text', 'clean.py']) == 0
    text_out = capsys.readouterr().out
    assert 'python-quality-profiles: passed' in text_out

    bad_file = tmp_path / 'bad.py'
    bad_file.write_text('import sys\n', encoding='utf-8')
    assert main(['--repo-root', str(tmp_path), 'bad.py']) == 1
    bad_out = json.loads(capsys.readouterr().out)
    assert bad_out['status'] == 'failed'

    assert main(['--repo-root', str(tmp_path), '../outside.py']) == 2
    err_out = json.loads(capsys.readouterr().out)
    assert err_out['classification'] == 'tool-failure'

