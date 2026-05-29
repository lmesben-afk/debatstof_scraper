"""
Berlingske-specific scraper.

Denne fil indeholder Berlingskes særlogik.
run_scraper.py kalder funktionen scrape_berlingske_direct herfra.
"""

from typing import List, Optional
import datetime as dt

from bs4 import BeautifulSoup
from urllib.parse import urljoin


def berlingske_label_to_debate_type(label: str, helpers) -> str:
    from_config = helpers["label_from_rules"]("Berlingske", label)
    if from_config:
        return from_config
    return ""


def berlingske_card_label(card, helpers) -> str:
    """
    Finder opinionstype i et Berlingske-kort.
    """
    try:
        text = helpers["normalize_label_text"](card.get_text(" ", strip=True))

        for pattern in helpers["BERLINGSKE_ALLOWED_LABEL_PATTERNS"]:
            match = helpers["re"].search(pattern, text, flags=helpers["re"].IGNORECASE)
            if match:
                return match.group(0)

    except Exception:
        pass

    return ""


def berlingske_url_looks_like_article(url: str, helpers) -> bool:
    """
    Berlingske-opinionsartikler ligger i flere URL-spor.
    Segmenterne læses fra config/media_rules.yaml.
    """
    value = (url or "").lower()

    if "berlingske.dk" not in value:
        return False

    allowed_segments = helpers["media_rule_segments"]("Berlingske")

    if not allowed_segments:
        allowed_segments = [
            "/opinion/",
            "/kommentatorer/",
            "/laesere/",
            "/synspunkter/",
            "/ledere/",
            "/kronikker/",
        ]

    if not any(segment.lower() in value for segment in allowed_segments):
        return False

    # Frasorter rene sektionsforsider ud fra segmenterne.
    for segment in allowed_segments:
        clean_segment = segment.strip("/")
        if value.rstrip("/") == f"https://www.berlingske.dk/{clean_segment}":
            return False

    return True


def scrape_berlingske_direct(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    """
    Berlingske-opinionsscraper.

    Strategi:
    - accepter kendte opinions-URL'er
    - brug første ord/sektion i kortteksten som type
    - hent manchet fra artikelsiden
    """
    if helpers is None:
        raise RuntimeError("Berlingske scraper mangler helpers")

    DebateItem = helpers["DebateItem"]
    items: List[DebateItem] = []
    seen = set()

    if not source.section_urls:
        return items

    section_url = source.section_urls[0]

    html_text = helpers["fetch_text"](client, section_url)

    if not html_text:
        print("[BERLINGSKE DEBUG] Kunne ikke hente opinionsforsiden.")
        return items

    soup = BeautifulSoup(html_text, "lxml")
    all_links = soup.find_all("a", href=True)

    print(f"[BERLINGSKE DEBUG] Hentede {len(html_text)} tegn fra {section_url}")
    print(f"[BERLINGSKE DEBUG] Fandt {len(all_links)} links i HTML.")

    for a in all_links:
        href = (a.get("href") or "").strip()

        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        absolute = helpers["canonicalize_url_for_dedupe"](
            helpers["clean_url"](urljoin(section_url, href))
        )

        if not absolute.startswith("http"):
            continue

        if not helpers["same_domain_or_subdomain"](absolute, source.base_url):
            continue

        if not berlingske_url_looks_like_article(absolute, helpers):
            continue

        if absolute in seen:
            continue

        card = a.find_parent("article")

        if not card:
            card = a
            for parent in a.parents:
                if not getattr(parent, "name", None):
                    continue
                if parent.name in ["div", "li", "section"]:
                    text = parent.get_text(" ", strip=True)
                    if 20 <= len(text) <= 2500:
                        card = parent
                        break

        card_text = helpers["clean_text"](card.get_text(" ", strip=True))

        # Brug første ord/sektion som label.
        first_word = helpers["normalize_label_text"](card_text.split(" ", 1)[0])

        label = first_word
        debate_type = berlingske_label_to_debate_type(label, helpers)

        if not debate_type:
            # fallback: scan hele kortteksten
            debate_type = berlingske_label_to_debate_type(card_text, helpers)

        if not debate_type:
            continue

        # Rubrik
        title = ""

        heading = None
        if hasattr(card, "find"):
            heading = card.find(["h1", "h2", "h3", "h4"])

        if heading:
            title = heading.get_text(" ", strip=True)

        if not title:
            title = a.get_text(" ", strip=True)

        title = helpers["clean_text"](title)

        # Hvis linktekst er tom, brug kortteksten minus label
        if not title:
            title = card_text

        # Fjern typeord i starten af rubrikken
        prefixes = [
            "Kommentatorer",
            "Kronikker",
            "Ledere",
            "Læsere",
            "Synspunkter",
            "Opinion",
        ]

        for prefix in prefixes:
            if title.startswith(prefix):
                title = title[len(prefix):].strip(" :-–")

        title = helpers["clean_text"](title)

        if not title or len(title) < 8:
            continue

        item = helpers["extract_article_metadata"](client, source, absolute, "section_page")

        if not item:
            item = DebateItem(
                discovered_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                published_at="",
                media=source.name,
                media_type=source.media_type,
                region=source.region,
                title=title,
                deck="",
                author="",
                debate_type=debate_type,
                url=absolute,
                source_method="section_page",
                status="new",
            )
        else:
            item.debate_type = debate_type

            if not item.title or len(item.title) < 8:
                item.title = title

        items.append(item)
        seen.add(absolute)

        print(f"- {item.media}: {item.title}")

        if limit and len(items) >= limit:
            break

    print(f"[BERLINGSKE DEBUG] Accepterede {len(items)} Berlingske-artikler.")
    return items
