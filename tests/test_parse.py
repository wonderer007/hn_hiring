import pytest
from hn_ingest.parse import classify_kind, parse_month


class TestClassifyKind:
    def test_hiring(self):
        assert classify_kind("Ask HN: Who is hiring? (July 2026)") == "hiring"

    def test_hiring_prefix_required(self):
        # must START with "Ask HN: Who is hiring?"
        assert classify_kind("Ask HN: Who is hiring? (March 2015)") == "hiring"

    def test_seekers(self):
        assert classify_kind("Ask HN: Who wants to be hired? (July 2026)") == "seekers"

    def test_freelancer(self):
        assert classify_kind("Ask HN: Freelancer? Seeking freelancer? (April 2020)") == "freelancer"

    def test_other(self):
        assert classify_kind("Ask HN: Something completely different") == "other"

    def test_empty(self):
        assert classify_kind("") == "other"

    def test_case_sensitive_hiring(self):
        # lowercase "ask HN" does not match
        assert classify_kind("ask HN: Who is hiring? (July 2026)") == "other"


class TestParseMonth:
    def test_standard_title(self):
        assert parse_month("Ask HN: Who is hiring? (July 2026)", None) == "2026-07"

    def test_january(self):
        assert parse_month("Ask HN: Who is hiring? (January 2011)", None) == "2011-01"

    def test_december(self):
        assert parse_month("Ask HN: Who is hiring? (December 2023)", None) == "2023-12"

    def test_fallback_on_no_match(self):
        assert parse_month("Ask HN: Something else", "2020-03") == "2020-03"

    def test_fallback_none(self):
        assert parse_month("No parenthetical here", None) is None

    def test_unknown_month_name_falls_back(self):
        assert parse_month("Ask HN: (Julember 2026)", "2026-01") == "2026-01"

    def test_two_digit_month_padding(self):
        result = parse_month("Ask HN: Who is hiring? (September 2019)", None)
        assert result == "2019-09"

    def test_early_thread(self):
        assert parse_month("Ask HN: Who is hiring? (June 2011)", None) == "2011-06"
