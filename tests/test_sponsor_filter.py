import pytest
from job_search_email.sponsor_filter import _normalize, load_sponsor_set
from pathlib import Path


def test_normalize_strips_leading_whitespace():
    assert _normalize(" Bossmans Retail Ltd") == "bossmans retail"


def test_normalize_strips_trailing_whitespace():
    assert _normalize("Bossmans Retail Ltd   ") == "bossmans retail"


def test_normalize_lowercases():
    assert _normalize("BOSSMANS RETAIL LTD") == "bossmans retail"


def test_normalize_strips_ltd():
    assert _normalize("Acme Ltd") == "acme"


def test_normalize_strips_limited():
    assert _normalize("Acme Limited") == "acme"


def test_normalize_strips_plc():
    assert _normalize("Tesco Plc") == "tesco"


def test_normalize_strips_llp():
    assert _normalize("Smith Partners LLP") == "smith partners"


def test_normalize_strips_llc():
    assert _normalize("Global Solutions LLC") == "global solutions"


def test_normalize_strips_corp():
    assert _normalize("Big Corp") == "big"


def test_normalize_strips_corporation():
    assert _normalize("Big Corporation") == "big"


def test_normalize_strips_inc():
    assert _normalize("Startup Inc") == "startup"


def test_normalize_strips_co_suffix():
    assert _normalize("John Lewis & Co") == "john lewis"


def test_normalize_strips_ta_clause():
    assert _normalize("HAH Hospitality Limited t/a Indian Affair Ancoats") == "hah hospitality"


def test_normalize_strips_ta_with_uppercase():
    assert _normalize("CASA BAMBOO LTD T/A Pho Le Vietnamese Restaurant") == "casa bamboo"


def test_normalize_removes_punctuation():
    assert _normalize("F-Secure (UK) Limited") == "f-secure uk"


def test_normalize_preserves_hyphen_within_word():
    # hyphens between word chars are kept
    assert "f-secure" in _normalize("F-Secure UK Limited")


def test_normalize_collapses_whitespace():
    assert _normalize("  Big   Corp  Co  ") == "big corp"


def test_normalize_empty_string_returns_empty():
    assert _normalize("") == ""


def test_normalize_strips_trailing_period_on_suffix():
    assert _normalize("Acme Co.") == "acme"


@pytest.fixture
def sponsor_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "sponsors.csv"
    csv_file.write_text(
        "Organisation Name,Town/City,County,Type & Rating,Route\n"
        "\n"
        '" Bossmans Retail Abergavenny Ltd",Abergavenny,,Worker (A rating),Skilled Worker\n'
        "\n"
        '" F-Secure (UK) Limited",Gerrards Cross,Buckinghamshire,Worker (A rating),Skilled Worker\n'
        "\n"
        '" NHS Foundation Trust",London,,Worker (A rating),Skilled Worker\n'
        "\n"
        '"Short",London,,Worker (A rating),Skilled Worker\n',
        encoding="utf-8",
    )
    return csv_file


def test_load_sponsor_set_returns_frozenset(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert isinstance(result, frozenset)


def test_load_sponsor_set_contains_full_normalized_name(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert "bossmans retail abergavenny" in result


def test_load_sponsor_set_contains_two_word_prefix(sponsor_csv: Path):
    # "bossmans retail abergavenny" → prefix "bossmans retail" added
    result = load_sponsor_set(sponsor_csv)
    assert "bossmans retail" in result


def test_load_sponsor_set_does_not_add_single_word_prefix(sponsor_csv: Path):
    # "bossmans" alone must NOT be added as a prefix
    result = load_sponsor_set(sponsor_csv)
    assert "bossmans" not in result


def test_load_sponsor_set_contains_fsecure_entry(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert "f-secure uk" in result


def test_load_sponsor_set_skips_blank_rows(sponsor_csv: Path):
    result = load_sponsor_set(sponsor_csv)
    assert "" not in result


def test_load_sponsor_set_prefix_requires_8_chars(sponsor_csv: Path):
    # "nhs foundation trust" → prefix "nhs foundation" is 14 chars and 2 words → added
    # "nhs" alone (3 chars, 1 word) → NOT added
    result = load_sponsor_set(sponsor_csv)
    assert "nhs foundation" in result
    assert "nhs" not in result


def test_load_sponsor_set_skips_name_too_short_to_normalize(sponsor_csv: Path):
    # "Short" normalizes to "short" (5 chars) — full name still included
    result = load_sponsor_set(sponsor_csv)
    assert "short" in result
