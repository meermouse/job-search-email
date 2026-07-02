import pytest
from pathlib import Path
from job_search_email.recruitment_filter import load_recruitment_set


@pytest.fixture
def recruitment_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "recruiters.csv"
    csv_file.write_text(
        "Organisation Name\n"
        "\n"
        '"Hays Specialist Recruitment Limited"\n'
        "\n"
        '"1 Force Recruitment Ltd"\n'
        '"Short"\n',
        encoding="utf-8",
    )
    return csv_file


def test_load_recruitment_set_returns_frozenset(recruitment_csv: Path):
    assert isinstance(load_recruitment_set(recruitment_csv), frozenset)


def test_load_recruitment_set_contains_full_normalized_name(recruitment_csv: Path):
    assert "hays specialist recruitment" in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_contains_two_word_prefix(recruitment_csv: Path):
    assert "hays specialist" in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_does_not_add_single_word_prefix(recruitment_csv: Path):
    assert "hays" not in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_skips_blank_rows(recruitment_csv: Path):
    assert "" not in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_keeps_short_single_word(recruitment_csv: Path):
    assert "short" in load_recruitment_set(recruitment_csv)


def test_load_recruitment_set_handles_utf8_bom(tmp_path):
    # Regression: the real asset ships with a UTF-8 BOM; the loader must not
    # read the header as '﻿Organisation Name' and drop every row.
    csv_file = tmp_path / "recruiters_bom.csv"
    csv_file.write_bytes(
        b"\xef\xbb\xbf"
        + b'Organisation Name\n"Hays Specialist Recruitment Limited"\n'
    )
    result = load_recruitment_set(csv_file)
    assert result  # non-empty
    assert "hays specialist recruitment" in result
