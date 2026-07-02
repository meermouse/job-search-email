import re
from typing import Any
from .models import FilteredResult, JobListing, Profile, SearchPlan
from .sponsor_filter import _normalize as _normalize_company, _build_entries

_REJECT_TYPES = frozenset({
    "contract", "fixed-term", "temporary", "locum", "bank",
    "agency", "casual", "zero-hours", "part-time", "internship",
})

_PASS_TYPES = frozenset({"full-time", "permanent"})

_CONTRACT_PATTERNS = re.compile(
    r"fixed[\s\-]?term"
    r"|temporary (?:contract|post|role)"
    r"|contract basis"
    r"|maternity cover"
    r"|parental leave cover"
    r"|\d+[\s\-]month (?:contract|fixed)"
    r"|zero[\s\-]hours"
    r"|bank staff"
    r"|locum post"
    r"|\bftc\b",
    re.IGNORECASE,
)

_NHS_BAND_RE = re.compile(r"Band\s*(\d+[a-dA-D]?)", re.IGNORECASE)
_LONDON_WEIGHTING = 1.20
_MIN_COMPANY_CHARS = 8
_MIN_COMPANY_WORDS = 2
_RECRUITMENT_REASON = "recruitment agency — client company not disclosed, cannot verify sponsor"


def _check_employment_type(job: JobListing) -> FilteredResult:
    et = (job.employment_type or "").lower().strip()

    if et in _REJECT_TYPES:
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=f"employment type: {et}")

    # A structured type field can carry a contract signal even alongside
    # "permanent" (e.g. Indeed's "Permanent, Fixed term contract"). Attribute
    # the rejection to the type field so the debug email reads accurately.
    if _CONTRACT_PATTERNS.search(et):
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=f"employment type: {et}")

    text = f"{job.title} {(job.description or '')[:500]}"
    if _CONTRACT_PATTERNS.search(text):
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason="description contains contract indicators")

    if et in _PASS_TYPES:
        return FilteredResult(job=job, flags=[], rejected=False, reject_reason=None)

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
    search_text = f"{job.title} {(job.description or '')[:500]}"  # title unbounded; description capped at 500 chars
    match = _NHS_BAND_RE.search(search_text)

    if match is None:
        return None

    band_key = f"Band {match.group(1).lower()}"  # "Band" capitalisation matches nhs_rules band_salary_map keys
    band_map: dict[str, int] = nhs_rules.get("band_salary_map", {})
    base_salary = band_map.get(band_key, 0)  # 0 for out-of-map bands (Bands 1-6) — guarantees rejection

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


def _check_recruitment(job: JobListing, recruitment_set: frozenset[str]) -> FilteredResult | None:
    if job.source == "nhs":
        return None

    if job.posted_by_agency:
        return FilteredResult(job=job, flags=[], rejected=True, reject_reason=_RECRUITMENT_REASON)

    normalized = _normalize_company(job.company or "")
    if not normalized:
        return None

    for candidate in _build_entries(normalized):
        if candidate in recruitment_set:
            return FilteredResult(job=job, flags=[], rejected=True, reject_reason=_RECRUITMENT_REASON)

    return None


def _check_sponsor(job: JobListing, sponsor_set: frozenset[str]) -> FilteredResult | None:
    if job.source == "nhs":
        return None

    normalized = _normalize_company(job.company or "")
    words = normalized.split()

    if normalized in sponsor_set:
        return None

    if len(normalized) < _MIN_COMPANY_CHARS or len(words) < _MIN_COMPANY_WORDS:
        return FilteredResult(
            job=job,
            flags=[],
            rejected=True,
            reject_reason="company not specified — cannot verify approved sponsor",
        )

    return FilteredResult(
        job=job,
        flags=[],
        rejected=True,
        reject_reason="company not on approved sponsor list",
    )


def _check_location(job: JobListing, rejected_locations: frozenset[str]) -> FilteredResult | None:
    if not job.location or job.location not in rejected_locations:
        return None
    return FilteredResult(
        job=job, flags=[], rejected=True,
        reject_reason=f"location outside radius: {job.location}",
    )


def filter_jobs(
    jobs: list[JobListing],
    plan: SearchPlan,
    profile: Profile,
    rejected_locations: frozenset[str] = frozenset(),
    recruitment_set: frozenset[str] | None = None,
    sponsor_set: frozenset[str] | None = None,
) -> list[FilteredResult]:
    exclusion_roles = plan.exclusions.get("roles", [])
    results: list[FilteredResult] = []

    for job in jobs:
        loc_result = _check_location(job, rejected_locations)
        if loc_result is not None:
            results.append(loc_result)
            continue

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

        if recruitment_set is not None:
            recruitment_result = _check_recruitment(job, recruitment_set)
            if recruitment_result is not None:
                results.append(recruitment_result)
                continue

        if sponsor_set is not None:
            sponsor_result = _check_sponsor(job, sponsor_set)
            if sponsor_result is not None:
                results.append(sponsor_result)
                continue

        results.append(FilteredResult(
            job=job,
            flags=et_result.flags,
            rejected=False,
            reject_reason=None,
        ))

    return results
