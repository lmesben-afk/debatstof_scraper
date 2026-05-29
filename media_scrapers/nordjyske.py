"""
Nordjyske-specific scraper.

Denne fil indeholder Nordjyskes særlogik.
run_scraper.py kalder scrape_nordjyske_direct herfra.
"""

from typing import List, Optional
import datetime as dt
from urllib.parse import urljoin


def nordjyske_type_from_card_text(card_text: str, helpers) -> str:
    value = helpers["normalize_label_text"](card_text)

    required_prefix = helpers["media_rule"]("Nordjyske").get("required_card_prefix", "Debat")
    required = helpers["normalize_label_text"](required_prefix)

    # Kræv at kortet starter med debatmarkøren.
    # Det forhindrer, at store navigation-containere med ordet "debat" accepteres.
    if value.startswith(required + " "):
        return "Debat"
    if value == required:
        return "Debat"

    return ""


def nordjyske_url_looks_like_article(url: str) -> bool:
    value = (url or "").lower()

    if "nordjyske.dk" not in value:
        return False

    blocked = [
        "/nyheder/debat",
        "/nyheder/byudvikling",
        "/nyheder/natur-og-miljoe",
        "/nyheder",
        "/abonnement",
        "/login",
        "/kundeservice",
        "/annoncer",
        "/nyhedsbrev",
        "/search",
        "/tag/",
    ]

    # Blokér rene sektionsforsider.
    for part in blocked:
        if value.rstrip("/").endswith(part):
            return False

    return True


def nordjyske_clean_title_from_card(card_text: str, helpers) -> str:
    """
    Nordjyske-kortet er typisk:
    Debat RUBRIK evt. dato/metadata

    Vi fjerner kun den indledende debatmarkør.
    """
    title = helpers["clean_text"](card_text)

    if title.lower().startswith("debat "):
        title = title[6:].strip(" :-–")

    return helpers["clean_text"](title)


def scrape_nordjyske_direct(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    """
    Særskilt Nordjyske-forsidescraper.

    Kun debatforsiden.
    Krav:
    - linket skal være på https://nordjyske.dk/nyheder/debat-siden
    - nærmeste lille kort/container skal starte med 'Debat'
    - navigation og sektionslinks frasorteres
    """
    if helpers is None:
        raise RuntimeError("Nordjyske scraper mangler helpers")

    DebateItem = helpers["DebateItem"]
    items: List[DebateItem] = []
    seen = set()
    diagnostics = []

    if not source.section_urls:
        return items

    section_url = source.section_urls[0]
    html_text = helpers["fetch_text"](client, section_url)

    if not html_text:
        print("[NORDJYSKE DEBUG] Kunne ikke hente debatforsiden.")
        return items

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "lxml")
    all_links = soup.find_all("a", href=True)

    print(f"[NORDJYSKE DEBUG] Hentede {len(html_text)} tegn fra {section_url}")
    print(f"[NORDJYSKE DEBUG] Fandt {len(all_links)} links i HTML.")

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

        if not nordjyske_url_looks_like_article(absolute):
            continue

        if absolute in seen:
            continue

        # Find den mindste brugbare container tæt på linket.
        candidate_containers = []

        if a.find_parent("article"):
            candidate_containers.append(a.find_parent("article"))

        for parent in a.parents:
            if not getattr(parent, "name", None):
                continue
            if parent.name in ["a", "div", "li", "article"]:
                text = helpers["clean_text"](parent.get_text(" ", strip=True))
                # Vigtigt: hold containeren lille, så vi ikke får navigation eller hele sektioner.
                if 15 <= len(text) <= 700:
                    candidate_containers.append(parent)

        accepted_card = None
        accepted_text = ""
        debate_type = ""

        for candidate in candidate_containers:
            text = helpers["clean_text"](candidate.get_text(" ", strip=True))
            dtype = nordjyske_type_from_card_text(text, helpers)
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
        card_text = accepted_text

        # Rubrik.
        title = ""

        heading = None
        if hasattr(card, "find"):
            heading = card.find(["h1", "h2", "h3", "h4"])

        if heading:
            title = helpers["clean_text"](heading.get_text(" ", strip=True))

        if not title:
            title = helpers["clean_text"](a.get_text(" ", strip=True))

        if not title or helpers["normalize_label_text"](title) == "debat":
            title = nordjyske_clean_title_from_card(card_text, helpers)

        if title.lower().startswith("debat "):
            title = title[6:].strip(" :-–")

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

        # Nordjyske har ikke altid manchetter; behold tomt hvis ingen findes.
        if not item.deck:
            item = helpers["enrich_missing_deck_from_article_page"](client, item, source)

        items.append(item)
        seen.add(absolute)

        print(f"- {item.media}: {item.title}")

        if limit and len(items) >= limit:
            break

    print(f"[NORDJYSKE DEBUG] Accepterede {len(items)} Nordjyske-artikler fra debatforside.")

    if not items:
        print("[NORDJYSKE DEBUG] Ingen artikler accepteret. Første 80 Nordjyske-links/kort:")
        for i, d in enumerate(diagnostics[:80], start=1):
            print(f"[NORDJYSKE DEBUG] {i}.")
            print(f"[NORDJYSKE DEBUG]    debat_type={d['debate_type'] or '-'}")
            print(f"[NORDJYSKE DEBUG]    linktekst={d['link_text'][:220] or '-'}")
            print(f"[NORDJYSKE DEBUG]    url={d['url']}")
            print(f"[NORDJYSKE DEBUG]    korttekst={d['card_text'] or '-'}")

    return items
