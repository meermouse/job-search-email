import json
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch
from unittest.mock import patch as _patch

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


def test_main_loads_and_saves_location_cache(tmp_path, monkeypatch):
    """Location cache is loaded before classify and saved after."""
    import sys
    import importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    # Point all file paths to tmp_path
    monkeypatch.setattr(main_mod, "ROOT", tmp_path)
    monkeypatch.setattr(main_mod, "PROFILE_PATH", tmp_path / "profile.yaml")
    monkeypatch.setattr(main_mod, "CACHE_PATH", tmp_path / "plan_cache.json")
    monkeypatch.setattr(main_mod, "PLAN_PATH", tmp_path / "plan.json")
    monkeypatch.setattr(main_mod, "RESULTS_PATH", tmp_path / "results.json")
    monkeypatch.setattr(main_mod, "FILTERED_RESULTS_PATH", tmp_path / "filtered.json")
    monkeypatch.setattr(main_mod, "SCORED_RESULTS_PATH", tmp_path / "scored.json")
    monkeypatch.setattr(main_mod, "SCORE_CACHE_PATH", tmp_path / "score_cache.json")
    monkeypatch.setattr(main_mod, "LOCATION_CACHE_PATH", tmp_path / "location_cache.json")

    # Write a minimal profile.yaml
    (tmp_path / "profile.yaml").write_text(
        "profile:\n  name: Test\n  current_role: ''\n  about: ''\n"
        "  seniority: ''\n  industry: ''\n  skills: []\n  previous_roles: []\n"
        "  target_roles: []\n  open_to: []\n  not_open_to: []\n"
        "  qualifications: []\n  employment_type: [full-time]\n"
        "location: Bristol\nmin_salary: 60000\n",
        encoding="utf-8",
    )

    from job_search_email.models import JobListing

    dummy_job = JobListing(
        title="Manager", company="NHS", location="Bristol, BS1",
        salary_min=65000, description="", url="https://x.com/1",
        source="reed", employment_type="full-time",
    )

    from job_search_email.models import SearchPlan

    dummy_plan = SearchPlan(
        profile_fingerprint="test",
        queries=["test query"],
        exclusions={"roles": [], "employment_types": []},
        nhs_rules={},
        evaluator_notes=[],
    )

    with (
        patch("job_search_email.main.fetch_all_jobs", return_value=[dummy_job]),
        patch("job_search_email.main.generate_search_plan", return_value=dummy_plan),
        patch("job_search_email.main.classify_locations", return_value={"Bristol, BS1": "within"}) as mock_classify,
        patch("job_search_email.main.score_jobs", return_value=[]),
        patch("job_search_email.main.build_email_html", return_value=("<html/>", 0)),
        patch("job_search_email.main.send_email"),
    ):
        main_mod.main()

    mock_classify.assert_called_once()
    call_kwargs = mock_classify.call_args
    assert "Bristol" in str(call_kwargs)
    assert (tmp_path / "location_cache.json").exists()


def test_print_location_summary_outputs_counts(capsys):
    from job_search_email.main import _print_location_summary
    from job_search_email.models import JobListing

    def make_job(location, source):
        return JobListing(
            title="Manager", company="Corp", location=location,
            salary_min=60000, description="", url="https://x.com",
            source=source, employment_type="full-time",
        )

    jobs = [
        make_job("Bristol, BS1", "reed"),
        make_job("Bristol, BS1", "reed"),
        make_job("Reading, RG1", "linkedin"),
        make_job("Bath, BA1", "indeed"),
    ]

    _print_location_summary(jobs)
    out = capsys.readouterr().out

    assert "Bristol, BS1" in out
    assert "Reading, RG1" in out
    assert "Bath, BA1" in out
    assert "reed" in out
    assert "linkedin" in out


