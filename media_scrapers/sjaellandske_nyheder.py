"""
Sjællandske Nyheder-specific scraper.

SN-model:
- Debatforsiden henter artikelkort fra data-bridge.production.aws.sn.dk.
- Vi bruger de data-bridge priority-requests, som browseren kalder.
- Kun URL'er med /debat-sjaelland/ accepteres.
- Artikelsiden bruges til rubrik, billedtekst som manchet, forfatter og dato.
- Ingen fallback til metadata, intro eller brødtekst som manchet.
"""

from typing import List, Optional, Any
import datetime as dt
from urllib.parse import urljoin, unquote
import html
import json
import re

from bs4 import BeautifulSoup


SN_SECTION_URL = "https://www.sn.dk/debat/"

SN_DATABRIDGE_URLS = [
    # Browserens priority-kald fra SN-debatforsiden.
    "https://data-bridge.production.aws.sn.dk/v1/priority/?imgPack=landing&query=eyJsIjo4LCJjYXQiOlsiMzk0MiJdfQ==",
    "https://data-bridge.production.aws.sn.dk/v1/priority/?imgPack=landing&query=eyJsIjo2LCJvIjo5LCJjYXQiOlsiMzk0MiJdfQ==",
    "https://data-bridge.production.aws.sn.dk/v1/priority/?imgPack=landing&query=eyJsIjoxMSwibG9jIjpbNDE2NF0sIm5hdXQiOlszNF19",
    "https://data-bridge.production.aws.sn.dk/v1/priority/?imgPack=landing&query=eyJsIjoxMCwiY2F0IjpbIjQxNTAiXSwibG9jIjpbNDE2NF19",
]


def sn_decode_raw(text: str) -> str:
    value = text or ""
    value = html.unescape(value)
    value = value.replace("\\/", "/")
    value = value.replace("\\u002F", "/").replace("\\u002f", "/")
    value = value.replace("\\u002D", "-").replace("\\u002d", "-")
    value = value.replace("\\u003A", ":").replace("\\u003a", ":")
    value = value.replace("\\u0026", "&")
    return value


def sn_url_is_debate(url: str) -> bool:
    value = unquote(sn_decode_raw(url)).lower()

    if "sn.dk" not in value:
        return False

    if "/debat-sjaelland/" not in value:
        return False

    bad_parts = [
        "/abonnement",
        "/login",
        "/kundeservice",
        "/nyhedsbrev",
        "/search",
        "/tag/",
        "/mest-laeste",
        "/annonce",
        "/annoncer",
        "/doedsannoncer",
        "/dodsannoncer",
        "/dødsannoncer",
        "/om-os/",
    ]

    return not any(part in value for part in bad_parts)


def sn_clean_url(url: str, base_url: str, helpers) -> str:
    url = sn_decode_raw(str(url or ""))
    url = unquote(url)
    return helpers["canonicalize_url_for_dedupe"](
        helpers["clean_url"](urljoin(base_url, url))
    )


def clean_sn_title(title: str, helpers) -> str:
    title = helpers["clean_text"](title)

    prefixes = [
        "LÆSERBREV",
        "LAESERBREV",
        "KRONIK",
        "KLUMME",
        "KOMMENTAR",
        "LEDER",
        "DEBAT SJÆLLAND",
        "DEBAT SJAELLAND",
        "DEBAT",
    ]

    for prefix in prefixes:
        if title.upper().startswith(prefix):
            title = title[len(prefix):].strip(" :-–|")

    title = re.sub(r"^\d{1,2}\.\d{2}\s+", "", title)

    suffixes = [
        " | Sjællandske Nyheder",
        " - Sjællandske Nyheder",
        " | SN.dk",
        " - SN.dk",
        " | sn.dk",
        " - sn.dk",
    ]

    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()

    return helpers["clean_text"](title)


def sn_title_is_navigation(title: str, helpers) -> bool:
    value = helpers["normalize_label_text"](title)

    navigation_titles = {
        "dødsannoncer",
        "doedsannoncer",
        "dodsannoncer",
        "mest læste",
        "mest laeste",
        "seneste nyt",
        "se alle",
        "debat",
        "mere",
        "log ind",
        "log ud",
        "search",
        "område",
        "omraade",
        "emne",
        "indhold",
    }

    return value in navigation_titles or len(value) < 8


