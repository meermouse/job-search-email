This is a python application that is designed to run directly from github through a daily or weekly action. The information provided by the user for now will be hard coded in per-person YAML files under `profiles/` (one email per profile per run).

Its  goal is to provide a regular email to a user with a list of potential job opportunities. This will filter out jobs based upon location, salary range, employment type (permanent, contract, part time), and job suitability. This application also has the important role of only returning jobs from companies and organisations that are part of the uk governments list of approved sponsor companies for immigrants. There is a list of these companies held in a csv file located in:
/assets/sponsor_cache.csv
Profiles that don't need visa sponsorship can set `filter_sponsors: false`.

## Local debugging tools

Three console scripts (defined in pyproject.toml) help debug the pipeline locally:

- `explain-job {job url}` — replays the full filter/score pipeline for one job and explains its rating. Flags: `--profile` (alternate profile YAML, e.g. `--profile profiles/<name>.yaml` selects the person), `--job-file` (supply job fields as YAML — required for LinkedIn/Indeed which can't be auto-fetched), `--force-score` (run the AI scorer even if a hard filter rejected the job), `--run-data` (path to a run's job_results.json, default `runs/<profile>/job_results.json`), `--dump-job-file` (save the resolved job to YAML for reuse).
- `job-search-debug` — runs the real pipeline (live scraping + AI scoring) but writes an HTML decisions report to `debug_report.html` and prints keep/drop decisions instead of emailing.
- `job-search-email-local` — offline dry run against fixture jobs/scores; writes `search_plan.json`, `job_results_filtered.json`, `job_results_scored.json`, and `email_preview.html`. No network or API cost.

IMPORTANT: always check cached data before making unnecessary live calls. `explain-job` resolves jobs from local run data (`job_results.json`) first — pass `--run-data` or use `--dump-job-file` once then `--job-file` for repeat experiments, rather than refetching or re-calling the API. Note that `explain-job` still makes live LLM calls for location classification and exclusions (needs `ANTHROPIC_API_KEY`); use `job-search-email-local` when fixtures are enough.