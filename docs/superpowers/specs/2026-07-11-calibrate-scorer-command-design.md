# /calibrate-scorer — Automated Score-Disagreement Analysis — Design

**Date:** 2026-07-11
**Status:** Approved

## Problem

Scores in the daily email have repeatedly disagreed with the user's own
judgement. The fix each time has been manual: use the debug tools to capture
the problematic job, have a strong Claude model re-analyse it, and adjust the
scorer prompt (see `2026-07-04-scorer-calibration-design.md` for one such
round). This design automates that loop for the top 5 jobs of a test run.

## Decisions made during brainstorming

- **Form:** a Claude Code slash command (`.claude/commands/calibrate-scorer.md`),
  not a Python console script. The judging and prompt-editing halves both need
  a strong model with code-editing ability — exactly what Claude Code is.
  No Python changes are expected.
- **Data source:** always a fresh `job-search-debug` run, so the top 5 reflect
  current listings and the current prompt. Score caching keeps repeat cost low.
- **Apply policy:** propose first, apply only on user approval, then verify.
- **Profile:** one per invocation, passed as an argument, default `jie-zhou`.
- **Regression corpus included** (approach A + B): each disagreement is saved
  as a case file and all past cases are re-checked after any prompt edit, so a
  new fix cannot silently undo an old one.

## Command flow

Invoked as `/calibrate-scorer` or `/calibrate-scorer marc-brookes`
(argument = profile stem, default `jie-zhou`).

1. **Fresh run** — run `job-search-debug --profile profiles/<name>.yaml`
   (live scraping + Haiku scoring; requires `ANTHROPIC_API_KEY`; takes a few
   minutes).
2. **Select cases** — read `runs/<name>/job_results_scored.json`; take the top
   5 kept (non-rejected) jobs by `analysis.score`, the same ordering the email
   uses. Fewer than 5 kept: use what exists and say so.
3. **Blind re-assessment** — for each job, Claude reads only the raw job
   fields (title, company, location, salary, description) and the profile
   YAML, and writes its own score band and reasoning *before* reading the
   scorer's analysis for that job. The ordering is written into the command to
   prevent anchoring on the score under review.
4. **Compare and diagnose** — classify each job as one of:
   - **agree** — within ±1 of the scorer;
   - **prompt gap** — the rubric in `_build_system_prompt`
     (`src/job_search_email/scorer.py`) does not cover this failure mode;
   - **execution miss** — the rubric covers it but Haiku misapplied it
     (a clarifying prompt edit may still help);
   - **data problem** — truncated description, missing salary, etc.; flagged
     separately, not a prompt issue.
5. **Propose** — where disagreements share a pattern, present a concrete edit
   to the scorer system prompt, noting that any edit invalidates the score
   cache (the next run re-scores everything — a one-off Haiku cost). No file
   is touched before the user approves.
6. **Apply and verify** — on approval, edit `scorer.py`, then re-run each
   disagreement case *and every saved regression case* through
   `explain-job --job-file <case> --profile profiles/<case.profile>.yaml
   --force-score`, confirming scores land inside the expected bounds.
   `--force-score` is required because explain-job replays the hard filters
   first and a case job might otherwise be rejected before scoring.
7. **Record** — save each new disagreement to the corpus and finish with a
   summary table: job, Haiku score, Claude's assessment, diagnosis, action.

## Regression corpus

Location: `calibration/cases/<date>-<job-slug>.yaml`, checked into git.
Each file is `explain-job --dump-job-file` output plus a `calibration` block:

```yaml
# ...standard dumped job fields (title, company, url, description, ...)
calibration:
  profile: jie-zhou            # profile the case was scored against
  scored: 7                    # what Haiku gave at the time
  expected_max: 6              # pass if score <= 6 (expected_min also allowed)
  reason: "Lacks fee-earning track record — gatekeeping gap at AD grade"
  date: 2026-07-11
```

`expected_min` / `expected_max` bound the acceptable score rather than pin an
exact value, because Haiku scores wobble ±1 between runs. Implementation must
confirm `explain-job --job-file` tolerates the extra `calibration` key; if it
does not, the command strips the block into a temp copy before invoking.
This is the only integration point to verify.

A regression failure blocks the "done" summary: the command must refine or
revert the edit, never leave a silently regressed prompt.

Seeding: the AECOM case from `2026-07-04-scorer-calibration-design.md`
becomes the first corpus entry if its job YAML still exists or can be
re-dumped from run data.

## Edge cases

- Top job with `analysis: null` (scoring failed): skipped, noted in summary.
- Claude agrees with all 5 scores: report "no disagreements, no changes
  proposed" and stop — a valid outcome.
- Pipeline run fails (network, scraper): stop and report; never silently
  analyse stale data.

## Gitignore change

`.gitignore` currently ignores `.claude/` wholesale, which would exclude the
new command file. Because git will not descend into a fully ignored
directory, the pattern must change to allow the negation:

```gitignore
.claude/*
!.claude/commands/
```

This keeps worktrees and local settings ignored while versioning the command.

## Documentation

Add a short section to `CLAUDE.md` under the existing debugging-tools list
describing `/calibrate-scorer` and the `calibration/cases/` convention.

## Out of scope

- No changes to the scorer prompt itself in this work — the command is the
  deliverable; prompt edits happen when it is used.
- No multi-profile cross-verification per invocation (run the command once
  per profile instead).
- No automated (unapproved) prompt application.
