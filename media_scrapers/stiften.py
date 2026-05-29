"""
Århus Stiftstidende-specific scraper.

Stram debatforside-scraper.
Bruger stofmarkør lige over rubrikken:
- Læserbrev
- Kronik
- Klumme
- Kommentar
- Leder
- Debat

Formål:
- Brug kun https://stiften.dk/debat
- Undgå "Mest læste", navigation og andre sideelementer
"""

from typing import List, Optional
import datetime as dt
from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup


STIFTEN_MARKER_WORDS = [
    "læserbrev",
    "laeserbrev",
    "kronik",
    "klumme",
    "kommentar",
    "leder",
    "debat",
]


def stiften_debate_type_from_text(text: str, helpers) -> str:
    value = helpers["normalize_label_text"](text)

    if value in ["læserbrev", "laeserbrev"]:
        return "Læserbrev"
    if value == "kronik":
        return "Kronik"
    if value == "klumme":
        return "Klumme"
    if value == "kommentar":
        return "Kommentar"
    if value == "leder":
        return "Leder"
    if value == "debat":
        return "Debat"

    return ""


def stiften_url_looks_like_debate_article(url: str) -> bool:
    value = (url or "").lower()

    if "stiften.dk" not in value:
        return False

    # Blokér debatforsiden og andre rene sektionslinks.
    if value.rstrip("/").endswith("/debat"):
        return False

    # Debatartikler forventes at ligge under /debat/.
    if "/debat/" not in value:
        return False

    bstiften_parts = [
        "/abonnement",
        "/login",
        "/kundeservice",
        "/nyhedsbrev",
        "/search",
        "/tag/",
        "/mest-laeste",
    ]

    if any(part in value for part in bstiften_parts):
        return False

    return True


def clean_stiften_title(title: str, helpers) -> str:
    title = helpers["clean_text"](title)

    # Fjern debatmarkør i starten.
    prefixes = [
        "LÆSERBREV",
        "LAESERBREV",
        "KRONIK",
        "KLUMME",
        "KOMMENTAR",
        "LEDER",
        "DEBAT",
        "ERHVERVSKLUMMEN",
    ]

    for prefix in prefixes:
        if title.upper().startswith(prefix):
            title = title[len(prefix):].strip(" :-–")

    # Fjern klokkeslæt som "17.00" eller "06.01".
    title = re.sub(r"^\d{1,2}\.\d{2}\s+", "", title)

    suffixes = [
        " | Århus Stiftstidende",
        " - Århus Stiftstidende",
        " | Aarhus Stiftstidende",
        " - Aarhus Stiftstidende",
        " | stiften.dk",
        " - stiften.dk",
    ]

    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()

    return helpers["clean_text"](title)


def stiften_metadata_looks_wrong(text: str, helpers) -> bool:
    value = helpers["normalize_label_text"](text or "")

    wrong_fragments = [
        "der har været enorm interesse for at få fat i århus stiftstidendes papirudgave",
        "der har vaeret enorm interesse for at faa fat i aarhus stiftstidendes papirudgave",
        "vi har derfor som noget helt særligt fået lavet et større antal forsider",
        "vi har derfor som noget helt saerligt faaet lavet et stoerre antal forsider",
    ]

    return any(fragment in value for fragment in wrong_fragments)


def stiften_author_looks_wrong(author: str, helpers) -> bool:
    value = helpers["normalize_label_text"](author or "")

    wrong_fragments = [
        "henrik lund",
        "helu@stiften.dk",
    ]

    return any(fragment in value for fragment in wrong_fragments)



def stiften_text_is_bad_deck(text: str, helpers) -> bool:
    value = helpers["normalize_label_text"](text or "")
    if not value:
        return True
    bad_fragments = [
        "der har været enorm interesse for at få fat i århus stiftstidendes papirudgave",
        "der har vaeret enorm interesse for at faa fat i aarhus stiftstidendes papirudgave",
        "vi har derfor som noget helt særligt fået lavet et større antal forsider",
        "vi har derfor som noget helt saerligt faaet lavet et stoerre antal forsider",
        "mest læste",
        "mest laeste",
        "seneste nyt",
        "annoncørbetalt",
        "annoncoerbetalt",
        "læs også",
        "laes ogsaa",
    ]
    return any(fragment in value for fragment in bad_fragments)


