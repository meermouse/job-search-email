from dataclasses import asdict
from job_search_email.models import FilteredResult, JobListing, Profile, SearchPlan


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


from job_search_email.filter import _check_employment_type, _check_location


def test_check_location_rejects_outside_location():
    job = make_job(location="Reading, RG1")
    result = _check_location(job, rejected_locations=frozenset({"Reading, RG1"}))
    assert result is not None
    assert result.rejected is True
    assert result.reject_reason == "location outside radius: Reading, RG1"


def test_check_location_passes_within_location():
    job = make_job(location="Bath, BA1")
    result = _check_location(job, rejected_locations=frozenset({"Reading, RG1"}))
    assert result is None


def test_check_location_passes_empty_rejected_set():
    job = make_job(location="Reading, RG1")
    result = _check_location(job, rejected_locations=frozenset())
    assert result is None


def test_check_location_passes_blank_location():
    job = make_job(location="")
    result = _check_location(job, rejected_locations=frozenset({""}))
    assert result is None


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


def make_plan(roles: list[str] | None = None, nhs_rules: dict | None = None) -> SearchPlan:
    return SearchPlan(
        profile_fingerprint="abc123",
        queries=["test query"],
        exclusions={"roles": roles or [], "employment_types": []},
        nhs_rules=nhs_rules or {},
        evaluator_notes=[],
    )


def make_profile_stub():
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


def test_role_suitability_does_not_reject_word_containing_clinical_term():
    # "ward" in STANDARD_CLINICAL_TERMS must not reject "Forward Planning Lead"
    job = make_job(title="Forward Planning Lead")
    result = _check_role_suitability(job, ["ward"])
    assert result is None


from job_search_email.filter import _check_nhs_band_salary

_NHS_RULES = {
    "band_salary_map": {
        "Band 7":  43742,
        "Band 8a": 53755,
        "Band 8b": 62215,
        "Band 8c": 72293,
        "Band 8d": 83571,
        "Band 9":  96376,
    }
}


def test_nhs_band_non_nhs_source_no_band_returns_none():
    job = make_job(source="reed", title="Business Manager", description="Great senior role.")
    assert _check_nhs_band_salary(job, _NHS_RULES, 60000) is None


def test_nhs_band_7_below_threshold_rejected():
    job = make_job(title="Transformation Manager Band 7", source="nhs_jobs", location="Bristol")
    result = _check_nhs_band_salary(job, _NHS_RULES, 60000)
    assert result is not None
    assert result.rejected is True
    assert "Band 7" in result.reject_reason
    assert "43,742" in result.reject_reason


def test_nhs_band_8b_above_threshold_returns_none():
    job = make_job(title="Digital Lead Band 8b", source="nhs_jobs", location="Bristol")
    assert _check_nhs_band_salary(job, _NHS_RULES, 60000) is None


def test_nhs_band_7_london_below_threshold_rejected():
    # 43742 * 1.20 = 52490 < 60000 — still rejected
    job = make_job(title="Manager Band 7", source="nhs_jobs", location="London")
    result = _check_nhs_band_salary(job, _NHS_RULES, 60000)
    assert result is not None
    assert result.rejected is True
    assert "London" in result.reject_reason
    assert "52,490" in result.reject_reason


def test_nhs_band_8a_london_above_threshold_returns_none():
    # 53755 * 1.20 = 64506 >= 60000 — passes
    job = make_job(title="Manager Band 8a", source="nhs_jobs", location="Greater London")
    assert _check_nhs_band_salary(job, _NHS_RULES, 60000) is None


def test_nhs_band_5_out_of_map_rejected():
    job = make_job(title="Admin Band 5", source="nhs_jobs", location="Bristol")
    result = _check_nhs_band_salary(job, _NHS_RULES, 60000)
    assert result is not None
    assert result.rejected is True


def test_nhs_band_detected_in_description():
    job = make_job(source="reed", title="NHS Digital Manager", description="AfC Band 7 post in Bristol.")
    result = _check_nhs_band_salary(job, _NHS_RULES, 60000)
    assert result is not None
    assert result.rejected is True


def test_nhs_band_beyond_500_chars_not_detected():
    job = make_job(source="reed", title="Digital Manager", description=("A" * 500) + " Band 7 post.")
    assert _check_nhs_band_salary(job, _NHS_RULES, 60000) is None


