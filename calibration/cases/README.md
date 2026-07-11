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
