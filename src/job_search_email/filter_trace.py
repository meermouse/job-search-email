from dataclasses import dataclass

from .filter import (
    _check_employment_type,
    _check_location,
    _check_nhs_band_salary,
    _check_role_suitability,
    _check_salary,
    _check_sponsor,
)
from .models import JobListing, Profile


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    is_first_reject: bool


def run_filter_gates(
    job: JobListing,
    profile: Profile,
    *,
    location_verdict: str,
    sponsor_set: frozenset[str] | None,
    nhs_rules: dict,
    exclusion_roles: list[str],
) -> list[GateResult]:
    gates: list[GateResult] = []

    # Location — reuse the real gate by deriving rejected_locations from the verdict.
    rejected_locations = frozenset({job.location}) if location_verdict == "outside" else frozenset()
    loc = _check_location(job, rejected_locations)
    gates.append(GateResult(
        "Location", loc is None,
        f"{location_verdict} radius ({job.location or 'not stated'})"
        if loc is None else (loc.reject_reason or ""),
        False,
    ))

    et = _check_employment_type(job)
    gates.append(GateResult(
        "Employment type", not et.rejected,
        (et.reject_reason or f"{job.employment_type or 'unknown'}"),
        False,
    ))

    role = _check_role_suitability(job, exclusion_roles)
    gates.append(GateResult(
        "Role suitability", role is None,
        "no excluded term matched" if role is None else (role.reject_reason or ""),
        False,
    ))

    nhs = _check_nhs_band_salary(job, nhs_rules, profile.min_salary)
    gates.append(GateResult(
        "NHS band salary", nhs is None,
        "n/a (no NHS band in title/description)" if nhs is None else (nhs.reject_reason or ""),
        False,
    ))

    salary = _check_salary(job, profile.min_salary)
    gates.append(GateResult(
        "Salary", salary is None,
        f"£{job.salary_min:,} ≥ £{profile.min_salary:,}" if salary is None and job.salary_min is not None
        else ("not stated" if salary is None else (salary.reject_reason or "")),
        False,
    ))

    sponsor = _check_sponsor(job, sponsor_set) if sponsor_set is not None else None
    if sponsor_set is None:
        sponsor_detail = "disabled (filter_sponsors=false)"
    elif sponsor is None:
        sponsor_detail = "n/a (NHS source)" if job.source == "nhs" else "on approved sponsor list"
    else:
        sponsor_detail = sponsor.reject_reason or ""
    gates.append(GateResult("Sponsor list", sponsor is None, sponsor_detail, False))

    for gate in gates:
        if not gate.passed:
            gate.is_first_reject = True
            break

    return gates
