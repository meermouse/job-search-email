from dataclasses import asdict
from job_search_email.models import FilteredResult, JobListing


def make_job(**kwargs) -> JobListing:
    defaults = dict(
        title="Business Manager",
        company="NHS Trust",
        location="Bristol",
        salary_min=65000,
        description="",
        url="https://example.com/job/1",
        source="reed",
        employment_type=None,
    )
    defaults.update(kwargs)
    return JobListing(**defaults)


def test_filtered_result_rejected():
    job = make_job(employment_type="contract")
    result = FilteredResult(job=job, flags=[], rejected=True, reject_reason="employment type: contract")
    assert result.rejected is True
    assert result.reject_reason == "employment type: contract"
    assert result.flags == []


def test_filtered_result_kept_with_flag():
    job = make_job()
    result = FilteredResult(job=job, flags=["employment_type_unknown"], rejected=False, reject_reason=None)
    assert result.rejected is False
    assert result.reject_reason is None
    assert "employment_type_unknown" in result.flags


def test_filtered_result_serialises_with_asdict():
    job = make_job(employment_type="full-time")
    result = FilteredResult(job=job, flags=[], rejected=False, reject_reason=None)
    data = asdict(result)
    assert data["rejected"] is False
    assert data["job"]["title"] == "Business Manager"
    assert data["flags"] == []


from job_search_email.filter import _check_employment_type


# --- Stage 1: structured employment_type field ---

def test_employment_type_contract_rejected():
    result = _check_employment_type(make_job(employment_type="contract"))
    assert result.rejected is True
    assert result.reject_reason == "employment type: contract"


def test_employment_type_fixed_term_rejected():
    result = _check_employment_type(make_job(employment_type="fixed-term"))
    assert result.rejected is True


def test_employment_type_part_time_rejected():
    result = _check_employment_type(make_job(employment_type="part-time"))
    assert result.rejected is True


def test_employment_type_full_time_passes():
    result = _check_employment_type(make_job(employment_type="full-time"))
    assert result.rejected is False
    assert result.flags == []


def test_employment_type_permanent_passes():
    result = _check_employment_type(make_job(employment_type="permanent"))
    assert result.rejected is False
    assert result.flags == []


# --- Stage 2: text scan ---

def test_employment_type_fixed_term_contract_in_description_rejected():
    job = make_job(description="This is a fixed-term contract post based in Bristol.")
    result = _check_employment_type(job)
    assert result.rejected is True
    assert result.reject_reason == "description contains contract indicators"


def test_employment_type_maternity_cover_rejected():
    job = make_job(description="This is a maternity cover position for 12 months.")
    result = _check_employment_type(job)
    assert result.rejected is True


def test_employment_type_month_contract_rejected():
    job = make_job(description="This is a 12-month contract with possible extension.")
    result = _check_employment_type(job)
    assert result.rejected is True


def test_employment_type_zero_hours_rejected():
    job = make_job(description="This zero-hours role requires flexibility.")
    result = _check_employment_type(job)
    assert result.rejected is True


def test_employment_type_contract_in_duties_not_rejected():
    # "contract" as a job duty term must not trigger rejection
    job = make_job(description="The role involves managing contracts with suppliers and reviewing procurement.")
    result = _check_employment_type(job)
    assert result.rejected is False


def test_employment_type_unknown_flagged():
    # No structured type, no contract phrases in description
    job = make_job(description="A great senior management opportunity at an NHS trust.")
    result = _check_employment_type(job)
    assert result.rejected is False
    assert "employment_type_unknown" in result.flags


def test_employment_type_none_with_clean_description_flagged():
    result = _check_employment_type(make_job(employment_type=None, description=""))
    assert result.rejected is False
    assert "employment_type_unknown" in result.flags


def test_employment_type_text_scan_limited_to_500_chars():
    # Contract phrase buried deep in description should NOT trigger rejection
    prefix = "A" * 500
    job = make_job(description=f"{prefix} This is a fixed-term contract post.")
    result = _check_employment_type(job)
    assert result.rejected is False


def test_employment_type_zero_hours_no_false_match():
    # "zerophours" (no separator) must NOT trigger rejection
    job = make_job(description="This zerophours system tracks time.")
    result = _check_employment_type(job)
    assert result.rejected is False


