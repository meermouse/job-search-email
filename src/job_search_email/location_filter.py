import json
import os
import sys
from pathlib import Path

import anthropic

client = anthropic.Anthropic()

_MODEL = os.getenv("SCORER_MODEL", "claude-haiku-4-5-20251001")

_SYSTEM_PROMPT = (
    "You are a UK geography expert. Given a home city, a radius in miles, and a list of "
    "location strings from job listings, classify each string as:\n"
    '- "within": the location is clearly within the radius\n'
    '- "outside": the location is clearly outside the radius\n'
    '- "uncertain": the location is ambiguous, vague (e.g. "Remote", "United Kingdom", '
    '"Hybrid"), or too obscure to judge confidently\n\n'
    "When in doubt, use uncertain — it is always safer to allow a job through than to "
    "incorrectly reject it.\n"
    "Respond only with valid JSON: an object mapping each input string to its verdict."
)


def _cache_key(home: str, radius_miles: int, location: str) -> str:
    return f"{home}:{radius_miles}:{location}"


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        return "\n".join(lines[1:end]).strip()
    return stripped


def classify_locations(
    locations: list[str],
    home: str,
    radius_miles: int,
    cache: dict[str, str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    to_classify: list[str] = []

    for loc in locations:
        key = _cache_key(home, radius_miles, loc)
        if key in cache:
            result[loc] = cache[key]
        else:
            to_classify.append(loc)

    if not to_classify:
        return result

    try:
        user_message = (
            f"Home location: {home}. Radius: {radius_miles} miles.\n"
            f"Classify these locations:\n{json.dumps(to_classify, ensure_ascii=False)}"
        )
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text if response.content else ""
        raw = json.loads(_strip_code_fence(text))
        if not isinstance(raw, dict):
            raise ValueError(f"expected dict, got {type(raw).__name__}")
        verdicts: dict[str, str] = raw
    except Exception as exc:
        print(f"[location_filter] classify call failed: {exc}", file=sys.stderr)
        verdicts = {}

    for loc in to_classify:
        verdict = verdicts.get(loc, "uncertain")
        if verdict not in ("within", "outside", "uncertain"):
            verdict = "uncertain"
        result[loc] = verdict
        cache[_cache_key(home, radius_miles, loc)] = verdict

    return result


def load_location_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_location_cache(cache: dict[str, str], path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, path)
