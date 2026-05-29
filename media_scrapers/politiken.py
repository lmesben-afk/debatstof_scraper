"""
Politiken-specific scraper.

Denne fil indeholder Politikens særlogik.
run_scraper.py kalder scrape_politiken_direct herfra.
"""

from typing import List, Optional
import datetime as dt
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def politiken_title_is_navigation(title: str, helpers) -> bool:
    value = helpers["normalize_label_text"](title)
    navigation_titles = {
        "sektioner",
        "internationalt",
        "kroniken",
        "debatindlæg",
        "debatindlaeg",
        "du har ordet",
        "samtaler",
        "dagens tegning",
        "dagens avis",
        "podcast",
        "nyhedsbreve",
        "politiken",
    }
    return value in navigation_titles


def politiken_url_looks_like_article(url: str, helpers) -> bool:
    """
    Politiken-krav læses fra config/media_rules.yaml.
    """
    value = (url or "").lower()

    requirements = helpers["media_rule_segments"]("Politiken", key="accepted_url_requirements")

    if not requirements:
        requirements = ["/debat/", "/art"]

    for requirement in requirements:
        if requirement.lower() not in value:
            return False

    return True


def politiken_type_from_url(url: str) -> str:
    value = (url or "").lower()

    if "/debat/klummer/" in value:
        return "Klumme"
    if "/debat/kroniken/" in value:
        return "Kronik"
    if "/debat/debatindlaeg/" in value or "/debat/debatindlæg/" in value:
        return "Debat"
    if "/debat/ledere/" in value:
        return "Leder"

    return ""


def clean_politiken_deck(card_text: str, title: str, label: str, helpers) -> str:
    """
    Bevares som fallback. Politiken henter normalt manchet fra artikelsiden.
    """
    clean_text = helpers["clean_text"]
    re = helpers["re"]

    text = clean_text(card_text or "")
    title = clean_text(title or "")
    label = clean_text(label or "")

    if not text or not title:
        return ""

    if title in text:
        text = text.replace(title, " ", 1)

    if label and label in text:
        text = text.replace(label, " ", 1)

    text = re.sub(
        r"^(klumme|kronik|leder|debatindlæg|debatindlaeg|kommentar|debat)\s+af\s+[^0-9»]{1,120}",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^(klumme|kronik|leder|debatindlæg|debatindlaeg|kommentar|debat)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\b\d{1,2}\.\s+[A-ZÆØÅ]{3,}\s+\d{4},\s+\d{1,2}\.\d{2}\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = clean_text(text)

    if not text or len(text) < 25:
        return ""

    if len(text) > 450:
        text = text[:450].rsplit(" ", 1)[0]

    return text.strip()




def scrape_politiken_direct(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    """
    Politiken-scraper.

    Strategi:
    - find alle egentlige debatartikel-links på debatforsiden
    - kræv /debat/ og /art i URL
    - find rubrik i link/container
    - brug label hvis den findes, ellers URL-sektion som type
    - hent metadata/manchet fra artikelsiden
    """
    if helpers is None:
        raise RuntimeError("Politiken scraper mangler helpers")

    DebateItem = helpers["DebateItem"]
    items: List[DebateItem] = []
    seen = set()

    if not source.section_urls:
        return items

    section_url = source.section_urls[0]
    html_text = helpers["fetch_text"](client, section_url)

    if not html_text:
        print("[POLITIKEN DEBUG] Kunne ikke hente debatforsiden.")
        return items

    soup = BeautifulSoup(html_text, "lxml")

    all_links = soup.find_all("a", href=True)
    print(f"[POLITIKEN DEBUG] Fandt {len(all_links)} links i HTML.")

    for a in all_links:
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        absolute = helpers["canonicalize_url_for_dedupe"](
            helpers["clean_url"](urljoin(section_url, href))
        )

        value = absolute.lower()

        if not absolute.startswith("http"):
            continue
        if not helpers["same_domain_or_subdomain"](absolute, source.base_url):
            continue
        if not politiken_url_looks_like_article(absolute, helpers):
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
                    if 20 <= len(text) <= 2200:
                        card = parent
                        break

        card_text = card.get_text(" ", strip=True)

        label = helpers["politiken_card_label"](card)
        debate_type = helpers["politiken_label_to_debate_type"](label)

        if not debate_type:
            debate_type = politiken_type_from_url(absolute)

        if not debate_type:
            continue

        title = ""

        heading = None
        if hasattr(card, "find"):
            heading = card.find(["h1", "h2", "h3", "h4"])

        if heading:
            title = heading.get_text(" ", strip=True)

        if not title:
            title = a.get_text(" ", strip=True)

        if not title:
            title = card_text

        title = helpers["clean_text"](title)

        prefixes = [
            "Klumme",
            "Kronik",
            "Leder",
            "Debat",
            "Debatindlæg",
            "Kommentar",
        ]

        for prefix in prefixes:
            if title.startswith(prefix):
                title = title[len(prefix):].strip(" :-–")

        title = helpers["clean_text"](title)

        if not title or len(title) < 8:
            continue

        if politiken_title_is_navigation(title, helpers):
            continue

        item = helpers["extract_article_metadata"](client, source, absolute, "section_page")

        if not item:
            deck = clean_politiken_deck(card_text, title, label, helpers)
            item = DebateItem(
                discovered_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                published_at="",
                media=source.name,
                media_type=source.media_type,
                region=source.region,
                title=title,
                deck=deck,
                author="",
                debate_type=debate_type,
                url=absolute,
                source_method="section_page",
                status="new",
            )
        else:
            # Behold typen fra debatforsiden/URL'en.
            item.debate_type = debate_type

            # Vigtigt:
            # Politiken kan give afkortet rubrik fra artikelsidens metadata.
            # Derfor er forsiderubrikken autoritativ.
            # Artikelsiden bruges til manchet, dato og evt. forfatter.
            if title and len(title) >= 8:
                item.title = title

        items.append(item)
        seen.add(absolute)

        print(f"- {item.media}: {item.title}")

        if limit and len(items) >= limit:
            break

    print(f"[POLITIKEN DEBUG] Accepterede {len(items)} Politiken-artikler.")
    return items
