from job_search_email.explain_render import render_explanation
from job_search_email.filter_trace import GateResult
from job_search_email.models import JobAnalysis, JobListing
from job_search_email.scorer import AnalysisTrace


def _job() -> JobListing:
    return JobListing(
        title="Senior Project Manager", company="Acme Ltd", location="Bristol",
        salary_min=65000, description="d", url="https://x/1",
        source="reed", employment_type="permanent",
    )


def _gates_all_pass() -> list[GateResult]:
    return [
        GateResult("Location", True, "within radius (Bristol)", False),
        GateResult("Employment type", True, "permanent", False),
        GateResult("Role suitability", True, "no excluded term matched", False),
        GateResult("NHS band salary", True, "n/a", False),
        GateResult("Sponsor list", True, "on approved sponsor list", False),
    ]


def _scorer_trace() -> AnalysisTrace:
    return AnalysisTrace(
        analysis=JobAnalysis(
            score=8, matched_skills=["delivery"], missing_essentials=["PRINCE2"],
            employment_type_note="Permanent", verdict="Strong match",
        ),
        system_prompt="SYS", user_message="USER", raw_text='{"score": 8}',
    )


def test_render_kept_job_includes_score_and_verbatim_llm():
    out = render_explanation(_job(), _gates_all_pass(), _scorer_trace(), None)
    assert "Senior Project Manager" in out
    assert "Acme Ltd" in out
    assert "Score: 8/10" in out
    assert "Strong match" in out
    assert "SYS" in out and "USER" in out and '{"score": 8}' in out
    assert "✓ Location" in out


def test_render_rejected_job_marks_first_reject_and_skips_scorer():
    gates = [
        GateResult("Location", True, "within radius (Bristol)", False),
        GateResult("Employment type", False, "employment type: contract", True),
        GateResult("Role suitability", True, "no excluded term matched", False),
        GateResult("NHS band salary", True, "n/a", False),
        GateResult("Sponsor list", True, "on approved sponsor list", False),
    ]
    out = render_explanation(_job(), gates, None, "rejected by Employment type")
    assert "✗ Employment type" in out
    assert "first reject" in out.lower()
    assert "rejected by Employment type" in out
    assert "AI SUITABILITY" not in out


def test_render_scorer_guards_empty_exclude_reason():
    """When exclude=True but exclude_reason is empty, show fallback text."""
    trace = AnalysisTrace(
        analysis=JobAnalysis(
            score=7, matched_skills=["management"], missing_essentials=[],
            employment_type_note="Permanent", verdict="Good fit",
            exclude=True, exclude_reason="",  # Empty reason edge case
        ),
        system_prompt="SYS", user_message="USER", raw_text='{"score": 7}',
    )
    out = render_explanation(_job(), _gates_all_pass(), trace, None)
    # Should NOT contain dangling "yes — " with nothing after
    assert "yes — \n" not in out
    # Should contain fallback text
    assert "yes — (reason not provided)" in out
