import json
import os
import sys
from pathlib import Path

import anthropic

from .location_filter import _extract_json_object
from .models import JobListing

client = anthropic.Anthropic()

_MODEL = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")
_BATCH_SIZE = 20
_DESCRIPTION_CHARS = 4000

_SYSTEM_PROMPT = (
    "You are vetting UK job postings for fully-remote working. For each job you are "
    "given an id, title, location string, and description. Classify each job as:\n"
    '- "remote": the posting positively and explicitly confirms fully-remote working '
    '(e.g. "fully remote", "100% remote", "work from anywhere in the UK"). Occasional '
    "pre-arranged visits such as quarterly team days do not disqualify.\n"
    '- "not_remote": everything else — hybrid, a set number of office days per week, '
    '"remote optional", on-site, or the posting never clearly confirms fully-remote '
    "working.\n\n"
    "Silence is not confirmation: when the text does not explicitly confirm fully-remote "
    'working, answer "not_remote".\n'
    "Respond only with valid JSON: an object mapping each job id to its verdict."
)


def _classify_batch(batch: list[JobListing]) -> dict | None:
    payload = [
        {
            "id": str(i),
            "title": job.title,
            "location": job.location,
            "description": (job.description or "")[:_DESCRIPTION_CHARS],
        }
        for i, job in enumerate(batch)
    ]
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": "Classify these jobs:\n" + json.dumps(payload, ensure_ascii=False),
            }],
        )
        text = response.content[0].text if response.content else ""
        raw = _extract_json_object(text)
        if not isinstance(raw, dict):
            raise ValueError(f"expected dict, got {type(raw).__name__}")
        return raw
    except Exception as exc:
        print(f"[remote_filter] classify call failed: {exc}", file=sys.stderr)
        return None


def classify_remote(jobs: list[JobListing], cache: dict[str, str]) -> dict[str, str]:
    """Map each job URL to "remote", "not_remote", or "unverified".

    "unverified" marks jobs whose check could not run (API failure). It is
    never cached, so the next run retries them — the filter gate fails closed
    on it rather than letting an unchecked far-afield job through.
    """
    result: dict[str, str] = {}
    to_check: list[JobListing] = []
    for job in jobs:
        if job.url in cache:
            result[job.url] = cache[job.url]
        else:
            to_check.append(job)

    for start in range(0, len(to_check), _BATCH_SIZE):
        batch = to_check[start:start + _BATCH_SIZE]
        verdicts = _classify_batch(batch)
        for i, job in enumerate(batch):
            if verdicts is None:
                result[job.url] = "unverified"
                continue
            verdict = verdicts.get(str(i))
            if verdict not in ("remote", "not_remote"):
                # Model omitted or garbled the verdict: no positive
                # confirmation exists, which is the strict default.
                verdict = "not_remote"
            result[job.url] = verdict
            cache[job.url] = verdict

    return result


def load_remote_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_remote_cache(cache: dict[str, str], path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, path)
