"""
Country code and location normalization utilities.

Provides mappings from ISO 3166-1 alpha-2 / alpha-3 country codes and country
names to canonical country information, demonyms, top-level domains (ccTLDs),
and known regional indicators. Used to strictly enforce location hints
during discovery, candidate filtering, and entity resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CountryInfo:
    code: str                  # ISO 3166-1 alpha-2, e.g. "KE"
    name: str                  # English name, e.g. "Kenya"
    demonym: str               # e.g. "Kenyan"
    aliases: tuple[str, ...]   # ["ke", "kenya", "kenyan", "nairobi", ...]
    tlds: tuple[str, ...]      # [".ke", ".co.ke", "ke.linkedin.com"]
    ddgs_region: str | None = None  # DuckDuckGo region code if applicable, e.g. "ke-en"


# Comprehensive mapping of common countries and ISO alpha-2 codes
_COUNTRY_REGISTRY: list[CountryInfo] = [
    CountryInfo(
        code="KE",
        name="Kenya",
        demonym="Kenyan",
        aliases=("ke", "kenya", "kenyan", "nairobi", "mombasa", "kisumu", "nakuru", "eldoret"),
        tlds=(".ke", ".co.ke", ".or.ke", ".go.ke", "ke.linkedin.com"),
        ddgs_region="ke-en",
    ),
    CountryInfo(
        code="UG",
        name="Uganda",
        demonym="Ugandan",
        aliases=("ug", "uganda", "ugandan", "kampala", "entebbe", "jinja"),
        tlds=(".ug", ".co.ug", ".go.ug", "ug.linkedin.com"),
        ddgs_region="ug-en",
    ),
    CountryInfo(
        code="TZ",
        name="Tanzania",
        demonym="Tanzanian",
        aliases=("tz", "tanzania", "tanzanian", "dar es salaam", "dodoma", "arusha", "zanzibar"),
        tlds=(".tz", ".co.tz", ".go.tz", "tz.linkedin.com"),
        ddgs_region="tz-en",
    ),
    CountryInfo(
        code="RW",
        name="Rwanda",
        demonym="Rwandan",
        aliases=("rw", "rwanda", "rwandan", "kigali"),
        tlds=(".rw", ".co.rw", ".gov.rw", "rw.linkedin.com"),
        ddgs_region="rw-en",
    ),
    CountryInfo(
        code="NG",
        name="Nigeria",
        demonym="Nigerian",
        aliases=("ng", "nigeria", "nigerian", "lagos", "abuja", "ibadan", "port harcourt"),
        tlds=(".ng", ".com.ng", ".gov.ng", "ng.linkedin.com"),
        ddgs_region="ng-en",
    ),
    CountryInfo(
        code="ZA",
        name="South Africa",
        demonym="South African",
        aliases=("za", "south africa", "south african", "johannesburg", "cape town", "durban", "pretoria"),
        tlds=(".za", ".co.za", ".gov.za", "za.linkedin.com"),
        ddgs_region="za-en",
    ),
    CountryInfo(
        code="GH",
        name="Ghana",
        demonym="Ghanaian",
        aliases=("gh", "ghana", "ghanaian", "accra", "kumasi"),
        tlds=(".gh", ".com.gh", ".gov.gh", "gh.linkedin.com"),
        ddgs_region="gh-en",
    ),
    CountryInfo(
        code="ET",
        name="Ethiopia",
        demonym="Ethiopian",
        aliases=("et", "ethiopia", "ethiopian", "addis ababa"),
        tlds=(".et", ".com.et", "et.linkedin.com"),
        ddgs_region="et-en",
    ),
    CountryInfo(
        code="US",
        name="United States",
        demonym="American",
        aliases=("us", "usa", "united states", "united states of america", "america", "american", "new york", "california", "washington"),
        tlds=(".us", ".gov", ".edu", "www.linkedin.com/in/"),
        ddgs_region="us-en",
    ),
    CountryInfo(
        code="GB",
        name="United Kingdom",
        demonym="British",
        aliases=("gb", "uk", "united kingdom", "great britain", "england", "scotland", "wales", "london", "british"),
        tlds=(".uk", ".co.uk", ".gov.uk", ".ac.uk", "uk.linkedin.com"),
        ddgs_region="uk-en",
    ),
    CountryInfo(
        code="CA",
        name="Canada",
        demonym="Canadian",
        aliases=("ca", "canada", "canadian", "toronto", "vancouver", "montreal", "ottawa", "ontario"),
        tlds=(".ca", "ca.linkedin.com"),
        ddgs_region="ca-en",
    ),
    CountryInfo(
        code="AU",
        name="Australia",
        demonym="Australian",
        aliases=("au", "australia", "australian", "sydney", "melbourne", "brisbane", "perth", "canberra"),
        tlds=(".au", ".com.au", ".gov.au", "au.linkedin.com"),
        ddgs_region="au-en",
    ),
    CountryInfo(
        code="IN",
        name="India",
        demonym="Indian",
        aliases=("in", "india", "indian", "delhi", "new delhi", "mumbai", "bengaluru", "bangalore", "hyderabad", "chennai"),
        tlds=(".in", ".co.in", ".gov.in", "in.linkedin.com"),
        ddgs_region="in-en",
    ),
    CountryInfo(
        code="DE",
        name="Germany",
        demonym="German",
        aliases=("de", "germany", "deutschland", "german", "berlin", "munich", "frankfurt", "hamburg"),
        tlds=(".de", "de.linkedin.com"),
        ddgs_region="de-de",
    ),
    CountryInfo(
        code="FR",
        name="France",
        demonym="French",
        aliases=("fr", "france", "french", "paris", "lyon", "marseille"),
        tlds=(".fr", "fr.linkedin.com"),
        ddgs_region="fr-fr",
    ),
    CountryInfo(
        code="AE",
        name="United Arab Emirates",
        demonym="Emirati",
        aliases=("ae", "uae", "united arab emirates", "dubai", "abu dhabi", "sharjah"),
        tlds=(".ae", "ae.linkedin.com"),
        ddgs_region="ae-en",
    ),
]

# Lookup index by code and alias
_BY_CODE: dict[str, CountryInfo] = {c.code.upper(): c for c in _COUNTRY_REGISTRY}
_BY_ALIAS: dict[str, CountryInfo] = {}
for _c in _COUNTRY_REGISTRY:
    for _alias in _c.aliases:
        _BY_ALIAS[_alias.lower()] = _c


def parse_country(raw: str | None) -> CountryInfo | None:
    """
    Parse a country string (ISO code or country name) into CountryInfo.
    Returns None if input is empty or unparseable.
    """
    if not raw or not raw.strip():
        return None
    val = raw.strip().lower()
    val_upper = raw.strip().upper()

    if val_upper in _BY_CODE:
        return _BY_CODE[val_upper]

    if val in _BY_ALIAS:
        return _BY_ALIAS[val]

    # Substring matching for aliases
    for alias, c in _BY_ALIAS.items():
        if alias == val or (len(alias) >= 4 and alias in val):
            return c

    # Fallback generic CountryInfo if not in registry
    clean_name = raw.strip()
    return CountryInfo(
        code=clean_name.upper()[:3],
        name=clean_name.title(),
        demonym=clean_name.title(),
        aliases=(clean_name.lower(),),
        tlds=(f".{clean_name.lower()[:2]}",),
    )


def text_matches_country(text: str, country: CountryInfo) -> bool:
    """
    Check if text (e.g. snippet, title, claim evidence) matches the country.
    """
    if not text:
        return False
    lower = text.lower()

    # Direct check of country name or demonym
    if country.name.lower() in lower or country.demonym.lower() in lower:
        return True

    # Check for country code with word boundary (e.g. "Nairobi, KE" or "Kenya (KE)")
    if re.search(rf"\b{re.escape(country.code.lower())}\b", lower):
        # Avoid false positives for common English two-letter words like 'in', 'us', 'at', 'is'
        if country.code.lower() in ("us", "in", "it", "at", "to", "no", "is", "me"):
            # Only match if preceded by comma or in location context e.g. "city, us" or "united states"
            if re.search(rf",\s*{re.escape(country.code.lower())}\b", lower) or re.search(rf"\b{re.escape(country.code.upper())}\b", text):
                return True
        else:
            return True

    # Check key aliases (e.g. cities like Nairobi)
    for alias in country.aliases:
        if len(alias) >= 4 and re.search(rf"\b{re.escape(alias)}\b", lower):
            return True

    # Check TLDs
    for tld in country.tlds:
        if tld in lower:
            return True

    return False


def text_conflicts_with_country(text: str, target_country: CountryInfo) -> tuple[bool, str | None]:
    """
    Check if text clearly refers to a DIFFERENT country than target_country.
    Returns (True, conflicting_country_name) if a conflict is detected,
    or (False, None) if compatible or inconclusive.
    """
    if not text:
        return False, None

    lower = text.lower()

    # If the text also matches the target country, treat it as compatible/not a pure conflict
    if text_matches_country(text, target_country):
        return False, None

    # Check against known other countries
    for other in _COUNTRY_REGISTRY:
        if other.code == target_country.code:
            continue

        # Look for explicit location markers: "Location: United States", "Greater Perth Area", "London, UK", etc.
        # Check TLD (e.g. uk.linkedin.com, ae.linkedin.com)
        for tld in other.tlds:
            if len(tld) > 3 and tld in lower:
                return True, other.name

        # Explicit location phrase matching
        loc_patterns = [
            rf"location:\s*{re.escape(other.name.lower())}",
            rf"location:\s*[^,]+,\s*{re.escape(other.name.lower())}",
            rf"based in\s+{re.escape(other.name.lower())}",
            rf",\s*{re.escape(other.name.lower())}\b",
            rf"\b{re.escape(other.name.lower())}\s*\|\s*professional profile",
        ]
        for pat in loc_patterns:
            if re.search(pat, lower):
                return True, other.name

        # For major distinct cities/aliases of other countries
        for alias in other.aliases:
            if len(alias) >= 5:
                # e.g. "location: united states", "dubai", "toronto", "sydney"
                if re.search(rf"location:\s*[^.]*\b{re.escape(alias)}\b", lower):
                    return True, other.name

    return False, None
