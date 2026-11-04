"""Exact ANN-only settings preserve SQL, roles and the exact-reference calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from repomap_test_support.w5_component_planner_adapter import (
    FunctionalAdapterRefusal, PLANNER_OPTION, make_functional_adapter,
    selected_options, sql_digest,
)
from repomap_test_support.postgres_container_config import build_psql_wrapper_script


EXPLAIN = 'SET ROLE "w5_experiment_reader";\nBEGIN READ ONLY; EXPLAIN SELECT 1; COMMIT;'
ANN = 'SET ROLE "w5_experiment_reader";\nBEGIN READ ONLY; SELECT 1; COMMIT;'
ALLOWED = {"ann_explain":(sql_digest(EXPLAIN.encode()),),"ann_candidates":(sql_digest(ANN.encode()),)}
READ_ONLY = "-c role=w5_experiment_reader -c default_transaction_read_only=on"


@pytest.mark.parametrize("sql,route", [(EXPLAIN,"ann_explain"),(ANN,"ann_candidates")])
def test_only_two_exact_sql_payloads_get_the_control(sql: str, route: str) -> None:
    actual, options = selected_options(sql.encode(),READ_ONLY,ALLOWED)
    assert actual == route
    assert options == READ_ONLY + " " + PLANNER_OPTION
    assert PLANNER_OPTION == "-c enable_seqscan=off -c enable_sort=off"


@pytest.mark.parametrize("sql", [
    "SELECT exact_reference", "CREATE INDEX fixture", "DROP INDEX fixture",
    "SELECT index_catalog", EXPLAIN+" ", ANN.replace("SELECT 1","SELECT 2"),
])
def test_exact_setup_catalog_cleanup_and_near_matches_are_unchanged(sql: str) -> None:
    assert selected_options(sql.encode(),READ_ONLY,ALLOWED) == ("unchanged",READ_ONLY)
    assert selected_options(sql.encode(),None,ALLOWED) == ("unchanged",None)


@pytest.mark.parametrize("option",["enable_seqscan=on","enable_sort=on"])
def test_preexisting_planner_control_refuses_targeted_invocation(option: str) -> None:
    with pytest.raises(FunctionalAdapterRefusal,match="preexisting"):
        selected_options(EXPLAIN.encode(),"-c "+option,ALLOWED)


@pytest.mark.parametrize("allowed", [{}, {"ann_explain":("bad",),"ann_candidates":("bad",)},
    {"ann_explain":("sha256:"+"a"*64,),"ann_candidates":("sha256:"+"a"*64,)}])
def test_ambiguous_route_configuration_refuses(allowed) -> None:
    with pytest.raises(FunctionalAdapterRefusal):
        selected_options(EXPLAIN.encode(),None,allowed)


def _fake_psql(root: Path) -> tuple[Path,Path]:
    capture = root / "capture.json"
    executable = root / "fixture-transport"
    executable.write_text(
        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        f"Path({str(capture)!r}).write_text(json.dumps({{'argv':sys.argv[1:],'sql':sys.stdin.read(),'options':os.environ.get('PGOPTIONS')}}))\n"
        "print('{}')\n"
    )
    executable.chmod(0o700)
    return executable,capture


@pytest.mark.parametrize("sql,options,expected_route", [
    (EXPLAIN,None,"ann_explain"), (ANN,READ_ONLY,"ann_candidates"),
    ("SELECT exact_reference",READ_ONLY,"unchanged"),
    ("CREATE INDEX fixture",None,"unchanged"),
])
def test_real_subprocess_transport_preserves_all_bytes(
    tmp_path: Path, sql: str, options: str | None, expected_route: str,
) -> None:
    transport,capture = _fake_psql(tmp_path)
    adapter = make_functional_adapter(tmp_path/"adapter",str(transport),{
        "ann_explain":(EXPLAIN,),"ann_candidates":(ANN,),
    })
    environment = os.environ.copy()
    environment.pop("PGOPTIONS",None)
    if options is not None: environment["PGOPTIONS"] = options
    args = ["-qAt","-v","ON_ERROR_STOP=1"]
    completed = subprocess.run([str(adapter.command),*args],input=sql,text=True,env=environment,
                               capture_output=True,check=False,timeout=10)
    assert completed.returncode == 0,completed.stderr
    actual = json.loads(capture.read_bytes())
    assert actual["argv"] == args and actual["sql"] == sql
    assert actual["options"] == selected_options(sql.encode(),options,ALLOWED)[1]
    receipt, = adapter.read_receipts()
    assert receipt["route"] == expected_route
    assert receipt["planner_option_appended"] is (expected_route != "unchanged")
    assert receipt["inherited_options_preserved"] is True
    assert receipt["sql_sha256"] == sql_digest(sql.encode())
    assert "options" not in receipt and "sql" not in receipt
    assert str(tmp_path) not in adapter.receipt.read_text()


@pytest.mark.parametrize("args", [["-c","SELECT bypass"],["--command=SELECT bypass"],["-Xc","SELECT bypass"],["-Xf","public.sql"],
    ["-f","unsafe.sql"],["--file=unsafe.sql"]])
def test_command_or_file_payload_cannot_bypass_stdin_classification(tmp_path: Path,args: list[str]) -> None:
    transport,capture = _fake_psql(tmp_path)
    adapter = make_functional_adapter(tmp_path/"adapter",str(transport),{
        "ann_explain":(EXPLAIN,),"ann_candidates":(ANN,),
    })
    completed = subprocess.run([str(adapter.command),*args],input=EXPLAIN,text=True,
                               capture_output=True,check=False,timeout=10)
    assert completed.returncode == 3 and not capture.exists()
    assert adapter.read_receipts() == ()


def test_two_bindings_have_four_exact_routes_and_no_fifth_digest() -> None:
    extra_explain = EXPLAIN.replace("SELECT 1","SELECT 2")
    extra_ann = ANN.replace("SELECT 1","SELECT 2")
    allowed: dict[str, tuple[str, ...]] = {"ann_explain":(*ALLOWED["ann_explain"],sql_digest(extra_explain.encode())),
               "ann_candidates":(*ALLOWED["ann_candidates"],sql_digest(extra_ann.encode()))}
    assert selected_options(extra_explain.encode(),None,allowed) == ("ann_explain",PLANNER_OPTION)
    assert selected_options(extra_ann.encode(),None,allowed) == ("ann_candidates",PLANNER_OPTION)
    allowed["ann_explain"] += (sql_digest(b"third binding"),)
    with pytest.raises(FunctionalAdapterRefusal):
        selected_options(EXPLAIN.encode(),None,allowed)


def test_maintained_container_shim_forwards_actual_controlled_options(tmp_path: Path) -> None:
    runtime,capture = _fake_psql(tmp_path)
    shim = tmp_path / "fixture-psql"
    shim.write_text(build_psql_wrapper_script(password="unused",runtime=str(runtime),container_name="owned-fixture"))
    shim.chmod(0o700)
    adapter = make_functional_adapter(tmp_path/"adapter",str(shim),{
        "ann_explain":(EXPLAIN,),"ann_candidates":(ANN,),
    })
    environment = os.environ.copy()
    environment["PGOPTIONS"] = READ_ONLY
    completed = subprocess.run([str(adapter.command),"-qAt"],input=EXPLAIN,text=True,env=environment,
                               capture_output=True,check=False,timeout=10)
    assert completed.returncode == 0,completed.stderr
    actual = json.loads(capture.read_bytes())
    assert actual["options"] == READ_ONLY + " " + PLANNER_OPTION
    assert actual["sql"] == EXPLAIN
    assert actual["argv"][:7] == ["exec","-i","-e","PGPASSWORD","-e","PGOPTIONS","owned-fixture"]
