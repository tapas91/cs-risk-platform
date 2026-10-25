"""The agent's run loop (pipeline/agent.py): one bad case costs that case, never the run, and every run is
recorded with its real outcome.

    .venv/bin/python -m pytest -q tests/test_agent_robustness.py

Fallback mode (no API key) with the tools replaced by fakes, on an in-memory DuckDB."""
from contextlib import contextmanager

import duckdb
import pandas as pd
import pytest

from pipeline import agent

AS_OF = pd.Timestamp("2026-10-15")


def fresh():
    con = duckdb.connect()
    agent.ensure_schema(con)
    return con


def queue(*accounts):
    return pd.DataFrame([dict(tenant_id="t", account_id=a, account_name=f"Account {a}", owner_id="csm", as_of=AS_OF,
                              feature_cutoff=AS_OF, trigger="entered_red", risk_prob=0.4, band="red", status="scored")
                         for a in accounts])


def summary_ok(con, case):
    return {"facts": [case.fact("Model risk of churn or downsell in 90 days: 40% (red)", "ml.score_log", "k", 0.4)]}


def no_facts(con, case):
    return {"facts": []}


@contextmanager
def tools(summary=summary_ok, billing=no_facts, work=no_facts, people=no_facts):
    saved = agent.get_risk_summary, agent.get_billing, agent.get_open_work, agent.get_relationship
    agent.get_risk_summary, agent.get_billing, agent.get_open_work, agent.get_relationship = summary, billing, work, people
    try:
        yield
    finally:
        agent.get_risk_summary, agent.get_billing, agent.get_open_work, agent.get_relationship = saved


def run(con, q, run_id="r1"):
    return agent.run_reviews(con, None, q, {"t": "Tenant"}, {}, run_id)


def run_row(con, run_id="r1"):
    return con.execute("select status, handled, failed_cases, error from agent.runs where run_id = ?", [run_id]).fetchone()


def test_a_tool_error_costs_one_case_not_the_run():
    con = fresh()
    summary = lambda c, case: {"error": "no score for this account on this date"} if case.account_id == "B" else summary_ok(c, case)
    with tools(summary=summary):
        result = run(con, queue("A", "B"))
    assert result["status"] == "partial"
    assert con.execute("select account_id from agent.cases").fetchall() == [("A",)]
    assert con.execute("select count(*) from agent.actions").fetchone()[0] == 1
    assert con.execute("select account_id, error from agent.failures").fetchall() == [
        ("B", "CaseUnavailable: no score for this account on this date")]
    status, handled, failed, error = run_row(con)
    assert (status, handled, failed) == ("partial", 1, 1) and "B:" in error


def test_every_case_failing_marks_the_run_failed():
    con = fresh()
    def broken(c, case):
        raise RuntimeError("billing table missing")
    with tools(billing=broken):
        result = run(con, queue("A", "B"))
    assert result["status"] == "failed"
    assert run_row(con)[:3] == ("failed", 0, 2)
    assert con.execute("select count(*) from agent.cases").fetchone()[0] == 0


def test_a_crash_mid_run_keeps_finished_cases_and_records_failed():
    con = fresh()
    real_persist, calls = agent.persist, []
    def persist_then_crash(c, run_id, results):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        real_persist(c, run_id, results)
    agent.persist = persist_then_crash
    try:
        with tools(), pytest.raises(OSError):
            run(con, queue("A", "B", "C"))
    finally:
        agent.persist = real_persist
    assert con.execute("select count(*) from agent.cases").fetchone()[0] == 1  # the first case survived
    status, _, _, error = run_row(con)
    assert status == "failed" and "disk full" in error


def test_an_empty_queue_is_an_ok_run():
    con = fresh()
    assert run(con, queue().iloc[0:0])["status"] == "ok"
    assert run_row(con)[:3] == ("ok", 0, 0)


def test_rejected_brief_is_kept_but_creates_no_action():
    con = fresh()
    case = agent.Case("t", "A", AS_OF.date(), AS_OF)
    row = next(queue("A").itertuples(index=False))._replace(as_of=AS_OF.date())
    decision = dict(route="csm_task", priority="high", headline="h", brief=[], recommended_action="Call",
                    outreach=dict(needed=False, subject="", body=""))
    agent.persist(con, "r1", [dict(row=row, case=case, decision=decision, vstatus="rejected", errors=["x"],
                                   decided_by="fallback_after_validation", usage={}, log=[], turns=0)])
    assert con.execute("select count(*) from agent.cases").fetchone()[0] == 1
    assert con.execute("select count(*) from agent.actions").fetchone()[0] == 0


def test_triage_stops_retrying_after_three_failures():
    con = fresh()
    con.execute("create schema ml")
    con.execute("""create table ml.risk_scores (as_of date, tenant_id varchar, account_id varchar, owner_id varchar,
                   risk_prob double, band varchar, status varchar, rank_in_book integer, days_to_renewal integer, priority double)""")
    for acc in ("A", "B"):
        con.execute("insert into ml.risk_scores values ('2026-10-08','t',?,'csm',0.05,'green','scored',9,200,1)", [acc])
        con.execute("insert into ml.risk_scores values ('2026-10-15','t',?,'csm',0.40,'red','scored',9,200,1)", [acc])
    for _ in range(3):
        con.execute("insert into agent.failures values ('r','t','A','2026-10-15','entered_red','boom',now())")
    con.execute("insert into agent.failures values ('r','t','B','2026-10-15','entered_red','boom',now())")
    assert sorted(agent.triage(con).account_id) == ["B"]  # A gave up after 3 attempts; B is retried
