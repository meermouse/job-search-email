from pathlib import Path

from .debug_email import build_debug_email_html
from .main import PROFILE_PATH, load_profile, run_pipeline
from .models import ScoredResult

DEBUG_REPORT_PATH = Path.cwd() / "debug_report.html"


def _print_decisions(scored: list[ScoredResult]) -> None:
    kept = [r for r in scored if not r.rejected]
    rejected = [r for r in scored if r.rejected]
    print("\nDecisions:")
    print(f"  {len(kept)} kept, {len(rejected)} rejected")
    for r in sorted(kept, key=lambda r: (r.analysis.score if r.analysis else 0), reverse=True):
        score = r.analysis.score if r.analysis else "—"
        print(f"  [keep] {score:>3}  {r.job.title} — {r.job.company}")
    for r in rejected:
        print(f"  [drop]      {r.job.title} — {r.job.company}  ({r.reject_reason})")


def main(argv: list[str] | None = None) -> int:
    profile = load_profile(PROFILE_PATH)
    classification, scored = run_pipeline(profile)

    html = build_debug_email_html(classification, scored, profile)
    DEBUG_REPORT_PATH.write_text(html, encoding="utf-8")

    _print_decisions(scored)
    print(f"\nDecisions report written to: {DEBUG_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
