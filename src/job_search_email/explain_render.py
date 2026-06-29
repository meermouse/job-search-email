from .filter_trace import GateResult
from .models import JobListing
from .scorer import AnalysisTrace

_RULE = "─" * 46


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "(none)"


def _gates_block(gates: list[GateResult]) -> str:
    lines = []
    for g in gates:
        mark = "✓" if g.passed else "✗"
        suffix = "   ← first reject" if g.is_first_reject else ""
        lines.append(f"{mark} {g.name:<18} {g.detail}{suffix}")
    return "\n".join(lines)


def _scorer_block(trace: AnalysisTrace) -> str:
    a = trace.analysis
    qual = a.qualification_status or "n/a"
    return (
        f"Score: {a.score}/10\n"
        f"Verdict: {a.verdict}\n"
        f"Matched: {_format_list(a.matched_skills)}\n"
        f"Missing: {_format_list(a.missing_essentials)}\n"
        f"Qualifications: {qual} (gaps: {_format_list(a.qualification_gaps)})\n"
        f"Exclude: {'yes — ' + (a.exclude_reason or '(reason not provided)') if a.exclude else 'no'}\n"
        f"\n── LLM CALL (verbatim) {_RULE[:24]}\n"
        f"[system prompt]\n{trace.system_prompt}\n\n"
        f"[user message]\n{trace.user_message}\n\n"
        f"[raw response]\n{trace.raw_text}"
    )


def render_explanation(
    job: JobListing,
    gates: list[GateResult],
    scorer_trace: AnalysisTrace | None,
    skipped_reason: str | None,
) -> str:
    salary = f"£{job.salary_min:,}" if job.salary_min else "not stated"
    header = (
        f"JOB: {job.title} — {job.company}  ({job.source})\n"
        f"URL: {job.url or '(none)'}\n"
        f"Salary: {salary} | Type: {job.employment_type or 'not stated'} "
        f"| Location: {job.location or 'not stated'}\n"
    )

    parts = [header, f"── HARD FILTERS {_RULE}", _gates_block(gates)]

    if scorer_trace is not None:
        parts.append(f"\n── AI SUITABILITY {_RULE}")
        parts.append(_scorer_block(scorer_trace))
    elif skipped_reason is not None:
        parts.append(f"\n→ AI scorer skipped ({skipped_reason}). "
                     "Re-run with --force-score to score anyway.")

    return "\n".join(parts) + "\n"
