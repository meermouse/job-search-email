import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from html import escape as _escape

from .models import Profile, ScoredResult


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


def build_email_html(results: list[ScoredResult], profile: Profile) -> tuple[str, int]:
    eligible = [r for r in results if not r.rejected and r.analysis is not None]
    eligible.sort(key=lambda r: r.analysis.score, reverse=True)
    top = eligible[:20]

    rows = []
    for i, r in enumerate(top, 1):
        row_bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
        salary = f"£{r.job.salary_min:,}" if r.job.salary_min is not None else "Not stated"
        badge = _score_badge(r.analysis.score)
        cell = 'style="padding:8px 6px; border-bottom:1px solid #eeeeee;"'
        rows.append(
            f'<tr style="background:{row_bg};">'
            f"<td {cell}>{i}</td>"
            f"<td {cell}>{badge}</td>"
            f'<td {cell}><a href="{_escape(r.job.url, quote=True)}" style="color:#0066cc; text-decoration:none;">{_escape(r.job.title)}</a></td>'
            f"<td {cell}>{_escape(r.job.company)}</td>"
            f'<td {cell} style="white-space:nowrap;">{salary}</td>'
            f"<td {cell}>{_escape(r.analysis.verdict)}</td>"
            f"</tr>"
        )

    n = len(top)
    today = date.today().strftime("%Y-%m-%d")
    th = 'style="padding:8px 6px; text-align:left; border-bottom:2px solid #dddddd; background:#f0f0f0;"'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif; background:#ffffff; color:#333333; max-width:920px; margin:0 auto; padding:20px;">
  <p style="font-size:16px; margin-bottom:20px;">{_escape(profile.preamble)}</p>
  <p style="font-size:14px; color:#666666; margin-bottom:16px;">Here are your top {n} jobs from today's search, ranked by suitability.</p>
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr>
        <th {th}>#</th>
        <th {th}>Score</th>
        <th {th}>Job Title</th>
        <th {th}>Company</th>
        <th {th}>Salary</th>
        <th {th}>Verdict</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <p style="font-size:12px; color:#999999; margin-top:24px;">Generated on {today}</p>
</body>
</html>""", n


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