def stiften_extract_deck_from_article_page(client, url: str, title: str, helpers) -> str:
    try:
        html_text = helpers["fetch_text"](client, url)
    except Exception:
        return ""

    if not html_text:
        return ""

    try:
        soup = BeautifulSoup(html_text, "lxml")
    except Exception:
        return ""

    title_norm = helpers["normalize_label_text"](title or "")
    candidates = []

    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").lower()
        if key in ["description", "og:description", "twitter:description"]:
            content = tag.get("content") or ""
            if content:
                candidates.append(content)

    for selector in ["article p", "main p", "[class*='intro']", "[class*='lead']", "[class*='teaser']", "[class*='article'] p"]:
        try:
            for el in soup.select(selector):
                text = helpers["clean_text"](el.get_text(" ", strip=True))
                if text:
                    candidates.append(text)
        except Exception:
            pass

    for candidate in candidates:
        text = helpers["clean_text"](candidate)
        value = helpers["normalize_label_text"](text)

        if len(text) < 45 or len(text) > 650:
            continue
        if title_norm and (value == title_norm or value in title_norm):
            continue
        if stiften_text_is_bad_deck(text, helpers):
            continue
        if "@" in text and len(text) < 120:
            continue

        return text

    return ""



def stiften_extract_article_page_fields(client, url: str, title: str, helpers) -> dict:
    """
    Henter Stiften-felter direkte fra artikelsiden.

    Forsiden er autoritativ for:
    - rubrik
    - debat_type
    - url

    Artikelsiden bruges til:
    - billedtekst som manchet
    - forfatter
    - udgivelsestidspunkt

    Vigtigt:
    - Ingen fallback til meta description, JSON-LD eller brødtekst.
    - Hvis der ikke findes en sikker billedtekst, bliver manchet tom.
    """
    result = {
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

    # Udgivelsestidspunkt
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
        if "henrik lund" in value or "helu@stiften.dk" in value:
            continue
        if value in ["af", "skrevet af"]:
            continue
        result["author"] = author
        break

    # Manchet: kun billedtekst.
    caption_candidates = []

    for selector in [
        "figcaption",
        "figure figcaption",
        "[class*='caption']",
        "[class*='image-text']",
        "[class*='imageText']",
        "[class*='photo-caption']",
        "[class*='photocaption']",
    ]:
        try:
            for el in soup.select(selector):
                text = helpers["clean_text"](el.get_text(" ", strip=True))
                if text:
                    caption_candidates.append(text)
        except Exception:
            pass

    title_norm = helpers["normalize_label_text"](title or "")

    for caption in caption_candidates:
        text = helpers["clean_text"](caption)
        value = helpers["normalize_label_text"](text)

        if len(text) < 25 or len(text) > 650:
            continue
        if title_norm and (value == title_norm or value in title_norm):
            continue
        if stiften_text_is_bad_deck(text, helpers):
            continue
        if "@" in text and len(text) < 120:
            continue

        result["deck"] = text
        break

    return result


def stiften_title_is_navigation(title: str, helpers) -> bool:
    value = helpers["normalize_label_text"](title)

    navigation_titles = {
        "mest læste",
        "mest laeste",
        "seneste nyt",
        "se alle",
        "debat",
        "mere",
    }

    if value in navigation_titles:
        return True

    if value.startswith("mest læste") or value.startswith("mest laeste"):
        return True

    return False


def stiften_find_marker_near_link(a, helpers) -> str:
    """
    Finder stofmærket tæt på rubrikken.

    Århus Stiftstidende viser markøren lige over rubrikken, men den er typisk
    ikke del af selve linkteksten. Derfor kigger vi i små elementer i
    samme kort/container og i tekst lige før rubrikken.
    """
    containers = []

    article = a.find_parent("article")
    if article:
        containers.append(article)

    for parent in a.parents:
        if not getattr(parent, "name", None):
            continue

        if parent.name in ["article", "div", "li", "section"]:
            text = helpers["clean_text"](parent.get_text(" ", strip=True))

            # Hold containeren tæt på artiklen. Store sidekolonner som "Mest læste"
            # bliver typisk for store eller uden korrekt markør.
            if 20 <= len(text) <= 1600:
                containers.append(parent)

    # 1. Små elementer i kortet.
    for container in containers:
        if not hasattr(container, "find_all"):
            continue

        for el in container.find_all(["span", "div", "p", "strong", "em"], recursive=True):
            text = helpers["clean_text"](el.get_text(" ", strip=True))
            value = helpers["normalize_label_text"](text)
            if value in STIFTEN_MARKER_WORDS:
                return text

    # 2. Tidligere søskende til rubriklinket.
    current = a
    for _ in range(6):
        previous = current.find_previous_sibling()
        if not previous:
            break
        text = helpers["clean_text"](previous.get_text(" ", strip=True))
        value = helpers["normalize_label_text"](text)
        if value in STIFTEN_MARKER_WORDS:
            return text
        current = previous

    # 3. Tekst lige før rubrikken i nærmeste container.
    link_text = helpers["clean_text"](a.get_text(" ", strip=True))
    for container in containers:
        text = helpers["clean_text"](container.get_text(" ", strip=True))
        if not link_text or link_text not in text:
            continue

        before = text.split(link_text, 1)[0].strip()
        before_tail = " ".join(before.split()[-3:])
        dtype = stiften_debate_type_from_text(before_tail, helpers)
        if dtype:
            return before_tail

    return ""


def scrape_stiften_direct(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    if helpers is None:
        raise RuntimeError("Århus Stiftstidende scraper mangler helpers")

    DebateItem = helpers["DebateItem"]
    items: List[DebateItem] = []
    seen = set()
    diagnostics = []

    section_url = "https://stiften.dk/debat"
    html_text = helpers["fetch_text"](client, section_url)

    if not html_text:
        print("[STIFTEN DEBUG] Kunne ikke hente debatforsiden.")
        return items

    soup = BeautifulSoup(html_text, "lxml")
    all_links = soup.find_all("a", href=True)

    print(f"[STIFTEN DEBUG] Hentede {len(html_text)} tegn fra {section_url}")
    print(f"[STIFTEN DEBUG] Fandt {len(all_links)} links i HTML.")

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

        if not stiften_url_looks_like_debate_article(absolute):
            continue

        if absolute in seen:
            continue

        marker_text = stiften_find_marker_near_link(a, helpers)
        debate_type = stiften_debate_type_from_text(marker_text, helpers)

        link_text = helpers["clean_text"](a.get_text(" ", strip=True))

        diagnostics.append({
            "url": absolute,
            "link_text": link_text,
            "marker": marker_text,
            "debate_type": debate_type,
        })

        if not debate_type:
            continue

        title = clean_stiften_title(link_text, helpers)

        if not title or len(title) < 8:
            continue

        if stiften_title_is_navigation(title, helpers):
            continue

        article_fields = stiften_extract_article_page_fields(client, absolute, title, helpers)

        item = DebateItem(
            discovered_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            published_at=article_fields.get("published_at", ""),
            media=source.name,
            media_type=source.media_type,
            region=source.region,
            title=title,
            deck=article_fields.get("deck", ""),
            author=article_fields.get("author", ""),
            debate_type=debate_type,
            url=absolute,
            source_method="section_page",
            status="new",
        )

        items.append(item)
        seen.add(absolute)

        print(f"- {item.media}: {item.title}" + (f"\n  {item.url}" if show_urls else ""))

        if limit and len(items) >= limit:
            break

    print(f"[STIFTEN DEBUG] Accepterede {len(items)} Århus Stiftstidende-artikler fra debatforside.")

    if not items:
        print("[STIFTEN DEBUG] Ingen artikler accepteret. Første 100 relevante links/kort:")
        for i, d in enumerate(diagnostics[:100], start=1):
            print(f"[STIFTEN DEBUG] {i}.")
            print(f"[STIFTEN DEBUG]    debat_type={d['debate_type'] or '-'}")
            print(f"[STIFTEN DEBUG]    marker={d.get('marker') or '-'}")
            print(f"[STIFTEN DEBUG]    linktekst={d['link_text'][:220] or '-'}")
            print(f"[STIFTEN DEBUG]    url={d['url']}")

    return items
