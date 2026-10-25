"""The agent's triage (pipeline/agent.py): which flagged accounts get reviewed, and the 7-day cooldown.

    .venv/bin/python -m pytest -q tests/test_agent_triage.py

Builds the two tables triage reads in an in-memory DuckDB; no warehouse and no API key needed."""
import duckdb
import pytest

from pipeline import agent


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("create schema ml")
    c.execute("""create table ml.risk_scores (as_of date, tenant_id varchar, account_id varchar, owner_id varchar,
                 risk_prob double, band varchar, status varchar, rank_in_book integer, days_to_renewal integer, priority double)""")
    agent.ensure_schema(c)
    # last week every account was green at 5%; this week each one trips a different trigger
    for acc, prob, band, status in (("jump", 0.20, "yellow", "scored"), ("red", 0.40, "red", "scored"),
                                    ("notice", 0.30, "yellow", "customer_notice")):
        c.execute("insert into ml.risk_scores values ('2026-10-08','t',?,'csm',0.05,'green','scored',9,200,1)", [acc])
        c.execute("insert into ml.risk_scores values ('2026-10-15','t',?,?,?,?,?,9,200,1)", [acc, "csm-" + acc, prob, band, status])
    return c


def reviewed(con, account, as_of):
    con.execute("insert into agent.cases (case_id, tenant_id, account_id, as_of) values (?, 't', ?, ?)",
                [f"t|{account}|{as_of}", account, as_of])


def queued(con):
    return dict(zip(agent.triage(con).account_id, agent.triage(con).trigger))


def test_flags_each_trigger(con):
    assert queued(con) == {"jump": "risk_jump", "red": "entered_red", "notice": "new_notice"}


def test_recent_review_cools_down_unless_things_got_worse(con):
    for acc in ("jump", "red", "notice"):
        reviewed(con, acc, "2026-10-12")
    assert queued(con) == {"red": "entered_red", "notice": "new_notice"}


def test_review_older_than_the_cooldown_does_not_count(con):
    reviewed(con, "jump", "2026-10-08")
    assert "jump" in queued(con)


def test_same_score_date_is_never_reviewed_twice(con):
    for acc in ("jump", "red", "notice"):
        reviewed(con, acc, "2026-10-15")
    assert queued(con) == {}
