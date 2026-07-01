import argparse
import sys
import time
from pathlib import Path

from .exclusions import get_exclusions
from .explain_render import render_explanation
from .filter_trace import run_filter_gates
from .job_resolver import (
    UnsupportedSourceError,
    dump_job_file,
    load_run_data,
    lookup_job,
    resolve_job,
)
from .location_filter import classify_locations
from .main import SPONSOR_CACHE_PATH, load_profile
from .nhs_rules import get_nhs_rules
from .scorer import analyse_job
from .sponsor_filter import load_sponsor_set


def _format_age(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)}m old"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h old"
    return f"{int(seconds // 86400)}d old"


def explain(
    url: str | None,
    *,
    profile_path: str = "profile.yaml",
    job_file: str | None = None,
    force_score: bool = False,
    run_data_path: str = "job_results.json",
    dump_job_file_path: str | None = None,
) -> str:
    profile = load_profile(Path(profile_path))

    run_data = None
    run_data_note = None
    rd = Path(run_data_path)
    if rd.exists():
        run_data = load_run_data(rd)

    job = resolve_job(url, job_file, run_data=run_data)

    if run_data is not None and job_file is None and url is not None and lookup_job(url, run_data) is not None:
        age = _format_age(time.time() - rd.stat().st_mtime)
        run_data_note = f"{rd.name} (local run data, {age})"

    if dump_job_file_path:
        dump_job_file(job, dump_job_file_path)

    if job.location:
        verdict = classify_locations(
            [job.location], home=profile.location,
            radius_miles=profile.radius_miles, cache={},
        ).get(job.location, "uncertain")
    else:
        verdict = "uncertain"

    # NOTE: classify_locations and get_exclusions both make live LLM calls and
    # therefore require ANTHROPIC_API_KEY to be set, even when the job is
    # ultimately rejected by a hard filter gate (sponsor, employment-type, etc.).
    sponsor_set = load_sponsor_set(SPONSOR_CACHE_PATH)
    gates = run_filter_gates(
        job, profile,
        location_verdict=verdict,
        sponsor_set=sponsor_set,
        nhs_rules=get_nhs_rules(),
        exclusion_roles=get_exclusions(profile)["roles"],
    )

    first_reject = next((g for g in gates if g.is_first_reject), None)
    if first_reject is not None and not force_score:
        return render_explanation(
            job, gates, None, f"rejected by {first_reject.name}",
            run_data_note=run_data_note,
        )

    scorer_trace = analyse_job(job, profile)
    return render_explanation(job, gates, scorer_trace, None, run_data_note=run_data_note)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="explain-job",
        description="Explain why a job got its rating by replaying the pipeline.",
    )
    parser.add_argument("url", nargs="?", help="Job URL (from the email).")
    parser.add_argument("--profile", default="profile.yaml",
                        help="Path to the profile YAML (default: profile.yaml).")
    parser.add_argument("--job-file",
                        help="YAML with job fields; fallback for LinkedIn/Indeed.")
    parser.add_argument("--force-score", action="store_true",
                        help="Run the AI scorer even if a hard filter rejected the job.")
    parser.add_argument("--run-data", default="job_results.json",
                        help="Path to a local run's job_results.json (default: job_results.json).")
    parser.add_argument("--dump-job-file",
                        help="Write the resolved job's data to this YAML path.")
    args = parser.parse_args(argv)

    try:
        output = explain(
            args.url, profile_path=args.profile,
            job_file=args.job_file, force_score=args.force_score,
            run_data_path=args.run_data, dump_job_file_path=args.dump_job_file,
        )
    except (UnsupportedSourceError, ValueError) as exc:
        print(f"explain-job: {exc}", file=sys.stderr)
        return 2

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
