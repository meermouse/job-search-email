import pytest
from job_search_email.location_filter import normalise_location


@pytest.mark.parametrize("raw", [
    "EC3A 5AT", "EC3A5AT", "WC2A3LH", "E20 1JN", "N1 9GU", "NW1 6XE",
    "SE1 7PB", "SW1A 1AA", "W1D 3QU", "ec1a 1bb",
])
def test_london_postcodes_map_to_london(raw):
    assert normalise_location(raw) == "London"


@pytest.mark.parametrize("raw", [
    "EN1 1AA", "SL1 2AB", "SG1 3CD", "WD17 1EF", "SM1 4GH", "RG1 1AA", "OX1 1AA",
])
def test_home_counties_postcodes_unchanged(raw):
    assert normalise_location(raw) == raw.strip()


@pytest.mark.parametrize("raw", [
    "London, England, UK", "Bristol", "Greater London, England, UK", "",
])
def test_non_postcodes_unchanged(raw):
    assert normalise_location(raw) == raw.strip()


def test_whitespace_collapsed():
    assert normalise_location("  London,   England  ") == "London, England"
