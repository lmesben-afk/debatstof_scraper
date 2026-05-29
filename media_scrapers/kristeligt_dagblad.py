"""
Kristeligt Dagblad-specific scraper.

Første version: stram debatforside-scraper med diagnostik.
"""

from typing import List, Optional
import datetime as dt
from urllib.parse import urljoin

from bs4 import BeautifulSoup


KD_MARKERS = [
    "debat",
    "kronik",
    "kommentar",
    "leder",
    "synspunkt",
]


def kd_debate_type_from_text(text: str, helpers) -> str:
    value = helpers["normalize_label_text"](text)

    # KD markerer debatstof lige over rubrikken. Markøren kan være et selvstændigt
    # søskendeelement og ikke del af selve linkteksten.
    if value in ["debat", "debatindlæg", "debatindlaeg"]:
        return "Debat"
    if value in ["kronik"]:
        return "Kronik"
    if value in ["kommentar", "mediekommentar"]:
        return "Kommentar"
    if value in ["leder", "kristeligt dagblad mener"]:
        return "Leder"

    return ""


def kd_find_marker_near_link(a, helpers) -> str:
    """
    Finder KD's stofmærke tæt på rubrikken.

    Markøren står typisk lige over rubrikken som fx:
    - Kommentar
    - Mediekommentar
    - Debat
    - Leder

    Derfor kigger vi i:
    1. små elementer i samme kort/container
    2. tidligere søskendeelementer før rubriklinket
    3. tekst lige før rubrikken i en større container
    """
    marker_words = [
        "mediekommentar",
        "kommentar",
        "debat",
        "debatindlæg",
        "debatindlaeg",
        "leder",
        "kronik",
        "kristeligt dagblad mener",
    ]

    # 1. Kig i små elementer tæt på linket.
    containers = []

    article = a.find_parent("article")
    if article:
        containers.append(article)

    for parent in a.parents:
        if not getattr(parent, "name", None):
            continue
        if parent.name in ["div", "li", "article", "section"]:
            text = helpers["clean_text"](parent.get_text(" ", strip=True))
            if 20 <= len(text) <= 1600:
                containers.append(parent)

    for container in containers:
        if not hasattr(container, "find_all"):
            continue

        # Små tekstnoder/elementer i containeren er gode kandidater til labels.
        for el in container.find_all(["span", "div", "p", "strong", "em"], recursive=True):
            text = helpers["clean_text"](el.get_text(" ", strip=True))
            value = helpers["normalize_label_text"](text)
            if value in marker_words:
                return text

    # 2. Kig på tidligere søskende til linket.
    current = a
    for _ in range(5):
        previous = current.find_previous_sibling()
        if not previous:
            break
        text = helpers["clean_text"](previous.get_text(" ", strip=True))
        value = helpers["normalize_label_text"](text)
        if value in marker_words:
            return text
        current = previous

    # 3. Kig i tekst lige før rubrikken i nærmeste brugbare container.
    link_text = helpers["clean_text"](a.get_text(" ", strip=True))
    for container in containers:
        text = helpers["clean_text"](container.get_text(" ", strip=True))
        if not link_text or link_text not in text:
            continue
        before = text.split(link_text, 1)[0].strip()
        # Tag kun de sidste få ord før rubrikken.
        before_tail = " ".join(before.split()[-4:])
        dtype = kd_debate_type_from_text(before_tail, helpers)
        if dtype:
            return before_tail

    return ""


def kd_url_looks_like_debate_article(url: str) -> bool:
    value = (url or "").lower()

    if "kristeligt-dagblad.dk" not in value:
        return False

    # Blokér selve forsiden.
    if value.rstrip("/").endswith("/debat"):
        return False

    # Første forsøg: debatartikler forventes at ligge under /debat/.
    if "/debat/" not in value:
        return False

    bad_parts = [
        "/abonnement",
        "/login",
        "/kundeservice",
        "/nyhedsbrev",
        "/search",
        "/tag/",
    ]
    if any(part in value for part in bad_parts):
        return False

    return True


def clean_kd_title(title: str, helpers) -> str:
    title = helpers["clean_text"](title)

    for prefix in ["Debat", "Kronik", "Kommentar", "Leder", "Synspunkt"]:
        if title.startswith(prefix):
            title = title[len(prefix):].strip(" :-–")

    # Metadata kan indeholde medienavn.
    suffixes = [
        " | Kristeligt Dagblad",
        " - Kristeligt Dagblad",
    ]
    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()

    return helpers["clean_text"](title)


