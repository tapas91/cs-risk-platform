"""The agent's output validator (pipeline/agent.py): every number in a brief must appear in a fact it cites.

    .venv/bin/python -m pytest -q tests/test_agent_validate.py

Pure functions, no warehouse and no API key needed."""
from pipeline.agent import numbers, validate
from pipeline.agent_tools import Case


def test_numbers_are_values_not_substrings():
    assert numbers("3 tickets") == {"3"}
    assert "3" not in numbers("30 tickets")
    assert numbers("$1,200 ARR") == numbers("1200 ARR") == {"1200"}
    assert numbers("12% of seats, 0.50 ratio, 10.0 hours") == {"12", "0.5", "10"}


def test_dates_evidence_ids_and_words_are_not_numbers():
    assert numbers("renews on 2026-03-01") == {"2026-03-01"}
    assert numbers("see E17 and E2") == set()
    assert numbers("a Q3 review on v2") == set()


def decision(text, evidence):
    return dict(route="csm_task", priority="normal", headline="h", recommended_action="a",
                brief=[{"text": text, "evidence": evidence}], outreach=dict(needed=False, subject="", body=""))


def case_with(*facts):
    c = Case("t", "a", "2026-10-15", "2026-10-15")
    for f in facts:
        c.fact(f, "test", "k")
    return c


def number_errors(text, evidence, *facts):
    return [e for e in validate(decision(text, evidence), case_with(*facts), "scored") if "number" in e]


def test_number_must_be_in_a_cited_fact():
    assert number_errors("3 urgent tickets are open.", ["E1"], "3 urgent tickets in 90 days") == []
    assert number_errors("3 urgent tickets are open.", ["E1"], "30 urgent tickets in 90 days") != []


def test_number_in_an_uncited_fact_does_not_count():
    assert number_errors("2 failed payments.", ["E1"], "Usage at 40% of its prior level", "2 failed card payments") != []


def test_formatting_differences_pass():
    assert number_errors("ARR is $1,200 and usage is 40%.", ["E1"], "ARR 1200 USD; usage at 40% of its prior level") == []


def test_citing_an_id_and_a_date_is_not_a_wrong_number():
    assert number_errors("Renewal on 2026-12-01 (E1).", ["E1"], "Renewal date 2026-12-01") == []
    assert number_errors("Renewal on 2026-12-02.", ["E1"], "Renewal date 2026-12-01") != []
