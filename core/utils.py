"""
Fælles hjælpefunktioner for debatstof-scraperen.

Flyttet ud af run_scraper.py i v13.1.

Kun sikre, generelle funktioner:
- tekst-rensning
- URL-rensning
- artikel-id
- timestamp-normalisering
"""

import datetime as dt
import hashlib
import html
from typing import Any
from urllib.parse import parse_qsl, urlencode, unquote, urlparse, urlunparse

from dateutil import parser as dateparser


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = html.unescape(text)
    text = " ".join(text.split())
    return text


def clean_url(url: str) -> str:
    url = url.strip()
    decoded = unquote(url)
    if decoded.startswith("http://") or decoded.startswith("https://"):
        return decoded
    return url


def canonicalize_url_for_dedupe(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def article_id_from_url(url: str) -> str:
    """
    Stabilt internt artikel-id baseret på canonical URL.
    Bruges senere af app/database/temaer.
    """
    canonical = canonicalize_url_for_dedupe(url)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]
    return f"art_{digest}"


def normalize_timestamp(value: str | None) -> str:
    """
    Konverterer tidsstempler til ISO-format.

    Eksempel:
    2026-05-23T14:32:11Z

    Hvis datoen ikke kan parses sikkert, returneres originalværdien.
    """
    if not value:
        return ""

    value = str(value).strip()

    # Allerede ISO-lignende.
    if "T" in value and value.endswith("Z"):
        return value

    candidate_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y",
    ]

    for fmt in candidate_formats:
        try:
            parsed = dt.datetime.strptime(value, fmt)
            return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue

    return value