def sn_extract_urls_from_text(text: str, base_url: str, helpers) -> List[str]:
    raw = sn_decode_raw(text or "")
    urls = []

    # Stram regex: stop ved citationstegn, whitespace og CSS/script-tegn.
    patterns = [
        r'https?://(?:www\.)?sn\.dk/art\d+/[a-z0-9\-]+/debat-sjaelland/[a-z0-9\-]+/?',
        r'//(?:www\.)?sn\.dk/art\d+/[a-z0-9\-]+/debat-sjaelland/[a-z0-9\-]+/?',
        r'/art\d+/[a-z0-9\-]+/debat-sjaelland/[a-z0-9\-]+/?',
    ]

    for pattern in patterns:
        for match in re.findall(pattern, raw, flags=re.IGNORECASE):
            absolute = sn_clean_url(match, base_url, helpers)
            if sn_url_is_debate(absolute):
                urls.append(absolute)

    seen = set()
    out = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def sn_walk_json_for_urls(obj: Any, base_url: str, helpers) -> List[str]:
    """
    Data-bridge JSON kan ændre form. Derfor går vi rekursivt gennem alle felter
    og leder efter strings, der ligner SN-debatlinks.
    """
    urls = []

    if isinstance(obj, dict):
        for value in obj.values():
            urls.extend(sn_walk_json_for_urls(value, base_url, helpers))
    elif isinstance(obj, list):
        for value in obj:
            urls.extend(sn_walk_json_for_urls(value, base_url, helpers))
    elif isinstance(obj, str):
        urls.extend(sn_extract_urls_from_text(obj, base_url, helpers))

        # Nogle API-felter kan indeholde path uden /art-regexen.
        candidate = sn_clean_url(obj, base_url, helpers)
        if sn_url_is_debate(candidate):
            urls.append(candidate)

    seen = set()
    out = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def sn_candidate_text_looks_like_caption(text: str, helpers) -> bool:
    text = helpers["clean_text"](text or "")

    if len(text) < 25 or len(text) > 650:
        return False

    if sn_text_is_bad_deck(text, helpers):
        return False

    value = helpers["normalize_label_text"](text)
    bad = [
        "sjællandske nyheder",
        "sjaellandske nyheder",
        "alt det vi taler om",
    ]

    if any(fragment in value for fragment in bad):
        return False

    if "@" in text and len(text) < 120:
        return False

    return True


def sn_walk_json_for_cards(obj: Any, base_url: str, helpers) -> List[dict]:
    """
    Går rekursivt gennem data-bridge JSON og returnerer mulige artikelkort.
    Vi gemmer både URL og mulige billedtekster/tekster fra samme objekt.
    """
    cards = []

    if isinstance(obj, dict):
        urls = []

        # Find URL'er i hele dette objekt.
        for value in obj.values():
            if isinstance(value, str):
                urls.extend(sn_extract_urls_from_text(value, base_url, helpers))
                candidate = sn_clean_url(value, base_url, helpers)
                if sn_url_is_debate(candidate):
                    urls.append(candidate)

        # Find tekstkandidater i samme objekt.
        text_candidates = []
        preferred_keys = [
            "caption",
            "imageCaption",
            "image_caption",
            "photoCaption",
            "photo_caption",
            "description",
            "excerpt",
            "teaser",
            "subTitle",
            "subtitle",
            "kicker",
            "alt",
        ]

        for key, value in obj.items():
            if isinstance(value, str):
                key_norm = helpers["normalize_label_text"](str(key))
                if any(helpers["normalize_label_text"](k) == key_norm for k in preferred_keys):
                    if sn_candidate_text_looks_like_caption(value, helpers):
                        text_candidates.append(value)

        # Som fallback inden for data-bridge: korte, brugbare tekstfelter i samme objekt.
        for value in obj.values():
            if isinstance(value, str) and sn_candidate_text_looks_like_caption(value, helpers):
                text_candidates.append(value)

        for url in urls:
            card = {"url": url, "deck": ""}
            if text_candidates:
                card["deck"] = helpers["clean_text"](text_candidates[0])
            cards.append(card)

        # Fortsæt rekursivt.
        for value in obj.values():
            cards.extend(sn_walk_json_for_cards(value, base_url, helpers))

    elif isinstance(obj, list):
        for value in obj:
            cards.extend(sn_walk_json_for_cards(value, base_url, helpers))

    return cards


