# /calibrate-scorer Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/calibrate-scorer [profile]` Claude Code slash command that re-runs the pipeline, blind-re-assesses the top 5 scored jobs, proposes scorer-prompt fixes for approval, and guards past fixes with a regression corpus in `calibration/cases/`.

**Architecture:** Pure orchestration — a markdown slash command drives the existing `job-search-debug` and `explain-job` tools; no new Python modules. The only code change is one new test pinning that `load_job_file` tolerates the corpus's extra `calibration` YAML block (verified true today: `job_resolver.load_job_file` reads only known keys via `data.get`).

**Tech Stack:** Claude Code slash commands (markdown + YAML frontmatter), existing console scripts (`job-search-debug`, `explain-job`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-11-calibrate-scorer-command-design.md`

## Global Constraints

- No new Python modules or console scripts; the command file orchestrates existing tools.
- Default profile stem is `jie-zhou`; profiles live at `profiles/<stem>.yaml`.
- The command must never edit `scorer.py` before explicit user approval.
- Corpus case files live at `calibration/cases/<YYYY-MM-DD>-<job-slug>.yaml` and are committed to git.
- The AECOM seed case from the 2026-07-04 spec is NOT recoverable (job absent from run data, Indeed cannot be auto-fetched) — the corpus starts empty; do not invent a seed case.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Un-ignore `.claude/commands/` in git

**Files:**
- Modify: `.gitignore:21` (the `.claude/` line)

**Interfaces:**
- Produces: git tracks files under `.claude/commands/` (Task 2 commits a file there); everything else under `.claude/` stays ignored.

- [ ] **Step 1: Change the ignore pattern**

In `.gitignore`, replace the line `.claude/` with:

```gitignore
.claude/*
!.claude/commands/
```

(Git never descends into a directory ignored as a whole, so the negation only works with the `/*` form.)

- [ ] **Step 2: Verify the negation works**

```powershell
New-Item -ItemType Directory -Force .claude\commands; git check-ignore -v .claude/commands/calibrate-scorer.md; git check-ignore -v .claude/worktrees/x
```

Expected: the first `git check-ignore` prints nothing for the commands path (exit code 1 → not ignored — the tool may report a nonzero exit; that is the pass condition), and the second prints a match against `.claude/*` (still ignored).

- [ ] **Step 3: Commit**

```powershell
git add .gitignore; git commit -m @'
chore: allow versioning .claude/commands/ while keeping the rest of .claude/ ignored

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: The `/calibrate-scorer` command file

**Files:**
- Create: `.claude/commands/calibrate-scorer.md`

**Interfaces:**
- Consumes: Task 1's gitignore change (file must be trackable).
- Produces: the `/calibrate-scorer` slash command; references `calibration/cases/` (created in Task 3) — the command already handles the directory being empty or absent ("no saved cases" path), so task order between 2 and 3 is not load-bearing.

- [ ] **Step 1: Write the command file**

Create `.claude/commands/calibrate-scorer.md` with exactly this content:

````markdown
---
description: Re-assess the top 5 scored jobs from a fresh test run and calibrate the scorer prompt
argument-hint: [profile-name]
---

# Calibrate the job scorer

You are auditing the AI job scorer against your own judgement, then fixing the
scorer prompt where it is miscalibrated. The profile stem is `$ARGUMENTS`; if
that is empty, use `jie-zhou`. All paths are relative to the repo root.

## 1. Fresh pipeline run

Run `job-search-debug --profile profiles/<stem>.yaml` (live scraping plus
Haiku scoring; requires `ANTHROPIC_API_KEY`; takes several minutes — use a
generous timeout and run it in the background if needed). If the run fails
(network, scraper, missing key), STOP and report the failure. Never analyse
stale run data silently.

## 2. Select the top 5

Read `runs/<stem>/job_results_scored.json`. Kept jobs are entries with
`rejected` false. Order kept jobs by `analysis.score` descending and take the
top 5 — the same ordering the email uses. Skip any entry whose `analysis` is
null (scoring failed) and note it in the final summary. If fewer than 5 kept
jobs exist, use however many there are and say so.

## 3. Blind re-assessment — anchoring discipline

Process the jobs ONE AT A TIME. For each job, read ONLY these fields —
`title`, `company`, `location`, `salary_min`, `employment_type`,
`description` — plus `profiles/<stem>.yaml`. Do NOT read the job's
`analysis` block yet.

Write down your own assessment first:

- your score (1–10) using the scorer's own bands: 8–10 strong match (would
  very likely survive the initial sift), 5–7 partial match (credible but real
  gaps), 1–4 weak (would not survive the sift);
- every gatekeeping requirement the candidate lacks (requirements a hiring
  manager screens on at the role's stated seniority);
- whether the job should have been excluded outright (not permanent, salary
  below minimum, wrong location, wrong profession);
- one or two sentences of reasoning.

Only after your assessment for that job is written down may you read its
`analysis` block and move to the comparison. Never read ahead to another
job's analysis either.

## 4. Compare and diagnose

For each job, compare your score with `analysis.score` and classify:

- **agree** — within ±1 and same exclude decision;
- **prompt gap** — the rubric in `_build_system_prompt`
  (`src/job_search_email/scorer.py`) does not cover this failure mode;
- **execution miss** — the rubric covers it but the scoring model misapplied
  it (a clarifying wording change may still help);
- **data problem** — truncated description, missing salary, scraper junk —
  not a prompt issue; flag it separately and do not propose prompt edits
  for it.

Remember `_parse_analysis` applies post-hoc caps (gatekeeping gaps cap the
score at 6; qualification mismatch caps it at 3) — account for these before
declaring a disagreement.

## 5. Propose

If every job is **agree**: report "no disagreements, no changes proposed",
write the summary (step 7, minus corpus entries), and stop. That is a valid,
useful outcome.

Otherwise, where disagreements share a pattern, draft a concrete edit to the
scorer system prompt in `_build_system_prompt`. Present to the user:

- the per-job verdict table (job, scorer's score, your score, diagnosis);
- the exact prompt wording you want to add or change, and why;
- a reminder that any system-prompt edit invalidates the score cache, so the
  next pipeline run re-scores everything up to `DEEP_ANALYSIS_LIMIT` — a
  one-off Haiku cost.

Ask for approval before touching any file. If the user declines, record the
analysis in the summary and stop.

## 6. Apply and verify (only after approval)

1. Edit `_build_system_prompt` in `src/job_search_email/scorer.py`.
2. Run `pytest` — the suite must pass (some tests assert on prompt content;
   update them only where the assertion is genuinely stale).
3. Save each disagreement job as a corpus case (step 7 format) BEFORE
   re-scoring, so the expectation is pinned.
4. Re-score every case file in `calibration/cases/` (including the new ones):
   `explain-job --job-file calibration/cases/<file> --profile profiles/<its
   calibration.profile>.yaml --force-score`
   (`--force-score` because explain-job replays the hard filters first and a
   case job might otherwise be rejected before scoring; each call makes live
   LLM calls, so this costs a few Haiku requests per case).
5. Compare each resulting score against the case's `expected_min` /
   `expected_max` bounds. A case outside its bounds is a REGRESSION: refine
   the edit or revert it and re-run this step. Never finish with a failing
   case in place.

## 7. Record and summarise

For each disagreement (regardless of whether a prompt edit was applied),
write `calibration/cases/<YYYY-MM-DD>-<job-slug>.yaml` — slug from the job
title, lowercase, hyphenated, ≤6 words. Build the YAML directly from the
job's fields in `job_results_scored.json` (do not re-fetch):

```yaml
title: ...
company: ...
location: ...
salary_min: ...
description: |
  ...full description...
url: ...
source: ...
employment_type: ...
calibration:
  profile: <stem>
  scored: <the score analysis.score gave this run>
  expected_max: <bound implied by your assessment>   # and/or expected_min
  reason: "<one line: why the original score was wrong>"
  date: <YYYY-MM-DD>
```

Use `expected_min`/`expected_max` bounds, not exact scores — Haiku wobbles
±1 between runs. Commit new case files together with any prompt edit.

Finish with a summary table: job, scorer score, your score, diagnosis,
action taken (prompt edited / case recorded / no change), plus any skipped
jobs and data problems.
````

- [ ] **Step 2: Verify the file is tracked and the frontmatter parses**

```powershell
git status --short .claude/commands/calibrate-scorer.md; python -c "import yaml,io; t=io.open('.claude/commands/calibrate-scorer.md',encoding='utf-8').read(); print(yaml.safe_load(t.split('---')[1]))"
```

Expected: `git status` shows `?? .claude/commands/calibrate-scorer.md` (untracked, not ignored), and the python one-liner prints `{'description': ..., 'argument-hint': ...}` without error.

- [ ] **Step 3: Commit**

```powershell
git add .claude/commands/calibrate-scorer.md; git commit -m @'
feat: add /calibrate-scorer slash command for scorer prompt calibration

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: Corpus scaffold + `load_job_file` tolerance test

**Files:**
- Create: `calibration/cases/README.md`
- Test: `tests/test_job_resolver.py` (append one test)

**Interfaces:**
- Consumes: `job_resolver.load_job_file(path: str) -> JobListing` (existing).
- Produces: `calibration/cases/` directory with its convention documented; a pinned guarantee that case files (with their extra `calibration` block) load cleanly through `explain-job --job-file`.

- [ ] **Step 1: Write the failing-or-passing tolerance test**

Append to `tests/test_job_resolver.py`:

```python
def test_load_job_file_ignores_calibration_block(tmp_path):
    # calibration/cases/*.yaml files carry an extra `calibration` block that
    # explain-job must silently ignore when replaying the job.
    case = tmp_path / "case.yaml"
    case.write_text(
        "title: Business Architect\n"
        "company: AECOM\n"
        "location: Cardiff\n"
        "salary_min: 70000\n"
        "description: Org design lead role.\n"
        "url: https://example.com/job\n"
        "source: manual\n"
        "employment_type: fulltime\n"
        "calibration:\n"
        "  profile: jie-zhou\n"
        "  scored: 7\n"
        "  expected_max: 6\n"
        "  reason: gatekeeping gap\n"
        "  date: 2026-07-11\n",
        encoding="utf-8",
    )
    job = load_job_file(str(case))
    assert job.title == "Business Architect"
    assert job.salary_min == 70000
    assert job.employment_type == "fulltime"
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_job_resolver.py::test_load_job_file_ignores_calibration_block -v`
Expected: PASS immediately — `load_job_file` already reads only known keys. This test is a pin, not TDD for new behaviour: it fails in future only if someone makes job-file loading strict, which would break every corpus case.

- [ ] **Step 3: Write the corpus README**

Create `calibration/cases/README.md`:

```markdown
# Scorer calibration cases

Regression corpus for the `/calibrate-scorer` command. Each YAML file is one
job where the scorer's rating was judged wrong, plus the bounds a correct
score must satisfy. After any scorer-prompt edit, `/calibrate-scorer` replays
every case with:

    explain-job --job-file calibration/cases/<file> \
        --profile profiles/<calibration.profile>.yaml --force-score

and fails the calibration run if any score lands outside its bounds.

## File format

Standard job fields (`title`, `company`, `location`, `salary_min`,
`description`, `url`, `source`, `employment_type`) — the same shape
`explain-job --dump-job-file` writes — plus a `calibration` block that
`explain-job` ignores:

    calibration:
      profile: jie-zhou        # profile stem the case was scored against
      scored: 7                # what the scorer gave when the case was filed
      expected_max: 6          # pass if score <= 6; expected_min also allowed
      reason: "why the original score was wrong"
      date: 2026-07-11

Use `expected_min`/`expected_max` bounds, not exact scores — scoring wobbles
±1 between runs. Files are named `<YYYY-MM-DD>-<job-slug>.yaml`.

The corpus starts empty: the AECOM case that motivated the 2026-07-04
calibration predates it and its job data is no longer recoverable.
```

- [ ] **Step 4: Run the full suite**

Run: `pytest`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add calibration/cases/README.md tests/test_job_resolver.py; git commit -m @'
feat: add calibration case corpus scaffold and job-file tolerance pin

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: Document the command in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (append to the "Local debugging tools" section, after the three console-script bullets)

**Interfaces:**
- Consumes: the command and corpus conventions from Tasks 2–3 (paths and flags must match exactly).

- [ ] **Step 1: Add the documentation**

In `CLAUDE.md`, after the `job-search-email-local` bullet (the last of the three console-script bullets) and before the `IMPORTANT:` paragraph, insert:

```markdown

There is also a Claude Code slash command for scorer calibration:

- `/calibrate-scorer [profile-stem]` (default `jie-zhou`) — runs `job-search-debug` fresh, blind-re-assesses the top 5 scored jobs, and proposes scorer-prompt edits for approval. Confirmed disagreements are saved to `calibration/cases/*.yaml` (job fields + a `calibration` block with `expected_min`/`expected_max` score bounds); after any prompt edit the command replays every saved case via `explain-job --job-file <case> --force-score` and must not finish with a case outside its bounds.
```

- [ ] **Step 2: Verify consistency**

Check the inserted text against the actual artifacts: the command file is `.claude/commands/calibrate-scorer.md`, the corpus dir is `calibration/cases/`, and the flags named exist in `explain-job --help`.

Run: `explain-job --help`
Expected: help text lists `--job-file`, `--profile`, `--force-score`.

- [ ] **Step 3: Commit**

```powershell
git add CLAUDE.md; git commit -m @'
docs: document /calibrate-scorer command and calibration corpus in CLAUDE.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```