from job_search_email.filter import _check_role_suitability


def test_role_suitability_rejects_matching_title():
    job = make_job(title="Staff Nurse Band 5")
    result = _check_role_suitability(job, ["staff nurse", "ward manager", "clinical lead"])
    assert result is not None
    assert result.rejected is True
    assert "staff nurse" in result.reject_reason


def test_role_suitability_rejects_case_insensitively():
    job = make_job(title="WARD MANAGER")
    result = _check_role_suitability(job, ["ward manager"])
    assert result is not None
    assert result.rejected is True


def test_role_suitability_rejects_on_partial_title_match():
    job = make_job(title="Senior Clinical Lead - Digital")
    result = _check_role_suitability(job, ["clinical lead"])
    assert result is not None
    assert result.rejected is True


def test_role_suitability_passes_non_matching_title():
    job = make_job(title="Business Manager Digital Transformation")
    result = _check_role_suitability(job, ["staff nurse", "ward manager", "clinical lead"])
    assert result is None


def test_role_suitability_passes_empty_exclusion_list():
    job = make_job(title="Staff Nurse")
    result = _check_role_suitability(job, [])
    assert result is None


def test_role_suitability_reject_reason_includes_matched_term():
    job = make_job(title="Consultant Physician")
    result = _check_role_suitability(job, ["consultant physician"])
    assert result is not None
    assert result.reject_reason == "unsuitable role: consultant physician"


from job_search_email.filter import filter_jobs
from job_search_email.models import SearchPlan


def make_plan(roles: list[str] | None = None) -> SearchPlan:
    return SearchPlan(
        profile_fingerprint="abc123",
        queries=["test query"],
        exclusions={"roles": roles or [], "employment_types": []},
        nhs_rules={},
        evaluator_notes=[],
    )


def make_profile_stub():
    from job_search_email.models import Profile
    return Profile(
        name="Test", current_role="Manager", about="", seniority="Senior",
        industry="NHS", skills=[], previous_roles=[], target_roles=[],
        open_to=[], not_open_to=[], qualifications=[],
        employment_type=["full-time"], location="Bristol", min_salary=60000,
    )


def test_filter_jobs_rejects_contract_role():
    jobs = [make_job(employment_type="contract")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub())
    assert len(results) == 1
    assert results[0].rejected is True


def test_filter_jobs_keeps_full_time_role():
    jobs = [make_job(employment_type="full-time")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub())
    assert len(results) == 1
    assert results[0].rejected is False
    assert results[0].flags == []


def test_filter_jobs_flags_unknown_employment_type():
    jobs = [make_job(employment_type=None, description="A management position.")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub())
    assert len(results) == 1
    assert results[0].rejected is False
    assert "employment_type_unknown" in results[0].flags


def test_filter_jobs_rejects_unsuitable_role_title():
    jobs = [make_job(title="Staff Nurse Band 5", employment_type="full-time")]
    results = filter_jobs(jobs, make_plan(roles=["staff nurse"]), make_profile_stub())
    assert len(results) == 1
    assert results[0].rejected is True
    assert "staff nurse" in results[0].reject_reason


def test_filter_jobs_employment_type_checked_before_role():
    # A contract role with a clinical title: reject reason should be employment type
    jobs = [make_job(title="Staff Nurse", employment_type="contract")]
    results = filter_jobs(jobs, make_plan(roles=["staff nurse"]), make_profile_stub())
    assert results[0].reject_reason == "employment type: contract"


def test_filter_jobs_returns_all_jobs_as_filtered_results():
    jobs = [
        make_job(employment_type="full-time"),
        make_job(employment_type="contract"),
        make_job(employment_type=None),
    ]
    results = filter_jobs(jobs, make_plan(), make_profile_stub())
    assert len(results) == 3


def test_filter_jobs_unknown_flag_preserved_on_passing_job():
    jobs = [make_job(employment_type=None, description="Permanent role with no type specified.")]
    results = filter_jobs(jobs, make_plan(), make_profile_stub())
    assert results[0].rejected is False
    assert "employment_type_unknown" in results[0].flags
