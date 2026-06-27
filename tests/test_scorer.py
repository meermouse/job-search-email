import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

from job_search_email.models import FilteredResult, JobAnalysis, JobListing, Profile, ScoredResult


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


from job_search_email.scorer import score_jobs


def make_profile() -> Profile:
    return Profile(
        name="Test", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=["digital transformation"],
        previous_roles=[], target_roles=["Business Manager"],
        open_to=[], not_open_to=["clinical roles"],
        qualifications=["MSc Management"],
        employment_type=["full-time"], location="Bristol", min_salary=60000,
    )


def make_kept(job=None, flags=None) -> FilteredResult:
    return FilteredResult(
        job=job or make_job(), flags=flags or [],
        rejected=False, reject_reason=None,
    )


def make_rejected(job=None) -> FilteredResult:
    return FilteredResult(
        job=job or make_job(), flags=[],
        rejected=True, reject_reason="employment type: contract",
    )


_GOOD_RESPONSE = json.dumps({
    "score": 8,
    "matched_skills": ["digital transformation", "Project management"],
    "missing_essentials": [],
    "employment_type_note": "Permanent full-time confirmed",
    "verdict": "Strong match for this senior management role.",
})


def _mock_client(text: str = _GOOD_RESPONSE) -> MagicMock:
    m = MagicMock()
    m.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return m


def test_score_jobs_empty_returns_empty():
    assert score_jobs([], make_profile()) == []


def test_score_jobs_rejected_result_gets_no_analysis():
    results = [make_rejected()]
    with patch("job_search_email.scorer.client", _mock_client()):
        scored = score_jobs(results, make_profile())
    assert len(scored) == 1
    assert scored[0].analysis is None
    assert scored[0].rejected is True


def test_score_jobs_parses_claude_response():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client()):
        scored = score_jobs(results, make_profile())
    assert len(scored) == 1
    a = scored[0].analysis
    assert a is not None
    assert a.score == 8
    assert a.matched_skills == ["digital transformation", "Project management"]
    assert a.missing_essentials == []
    assert a.employment_type_note == "Permanent full-time confirmed"
    assert "senior management" in a.verdict


def test_score_jobs_sorts_by_salary_before_cap():
    high = make_job(salary_min=80000, url="https://example.com/high")
    mid = make_job(salary_min=70000, url="https://example.com/mid")
    low = make_job(salary_min=60000, url="https://example.com/low")
    results = [make_kept(low), make_kept(high), make_kept(mid)]

    with patch("job_search_email.scorer.client", _mock_client()), \
         patch.dict("os.environ", {"DEEP_ANALYSIS_LIMIT": "2"}):
        scored = score_jobs(results, make_profile())

    analysed_urls = {r.job.url for r in scored if r.analysis is not None}
    assert "https://example.com/high" in analysed_urls
    assert "https://example.com/mid" in analysed_urls
    assert "https://example.com/low" not in analysed_urls


def test_score_jobs_beyond_cap_gets_none_analysis():
    results = [make_kept() for _ in range(3)]
    with patch("job_search_email.scorer.client", _mock_client()), \
         patch.dict("os.environ", {"DEEP_ANALYSIS_LIMIT": "2"}):
        scored = score_jobs(results, make_profile())
    none_kept = [r for r in scored if not r.rejected and r.analysis is None]
    assert len(none_kept) == 1


def test_score_jobs_api_failure_adds_flag():
    results = [make_kept()]
    m = MagicMock()
    m.messages.create.side_effect = ConnectionError("API unreachable")
    with patch("job_search_email.scorer.client", m):
        scored = score_jobs(results, make_profile())
    assert scored[0].analysis is None
    assert "analysis_failed" in scored[0].flags


def test_score_jobs_bad_json_adds_flag():
    results = [make_kept()]
    with patch("job_search_email.scorer.client", _mock_client("not valid json")):
        scored = score_jobs(results, make_profile())
    assert scored[0].analysis is None
    assert "analysis_failed" in scored[0].flags


def test_score_jobs_sorts_kept_by_score_desc():
    jobs = [
        make_job(salary_min=65000, url="https://example.com/a"),
        make_job(salary_min=65000, url="https://example.com/b"),
        make_job(salary_min=65000, url="https://example.com/c"),
    ]
    results = [make_kept(j) for j in jobs]

    score_map = {
        "https://example.com/a": 5,
        "https://example.com/b": 9,
        "https://example.com/c": 3,
    }

    def fake_analyse(job, system_prompt, model):
        return JobAnalysis(
            score=score_map[job.url],
            matched_skills=[], missing_essentials=[],
            employment_type_note="", verdict="",
        )

    with patch("job_search_email.scorer._analyse_job", side_effect=fake_analyse):
        scored = score_jobs(results, make_profile())

    kept = [r for r in scored if not r.rejected and r.analysis is not None]
    scores = [r.analysis.score for r in kept]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 9


import json
from pathlib import Path

from job_search_email.main import write_scored_results
from job_search_email.models import ScoredResult


def make_scored_kept(score: int = 7, url: str = "https://example.com/1") -> ScoredResult:
    return ScoredResult(
        job=make_job(url=url), flags=[], rejected=False, reject_reason=None,
        analysis=make_analysis(score=score),
    )


def make_scored_rejected() -> ScoredResult:
    return ScoredResult(
        job=make_job(), flags=[], rejected=True,
        reject_reason="employment type: contract", analysis=None,
    )


def make_scored_unanalysed() -> ScoredResult:
    return ScoredResult(
        job=make_job(), flags=[], rejected=False, reject_reason=None, analysis=None,
    )


def test_write_scored_results_creates_file(tmp_path: Path):
    results = [make_scored_kept(), make_scored_rejected()]
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results(results, path=output_path)

    assert output_path.exists()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "summary" in data
    assert "kept" in data
    assert "rejected" in data


def test_write_scored_results_summary_counts(tmp_path: Path):
    results = [
        make_scored_kept(score=8, url="https://example.com/a"),
        make_scored_kept(score=5, url="https://example.com/b"),
        make_scored_rejected(),
        make_scored_unanalysed(),
    ]
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results(results, path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    s = data["summary"]
    assert s["total"] == 4
    assert s["kept"] == 3       # 2 scored + 1 unanalysed
    assert s["rejected"] == 1
    assert s["analysed"] == 2
    assert s["unanalysed"] == 1
    assert s["analysis_failed"] == 0


def test_write_scored_results_kept_sorted_by_score_desc(tmp_path: Path):
    results = [
        make_scored_kept(score=4, url="https://example.com/low"),
        make_scored_kept(score=9, url="https://example.com/high"),
        make_scored_kept(score=6, url="https://example.com/mid"),
    ]
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results(results, path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    scores = [r["analysis"]["score"] for r in data["kept"] if r["analysis"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 9


def test_write_scored_results_analysis_failed_counted(tmp_path: Path):
    failed = ScoredResult(
        job=make_job(), flags=["analysis_failed"], rejected=False,
        reject_reason=None, analysis=None,
    )
    output_path = tmp_path / "job_results_scored.json"

    write_scored_results([failed], path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["summary"]["analysis_failed"] == 1
    assert data["summary"]["unanalysed"] == 0