def sn_fetch_databridge_cards(client, helpers) -> List[dict]:
    cards = []

    for api_url in SN_DATABRIDGE_URLS:
        try:
            text = helpers["fetch_text"](client, api_url)
        except Exception as e:
            print(f"[SN DEBUG] Kunne ikke hente data-bridge: {api_url} ({e})")
            continue

        if not text:
            print(f"[SN DEBUG] Tomt data-bridge-svar: {api_url}")
            continue

        found_cards = []

        # 1. Tekst/regex uden billedtekst.
        for url in sn_extract_urls_from_text(text, "https://www.sn.dk", helpers):
            found_cards.append({"url": url, "deck": ""})

        # 2. JSON-walk med mulighed for billedtekst/deck.
        try:
            data = json.loads(text)
            found_cards.extend(sn_walk_json_for_cards(data, "https://www.sn.dk", helpers))
        except Exception:
            pass

        # Dedup for dette kald.
        by_url = {}
        for card in found_cards:
            url = card.get("url", "")
            if not sn_url_is_debate(url):
                continue
            if url not in by_url:
                by_url[url] = {"url": url, "deck": card.get("deck", "") or ""}
            elif not by_url[url].get("deck") and card.get("deck"):
                by_url[url]["deck"] = card.get("deck", "")

        unique = list(by_url.values())
        print(f"[SN DEBUG] Data-bridge-kald fandt {len(unique)} debat-sjaelland-URL'er: {api_url}")

        cards.extend(unique)

    by_url = {}
    for card in cards:
        url = card.get("url", "")
        if not url:
            continue
        if url not in by_url:
            by_url[url] = {"url": url, "deck": card.get("deck", "") or ""}
        elif not by_url[url].get("deck") and card.get("deck"):
            by_url[url]["deck"] = card.get("deck", "")

    return list(by_url.values())


def sn_extract_title_from_article_page(soup, fallback_url: str, helpers) -> str:
    candidates = []

    h1 = soup.find("h1")
    if h1:
        candidates.append(h1.get_text(" ", strip=True))

    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or "").lower()
        if key in ["og:title", "twitter:title"]:
            content = tag.get("content") or ""
            if content:
                candidates.append(content)

    for candidate in candidates:
        title = clean_sn_title(candidate, helpers)
        if title and not sn_title_is_navigation(title, helpers):
            return title

    slug = fallback_url.rstrip("/").split("/")[-1]
    slug = unquote(slug).replace("-", " ")
    return helpers["clean_text"](slug[:1].upper() + slug[1:])


def sn_text_is_bad_deck(text: str, helpers) -> bool:
    value = helpers["normalize_label_text"](text or "")

    bad_fragments = [
        "mest læste",
        "mest laeste",
        "seneste nyt",
        "annoncørbetalt",
        "annoncoerbetalt",
        "læs også",
        "laes ogsaa",
        "cookie",
        "privatlivspolitik",
    ]

    return any(fragment in value for fragment in bad_fragments)


