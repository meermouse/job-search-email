import argparse
from pathlib import Path

from .debug_email import build_debug_email_html
from .main import DEFAULT_PROFILE_PATH, RUNS_DIR, run_pipeline
from .models import ScoredResult
from .profile import load_profile

DEBUG_REPORT_PATH = Path.cwd() / "debug_report.html"


def _print_decisions(scored: list[ScoredResult]) -> None:
    kept = [r for r in scored if not r.rejected]
    rejected = [r for r in scored if r.rejected]
    print("\nDecisions:")
    print(f"  {len(kept)} kept, {len(rejected)} rejected")
    for r in sorted(kept, key=lambda r: (r.analysis.score if r.analysis else 0), reverse=True):
        score = str(r.analysis.score) if r.analysis else "—"
        print(f"  [keep] {score:>3}  {r.job.title} — {r.job.company}")
    for r in rejected:
        print(f"  [drop]      {r.job.title} — {r.job.company}  ({r.reject_reason})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="job-search-debug",
        description="Run the real pipeline and write a decisions report instead of emailing.",
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH,
                        help=f"Path to the profile YAML (default: {DEFAULT_PROFILE_PATH}).")
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    classification, scored = run_pipeline(profile, RUNS_DIR / args.profile.stem)

    html = build_debug_email_html(classification, scored, profile)
    DEBUG_REPORT_PATH.write_text(html, encoding="utf-8")

    _print_decisions(scored)
    print(f"\nDecisions report written to: {DEBUG_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
