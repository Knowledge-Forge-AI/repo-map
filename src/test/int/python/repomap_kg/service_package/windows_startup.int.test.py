import os

import pytest
import run_windows_async15_tests as probe


pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="ASYNC15 native evidence requires Windows"
)


@pytest.mark.parametrize("logon_type", ("InteractiveToken", "S4U"))
def test_native_scheduler_probe_is_bounded_and_cleans_its_unique_task(logon_type):
    com = probe._task_scheduler_com_probe()
    result = probe._native_probe(logon_type)

    assert com["available"] is True
    assert result["logon_type"] == logon_type
    assert result["schtasks_available"] is True
    assert result["sc_available"] is True
    assert result["task_create_exit"] == 0
    assert result["task_query_exit"] == 0
    assert result["task_xml_valid"] is True
    assert result["task_xml_current_user"] is True
    assert result["task_xml_least_privilege"] is True
    assert result["task_xml_exact_argv"] is True
    assert result["task_run_exit"] == 0
    assert result["task_end_exit"] == 0
    assert result["task_delete_exit"] == 0
    assert result["task_delete_repeat_exit"] != 0
    assert result["task_absent_exit"] != 0
    assert result["temporary_cleanup"] is True
    assert result["probe_error"] is None
