import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_search_email.evaluator_notes import get_evaluator_notes
from job_search_email.queries import generate_queries
from job_search_email.exclusions import get_exclusions
from job_search_email.nhs_rules import get_nhs_rules
from job_search_email.cache import fingerprint_profile
from job_search_email.main import (
    generate_search_plan,
    load_cached_plan,
    load_profile,
    save_cached_plan,
)
from job_search_email.models import Profile, SearchPlan


PROFILE_YAML = """
profile:
  name: Test User
  current_role: NHS Project Manager
  about: Experienced project manager in NHS.
  seniority: Senior
  industry: NHS / Private Sector
  skills:
    - stakeholder management
    - digital transformation
  previous_roles:
    - Business Manager
    - Project Lead
  target_roles:
    - Programme Manager
    - Digital Lead
  open_to:
    - Strategy Consultant
  not_open_to:
    - clinical roles
    - nursing
  qualifications:
    - MSc Project Management
  employment_type:
    - full-time

location: Bristol
min_salary: 60000
preamble: "Test preamble"
"""


def make_profile() -> Profile:
    return Profile(
        name="Test User",
        current_role="NHS Project Manager",
        about="Experienced project manager in NHS.",
        seniority="Senior",
        industry="NHS / Private Sector",
        skills=["stakeholder management", "digital transformation"],
        previous_roles=["Business Manager", "Project Lead"],
        target_roles=["Programme Manager", "Digital Lead"],
        open_to=["Strategy Consultant"],
        not_open_to=["clinical roles", "nursing"],
        qualifications=["MSc Project Management"],
        employment_type=["full-time"],
        location="Bristol",
        min_salary=60000,
    )


def test_load_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")

    profile = load_profile(path=profile_path)

    assert profile.name == "Test User"
    assert profile.current_role == "NHS Project Manager"
    assert profile.seniority == "Senior"
    assert profile.location == "Bristol"
    assert profile.min_salary == 60000
    assert "clinical roles" in profile.not_open_to
    assert "stakeholder management" in profile.skills
    assert profile.preamble == "Test preamble"
    assert profile.recipient_email == ""


def test_fingerprint_and_cache(tmp_path: Path) -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([f"query {i}" for i in range(8)]))]

    profile = make_profile()
    fingerprint = fingerprint_profile(profile)

    with patch("job_search_email.queries.client") as mock_client, \
         patch("job_search_email.exclusions.client") as mock_excl_client:
        mock_client.messages.create.return_value = mock_response
        mock_excl_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="[]")]
        )
        plan = generate_search_plan(profile, fingerprint)

    cache_path = tmp_path / "search_plan_cache.json"
    save_cached_plan(plan, cache_path=cache_path)
    cached = load_cached_plan(cache_path=cache_path, fingerprint=fingerprint)

    assert cached is not None
    assert cached["profile_fingerprint"] == fingerprint
    assert len(cached["queries"]) == 8


def test_get_exclusions_merges_not_open_to() -> None:
    profile = make_profile()  # not_open_to: ["clinical roles", "nursing"]

    with patch("job_search_email.exclusions.client") as mock_client:
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text='["ward manager", "clinical lead"]')]
        )
        result = get_exclusions(profile)

    assert "roles" in result
    assert "employment_types" in result
    assert "clinical roles" in result["roles"]
    assert "nursing" in result["roles"]
    assert "locum" in result["roles"]          # from STANDARD_CLINICAL_TERMS
    assert "ward manager" in result["roles"]   # from Claude
    assert "fixed-term" in result["employment_types"]
    assert "bank" in result["employment_types"]


def test_get_exclusions_deduplicates() -> None:
    profile = make_profile()
    profile.not_open_to.append("locum")        # already in STANDARD_CLINICAL_TERMS

    with patch("job_search_email.exclusions.client") as mock_client:
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="[]")]
        )
        result = get_exclusions(profile)

    assert result["roles"].count("locum") == 1


def test_get_nhs_rules_has_salary_map() -> None:
    result = get_nhs_rules()

    assert result["default_floor"] == "Band 8a"
    assert result["london_remote_floor"] == "Band 7"
    assert "band_salary_map" in result
    assert result["band_salary_map"]["Band 8a"] == 53755
    assert result["band_salary_map"]["Band 7"] == 43742
    assert "rule" in result


