import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from .models import Profile


def fingerprint_profile(profile: Profile) -> str:
    canonical = json.dumps(asdict(profile), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_score_key(url: str, profile_fingerprint: str) -> str:
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{url_hash}_{profile_fingerprint[:12]}"


def load_score_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_score_cache(cache: dict, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    os.replace(tmp, path)
