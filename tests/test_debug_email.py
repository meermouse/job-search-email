from job_search_email.debug_email import build_debug_email_html
from job_search_email.models import FilteredResult, JobListing, Profile


def _make_profile() -> Profile:
    return Profile(
        name="Jie", current_role="", about="", seniority="", industry="",
        skills=[], previous_roles=[], target_roles=[], open_to=[], not_open_to=[],
        qualifications=[], employment_type=[], location="Bristol", min_salary=60000,
    )


def _make_job(location: str = "Bristol") -> JobListing:
    return JobListing(
        title="Business Manager", company="NHS Trust", location=location,
        salary_min=65000, description="", url="https://example.com/1",
        source="reed", employment_type="full-time",
    )


def _kept(job: JobListing, flags: list[str] | None = None) -> FilteredResult:
    return FilteredResult(job=job, flags=flags or [], rejected=False, reject_reason=None)


def _rejected(job: JobListing, reason: str) -> FilteredResult:
    return FilteredResult(job=job, flags=[], rejected=True, reject_reason=reason)


def test_location_within_appears_in_html():
    html = build_debug_email_html({"Bristol": "within"}, [_kept(_make_job("Bristol"))], _make_profile())
    assert "Bristol" in html
    assert "Within" in html


def test_location_outside_appears_in_html():
    html = build_debug_email_html(
        {"London": "outside"},
        [_rejected(_make_job("London"), "location outside radius: London")],
        _make_profile(),
    )
    assert "London" in html
    assert "Outside" in html


def test_location_uncertain_appears_in_html():
    html = build_debug_email_html({"Remote": "uncertain"}, [_kept(_make_job("Remote"))], _make_profile())
    assert "Remote" in html
    assert "Uncertain" in html


def test_location_job_count_includes_kept_and_rejected():
    filtered = [
        _kept(_make_job("Bristol")),
        _rejected(_make_job("Bristol"), "employment type: contract"),
    ]
    html = build_debug_email_html({"Bristol": "within"}, filtered, _make_profile())
    assert ">2<" in html


def test_employment_type_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "employment type: contract")],
        _make_profile(),
    )
    assert "Business Manager" in html
    assert "employment type: contract" in html


def test_contract_indicator_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "description contains contract indicators")],
        _make_profile(),
    )
    assert "description contains contract indicators" in html


def test_employment_type_unknown_flag_summary_appears():
    html = build_debug_email_html(
        {},
        [_kept(_make_job(), flags=["employment_type_unknown"])],
        _make_profile(),
    )
    assert "unknown employment type" in html.lower()


def test_role_suitability_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "unsuitable role: nurse")],
        _make_profile(),
    )
    assert "Business Manager" in html
    assert "nurse" in html


def test_nhs_band_rejected_job_appears():
    html = build_debug_email_html(
        {},
        [_rejected(_make_job(), "nhs band salary below threshold: Band 6 (~£35,000)")],
        _make_profile(),
    )
    assert "Business Manager" in html
    assert "Band 6" in html


def test_debug_email_has_five_details_sections():
    html = build_debug_email_html({}, [], _make_profile())
    assert html.count("<details") == 5


def test_debug_email_includes_profile_name():
    html = build_debug_email_html({}, [], _make_profile())
    assert "Jie" in html


def test_sponsor_missing_company_rejected_job_appears():
    html = build_debug_email_html(
        {"Bristol": "within"},
        [_rejected(_make_job(), "company not specified — cannot verify approved sponsor")],
        _make_profile(),
    )
    assert "Sponsor Filter" in html
    assert "company not specified" in html


def test_sponsor_not_on_list_rejected_job_appears():
    html = build_debug_email_html(
        {"Bristol": "within"},
        [_rejected(_make_job(), "company not on approved sponsor list")],
        _make_profile(),
    )
    assert "company not on approved sponsor list" in html
