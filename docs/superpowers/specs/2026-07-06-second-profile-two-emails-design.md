# Second Profile → Two Daily Emails — Design

**Date:** 2026-07-06
**Branch:** feature/FE-017-additional-profile

## Goal

Support a second candidate profile so the daily GitHub Action sends **two
independent job-opportunity emails** — one per person, each to their own
recipient, filtered and scored against their own profile. Reuse the existing
manual "LinkedIn PDF import" flow to populate the second profile's YAML.

Today the pipeline loads a single hardcoded `profile.yaml` from the repo root
([main.py](../../../src/job_search_email/main.py)) and writes its run artifacts
to the root. This design generalises that to N profiles discovered from a
`profiles/` directory, run sequentially in one invocation.

## Approach

Auto-discover profiles from a `profiles/` directory. `main()` loops over every
profile file, runs the full fetch → classify → filter → score pipeline for each,
and sends that profile's email to its own recipient. Adding a third person later
is just dropping a YAML file into `profiles/` — no code or workflow change.

## Profile discovery

- New directory: `profiles/`.
- The existing root `profile.yaml` **moves** to `profiles/jie-zhou.yaml`
  (content unchanged). The second profile is added as a sibling file, its stem
  derived from the second person's name (known only once their LinkedIn PDF is
  provided at implementation time — see "Second profile content").
- Discovery order is deterministic: `sorted(profiles_dir.glob("*.yaml"))`.
- The per-profile YAML schema is **unchanged** — the same LinkedIn-shaped
  `profile:` block plus the same top-level keys (`location`, `radius_miles`,
  `min_salary`, `preamble`, `recipient_email`, `send_main_email`,
  `send_debug_email`, `filter_recruitment`). Each person carries their own
  recipient, location, salary, and toggles; the two profiles are fully
  independent.

## One invocation, two emails, with failure isolation

`main()` becomes:

1. Discover profile files in `profiles/`.
2. For each profile file, run the pipeline and send its email(s), wrapped in a
   try/except so **one profile's failure does not block the others**. A scrape
   error, scoring error, or SMTP failure for person A must not prevent person B's
   email.
3. Log each per-profile failure with a traceback to stderr and continue.
4. After the loop, if any profile failed, exit non-zero so the GitHub Action
   still surfaces the failure — but only after all profiles have been attempted.

The main-vs-debug email routing per profile (`send_main_email` /
`send_debug_email` / `SMTP_USER` redirect) is unchanged; it already reads from
the profile.

## Caches stay shared (no collision)

The three root cache files remain shared across profiles because their keys
already namespace by profile:

- `location_cache.json` — keyed `home:radius:location`
  ([location_filter.py](../../../src/job_search_email/location_filter.py) `_cache_key`).
  Different homes → different keys, no cross-contamination; a shared file lets
  person B reuse person A's classifications.
- `search_plan_cache.json` — keyed by profile fingerprint.
- `job_score_cache.json` — keyed by profile fingerprint (+ scorer prompt
  fingerprint).

Consequence: the GitHub Action's `actions/cache` step needs **no change** — the
same three files are restored/saved.

## Per-profile run outputs

The per-run debug artifacts currently written to the repo root
(`search_plan.json`, `job_results.json`, `job_results_filtered.json`,
`job_results_scored.json`) would overwrite each other between the two profile
runs. They move to a per-profile directory: `runs/<profile-stem>/…` (e.g.
`runs/jie-zhou/job_results.json`).

- `run_pipeline` gains an `output_dir` parameter; the four write paths are built
  relative to it. The shared caches keep their root paths.
- `runs/` is added to `.gitignore` (run artifacts are not committed).

## Debug tooling updates

The debug entry points operate on a single profile and must point at the new
locations:

- `explain-job` ([explain_job.py](../../../src/job_search_email/explain_job.py)):
  `--profile` default becomes `profiles/jie-zhou.yaml`; `--run-data` default
  becomes `runs/jie-zhou/job_results.json`. Debugging person B:
  `explain-job <url> --profile profiles/<person2>.yaml --run-data runs/<person2>/job_results.json`.
- `job-search-debug` ([debug_run.py](../../../src/job_search_email/debug_run.py))
  and `job-search-email-local`
  ([local_run.py](../../../src/job_search_email/local_run.py)): load the primary
  profile from `profiles/jie-zhou.yaml` (was `profile.yaml`). These remain
  single-profile debug tools; multi-profile is a production-pipeline concern
  only.

## GitHub Action

[daily_job.yml](../../../.github/workflows/daily_job.yml) is effectively
unchanged: it still installs the package and runs `job-search-email` once per
day (and on push to main). The command now loops over `profiles/` internally.
Cache paths are unchanged.

## Second profile content (the "PDF import")

There is no automated importer — "PDF import" is the established manual,
Claude-assisted transcription flow from the enhanced-linkedin-profile work
([2026-07-03 spec](2026-07-03-enhanced-linkedin-profile-design.md)):

1. The user drops the second person's LinkedIn "Save to PDF" export at
   `assets/Profile.pdf`.
2. Its content is transcribed **verbatim** into `profiles/<person2>.yaml`
   following the same schema, deriving the file stem from the person's name.
3. Known limitation carried over: LinkedIn's PDF export lists only the top 3
   skills, so `skills` merges those three with skill-like terms drawn from the
   experience descriptions.
4. The PDF is **deleted — not committed** (the YAML already carries the personal
   data the pipeline needs).

## Testing

- `main()` multi-profile loop: discovers all `profiles/*.yaml`, runs the
  pipeline once per file, and a failure in one profile still lets the others
  send (isolation). Update `test_main.py`, which currently patches `ROOT` /
  `PROFILE_PATH` — repoint at the `profiles/` discovery and `runs/<stem>/`
  outputs.
- `run_pipeline` writes its four artifacts under the given `output_dir`.
- Update tests that reference the moved `profile.yaml`
  (`tests/test_local_testing.py` copies it; `explain-job` default tests) to the
  new paths.
- Full suite green before merge.

## Documentation

- `README.md` and `CLAUDE.md`: profile location is now `profiles/<name>.yaml`;
  the pipeline runs every profile in `profiles/`; debug-tool default paths
  updated.

## Out of scope

- Automated LinkedIn re-sync or an automated PDF parser (transcription stays
  manual).
- Changing filter/score/search/email logic.
- Per-profile scheduling (both run in the same daily invocation).
- Parallelising the two profile runs (sequential is fine at this scale).