def sn_extract_article_page_fields(client, url: str, helpers) -> dict:
    result = {
        "title": "",
        "deck": "",
        "author": "",
        "published_at": "",
    }

    try:
        html_text = helpers["fetch_text"](client, url)
    except Exception:
        return result

    if not html_text:
        return result

    try:
        soup = BeautifulSoup(html_text, "lxml")
    except Exception:
        return result

    result["title"] = sn_extract_title_from_article_page(soup, url, helpers)

    time_tag = soup.find("time")
    if time_tag:
        result["published_at"] = (
            time_tag.get("datetime")
            or time_tag.get("content")
            or helpers["clean_text"](time_tag.get_text(" ", strip=True))
            or ""
        )

    # Forfatter
    author_candidates = []

    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").lower()
        if key in ["author", "article:author"]:
            content = helpers["clean_text"](tag.get("content") or "")
            if content:
                author_candidates.append(content)

    for selector in [
        "[rel='author']",
        "[class*='author']",
        "[class*='byline']",
        "[data-testid*='author']",
        "[data-testid*='byline']",
    ]:
        try:
            for el in soup.select(selector):
                text = helpers["clean_text"](el.get_text(" ", strip=True))
                if text:
                    author_candidates.append(text)
        except Exception:
            pass

    for author in author_candidates:
        value = helpers["normalize_label_text"](author)
        if not author or len(author) > 160:
            continue
        if "@" in author and len(author) < 80:
            continue
        if value in ["af", "skrevet af"]:
            continue
        result["author"] = author
        break

    # Manchet: kun billedtekst fra den konkrete artikelside.
    caption_candidates = []

    for selector in [
        "figcaption",
        "figure figcaption",
        "[class*='caption']",
        "[class*='Caption']",
        "[class*='image-text']",
        "[class*='imageText']",
        "[class*='photo-caption']",
        "[class*='photocaption']",
        "[class*='media-caption']",
        "[class*='MediaCaption']",
        "[data-testid*='caption']",
        "[data-test*='caption']",
    ]:
        try:
            for el in soup.select(selector):
                text = helpers["clean_text"](el.get_text(" ", strip=True))
                if text:
                    caption_candidates.append(text)
        except Exception:
            pass

    for img in soup.find_all(["img", "source"]):
        for attr in ["alt", "title", "aria-label", "data-caption", "data-credit"]:
            value = img.get(attr)
            if value:
                caption_candidates.append(value)

    raw = sn_decode_raw(html_text)
    for key in ["caption", "imageCaption", "image_caption", "photoCaption", "photo_caption"]:
        pattern = rf'"{key}"\s*:\s*"([^"]{{25,650}})"'
        for match in re.findall(pattern, raw, flags=re.IGNORECASE):
            caption_candidates.append(match)

    title_norm = helpers["normalize_label_text"](result["title"])

    for caption in caption_candidates:
        text = helpers["clean_text"](sn_decode_raw(caption))
        value = helpers["normalize_label_text"](text)

        if len(text) < 25 or len(text) > 650:
            continue
        if title_norm and (value == title_norm or value in title_norm):
            continue
        if sn_text_is_bad_deck(text, helpers):
            continue
        if "@" in text and len(text) < 120:
            continue

        credit_like = [
            "foto:",
            "foto ",
            "photo:",
            "arkivfoto",
            "privatfoto",
            "pressefoto",
            "ritzau",
            "sn.dk",
        ]
        if any(value.startswith(c) for c in credit_like) and len(text) < 90:
            continue

        result["deck"] = text
        break

    return result


def scrape_sn_direct(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    if helpers is None:
        raise RuntimeError("Sjællandske Nyheder scraper mangler helpers")

    DebateItem = helpers["DebateItem"]
    items: List[DebateItem] = []

    candidate_cards = sn_fetch_databridge_cards(client, helpers)

    print(f"[SN DEBUG] Samlet {len(candidate_cards)} unikke debat-sjaelland-URL'er efter data-bridge-filter.")

    if not candidate_cards:
        print("[SN DEBUG] Ingen debat-sjaelland-URL'er fundet i data-bridge.")
        return items

    for card in candidate_cards:
        absolute = card.get("url", "")
        fields = sn_extract_article_page_fields(client, absolute, helpers)
        title = clean_sn_title(fields.get("title") or "", helpers)

        if not title or sn_title_is_navigation(title, helpers):
            continue

        # Manchet: kun billedtekst fra den konkrete artikelside.
        deck = fields.get("deck", "")

        item = DebateItem(
            discovered_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            published_at=fields.get("published_at", ""),
            media=source.name,
            media_type=source.media_type,
            region=source.region,
            title=title,
            deck=deck,
            author=fields.get("author", ""),
            debate_type="Debat",
            url=absolute,
            source_method="section_page",
            status="new",
        )

        items.append(item)

        print(f"- {item.media}: {item.title}" + (f"\n  {item.url}" if show_urls else ""))

        if limit and len(items) >= limit:
            break

    print(f"[SN DEBUG] Accepterede {len(items)} Sjællandske Nyheder-artikler.")
    return items