def test_nhs_jobs_source_no_band_in_text_returns_none():
    job = make_job(source="nhs_jobs", title="Digital Transformation Lead", description="No pay grade stated.")
    assert _check_nhs_band_salary(job, _NHS_RULES, 60000) is None


def test_nhs_london_location_case_insensitive():
    # 53755 * 1.20 = 64506 >= 60000
    job = make_job(title="Manager Band 8a", source="nhs_jobs", location="LONDON")
    assert _check_nhs_band_salary(job, _NHS_RULES, 60000) is None


def test_nhs_band_reject_reason_non_london_format():
    job = make_job(title="Manager Band 7", source="nhs_jobs", location="Bristol")
    result = _check_nhs_band_salary(job, _NHS_RULES, 60000)
    assert result.reject_reason == "nhs band salary below threshold: Band 7 (~£43,742)"


def test_nhs_band_reject_reason_london_format():
    job = make_job(title="Manager Band 7", source="nhs_jobs", location="London")
    result = _check_nhs_band_salary(job, _NHS_RULES, 60000)
    assert result.reject_reason == "nhs band salary below threshold: Band 7 London (~£52,490)"


def test_filter_jobs_rejects_nhs_band_below_threshold():
    jobs = [make_job(title="Manager Band 7", source="nhs_jobs", employment_type="full-time", location="Bristol")]
    results = filter_jobs(jobs, make_plan(nhs_rules=_NHS_RULES), make_profile_stub())
    assert results[0].rejected is True
    assert "Band 7" in results[0].reject_reason


def test_filter_jobs_keeps_nhs_band_above_threshold():
    jobs = [make_job(title="Manager Band 8b", source="nhs_jobs", employment_type="full-time", location="Bristol")]
    results = filter_jobs(jobs, make_plan(nhs_rules=_NHS_RULES), make_profile_stub())
    assert results[0].rejected is False


def test_filter_jobs_employment_type_checked_before_nhs_band():
    # contract should be rejected for employment type, not band salary
    jobs = [make_job(title="Manager Band 7", source="nhs_jobs", employment_type="contract")]
    results = filter_jobs(jobs, make_plan(nhs_rules=_NHS_RULES), make_profile_stub())
    assert results[0].reject_reason == "employment type: contract"


def test_filter_jobs_role_check_before_nhs_band():
    # clinical role title should be rejected for role suitability, not band salary
    jobs = [make_job(title="Staff Nurse Band 7", source="nhs_jobs", employment_type="full-time")]
    results = filter_jobs(jobs, make_plan(roles=["staff nurse"], nhs_rules=_NHS_RULES), make_profile_stub())
    assert "staff nurse" in results[0].reject_reason


def test_filter_jobs_rejects_outside_location():
    jobs = [
        make_job(employment_type="full-time", location="Reading, RG1"),
        make_job(employment_type="full-time", location="Bath, BA1"),
    ]
    plan = SearchPlan(
        profile_fingerprint="fp",
        queries=[],
        exclusions={"roles": []},
        nhs_rules={},
        evaluator_notes=[],
    )
    profile = Profile(
        name="Test", current_role="", about="", seniority="", industry="",
        skills=[], previous_roles=[], target_roles=[], open_to=[], not_open_to=[],
        qualifications=[], employment_type=["full-time"],
        location="Bristol", min_salary=0,
    )
    results = filter_jobs(
        jobs, plan, profile,
        rejected_locations=frozenset({"Reading, RG1"}),
    )
    reading_result = next(r for r in results if r.job.location == "Reading, RG1")
    bath_result = next(r for r in results if r.job.location == "Bath, BA1")
    assert reading_result.rejected is True
    assert reading_result.reject_reason == "location outside radius: Reading, RG1"
    assert bath_result.rejected is False


def test_filter_jobs_default_no_location_rejection():
    jobs = [make_job(employment_type="full-time", location="Reading, RG1")]
    plan = SearchPlan(
        profile_fingerprint="fp", queries=[],
        exclusions={"roles": []}, nhs_rules={}, evaluator_notes=[],
    )
    profile = Profile(
        name="Test", current_role="", about="", seniority="", industry="",
        skills=[], previous_roles=[], target_roles=[], open_to=[], not_open_to=[],
        qualifications=[], employment_type=["full-time"],
        location="Bristol", min_salary=0,
    )
    results = filter_jobs(jobs, plan, profile)
    assert results[0].rejected is False
