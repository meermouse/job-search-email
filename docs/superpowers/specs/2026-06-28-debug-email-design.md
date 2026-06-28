# Debug Email Design

**Date:** 2026-06-28
**Branch:** feature/FE-011-debug-email

## Overview

Add a debug email that logs the decisions made by the pipeline's filter stages. Two new boolean toggles in `profile.yaml` control whether the main email and/or debug email are sent, and to whom.

## Goals

- Allow the developer/operator to receive a parallel email showing what each filter accepted, rejected, and why — without touching the recipient's inbox.
- Start with the location filter (currently producing unexpected results for distant locations) and cover all four filter stages.
- Keep the main email path entirely unchanged when the feature is off.

## Config Toggles

Two new fields added to `profile.yaml` at the top level:

```yaml
send_main_email: true
send_debug_email: false
```

Both have sensible defaults so existing configs without these fields continue to work:
- `send_main_email` defaults to `true`
- `send_debug_email` defaults to `false`

The `Profile` dataclass in `models.py` gains two corresponding `bool` fields with the same defaults. `load_profile()` reads them via `data.get()`.

## Email Routing Logic

Routing is handled in `main()` after the pipeline completes. The `send_email()` function gains an optional `override_to: str | None = None` parameter; when set, it replaces `profile.recipient_email` as the recipient.

| `send_main_email` | `send_debug_email` | Behaviour |
|---|---|---|
| `true` | `false` | Main email → `recipient_email` (unchanged) |
| `true` | `true` | Main email → `recipient_email`; debug email → `SMTP_USER` |
| `false` | `true` | Main email → `SMTP_USER`; debug email → `SMTP_USER` |
| `false` | `false` | Nothing sent |

A dedicated `send_debug_report()` function in `email.py` sends the debug HTML to `SMTP_USER` with a distinct subject line: `[DEBUG] Job Search – {date}`. Like `send_email()`, it gracefully skips with a warning if SMTP credentials are not configured.

## Debug Email Content

New module: `src/job_search_email/debug_email.py`

```python
def build_debug_email_html(
    classification: dict[str, str],
    filtered: list[FilteredResult],
    profile: Profile,
) -> str
```

The function receives:
- `classification` — the full dict from `classify_locations()`, mapping each unique location string to `"within"` / `"outside"` / `"uncertain"`
- `filtered` — the full `list[FilteredResult]` from `filter_jobs()`, including both kept and rejected jobs

### Email structure

Four sections, each wrapped in a `<details>`/`<summary>` block (zero-JS toggling):

#### 1. Location Filter

Three sub-tables with colour-coded headers:

| Verdict | Header colour | Contents |
|---|---|---|
| Within | Green | Location string, job count |
| Uncertain | Amber | Location string, job count |
| Outside | Red | Location string, job count |

Job counts per location are derived from iterating all of `filtered` (both kept and rejected) and grouping by `job.location`, so the count reflects every job that had that location string — not just the ones that passed.

#### 2. Employment Type Filter

- Table of jobs rejected with `reject_reason` matching `"employment type: …"` or `"description contains contract indicators"`, showing job title, company, and reason.
- A summary line: "N jobs passed through with unknown employment type" (jobs in `filtered` with `"employment_type_unknown"` in `flags` and `rejected=False`).

#### 3. Role Suitability Filter

Table of jobs rejected with `reject_reason` matching `"unsuitable role: …"`, showing job title, company, and the matched exclusion term extracted from the reason string.

#### 4. NHS Band Salary Filter

Table of jobs rejected with `reject_reason` matching `"nhs band salary below threshold: …"`, showing job title, company, and the band/salary detail from the reason string.

### Subject line

```
[DEBUG] Job Search – 2026-06-28
```

## Files Changed

| File | Change |
|---|---|
| `profile.yaml` | Add `send_main_email`, `send_debug_email` fields |
| `src/job_search_email/models.py` | Add `send_main_email: bool = True`, `send_debug_email: bool = False` to `Profile` |
| `src/job_search_email/main.py` | Update `load_profile()` to read new fields; replace send block with routing logic |
| `src/job_search_email/email.py` | Add `override_to` param to `send_email()`; add `send_debug_report()` function |
| `src/job_search_email/debug_email.py` | New module with `build_debug_email_html()` |

## Non-Goals

- No other filter stages (scorer, dedup) are logged in this iteration.
- No persistent debug log file — debug info is email-only.
- No UI for toggling — profile.yaml only.
