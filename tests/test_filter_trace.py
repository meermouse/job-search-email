from job_search_email.filter_trace import GateResult, run_filter_gates
from job_search_email.models import JobListing, Profile
from job_search_email.nhs_rules import get_nhs_rules
from profile_helpers import make_profile


def _job(**kw) -> JobListing:
    defaults = dict(
        title="Project Manager", company="Acme Industries Ltd", location="Bristol",
        salary_min=65000, description="Lead delivery.", url="https://x/1",
        source="reed", employment_type="permanent",
    )
    defaults.update(kw)
    return JobListing(**defaults)


def _profile() -> Profile:
    return make_profile()


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
        "NHS band salary", "Salary", "Sponsor list",
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


def test_below_minimum_salary_fails_salary_gate():
    gates = _gates(_job(salary_min=45000))
    by_name = {g.name: g for g in gates}
    assert by_name["Salary"].passed is False
    assert by_name["Salary"].is_first_reject is True
    assert by_name["Salary"].detail == "salary below minimum: £45,000 < £60,000"


def test_reports_all_gates_even_after_first_reject():
    # Outside location AND non-sponsor: both fail, but only the first is flagged.
    job = _job(location="Aberdeen", company="Tiny")
    gates = _gates(job, location_verdict="outside", sponsor_set=frozenset())
    by_name = {g.name: g for g in gates}
    assert by_name["Location"].passed is False
    assert by_name["Location"].is_first_reject is True
    assert by_name["Sponsor list"].passed is False
    assert by_name["Sponsor list"].is_first_reject is False
    assert len(gates) == 6  # every gate still reported


def test_sponsor_gate_disabled_when_sponsor_set_none():
    job = _job()
    profile = make_profile(filter_sponsors=False, min_salary=80000, location="Bristol")

    gates = run_filter_gates(
        job, profile,
        location_verdict="within",
        sponsor_set=None,
        nhs_rules={},
        exclusion_roles=[],
    )

    sponsor_gate = next(g for g in gates if g.name == "Sponsor list")
    assert sponsor_gate.passed is True
    assert sponsor_gate.detail == "disabled (filter_sponsors=false)"


def _remote_job(**kwargs) -> JobListing:
    defaults = dict(
        title="Digital Manager", company="Acme Analytics Ltd", location="Manchester",
        salary_min=70000, description="", url="https://x.com/1",
        source="reed", employment_type="permanent",
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


def test_gates_remote_verdict_confirmed_passes_location():
    gates = run_filter_gates(
        _remote_job(), make_profile(),
        location_verdict="outside", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
        remote_verdict="remote",
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is True
    assert "confirmed fully remote" in loc.detail


def test_gates_remote_verdict_not_remote_rejects_location():
    gates = run_filter_gates(
        _remote_job(), make_profile(),
        location_verdict="outside", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
        remote_verdict="not_remote",
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is False
    assert loc.is_first_reject is True
    assert loc.detail == "location outside radius and not confirmed fully remote: Manchester"


def test_gates_remote_verdict_unverified_fails_closed():
    gates = run_filter_gates(
        _remote_job(), make_profile(),
        location_verdict="uncertain", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
        remote_verdict="unverified",
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is False
    assert "remote check unavailable" in loc.detail


def test_gates_no_remote_verdict_keeps_legacy_detail():
    gates = run_filter_gates(
        _remote_job(location="Bristol"), make_profile(),
        location_verdict="within", sponsor_set=None,
        nhs_rules={}, exclusion_roles=[],
    )
    loc = next(g for g in gates if g.name == "Location")
    assert loc.passed is True
    assert loc.detail == "within radius (Bristol)"
