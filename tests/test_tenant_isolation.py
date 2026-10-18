"""Tenant isolation for the dashboard's data layer (app/data.py).

    docker compose exec dashboard pytest -q tests

Signs in as a CSM and a manager from one tenant and asks for another tenant's accounts and agent cases
through every function. Each call must refuse (NotVisible) or return nothing; a CSM must also be refused
accounts in a colleague's book."""
import pytest

import data as D


@pytest.fixture(scope="module")
def con():
    c = D.connect()
    yield c
    c.close()


@pytest.fixture(scope="module")
def people(con):
    u = D.demo_users(con)
    csm = u[(u.role == "csm") & (u.accounts > 0)].iloc[0]
    mgr = u[(u.role == "manager") & (u.tenant_id == csm.tenant_id)].iloc[0]
    as_viewer = lambda r: D.Viewer(r.tenant_id, r.user_id, r.user_name, r.role)
    return as_viewer(csm), as_viewer(mgr)


def other_tenant_account(con, tenant):
    return con.execute("""select tenant_id, account_id from ml.risk_scores where tenant_id <> ?
                          and as_of = (select max(as_of) from ml.risk_scores) limit 1""", [tenant]).fetchone()


def other_tenant_case(con, tenant):
    return con.execute("select case_id, account_id from agent.cases where tenant_id <> ? limit 1", [tenant]).fetchone()


ACCOUNT_FUNCS = [D.account_header, D.risk_history, D.reasons, D.features, D.agent_case, D.usage_weekly]


def test_worklists_stay_in_tenant(con, people):
    for v in people:
        book = D.worklist(con, v)
        assert not book.empty
        ids = set(book.account_id)
        theirs = {r[0] for r in con.execute("select account_id from ml.risk_scores where tenant_id = ?", [v.tenant_id]).fetchall()}
        assert ids <= theirs


def test_csm_sees_only_own_book(con, people):
    csm, _ = people
    assert set(D.worklist(con, csm).owner_id) == {csm.user_id}
    colleague = con.execute("""select account_id from ml.risk_scores where tenant_id = ? and owner_id <> ?
                               and as_of = (select max(as_of) from ml.risk_scores) limit 1""", [csm.tenant_id, csm.user_id]).fetchone()[0]
    for f in ACCOUNT_FUNCS:
        with pytest.raises(D.NotVisible):
            f(con, csm, colleague)


@pytest.mark.parametrize("func", ACCOUNT_FUNCS)
def test_other_tenant_accounts_refused(con, people, func):
    for v in people:
        _, account = other_tenant_account(con, v.tenant_id)
        with pytest.raises(D.NotVisible):
            func(con, v, account)


def test_other_tenant_cases_refused(con, people):
    for v in people:
        found = other_tenant_case(con, v.tenant_id)
        if found is None:
            pytest.skip("no agent cases in another tenant")
        case_id, account = found
        for f in (D.evidence, D.tool_calls):
            with pytest.raises(D.NotVisible):
                f(con, v, case_id)
        with pytest.raises(D.NotVisible):
            D.source_rows(con, v, account, "silver.fct_charge", f"x/{account}")


def test_manager_pages_refused_to_csm(con, people):
    csm, mgr = people
    for f in (D.team_overview, D.agent_activity, D.quarantine_counts):
        with pytest.raises(D.NotVisible):
            f(con, csm)
        assert f(con, mgr) is not None
    assert set(D.data_health(con, mgr).columns) >= {"source_table", "freshness_status"}
