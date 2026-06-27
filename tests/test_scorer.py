from dataclasses import asdict
from job_search_email.models import JobAnalysis, JobListing, ScoredResult


def make_job(**kwargs) -> JobListing:
    defaults = dict(
        title="Business Manager", company="NHS Trust", location="Bristol",
        salary_min=65000, description="Senior role.", url="https://example.com/1",
        source="reed", employment_type="full-time",
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


def make_analysis(**kwargs) -> JobAnalysis:
    defaults = dict(
        score=7,
        matched_skills=["digital transformation"],
        missing_essentials=[],
        employment_type_note="Permanent full-time confirmed",
        verdict="Strong match for senior management roles.",
    )
    defaults.update(kwargs)
    return JobAnalysis(**defaults)


def test_job_analysis_fields():
    a = make_analysis()
    assert a.score == 7
    assert a.matched_skills == ["digital transformation"]
    assert a.missing_essentials == []
    assert a.employment_type_note == "Permanent full-time confirmed"
    assert a.verdict == "Strong match for senior management roles."


def test_scored_result_with_analysis():
    result = ScoredResult(
        job=make_job(), flags=[], rejected=False,
        reject_reason=None, analysis=make_analysis(),
    )
    assert result.analysis.score == 7
    assert result.rejected is False


def test_scored_result_analysis_can_be_none():
    result = ScoredResult(
        job=make_job(), flags=[], rejected=True,
        reject_reason="employment type: contract", analysis=None,
    )
    assert result.analysis is None
    assert result.rejected is True


def test_scored_result_serialises_with_asdict():
    result = ScoredResult(
        job=make_job(), flags=[], rejected=False,
        reject_reason=None, analysis=make_analysis(),
    )
    data = asdict(result)
    assert data["analysis"]["score"] == 7
    assert data["job"]["title"] == "Business Manager"
    assert data["analysis"]["matched_skills"] == ["digital transformation"]
