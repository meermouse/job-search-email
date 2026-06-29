import csv
import re
from pathlib import Path

_TA_RE = re.compile(r"\bt/a\b.*$", re.IGNORECASE)
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|plc|llp|llc|co|corp|corporation|inc|incorporated)\.?\s*$",
    re.IGNORECASE,
)
_PUNCTUATION_RE = re.compile(r"(?<!\w)-(?!\w)|[^\w\s-]")
_WHITESPACE_RE = re.compile(r"\s+")

_MIN_PREFIX_CHARS = 8
_MIN_PREFIX_WORDS = 2


def _normalize(name: str) -> str:
    name = name.strip()
    name = _TA_RE.sub("", name).strip()
    name = _LEGAL_SUFFIX_RE.sub("", name).strip()
    name = name.lower()
    name = _PUNCTUATION_RE.sub("", name)
    name = _WHITESPACE_RE.sub(" ", name).strip()
    return name


def _build_entries(normalized: str) -> list[str]:
    entries = [normalized]
    words = normalized.split()
    for i in range(_MIN_PREFIX_WORDS, len(words)):
        prefix = " ".join(words[:i])
        if len(prefix) >= _MIN_PREFIX_CHARS:
            entries.append(prefix)
    return entries


def load_sponsor_set(csv_path: Path) -> frozenset[str]:
    entries: set[str] = set()
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw = (row.get("Organisation Name") or "").strip()
            if not raw:
                continue
            normalized = _normalize(raw)
            if not normalized:
                continue
            for entry in _build_entries(normalized):
                entries.add(entry)
    return frozenset(entries)
