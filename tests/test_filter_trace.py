from job_search_email.filter_trace import GateResult, run_filter_gates
from job_search_email.models import JobListing, Profile
from job_search_email.nhs_rules import get_nhs_rules


def _job(**kw) -> JobListing:
    defaults = dict(
        title="Project Manager", company="Acme Industries Ltd", location="Bristol",
        salary_min=65000, description="Lead delivery.", url="https://x/1",
        source="reed", employment_type="permanent",
    )
    defaults.update(kw)
    return JobListing(**defaults)


def _profile() -> Profile:
    return Profile(
        name="Test", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=[], previous_roles=[], target_roles=[],
        open_to=[], not_open_to=[], qualifications=[],
        employment_type=["full-time"], location="Bristol", min_salary=60000,
    )


_SPONSORS = frozenset({"acme industries"})


def _gates(job, **over):
    kw = dict(location_verdict="within", sponsor_set=_SPONSORS,
              nhs_rules=get_nhs_rules(), exclusion_roles=["nurse"])
    kw.update(over)
    return run_filter_gates(job, _profile(), **kw)


def test_all_gates_reported_in_order():
    gates = _gates(_job())
    names = [g.name for g in gates]
    assert names == [
        "Location", "Employment type", "Role suitability",
        "NHS band salary", "Sponsor list",
    ]


def test_clean_job_passes_every_gate():
    gates = _gates(_job())
    assert all(g.passed for g in gates)
    assert not any(g.is_first_reject for g in gates)


def test_contract_job_fails_employment_gate():
    gates = _gates(_job(employment_type="contract"))
    by_name = {g.name: g for g in gates}
    assert by_name["Employment type"].passed is False
    assert by_name["Employment type"].is_first_reject is True


def test_reports_all_gates_even_after_first_reject():
    # Outside location AND non-sponsor: both fail, but only the first is flagged.
    job = _job(location="Aberdeen", company="Tiny")
    gates = _gates(job, location_verdict="outside", sponsor_set=frozenset())
    by_name = {g.name: g for g in gates}
    assert by_name["Location"].passed is False
    assert by_name["Location"].is_first_reject is True
    assert by_name["Sponsor list"].passed is False
    assert by_name["Sponsor list"].is_first_reject is False
    assert len(gates) == 5  # every gate still reported