def test_get_evaluator_notes_is_profile_aware() -> None:
    profile = make_profile()
    notes = get_evaluator_notes(profile)

    assert len(notes) == 8
    assert any("Senior" in note for note in notes)
    assert any("60,000" in note for note in notes)
    assert any("clinical roles" in note for note in notes)
    assert any("Programme Manager" in note or "Digital Lead" in note for note in notes)


def test_generate_queries_returns_eight_strings() -> None:
    mock_queries = [
        "Business Manager digital transformation NHS",
        "Senior Programme Manager healthcare",
        "Digital Transformation Lead NHS",
        "Strategy Consultant digital health",
        "Operations Manager NHS senior",
        "Workforce Governance Manager digital",
        "Project Planning Manager NHS",
        "Head of Digital Services NHS",
    ]
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(mock_queries))]

    with patch("job_search_email.queries.client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        result = generate_queries(make_profile())

    assert len(result) == 8
    assert all(isinstance(q, str) for q in result)
    assert result[0] == "Business Manager digital transformation NHS"


def test_generate_queries_prompt_includes_exclusions() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(["q"] * 8))]

    with patch("job_search_email.queries.client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        generate_queries(make_profile())
        prompt_content = mock_client.messages.create.call_args[1]["messages"][0]["content"]

    assert "clinical roles" in prompt_content
    assert "nursing" in prompt_content


def test_save_cached_plan_handles_corrupted_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "search_plan_cache.json"
    cache_path.write_text("not valid json", encoding="utf-8")  # corrupted file

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps([f"query {i}" for i in range(8)]))]

    profile = make_profile()
    fingerprint = fingerprint_profile(profile)

    with patch("job_search_email.queries.client") as mock_client, \
         patch("job_search_email.exclusions.client") as mock_excl_client:
        mock_client.messages.create.return_value = mock_response
        mock_excl_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="[]")]
        )
        plan = generate_search_plan(profile, fingerprint)

    save_cached_plan(plan, cache_path=cache_path)
    cached = load_cached_plan(cache_path=cache_path, fingerprint=fingerprint)
    assert cached is not None
    assert cached["profile_fingerprint"] == fingerprint


def test_generate_queries_raises_on_bad_response() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"not": "a list"}')]

    with patch("job_search_email.queries.client") as mock_client:
        mock_client.messages.create.return_value = mock_response
        import pytest
        with pytest.raises(ValueError, match="Expected list of 8 strings"):
            generate_queries(make_profile())


from job_search_email.main import write_filtered_results
from job_search_email.models import FilteredResult, JobListing


def make_job_listing(**kwargs) -> JobListing:
    defaults = dict(
        title="Business Manager", company="NHS Trust", location="Bristol",
        salary_min=65000, description="", url="https://example.com/1",
        source="reed", employment_type="full-time",
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


def test_write_filtered_results_creates_file(tmp_path: Path) -> None:
    kept = FilteredResult(job=make_job_listing(), flags=[], rejected=False, reject_reason=None)
    rejected = FilteredResult(
        job=make_job_listing(employment_type="contract"),
        flags=[], rejected=True, reject_reason="employment type: contract",
    )
    output_path = tmp_path / "job_results_filtered.json"

    write_filtered_results([kept, rejected], path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 2
    assert data["summary"]["kept"] == 1
    assert data["summary"]["rejected"] == 1
    assert data["summary"]["flagged"] == 0
    assert len(data["kept"]) == 1
    assert len(data["rejected"]) == 1


def test_write_filtered_results_counts_flagged(tmp_path: Path) -> None:
    flagged = FilteredResult(
        job=make_job_listing(employment_type=None),
        flags=["employment_type_unknown"], rejected=False, reject_reason=None,
    )
    output_path = tmp_path / "job_results_filtered.json"

    write_filtered_results([flagged], path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["summary"]["flagged"] == 1
    assert data["kept"][0]["flags"] == ["employment_type_unknown"]


def test_write_filtered_results_rejected_includes_reason(tmp_path: Path) -> None:
    result = FilteredResult(
        job=make_job_listing(), flags=[], rejected=True, reject_reason="unsuitable role: nurse",
    )
    output_path = tmp_path / "job_results_filtered.json"

    write_filtered_results([result], path=output_path)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["rejected"][0]["reject_reason"] == "unsuitable role: nurse"
