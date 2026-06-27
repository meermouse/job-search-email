import re
from typing import Any
from .models import FilteredResult, JobListing, Profile, SearchPlan

_REJECT_TYPES = frozenset({
    "contract", "fixed-term", "temporary", "locum", "bank",
    "agency", "casual", "zero-hours", "part-time", "internship",
})

_PASS_TYPES = frozenset({"full-time", "permanent"})

_CONTRACT_PATTERNS = re.compile(
    r"fixed.?term (?:contract|post|appointment)"
    r"|temporary (?:contract|post|role)"
    r"|contract basis"
    r"|maternity cover"
    r"|parental leave cover"
    r"|\d+[\s\-]month (?:contract|fixed)"
    r"|zero[\s\-]hours"
    r"|bank staff"
    r"|locum post",
    re.IGNORECASE,
)

_NHS_BAND_RE = re.compile(r"Band\s*(\d+[a-dA-D]?)", re.IGNORECASE)
_LONDON_WEIGHTING = 1.20


def _check_employment_type(job: JobListing) -> FilteredResult:
    et = (job.employment_type or "").lower().strip()

    if et in _REJECT_TYPES:
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=f"employment type: {et}")

    if et in _PASS_TYPES:
        return FilteredResult(job=job, flags=[], rejected=False, reject_reason=None)

    text = f"{job.title} {job.description}"[:500]
    if _CONTRACT_PATTERNS.search(text):
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason="description contains contract indicators")

    return FilteredResult(job=job, flags=["employment_type_unknown"], rejected=False, reject_reason=None)


def _check_role_suitability(job: JobListing, exclusion_roles: list[str]) -> FilteredResult | None:
    title_lower = job.title.lower()
    for term in exclusion_roles:
        if re.search(rf"\b{re.escape(term.lower())}\b", title_lower):
            return FilteredResult(job=job, flags=[], rejected=True, reject_reason=f"unsuitable role: {term}")
    return None


def _check_nhs_band_salary(
    job: JobListing,
    nhs_rules: dict[str, Any],
    min_salary: int,
) -> FilteredResult | None:
    search_text = f"{job.title} {(job.description or '')[:500]}"
    match = _NHS_BAND_RE.search(search_text)

    if match is None:
        return None

    band_key = f"Band {match.group(1).lower()}"  # normalise e.g. "8A" → "8a"
    band_map: dict[str, int] = nhs_rules.get("band_salary_map", {})
    base_salary = band_map.get(band_key, 0)

    is_london = "london" in (job.location or "").lower()
    if is_london:
        estimated = int(base_salary * _LONDON_WEIGHTING)
        label = f"{band_key} London (~£{estimated:,})"
    else:
        estimated = base_salary
        label = f"{band_key} (~£{estimated:,})"

    if estimated < min_salary:
        return FilteredResult(
            job=job,
            flags=[],
            rejected=True,
            reject_reason=f"nhs band salary below threshold: {label}",
        )

    return None


def filter_jobs(jobs: list[JobListing], plan: SearchPlan, profile: Profile) -> list[FilteredResult]:
    exclusion_roles = plan.exclusions.get("roles", [])
    results: list[FilteredResult] = []

    for job in jobs:
        et_result = _check_employment_type(job)
        if et_result.rejected:
            results.append(et_result)
            continue

        role_result = _check_role_suitability(job, exclusion_roles)
        if role_result is not None:
            results.append(role_result)
            continue

        nhs_result = _check_nhs_band_salary(job, plan.nhs_rules, profile.min_salary)
        if nhs_result is not None:
            results.append(nhs_result)
            continue

        results.append(FilteredResult(
            job=job,
            flags=et_result.flags,
            rejected=False,
            reject_reason=None,
        ))

    return results
