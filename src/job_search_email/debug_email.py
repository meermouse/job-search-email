from collections import Counter
from datetime import date
from html import escape as _escape

from .models import FilteredResult, Profile


def _location_section(classification: dict[str, str], filtered: list[FilteredResult]) -> str:
    job_counts: Counter[str] = Counter(r.job.location for r in filtered if r.job.location)

    def _table(verdict: str, header_bg: str) -> str:
        locs = sorted(loc for loc, v in classification.items() if v == verdict)
        if not locs:
            return f'<p style="color:#999; font-size:13px;">No locations classified as {verdict}.</p>'
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(loc)}</td>'
            f'<td style="padding:4px 8px; text-align:right;">{job_counts.get(loc, 0)}</td></tr>'
            for loc in locs
        )
        return (
            f'<table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:12px;">'
            f'<thead><tr style="background:{header_bg}; color:#fff;">'
            f'<th style="padding:4px 8px; text-align:left;">{verdict.title()}</th>'
            f'<th style="padding:4px 8px; text-align:right;">Jobs</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    return (
        "<details open><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "Location Filter</summary>"
        + _table("within", "#28a745")
        + _table("uncertain", "#e6a817")
        + _table("outside", "#dc3545")
        + "</details>"
    )


def _employment_type_section(filtered: list[FilteredResult]) -> str:
    et_prefixes = ("employment type:", "description contains contract indicators")
    rejected = [
        r for r in filtered
        if r.rejected and r.reject_reason and any(r.reject_reason.startswith(p) for p in et_prefixes)
    ]
    unknown_count = sum(1 for r in filtered if not r.rejected and "employment_type_unknown" in r.flags)

    if not rejected and unknown_count == 0:
        body = '<p style="color:#999; font-size:13px;">No employment type rejections.</p>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(r.job.title)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.job.company)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.reject_reason or "")}</td></tr>'
            for r in rejected
        )
        table = (
            '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
            '<thead><tr style="background:#f0f0f0;">'
            '<th style="padding:4px 8px; text-align:left;">Title</th>'
            '<th style="padding:4px 8px; text-align:left;">Company</th>'
            '<th style="padding:4px 8px; text-align:left;">Reason</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        ) if rejected else ""
        unknown_note = (
            f'<p style="font-size:13px; color:#666; margin-top:8px;">'
            f'{unknown_count} job(s) passed through with unknown employment type.</p>'
        ) if unknown_count else ""
        body = table + unknown_note

    return (
        "<details><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "Employment Type Filter</summary>" + body + "</details>"
    )


def _role_suitability_section(filtered: list[FilteredResult]) -> str:
    rejected = [
        r for r in filtered
        if r.rejected and r.reject_reason and r.reject_reason.startswith("unsuitable role:")
    ]

    if not rejected:
        body = '<p style="color:#999; font-size:13px;">No role suitability rejections.</p>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(r.job.title)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.job.company)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.reject_reason.replace("unsuitable role: ", "", 1))}</td></tr>'
            for r in rejected
        )
        body = (
            '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
            '<thead><tr style="background:#f0f0f0;">'
            '<th style="padding:4px 8px; text-align:left;">Title</th>'
            '<th style="padding:4px 8px; text-align:left;">Company</th>'
            '<th style="padding:4px 8px; text-align:left;">Matched Term</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    return (
        "<details><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "Role Suitability Filter</summary>" + body + "</details>"
    )


def _nhs_band_section(filtered: list[FilteredResult]) -> str:
    prefix = "nhs band salary below threshold:"
    rejected = [
        r for r in filtered
        if r.rejected and r.reject_reason and r.reject_reason.startswith(prefix)
    ]

    if not rejected:
        body = '<p style="color:#999; font-size:13px;">No NHS band salary rejections.</p>'
    else:
        rows = "".join(
            f'<tr><td style="padding:4px 8px;">{_escape(r.job.title)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.job.company)}</td>'
            f'<td style="padding:4px 8px;">{_escape(r.reject_reason.replace(prefix + " ", "", 1))}</td></tr>'
            for r in rejected
        )
        body = (
            '<table style="width:100%; border-collapse:collapse; font-size:13px;">'
            '<thead><tr style="background:#f0f0f0;">'
            '<th style="padding:4px 8px; text-align:left;">Title</th>'
            '<th style="padding:4px 8px; text-align:left;">Company</th>'
            '<th style="padding:4px 8px; text-align:left;">Band / Salary</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )

    return (
        "<details><summary style='font-size:15px; font-weight:bold; cursor:pointer; padding:8px 0;'>"
        "NHS Band Salary Filter</summary>" + body + "</details>"
    )


def build_debug_email_html(
    classification: dict[str, str],
    filtered: list[FilteredResult],
    profile: Profile,
) -> str:
    today = date.today().strftime("%Y-%m-%d")
    total = len(filtered)
    kept = sum(1 for r in filtered if not r.rejected)
    rejected = total - kept

    sections = (
        _location_section(classification, filtered)
        + _employment_type_section(filtered)
        + _role_suitability_section(filtered)
        + _nhs_band_section(filtered)
    )

    return (
        f'<!DOCTYPE html>\n<html>\n<head><meta charset="UTF-8"></head>\n'
        f'<body style="font-family:Arial,sans-serif; background:#ffffff; color:#333333; '
        f'max-width:920px; margin:0 auto; padding:20px;">\n'
        f'  <h2 style="margin-bottom:4px;">[DEBUG] Job Search – {today}</h2>\n'
        f'  <p style="font-size:13px; color:#666; margin-top:0;">'
        f'Profile: {_escape(profile.name)} &nbsp;| {total} jobs total &nbsp;| '
        f'{kept} kept &nbsp;| {rejected} rejected</p>\n'
        f'  <hr style="border:none; border-top:1px solid #ddd; margin:16px 0;">\n'
        f'  {sections}\n'
        f'  <p style="font-size:11px; color:#999; margin-top:24px;">Generated on {today}</p>\n'
        f'</body>\n</html>'
    )