def test_load_profile_send_flags_default_to_main_on_debug_off(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(PROFILE_YAML, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.send_main_email is True
    assert profile.send_debug_email is False


def test_load_profile_reads_explicit_send_flags(tmp_path: Path) -> None:
    yaml_with_flags = PROFILE_YAML + "send_main_email: false\nsend_debug_email: true\n"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml_with_flags, encoding="utf-8")
    profile = load_profile(path=profile_path)
    assert profile.send_main_email is False
    assert profile.send_debug_email is True


def _run_main_with_toggles(tmp_path: Path, monkeypatch, send_main: bool, send_debug: bool):
    import sys
    import importlib
    importlib.import_module("job_search_email.main")
    main_mod = sys.modules["job_search_email.main"]

    (tmp_path / "profile.yaml").write_text(
        "profile:\n  name: Test\n  current_role: ''\n  about: ''\n"
        "  seniority: ''\n  industry: ''\n  skills: []\n  previous_roles: []\n"
        "  target_roles: []\n  open_to: []\n  not_open_to: []\n"
        "  qualifications: []\n  employment_type: [full-time]\n"
        "location: Bristol\nmin_salary: 60000\n"
        f"send_main_email: {'true' if send_main else 'false'}\n"
        f"send_debug_email: {'true' if send_debug else 'false'}\n",
        encoding="utf-8",
    )

    for attr, val in [
        ("ROOT", tmp_path), ("PROFILE_PATH", tmp_path / "profile.yaml"),
        ("CACHE_PATH", tmp_path / "plan.json"), ("PLAN_PATH", tmp_path / "plan.json"),
        ("RESULTS_PATH", tmp_path / "results.json"),
        ("FILTERED_RESULTS_PATH", tmp_path / "filtered.json"),
        ("SCORED_RESULTS_PATH", tmp_path / "scored.json"),
        ("SCORE_CACHE_PATH", tmp_path / "score_cache.json"),
        ("LOCATION_CACHE_PATH", tmp_path / "location_cache.json"),
    ]:
        monkeypatch.setattr(main_mod, attr, val)

    from job_search_email.models import JobListing, SearchPlan
    dummy_job = JobListing(
        title="Manager", company="NHS", location="Bristol",
        salary_min=65000, description="", url="https://x.com/1",
        source="reed", employment_type="full-time",
    )
    dummy_plan = SearchPlan(
        profile_fingerprint="test", queries=["q"],
        exclusions={"roles": [], "employment_types": []},
        nhs_rules={}, evaluator_notes=[],
    )

    with (
        _patch("job_search_email.main.fetch_all_jobs", return_value=[dummy_job]),
        _patch("job_search_email.main.generate_search_plan", return_value=dummy_plan),
        _patch("job_search_email.main.classify_locations", return_value={"Bristol": "within"}),
        _patch("job_search_email.main.score_jobs", return_value=[]),
        _patch("job_search_email.main.build_email_html", return_value=("<html/>", 0)),
        _patch("job_search_email.main.send_email") as mock_send,
        _patch("job_search_email.main.send_debug_report") as mock_debug,
        _patch("job_search_email.main.build_debug_email_html", return_value="<debug/>"),
    ):
        main_mod.main()
        return mock_send.call_count, mock_debug.call_count, mock_send.call_args_list


def test_routing_main_on_debug_off_sends_only_main(tmp_path: Path, monkeypatch):
    send_count, debug_count, _ = _run_main_with_toggles(tmp_path, monkeypatch, send_main=True, send_debug=False)
    assert send_count == 1
    assert debug_count == 0


def test_routing_main_on_debug_on_sends_both(tmp_path: Path, monkeypatch):
    send_count, debug_count, _ = _run_main_with_toggles(tmp_path, monkeypatch, send_main=True, send_debug=True)
    assert send_count == 1
    assert debug_count == 1


def test_routing_main_off_debug_on_sends_main_to_smtp_user(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SMTP_USER", "sender@test.com")
    send_count, debug_count, call_args = _run_main_with_toggles(tmp_path, monkeypatch, send_main=False, send_debug=True)
    assert send_count == 1
    assert debug_count == 1
    assert call_args[0].kwargs.get("override_to") == "sender@test.com"


def test_routing_main_off_debug_off_sends_nothing(tmp_path: Path, monkeypatch):
    send_count, debug_count, _ = _run_main_with_toggles(tmp_path, monkeypatch, send_main=False, send_debug=False)
    assert send_count == 0
    assert debug_count == 0
