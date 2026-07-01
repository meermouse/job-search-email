import csv
from pathlib import Path

from .sponsor_filter import _normalize, _build_entries


def load_recruitment_set(csv_path: Path) -> frozenset[str]:
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
