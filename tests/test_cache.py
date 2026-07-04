import json
import os
from dataclasses import dataclass
from pathlib import Path

from job_search_email.cache import (
    fingerprint_profile,
    fingerprint_prompt,
    load_score_cache,
    make_score_key,
    save_score_cache,
)
from job_search_email.models import Profile
from profile_helpers import make_profile as _shared_profile


def make_profile(**kwargs) -> Profile:
    defaults = dict(skills=["python"], target_roles=["Lead"])
    defaults.update(kwargs)
    return _shared_profile(**defaults)


def test_load_score_cache_returns_empty_when_missing(tmp_path: Path):
    result = load_score_cache(tmp_path / "missing.json")
    assert result == {}


def test_load_score_cache_returns_empty_on_corrupt_file(tmp_path: Path):
    p = tmp_path / "cache.json"
    p.write_text("not valid json", encoding="utf-8")
    result = load_score_cache(p)
    assert result == {}


def test_load_score_cache_returns_contents(tmp_path: Path):
    p = tmp_path / "cache.json"
    data = {"key1": {"score": 8}}
    p.write_text(json.dumps(data), encoding="utf-8")
    assert load_score_cache(p) == data


def test_save_score_cache_writes_json(tmp_path: Path):
    p = tmp_path / "cache.json"
    data = {"key1": {"score": 8, "verdict": "good"}}
    save_score_cache(data, p)
    assert json.loads(p.read_text(encoding="utf-8")) == data


def test_save_score_cache_no_temp_file_left(tmp_path: Path):
    p = tmp_path / "cache.json"
    save_score_cache({"k": {}}, p)
    assert not (tmp_path / "cache.tmp").exists()


def test_save_score_cache_overwrites_existing(tmp_path: Path):
    p = tmp_path / "cache.json"
    p.write_text(json.dumps({"old": "data"}), encoding="utf-8")
    save_score_cache({"new": "data"}, p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"new": "data"}


def test_make_score_key_is_deterministic():
    key1 = make_score_key("https://example.com/job/1", "abc123fingerprint", "promptfp")
    key2 = make_score_key("https://example.com/job/1", "abc123fingerprint", "promptfp")
    assert key1 == key2


def test_make_score_key_differs_by_url():
    key1 = make_score_key("https://example.com/job/1", "fp", "pfp")
    key2 = make_score_key("https://example.com/job/2", "fp", "pfp")
    assert key1 != key2


def test_make_score_key_differs_by_fingerprint():
    key1 = make_score_key("https://example.com/job/1", "fp_a", "pfp")
    key2 = make_score_key("https://example.com/job/1", "fp_b", "pfp")
    assert key1 != key2


def test_make_score_key_differs_by_prompt_fingerprint():
    key1 = make_score_key("https://example.com/job/1", "fp", "prompt_fp_a")
    key2 = make_score_key("https://example.com/job/1", "fp", "prompt_fp_b")
    assert key1 != key2


def test_make_score_key_format():
    key = make_score_key("https://example.com/job/1", "abcdef123456789", "9876543210fedcba")
    parts = key.split("_")
    assert len(parts) == 3
    assert len(parts[0]) == 12
    assert len(parts[1]) == 12
    assert len(parts[2]) == 12


def test_fingerprint_profile_is_deterministic():
    p = make_profile()
    assert fingerprint_profile(p) == fingerprint_profile(p)


def test_fingerprint_profile_changes_with_profile():
    p1 = make_profile(name="Alice")
    p2 = make_profile(name="Bob")
    assert fingerprint_profile(p1) != fingerprint_profile(p2)


def test_fingerprint_profile_is_hex_string():
    fp = fingerprint_profile(make_profile())
    assert len(fp) == 64
    int(fp, 16)  # raises ValueError if not valid hex


def test_fingerprint_prompt_is_deterministic():
    assert fingerprint_prompt("some prompt") == fingerprint_prompt("some prompt")


def test_fingerprint_prompt_changes_with_text_and_is_hex():
    fp1 = fingerprint_prompt("prompt A")
    fp2 = fingerprint_prompt("prompt B")
    assert fp1 != fp2
    assert len(fp1) == 64
    int(fp1, 16)  # raises ValueError if not valid hex
