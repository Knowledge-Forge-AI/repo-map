from unittest.mock import Mock, patch

import pytest

from scale11_profile_readback import read_final_state


@pytest.mark.parametrize("state,resolved", [
    (("published", "committed", "reconciled", "eligible"), True),
    (("published", "committed", "unresolved", "eligible"), False),
    (None, False),
])
def test_readback_preserves_run_scope_and_requires_resolved_publication(state, resolved):
    connection = Mock()
    connection.execute.return_value.fetchone.side_effect = [(n,) for n in range(7)] + [state]
    with patch("scale11_profile_readback.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        counts, actual = read_final_state(["-h", "localhost", "-p", "5432", "-U", "reader", "-d", "graph"], 7, 9, "stage-test")
    connect.assert_called_once_with(host="localhost", port="5432", user="reader", dbname="graph")
    assert list(counts.values()) == list(range(7))
    assert actual is resolved
    calls = connection.execute.call_args_list
    assert calls[1].args[1] == (7, 9)
    assert calls[5].args[1] == (7, 9)
    assert calls[6].args[1] == (7, 9)
    assert calls[7].args[1] == ("stage-test",)


@pytest.mark.parametrize("row", [None, (), (True,), ("0",)])
def test_readback_refuses_missing_or_malformed_count_evidence(row):
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = row
    with patch("scale11_profile_readback.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        with pytest.raises(ValueError, match="one integer"):
            read_final_state([], 7, 9, "stage-test")
