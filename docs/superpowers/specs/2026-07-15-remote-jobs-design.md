# UK-Wide Remote Job Search with Strict Remote Confirmation

**Date:** 2026-07-15
**Branch:** feature/FE-020-remote-jobs
**Status:** Approved

## Problem

The pipeline searches only within `profile.location` + a fixed 50-mile radius. Users
want remote jobs from further afield — but job boards are sloppy: listings tagged
"Remote" are often hybrid or office-based. Worse, the existing location classifier
deliberately passes vague location strings ("Remote", "United Kingdom", "Hybrid")
through as `uncertain`, so far-afield non-remote jobs already leak into results.

Goal: search UK-wide for remote jobs, but only keep a far-afield job when the posting
**positively confirms fully-remote working**. Silence or ambiguity is not confirmation.

## Decisions Made

| Decision | Choice |
|---|---|
| Geographic scope of remote search | UK-wide (fits sponsor-list and salary logic) |
| Evidence standard for "fully remote" | The job description must positively state fully-remote working, with no hybrid/office contradiction. LLM check. Ambiguous → rejected. |
| Opt-in model | Per-profile YAML flag `include_remote`, default `false` |
| Gate scope | All far-afield jobs for opted-in profiles, whichever search found them (closes the `uncertain` leak) |
| Architecture | Dedicated confirmation stage (new module + cache), not folded into the location classifier or the scorer |
| Profiles with `include_remote: false` | Behaviour completely unchanged, including the existing `uncertain` pass-through leak |

## Design

### 1. Profile setting

New field on `Profile` (`models.py`), default `False`, loaded from profile YAML:

```yaml
include_remote: true
```

Follows the `filter_sponsors` / `filter_recruitment` pattern. The flag participates in
the profile fingerprint, so toggling it invalidates the cached search plan.

### 2. Search stage — the remote leg

When `include_remote` is on, each of the 8 queries gains extra UK-wide searches
alongside the existing radius searches:

- **jobspy (LinkedIn + Indeed)**: second `scrape_jobs` call with
  `location="United Kingdom"`, `is_remote=True`.
- **Reed**: second API call with no `locationName`/`distancefromLocation` (UK-wide)
  and `" remote"` appended to the keywords.
- **NHS Jobs**: no remote leg. The scraper returns empty descriptions, so no NHS job
  could ever pass description-based confirmation; searching would be waste.

Existing dedup absorbs overlap between legs. Roughly doubles jobspy/Reed calls for
opted-in profiles (16 extra searches per run); no API cost, just runtime.

### 3. Remote confirmation stage — `remote_filter.py`

Mirrors `location_filter.py`: batched Haiku call, JSON verdict map, persistent cache.

- **Input**: jobs whose location verdict is not `within` (i.e. `outside` or
  `uncertain`), for opted-in profiles only. Jobs with a **blank** location string
  never receive a verdict today and silently pass; under the gate they are treated
  as `uncertain` and must be confirmed remote.
- **Prompt sees**: title + location string + description. One question: *does this
  posting positively confirm fully-remote working (UK)?*
- **Verdicts**: `remote` / `not_remote`.
- **Strict by design** — the inverse of the location classifier's leniency. Hybrid,
  "remote optional", "x days in office", vague, or silent-on-remote all yield
  `not_remote`. Silence is not confirmation.
- **Cache**: `remote_check_cache.json`, keyed by job URL.
- **Fails closed**: on API error, unverified far-afield jobs are rejected with a
  distinct reject reason (visible in the debug report). Failing open would reopen
  the leak this feature closes.

### 4. Hard filter change

`_check_location` in `filter.py`, for opted-in profiles:

| Location verdict | Today | New (`include_remote: true`) |
|---|---|---|
| `within` | keep | keep (no remote check, no extra cost) |
| `outside` | reject | keep only if confirmed `remote`, else reject |
| `uncertain` | keep (the leak) | keep only if confirmed `remote`, else reject |

Confirmed-remote jobs get a `remote_confirmed` flag on their `FilteredResult` so the
email, debug report, and `explain-job` can show why a far-afield job appeared.

Reject reasons distinguish the cases: outside radius and not confirmed remote, vs.
uncertain location and not confirmed remote, vs. remote check unavailable (API error).

### 5. Debug tooling & tests

- `explain-job` and `job-search-debug` traces show the remote-check verdict and the
  new reject reasons, following the existing stage-trace pattern.
- `job-search-email-local` gains fixture remote verdicts so the offline dry run
  exercises the new stage without network.
- Unit tests cover the filter matrix above with injected verdicts — no live LLM calls
  in tests.

## Out of Scope

- Closing the `uncertain` pass-through leak for profiles with `include_remote: false`
  (large behaviour change; deliberately excluded).
- Overseas remote jobs.
- Remote leg for NHS Jobs.
