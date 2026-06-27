from .models import FilteredResult, JobAnalysis, JobListing, ScoredResult

_FIXTURE_ANALYSES: dict[str, JobAnalysis] = {
    "https://www.reed.co.uk/jobs/senior-business-manager/12345678": JobAnalysis(
        score=9,
        matched_skills=["digital transformation", "Business Strategy", "Project Initiation and Planning"],
        missing_essentials=[],
        employment_type_note="Permanent full-time — matches preference.",
        verdict="Strong match. Senior management role with well-aligned skills and target industry.",
    ),
    "https://www.jobs.nhs.uk/candidate/jobadvert/A1234-25-0001": JobAnalysis(
        score=7,
        matched_skills=["digital transformation", "Analytical Skills"],
        missing_essentials=["dedicated NHS digital leadership experience"],
        employment_type_note="Permanent full-time — matches preference.",
        verdict="Good fit for NHS digital transformation with minor experience gaps.",
    ),
    "https://www.reed.co.uk/jobs/strategy-consultant/12345680": JobAnalysis(
        score=6,
        matched_skills=["Business Strategy", "Analytical Skills"],
        missing_essentials=["consulting firm background"],
        employment_type_note="Permanent full-time — matches preference.",
        verdict="Partial match. Strategy focus aligns but consulting pedigree is thin.",
    ),
}

_FALLBACK_ANALYSIS = JobAnalysis(
    score=5,
    matched_skills=[],
    missing_essentials=[],
    employment_type_note="Unknown.",
    verdict="Insufficient data to score accurately.",
)


def fixture_queries() -> list[str]:
    return [
        "senior business manager NHS",
        "digital transformation manager",
        "head of digital services",
        "senior programme manager health",
        "business transformation lead",
        "strategy and operations manager",
        "senior project manager healthcare",
        "digital change manager NHS",
    ]


def fixture_jobs() -> list[JobListing]:
    return [
        JobListing(
            title="Senior Business Manager",
            company="Accenture UK",
            location="Bristol",
            salary_min=75000,
            description=(
                "Lead business transformation initiatives across our public sector clients. "
                "You will manage cross-functional teams and drive strategic change programmes. "
                "Permanent, full-time role based in Bristol."
            ),
            url="https://www.reed.co.uk/jobs/senior-business-manager/12345678",
            source="reed",
            employment_type="permanent",
        ),
        JobListing(
            title="Digital Transformation Consultant",
            company="Deloitte UK",
            location="Bristol",
            salary_min=80000,
            description=(
                "6-month contract engagement supporting a major NHS trust with their "
                "digital roadmap. Day rate negotiable."
            ),
            url="https://www.linkedin.com/jobs/view/12345679",
            source="linkedin",
            employment_type="contract",
        ),
        JobListing(
            title="Band 8b NHS Digital Transformation Manager",
            company="NHS Bristol, North Somerset and South Gloucestershire ICB",
            location="Bristol",
            salary_min=62215,
            description="",
            url="https://www.jobs.nhs.uk/candidate/jobadvert/A1234-25-0001",
            source="nhs_jobs",
            employment_type="permanent",
        ),
        JobListing(
            title="Band 5 NHS Administrator",
            company="University Hospitals Bristol NHS Foundation Trust",
            location="Bristol",
            salary_min=29970,
            description="",
            url="https://www.jobs.nhs.uk/candidate/jobadvert/A1234-25-0002",
            source="nhs_jobs",
            employment_type="permanent",
        ),
        JobListing(
            title="Strategy Consultant",
            company="PwC UK",
            location="Bristol",
            salary_min=65000,
            description=(
                "Work with senior leadership teams across financial services and public sector "
                "to develop and implement strategic change. Permanent role with hybrid working."
            ),
            url="https://www.reed.co.uk/jobs/strategy-consultant/12345680",
            source="reed",
            employment_type="permanent",
        ),
    ]


def fixture_scores(results: list[FilteredResult]) -> list[ScoredResult]:
    scored = []
    for r in results:
        if r.rejected:
            analysis = None
        else:
            analysis = _FIXTURE_ANALYSES.get(r.job.url, _FALLBACK_ANALYSIS)
        scored.append(ScoredResult(
            job=r.job,
            flags=r.flags,
            rejected=r.rejected,
            reject_reason=r.reject_reason,
            analysis=analysis,
        ))
    return scored
