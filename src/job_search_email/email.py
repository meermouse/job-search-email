import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from html import escape as _escape

from .location_filter import normalise_location
from .models import JobAnalysis, JobListing, Profile, ScoredResult


def job_hub(job: JobListing, hubs: list[str]) -> str | None:
    for hub in hubs:
        if f"jobspy:hub:{hub}" in job.search_legs:
            return hub
        if normalise_location(job.location or "").lower() == hub.lower():
            return hub
    return None


def _score_badge(score: int) -> str:
    if score >= 8:
        bg, fg = "#28a745", "#ffffff"
    elif score >= 5:
        bg, fg = "#ffc107", "#333333"
    else:
        bg, fg = "#dc3545", "#ffffff"
    return (
        f'<span style="background:{bg}; color:{fg}; padding:2px 8px; '
        f'border-radius:4px; font-weight:bold; font-size:12px;">{score}/10</span>'
    )


_REMOTE_BADGE = (
    ' <span style="background:#17a2b8; color:#ffffff; padding:2px 6px; '
    'border-radius:4px; font-size:11px;">Remote</span>'
)

_REMOTE_TRAVEL_BADGE = (
    ' <span style="background:#6f42c1; color:#ffffff; padding:2px 6px; '
    'border-radius:4px; font-size:11px;">Remote &#183; some travel</span>'
)


def _remote_badge(flags: list[str]) -> str:
    if "remote_with_travel" in flags:
        return _REMOTE_TRAVEL_BADGE
    if "remote_confirmed" in flags:
        return _REMOTE_BADGE
    return ""


def _quals_badge(analysis: JobAnalysis) -> str:
    status = analysis.qualification_status
    gaps = analysis.qualification_gaps

    if not status:
        return '<span style="color:#999999; font-size:12px;">&#8212;</span>'

    if status == "met":
        return (
            '<span style="background:#28a745; color:#ffffff; padding:2px 8px; '
            'border-radius:4px; font-size:12px;">&#10003; Met</span>'
        )

    shown = gaps[:2]
    suffix = f" +{len(gaps) - 2} more" if len(gaps) > 2 else ""
    gap_text = (", ".join(_escape(g) for g in shown) + suffix) if shown else ""

    if status == "mismatch":
        bg, fg, icon = "#dc3545", "#ffffff", "&#10007;"
    else:
        bg, fg, icon = "#ffc107", "#333333", "&#9888;"

    label = f"{icon} {gap_text}".strip() if gap_text else icon
    return (
        f'<span style="background:{bg}; color:{fg}; padding:2px 8px; '
        f'border-radius:4px; font-size:12px;">{label}</span>'
    )


