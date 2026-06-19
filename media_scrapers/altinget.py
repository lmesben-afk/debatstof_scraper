"""
Altinget-specific scraper.

Stram debatforside-scraper.
Formål:
- Brug kun https://www.altinget.dk/debat
- Undgå generiske links fra navigation, forsidemoduler, analyser og nyheder
- Accepter kun artikelkort med tydelig debat-/opinionsmarkør
"""

from typing import List, Optional
import datetime as dt
from urllib.parse import urljoin

from bs4 import BeautifulSoup


ALTINGET_ALLOWED_MARKERS = [
    "debat",
    "kommentar",
    "kronik",
    "synspunkt",
    "analyse",  # kun hvis den ligger som debatkort på debatforsiden
]


ALTINGET_BLOCKED_TITLE_PREFIXES = [
    "bag nato-chefens smil",
    "jp/politikens hus indstifter",
]


def altinget_card_type(card_text: str, helpers) -> str:
    value = helpers["normalize_label_text"](card_text)

    # Altinget-debatkort starter typisk med en markør eller har markør meget tæt på rubrikken.
    # Vi er bevidst stramme her for at undgå nyheder/analyser fra andre moduler.
    if value.startswith("debat "):
        return "Debat"
    if value.startswith("kommentar "):
        return "Kommentar"
    if value.startswith("kronik "):
        return "Kronik"
    if value.startswith("synspunkt "):
        return "Debat"

    return ""


def altinget_url_looks_like_debate_article(url: str) -> bool:
    value = (url or "").lower()

    if "altinget.dk" not in value:
        return False

    # Blokér rene sektions-/forsidelinks.
    blocked_endings = [
        "/debat",
        "/artikel",
        "/analyse",
        "/navnenyt",
        "/christiansborg",
        "/eu",
        "/kommunal",
        "/forsyning",
        "/arbejdsmarked",
    ]

    for ending in blocked_endings:
        if value.rstrip("/").endswith(ending):
            return False

    # Altinget-artikler har typisk /artikel/.
    if "/artikel/" not in value:
        return False

    return True


def clean_altinget_title(title: str, helpers) -> str:
    title = helpers["clean_text"](title)

    prefixes = [
        "Debat",
        "Kommentar",
        "Kronik",
        "Synspunkt",
    ]

    for prefix in prefixes:
        if title.startswith(prefix):
            title = title[len(prefix):].strip(" :-–")

    # Altinget har ofte "- Altinget" i title metadata.
    if title.endswith(" - Altinget"):
        title = title[:-11].strip()

    return helpers["clean_text"](title)


def altinget_title_is_blocked(title: str, helpers) -> bool:
    value = helpers["normalize_label_text"](title)
    return any(value.startswith(prefix) for prefix in ALTINGET_BLOCKED_TITLE_PREFIXES)


def altinget_clear_deck(item):
    item.deck = ""
    return item


def scrape_altinget_direct(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    if helpers is None:
        raise RuntimeError("Altinget scraper mangler helpers")

    DebateItem = helpers["DebateItem"]
    items: List[DebateItem] = []
    seen = set()
    diagnostics = []

    section_url = "https://www.altinget.dk/debat"

    html_text = helpers["fetch_text"](client, section_url)

    if not html_text:
        print("[ALTINGET DEBUG] Kunne ikke hente debatforsiden.")
        return items

    soup = BeautifulSoup(html_text, "lxml")
    all_links = soup.find_all("a", href=True)

    print(f"[ALTINGET DEBUG] Hentede {len(html_text)} tegn fra {section_url}")
    print(f"[ALTINGET DEBUG] Fandt {len(all_links)} links i HTML.")

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

        if not altinget_url_looks_like_debate_article(absolute):
            continue

        if absolute in seen:
            continue

        # Find mindste brugbare kort/container tæt på linket.
        candidate_containers = []

        article = a.find_parent("article")
        if article:
            candidate_containers.append(article)

        for parent in a.parents:
            if not getattr(parent, "name", None):
                continue

            if parent.name in ["a", "article", "div", "li"]:
                text = helpers["clean_text"](parent.get_text(" ", strip=True))

                # Hold containeren lille nok til ikke at fange hele sektioner/navigation.
                if 20 <= len(text) <= 900:
                    candidate_containers.append(parent)

        accepted_card = None
        accepted_text = ""
        debate_type = ""

        for candidate in candidate_containers:
            text = helpers["clean_text"](candidate.get_text(" ", strip=True))
            dtype = altinget_card_type(text, helpers)
            if dtype:
                accepted_card = candidate
                accepted_text = text
                debate_type = dtype
                break

        diagnostics.append({
            "url": absolute,
            "link_text": helpers["clean_text"](a.get_text(" ", strip=True)),
            "card_text": accepted_text or helpers["clean_text"](a.get_text(" ", strip=True)),
            "debate_type": debate_type,
        })

        if not accepted_card or not debate_type:
            continue

        card = accepted_card

        title = ""

        heading = None
        if hasattr(card, "find"):
            heading = card.find(["h1", "h2", "h3", "h4"])

        if heading:
            title = helpers["clean_text"](heading.get_text(" ", strip=True))

        if not title:
            title = helpers["clean_text"](a.get_text(" ", strip=True))

        if not title or helpers["normalize_label_text"](title) in ["debat", "kommentar", "kronik", "synspunkt"]:
            title = accepted_text

        title = clean_altinget_title(title, helpers)

        if not title or len(title) < 8:
            continue

        if altinget_title_is_blocked(title, helpers):
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
            # Forsidekortet afgør, at det er debatstof.
            item.debate_type = debate_type

            # Brug kortets rubrik som autoritativ, så metadata ikke trækker os over i nyheds-/analysesprog.
            if title and len(title) >= 8:
                item.title = title

        items.append(item)
        seen.add(absolute)

        print(f"- {item.media}: {item.title}" + (f"\n  {item.url}" if show_urls else ""))

        if limit and len(items) >= limit:
            break

    print(f"[ALTINGET DEBUG] Accepterede {len(items)} Altinget-artikler fra debatforside.")

    if not items:
        print("[ALTINGET DEBUG] Ingen artikler accepteret. Første 80 relevante links/kort:")
        for i, d in enumerate(diagnostics[:80], start=1):
            print(f"[ALTINGET DEBUG] {i}.")
            print(f"[ALTINGET DEBUG]    debat_type={d['debate_type'] or '-'}")
            print(f"[ALTINGET DEBUG]    linktekst={d['link_text'][:220] or '-'}")
            print(f"[ALTINGET DEBUG]    url={d['url']}")
            print(f"[ALTINGET DEBUG]    korttekst={d['card_text'] or '-'}")

    return items
