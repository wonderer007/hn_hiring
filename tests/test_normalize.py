import pytest
from hn_ingest.normalize import (
    apply_tech_alias,
    apply_city_alias,
    apply_country_alias,
    apply_currency_alias,
    normalize_salary,
    map_remote_region,
    infer_country_from_city,
)

# ── tech aliases ───────────────────────────────────────────────────────────────

_TECH = {
    "golang": "go",
    "reactjs": "react",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "nodejs": "node",
    "js": "javascript",
}


def test_tech_known_alias():
    assert apply_tech_alias("golang", _TECH) == "go"


def test_tech_case_insensitive():
    assert apply_tech_alias("Golang", _TECH) == "go"


def test_tech_unknown_passthrough():
    assert apply_tech_alias("somethingNew", _TECH) == "somethingnew"


def test_tech_k8s():
    assert apply_tech_alias("k8s", _TECH) == "kubernetes"


# ── country aliases ────────────────────────────────────────────────────────────

_COUNTRY = {
    "usa": "US",
    "united states": "US",
    "uk": "GB",
    "germany": "DE",
    "the netherlands": "NL",
}


def test_country_usa():
    assert apply_country_alias("USA", _COUNTRY) == "US"


def test_country_case_insensitive():
    assert apply_country_alias("united states", _COUNTRY) == "US"


def test_country_uk():
    assert apply_country_alias("UK", _COUNTRY) == "GB"


def test_country_unknown_passthrough():
    assert apply_country_alias("Narnia", _COUNTRY) == "Narnia"


def test_country_none():
    assert apply_country_alias(None, _COUNTRY) is None


# ── currency aliases ───────────────────────────────────────────────────────────

_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "usd": "USD"}


def test_currency_dollar():
    assert apply_currency_alias("$", _CURRENCY) == "USD"


def test_currency_euro():
    assert apply_currency_alias("€", _CURRENCY) == "EUR"


def test_currency_case():
    assert apply_currency_alias("USD", _CURRENCY) == "USD"


def test_currency_none():
    assert apply_currency_alias(None, _CURRENCY) is None


# ── salary normalization ───────────────────────────────────────────────────────


def test_salary_k_shorthand_year():
    mn, mx = normalize_salary(150, 250, "year")
    assert mn == 150_000
    assert mx == 250_000


def test_salary_no_k_shorthand_for_non_year():
    mn, mx = normalize_salary(50, 100, "hour")
    assert mn == 50
    assert mx == 100


def test_salary_inversion_swap():
    mn, mx = normalize_salary(300_000, 100_000, "year")
    assert mn == 100_000
    assert mx == 300_000


def test_salary_absurd_value_nulled():
    mn, mx = normalize_salary(3_000_000, None, "year")
    assert mn is None


def test_salary_none_values():
    mn, mx = normalize_salary(None, None, "year")
    assert mn is None
    assert mx is None


def test_salary_single_value():
    mn, mx = normalize_salary(120, None, "year")
    assert mn == 120_000
    assert mx is None


# ── remote region mapping ──────────────────────────────────────────────────────

_REMOTE_RULES = {
    "worldwide": ["worldwide", "global", "anywhere"],
    "us_only": ["us only", "usa only", "remote us", "remote (us)"],
    "eu_only": ["eu only", "europe only"],
    "timezone_bound": ["timezone", "est", "cet", "overlap"],
    "other": [],
}


def test_remote_worldwide():
    assert map_remote_region("worldwide", _REMOTE_RULES) == "worldwide"


def test_remote_global():
    assert map_remote_region("Global (anywhere)", _REMOTE_RULES) == "worldwide"


def test_remote_us_only():
    assert map_remote_region("Remote (US)", _REMOTE_RULES) == "us_only"


def test_remote_eu():
    assert map_remote_region("EU only", _REMOTE_RULES) == "eu_only"


def test_remote_timezone():
    assert map_remote_region("Must overlap EST", _REMOTE_RULES) == "timezone_bound"


def test_remote_other():
    assert map_remote_region("APAC preferred", _REMOTE_RULES) == "other"


def test_remote_none():
    assert map_remote_region(None, _REMOTE_RULES) is None


# ── city → country inference ───────────────────────────────────────────────────

_CITY_COUNTRY = {"San Francisco": "US", "London": "GB", "Berlin": "DE"}


def test_city_country_known():
    assert infer_country_from_city("San Francisco", _CITY_COUNTRY) == "US"


def test_city_country_unknown():
    assert infer_country_from_city("Atlantis", _CITY_COUNTRY) is None


def test_city_country_none():
    assert infer_country_from_city(None, _CITY_COUNTRY) is None