def build_email_html(results: list[ScoredResult], profile: Profile) -> tuple[str, int]:
    eligible = [r for r in results if not r.rejected and r.analysis is not None]

    hubs = profile.remote_hubs

    def _is_confirmed_remote(r: ScoredResult) -> bool:
        return bool({"remote_confirmed", "remote_with_travel"} & set(r.flags))

    unverified = [r for r in eligible if "sponsor_unverified" in r.flags]
    rest = [r for r in eligible if "sponsor_unverified" not in r.flags]
    london = [r for r in rest if _is_confirmed_remote(r) and hubs and job_hub(r.job, hubs)]
    london_urls = {r.job.url for r in london}
    main = [r for r in rest if r.job.url not in london_urls]

    main.sort(key=lambda r: r.analysis.score, reverse=True)
    london.sort(key=lambda r: r.analysis.score, reverse=True)
    unverified.sort(key=lambda r: r.analysis.score, reverse=True)
    top = main[:20]

    th = 'style="padding:8px 6px; text-align:left; border-bottom:2px solid #dddddd; background:#f0f0f0;"'
    cell = 'style="padding:8px 6px; border-bottom:1px solid #eeeeee;"'

    def _rows(items: list[ScoredResult]) -> str:
        rows = []
        for i, r in enumerate(items, 1):
            row_bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            salary = f"£{r.job.salary_min:,}" if r.job.salary_min is not None else "Not stated"
            badge = _score_badge(r.analysis.score)
            quals = _quals_badge(r.analysis)
            remote = _remote_badge(r.flags)
            rows.append(
                f'<tr style="background:{row_bg};">'
                f"<td {cell}>{i}</td>"
                f"<td {cell}>{badge}</td>"
                f'<td {cell}><a href="{_escape(r.job.url, quote=True)}" style="color:#0066cc; text-decoration:none;">{_escape(r.job.title)}</a>{remote}</td>'
                f"<td {cell}>{_escape(r.job.company)}</td>"
                f'<td {cell} style="white-space:nowrap;">{salary}</td>'
                f"<td {cell}>{quals}</td>"
                f"<td {cell}>{_escape(r.analysis.verdict)}</td>"
                f"</tr>"
            )
        return "".join(rows)

    def _table(items: list[ScoredResult]) -> str:
        return f"""<table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr>
        <th {th}>#</th>
        <th {th}>Score</th>
        <th {th}>Job Title</th>
        <th {th}>Company</th>
        <th {th}>Salary</th>
        <th {th}>Quals</th>
        <th {th}>Verdict</th>
      </tr>
    </thead>
    <tbody>
      {_rows(items)}
    </tbody>
  </table>"""

    n = len(top)
    today = date.today().strftime("%Y-%m-%d")

    parts = [
        f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif; background:#ffffff; color:#333333; max-width:920px; margin:0 auto; padding:20px;">
  <p style="font-size:16px; margin-bottom:20px;">{_escape(profile.preamble)}</p>
  <p style="font-size:14px; color:#666666; margin-bottom:16px;">Here are your top {n} jobs from today's search, ranked by suitability.</p>
  """,
        _table(top),
    ]

    if hubs and london:
        parts.append('<h2 style="font-size:16px; margin-top:28px;">Remote &#8212; London</h2>')
        parts.append(_table(london))
    if unverified:
        parts.append('<h2 style="font-size:16px; margin-top:28px;">Remote &#8212; sponsor not verified</h2>')
        parts.append('<p style="font-size:12px; color:#666;">Sponsor status could not be verified from the listing — check the employer manually.</p>')
        parts.append(_table(unverified))

    parts.append(
        f"""
  <p style="font-size:12px; color:#999999; margin-top:24px;">Generated on {today}</p>
</body>
</html>"""
    )

    return "".join(parts), n


def send_email(html: str, profile: Profile, n: int = 0, override_to: str | None = None) -> None:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    if not all([host, port, user, password]):
        print("[email] SMTP credentials not configured — skipping email send", file=sys.stderr)
        return

    to = override_to if override_to else profile.recipient_email
    if not to:
        print("[email] recipient_email not configured — skipping email send", file=sys.stderr)
        return

    today = date.today().strftime("%Y-%m-%d")
    msg = EmailMessage()
    msg["Subject"] = f"Job Search Results – {today} ({n} jobs found)"
    msg["From"] = user
    msg["To"] = to
    msg.set_content("Please view this email in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, int(port)) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"[email] sent to {to}")
    except Exception as exc:
        print(f"[email] failed to send: {exc}", file=sys.stderr)


def send_debug_report(html: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    if not all([host, port, user, password]):
        print("[email] SMTP credentials not configured — skipping debug report", file=sys.stderr)
        return

    today = date.today().strftime("%Y-%m-%d")
    msg = EmailMessage()
    msg["Subject"] = f"[DEBUG] Job Search – {today}"
    msg["From"] = user
    msg["To"] = user
    msg.set_content("Please view this email in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(host, int(port)) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
        print(f"[email] debug report sent to {user}")
    except Exception as exc:
        print(f"[email] failed to send debug report: {exc}", file=sys.stderr)
