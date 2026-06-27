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
