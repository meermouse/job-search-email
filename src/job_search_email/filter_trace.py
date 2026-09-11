from dataclasses import dataclass

from .filter import (
    _check_employment_type,
    _check_location,
    _check_nhs_band_salary,
    _check_recruitment,
    _check_role_suitability,
    _check_salary,
    _check_sponsor,
)
from .location_filter import normalise_location
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
    remote_verdict: str | None = None,
    recruitment_set: frozenset[str] | None = None,
) -> list[GateResult]:
    gates: list[GateResult] = []

    # Location — reuse the real gate by deriving the location sets from the verdict.
    # Keyed by the normalised location, matching _check_location's lookup.
    norm_location = normalise_location(job.location or "")
    rejected_locations = frozenset({norm_location}) if location_verdict == "outside" else frozenset()
    if remote_verdict is None:
        loc = _check_location(job, rejected_locations)
    else:
        within_locations = frozenset({norm_location}) if location_verdict == "within" else frozenset()
        loc = _check_location(job, rejected_locations, within_locations, {job.url: remote_verdict})

    if loc is not None and loc.rejected:
        loc_detail = loc.reject_reason or ""
    elif loc is not None and "remote_confirmed" in loc.flags:
        loc_detail = f"{location_verdict} radius, confirmed fully remote ({job.location or 'not stated'})"
    elif loc is not None and "remote_with_travel" in loc.flags:
        loc_detail = f"{location_verdict} radius, remote with regular travel ({job.location or 'not stated'})"
    elif loc is not None and "remote_unconfirmed" in loc.flags:
        loc_detail = f"{location_verdict} radius, kept — remote not confirmed (check could not run) ({job.location or 'not stated'})"
    else:
        loc_detail = f"{location_verdict} radius ({job.location or 'not stated'})"
    gates.append(GateResult("Location", loc is None or not loc.rejected, loc_detail, False))

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

    remote_ok = bool({"remote_confirmed", "remote_with_travel"} & set(loc.flags)) if loc is not None else False

    # Mirrors filter_jobs' dispatch: Recruitment runs first, and a non-rejected
    # carve-out is FINAL — _check_sponsor is not consulted for that job.
    rec = _check_recruitment(job, recruitment_set, remote_ok) if recruitment_set is not None else None
    recruitment_carved = False
    if recruitment_set is None:
        rec_detail = "disabled (filter_recruitment=false)"
    elif rec is None:
        rec_detail = "not agency / not on recruitment list"
    elif not rec.rejected:
        rec_detail = "kept — sponsor unverified (agency, confirmed remote)"
        recruitment_carved = True
    else:
        rec_detail = rec.reject_reason or ""
    gates.append(GateResult("Recruitment", rec is None or not rec.rejected, rec_detail, False))

    sponsor = (
        _check_sponsor(job, sponsor_set, remote_ok)
        if sponsor_set is not None and not recruitment_carved
        else None
    )
    if recruitment_carved:
        sponsor_detail = "skipped — recruitment carve-out"
    elif sponsor_set is None:
        sponsor_detail = "disabled (filter_sponsors=false)"
    elif sponsor is None:
        sponsor_detail = "n/a (NHS source)" if job.source == "nhs" else "on approved sponsor list"
    elif not sponsor.rejected:
        sponsor_detail = "kept — sponsor unverified (confirmed remote)"
    else:
        sponsor_detail = sponsor.reject_reason or ""
    gates.append(GateResult("Sponsor list", sponsor is None or not sponsor.rejected, sponsor_detail, False))

    for gate in gates:
        if not gate.passed:
            gate.is_first_reject = True
            break

    return gates
