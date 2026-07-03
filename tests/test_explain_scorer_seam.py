import json
from unittest.mock import MagicMock, patch

from job_search_email.models import JobListing, Profile
from job_search_email.scorer import AnalysisTrace, analyse_job
from profile_helpers import make_profile


def _job() -> JobListing:
    return JobListing(
        title="Project Manager", company="Acme Ltd", location="Bristol",
        salary_min=65000, description="Lead delivery. PRINCE2 required.",
        url="https://example.com/1", source="reed", employment_type="permanent",
    )


def _profile() -> Profile:
    return make_profile(skills=["delivery"], target_roles=["Project Manager"], qualifications=["MSc"])


_RESPONSE = json.dumps({
    "score": 8,
    "matched_skills": ["delivery"],
    "missing_essentials": ["PRINCE2"],
    "employment_type_note": "Permanent",
    "verdict": "Strong match",
})


def _mock_client(text: str = _RESPONSE) -> MagicMock:
    m = MagicMock()
    m.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return m


def test_analyse_job_returns_trace_with_prompt_and_raw():
    with patch("job_search_email.scorer.client", _mock_client()):
        trace = analyse_job(_job(), _profile())
    assert isinstance(trace, AnalysisTrace)
    assert trace.analysis.score == 8
    assert "job suitability analyst" in trace.system_prompt
    assert "Project Manager" in trace.user_message
    assert trace.raw_text == _RESPONSE


def test_analyse_job_applies_mismatch_cap():
    mismatch = json.dumps({
        "score": 9, "matched_skills": [], "missing_essentials": ["PRINCE2"],
        "employment_type_note": "", "verdict": "x",
        "required_qualifications": ["PRINCE2"], "qualification_gaps": ["PRINCE2"],
        "qualification_status": "mismatch",
    })
    with patch("job_search_email.scorer.client", _mock_client(mismatch)):
        trace = analyse_job(_job(), _profile())
    assert trace.analysis.score == 3