def kd_title_is_navigation(title: str, helpers) -> bool:
    value = helpers["normalize_label_text"](title)

    navigation_titles = {
        "seneste nyt se alle om debat mere",
        "seneste nyt",
        "se alle",
        "om debat",
        "mere",
        "debat",
    }

    if value in navigation_titles:
        return True

    if value.startswith("seneste nyt se alle"):
        return True

    return False


def scrape_kristeligt_dagblad_direct(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    if helpers is None:
        raise RuntimeError("Kristeligt Dagblad scraper mangler helpers")

    DebateItem = helpers["DebateItem"]
    items: List[DebateItem] = []
    seen = set()
    diagnostics = []

    section_url = "https://www.kristeligt-dagblad.dk/debat"
    html_text = helpers["fetch_text"](client, section_url)

    if not html_text:
        print("[KD DEBUG] Kunne ikke hente debatforsiden.")
        return items

    soup = BeautifulSoup(html_text, "lxml")
    all_links = soup.find_all("a", href=True)

    print(f"[KD DEBUG] Hentede {len(html_text)} tegn fra {section_url}")
    print(f"[KD DEBUG] Fandt {len(all_links)} links i HTML.")

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

        if not kd_url_looks_like_debate_article(absolute):
            continue

        if absolute in seen:
            continue

        candidate_containers = []

        article = a.find_parent("article")
        if article:
            candidate_containers.append(article)

        for parent in a.parents:
            if not getattr(parent, "name", None):
                continue
            if parent.name in ["a", "article", "div", "li"]:
                text = helpers["clean_text"](parent.get_text(" ", strip=True))
                if 20 <= len(text) <= 900:
                    candidate_containers.append(parent)

        accepted_card = None
        accepted_text = ""
        debate_type = ""

        marker_text = kd_find_marker_near_link(a, helpers)
        debate_type = kd_debate_type_from_text(marker_text, helpers)

        if debate_type:
            # Brug mindste brugbare container som kort.
            accepted_card = candidate_containers[0] if candidate_containers else a
            accepted_text = helpers["clean_text"](accepted_card.get_text(" ", strip=True))

        diagnostics.append({
            "url": absolute,
            "link_text": helpers["clean_text"](a.get_text(" ", strip=True)),
            "card_text": accepted_text or helpers["clean_text"](a.get_text(" ", strip=True)),
            "marker": marker_text,
            "debate_type": debate_type,
        })

        if not accepted_card or not debate_type:
            continue

        card = accepted_card

        title = ""

        heading = None
        if hasattr(card, "find"):
            heading = card.find(["h1", "h2", "h3", "h4"])

        # KD-rubrikken er selve linkteksten. Brug den før container-heading,
        # så labels/navigation fra kortet ikke bliver til rubrik.
        title = helpers["clean_text"](a.get_text(" ", strip=True))

        if not title and heading:
            title = helpers["clean_text"](heading.get_text(" ", strip=True))

        if not title or helpers["normalize_label_text"](title) in KD_MARKERS:
            title = accepted_text

        title = clean_kd_title(title, helpers)

        if not title or len(title) < 8:
            continue

        if kd_title_is_navigation(title, helpers):
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
            if title and len(title) >= 8:
                item.title = title

        items.append(item)
        seen.add(absolute)

        print(f"- {item.media}: {item.title}" + (f"\n  {item.url}" if show_urls else ""))

        if limit and len(items) >= limit:
            break

    print(f"[KD DEBUG] Accepterede {len(items)} Kristeligt Dagblad-artikler fra debatforside.")

    if not items:
        print("[KD DEBUG] Ingen artikler accepteret. Første 100 relevante links/kort:")
        for i, d in enumerate(diagnostics[:100], start=1):
            print(f"[KD DEBUG] {i}.")
            print(f"[KD DEBUG]    debat_type={d['debate_type'] or '-'}")
            print(f"[KD DEBUG]    marker={d.get('marker') or '-'}")
            print(f"[KD DEBUG]    linktekst={d['link_text'][:220] or '-'}")
            print(f"[KD DEBUG]    url={d['url']}")
            print(f"[KD DEBUG]    korttekst={d['card_text'] or '-'}")

    return items
