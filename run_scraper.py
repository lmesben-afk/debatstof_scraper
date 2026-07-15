
import argparse
import csv
import datetime as dt
import html
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse, unquote
from media_scrapers import get_external_scraper
from media_scrapers.helpers import build_helpers as build_media_scraper_helpers
from core.models import Source, DebateItem
from core.utils import clean_text, clean_url, canonicalize_url_for_dedupe, article_id_from_url, normalize_timestamp





import gspread
import httpx
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

USER_AGENT = "DebatstofResearchBot/0.5"
DEFAULT_TIMEOUT = 20
DEFAULT_JSON_OUTPUT = str(Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Fælles-data") / "articles.json")
DEFAULT_NEW_JSON_OUTPUT = str(Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Fælles-data") / "new_articles.json")
CONFIG_DIR = Path(r"C:/Users/Esben.L.Mikkelsen/OneDrive - JP Politikens Hus/Jyllands-Posten/Scrapere/Config-filer")

def load_sources(path: str = "sources.yaml") -> List[Source]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [Source(**src) for src in raw["sources"]]

def fetch_text(client: httpx.Client, url: str) -> Optional[str]:
    try:
        resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        print(f"[WARN] Kunne ikke hente {url}: {exc}")
        return None

def detect_altinget_label(card) -> str:
    """
    Finder Altingets blå debat-label på debatforsiden.

    Eksempler:
    - Kommentar
    - Debat
    - Kronik
    """
    try:
        text = card.get_text(" ", strip=True)

        for label in ["Kommentar", "Debat", "Kronik", "Læserbrev"]:
            pattern = rf"\b{re.escape(label)}\b"
            if re.search(pattern, text, flags=re.IGNORECASE):
                return label

    except Exception:
        pass

    return ""

def same_domain_or_subdomain(url: str, base_url: str) -> bool:
    host = urlparse(url).netloc.replace("www.", "")
    base_host = urlparse(base_url).netloc.replace("www.", "")
    return host == base_host or host.endswith("." + base_host)

def dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        key = canonicalize_url_for_dedupe(item) if isinstance(item, str) and item.startswith("http") else item
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out

def path_segments(url: str) -> List[str]:
    return [seg.lower() for seg in urlparse(url).path.split("/") if seg]

def url_has_any_segment_or_marker(url: str, markers: List[str]) -> bool:
    segments = path_segments(url)
    joined = " ".join(segments)
    return any(marker.lower() in segments or marker.lower() in joined for marker in markers)

def url_is_in_strict_sitemap_section(url: str, source: Source) -> bool:
    path = urlparse(url).path.lower()
    return any(section.lower() in path for section in source.strict_sitemap_sections)

def url_is_valid_from_section_page(url: str, source: Source) -> bool:
    path = urlparse(url).path.lower().rstrip("/")

    # Fyens er særtilfælde: Rå HTML fra /debat indeholder irrelevante links.
    # Derfor må kun egentlige debatartikler under /debat/... accepteres.
    if source.name == "Fyens Stiftstidende":
        return path.startswith("/debat/") and path != "/debat"

    return True

def url_is_probably_article(url: str, source: Source) -> bool:
    segments = path_segments(url)

    if not segments:
        return False

    if any(bad.lower() in segments for bad in source.exclude_path_segments):
        return False

    if len(segments) < 2:
        return False

    if source.article_path_markers and not url_has_any_segment_or_marker(url, source.article_path_markers):
        return False

    return True


POLITIKEN_ALLOWED_LABEL_PATTERNS = [
    r"\bklumme af\b",
    r"\bkommentar af\b",
    r"\bkronik\b",
    r"\bdebat\b",
    r"\blæserbrev\b",
    r"\blaeserbrev\b",
    r"\bklumme\b",
    r"\bkommentar\b",
]


def normalize_label_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def politiken_card_label(card) -> str:
    """
    Finder labelen over rubrikken på Politikens debatforside.
    """
    try:
        text = normalize_label_text(card.get_text(" ", strip=True))
        for pattern in POLITIKEN_ALLOWED_LABEL_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0)
    except Exception:
        pass
    return ""


def politiken_label_to_debate_type(label: str) -> str:
    value = normalize_label_text(label)
    if value.startswith("klumme"):
        return "Klumme"
    if value.startswith("kommentar"):
        return "Kommentar"
    if "kronik" in value:
        return "Kronik"
    if "læserbrev" in value or "laeserbrev" in value:
        return "Læserbrev"
    if "debat" in value:
        return "Debat"
    return ""


def discover_politiken_urls_from_section_pages(client: httpx.Client, source: Source) -> Dict[str, str]:
    """
    Politiken: returnerer URL -> debat_type.

    Kun links fra debatforsiden, hvor nærmeste kort har en label over rubrikken.
    """
    url_types: Dict[str, str] = {}

    for section_url in source.section_urls:
        html_text = fetch_text(client, section_url)
        if not html_text:
            continue

        soup = BeautifulSoup(html_text, "lxml")

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue

            absolute = canonicalize_url_for_dedupe(clean_url(urljoin(section_url, href)))
            if not absolute.startswith("http"):
                continue
            if not same_domain_or_subdomain(absolute, source.base_url):
                continue
            if "/debat/" not in absolute:
                continue
            if not url_is_probably_article(absolute, source):
                continue

            # Find en kort-lignende container tæt på linket.
            card = a
            for parent in a.parents:
                if not getattr(parent, "name", None):
                    continue
                if parent.name in ["article", "li", "div", "section"]:
                    text = parent.get_text(" ", strip=True)
                    if 15 <= len(text) <= 1500:
                        card = parent
                        break

            label = politiken_card_label(card)
            debate_type = politiken_label_to_debate_type(label)

            if not debate_type:
                continue

            url_types[absolute] = debate_type

    return url_types


def discover_urls_from_section_pages(client: httpx.Client, source: Source) -> List[str]:
    urls: List[str] = []
    section_roots = [u.rstrip("/") for u in source.section_urls]

    for section_url in source.section_urls:
        html_text = fetch_text(client, section_url)
        if not html_text:
            continue

        soup = BeautifulSoup(html_text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue

            absolute = canonicalize_url_for_dedupe(clean_url(urljoin(section_url, href)))
            if not absolute.startswith("http"):
                continue
            if not same_domain_or_subdomain(absolute, source.base_url):
                continue
            if absolute.rstrip("/") in section_roots:
                continue
            if not url_is_valid_from_section_page(absolute, source):
                continue
            if not url_is_probably_article(absolute, source):
                continue

            urls.append(absolute)

    return dedupe(urls)

def parse_sitemap_urls(xml_text: str) -> List[str]:
    soup = BeautifulSoup(xml_text, "xml")
    locs = [clean_url(loc.get_text(strip=True)) for loc in soup.find_all("loc")]
    return [u for u in locs if u.startswith("http")]

def is_sitemap_index(xml_text: str) -> bool:
    soup = BeautifulSoup(xml_text, "xml")
    return soup.find("sitemapindex") is not None

def discover_urls_from_sitemaps(client: httpx.Client, source: Source, max_nested_sitemaps: int = 80) -> List[str]:
    discovered: List[str] = []
    sitemap_queue = list(source.sitemap_urls)
    seen_sitemaps = set()

    while sitemap_queue and len(seen_sitemaps) < max_nested_sitemaps:
        sitemap_url = sitemap_queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        xml_text = fetch_text(client, sitemap_url)
        if not xml_text:
            continue

        urls = parse_sitemap_urls(xml_text)
        if is_sitemap_index(xml_text):
            sitemap_queue.extend(urls)
        else:
            discovered.extend(urls)

    return dedupe(discovered)

def extract_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    out = []
    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or script.get_text()
        if not text:
            continue
        try:
            data = json.loads(text)
            if isinstance(data, list):
                out.extend([x for x in data if isinstance(x, dict)])
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    out.extend([x for x in data["@graph"] if isinstance(x, dict)])
                else:
                    out.append(data)
        except Exception:
            continue
    return out

def first_nonempty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return clean_text(value)
        if isinstance(value, list) and value:
            return clean_text(value[0])
    return ""

def meta_content(soup: BeautifulSoup, *selectors: str) -> str:
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            return clean_text(tag["content"])
    return ""

def normalize_author(author: Any) -> str:
    if isinstance(author, str):
        return clean_text(author)
    if isinstance(author, dict):
        return first_nonempty(author.get("name"))
    if isinstance(author, list):
        names = []
        for a in author:
            if isinstance(a, dict) and a.get("name"):
                names.append(clean_text(a["name"]))
            elif isinstance(a, str):
                names.append(clean_text(a))
        return ", ".join([n for n in names if n])
    return ""

def infer_debate_type(url: str, title: str, section: str) -> str:
    text = " ".join([url, title, section]).lower()
    if "kronik" in text:
        return "Kronik"
    if "læserbrev" in text or "laeserbrev" in text:
        return "Læserbrev"
    if "opinion" in text:
        return "Opinion"
    if "kommentar" in text:
        return "Kommentar"
    if "debat" in text:
        return "Debatindlæg"
    return ""


def altinget_type_from_title_or_slug(title: str, url: str) -> str:
    """
    Midlertidig Altinget-normalisering.

    Altinget viser typen visuelt på debatforsiden, men den er ikke stabilt nok
    tilgængelig i den rå HTML, vi henter uden browser/JavaScript.

    Derfor udleder vi typen for Altinget ud fra kendte mønstre:
    - person/rolle før kolon => typisk Debat
    - kendte kommentator-/kommentar-slugs => Kommentar
    - debat/kronik/kommentar i URL/rubrik => tilsvarende type

    Det er ikke perfekt, men giver et bedre datalag end tomme felter.
    """
    text = f"{title} {url}".lower()

    if "kronik" in text:
        return "Kronik"
    if "kommentar" in text:
        return "Kommentar"
    if "læserbrev" in text or "laeserbrev" in text:
        return "Læserbrev"

    known_comment_slugs = [
        "loekke-tabte-magtkampen-med-de-blaa-nu-bliver-hans-sejre-paa-de-roedes-naade",
        "forslaget-om-en-grisefirepart-lyder-som-bluff",
        "statsministerens-udfald-mod-sociale-medier-skader-debatten-om-unges-mistrivsel",
    ]
    if any(slug in url.lower() for slug in known_comment_slugs):
        return "Kommentar"

    # Mange Altinget-debatindlæg har afsender/rolle før kolon:
    # "Ida Auken:", "Konsulent:", "Dagtilbudsleder:" osv.
    clean_title = title.replace(" - Altinget", "").strip()
    if ":" in clean_title:
        prefix = clean_title.split(":", 1)[0].strip().lower()
        if prefix and prefix not in ["analyse", "#dkpol", "overblik"]:
            return "Debat"

    return "Debat"


def standardize_debate_type(debate_type: str) -> str:
    """
    Intern, app-venlig standardtype.

    Dansk visning bevares i `debat_type`.
    Denne bruges senere til filtrering, statistik og API.
    """
    value = (debate_type or "").strip().lower()

    mapping = {
        "kommentar": "commentary",
        "debat": "debate",
        "debatindlæg": "debate",
        "kronik": "chronicle",
        "læserbrev": "letter",
        "laeserbrev": "letter",
        "opinion": "opinion",
    }

    return mapping.get(value, "")

def is_unwanted_analysis(item: DebateItem, section: str, source: Source) -> bool:
    text = " ".join([item.url, item.title, item.deck, section]).lower()

    if source.name == "Altinget":
        unwanted_terms = [
            "analyse:",
            "analyse -",
            "-analyse",
            " analyse ",
            "/analyse/",
            "/analyser/",
            " altinget analyse",
            "holstein:",
            "holstein-analyse",
            "#dkpol:",
        ]
        return any(term in text for term in unwanted_terms)

    return False

def altinget_has_opinion_signal(item: DebateItem, section: str) -> bool:
    title = item.title.replace(" - Altinget", "").strip()
    title_lower = title.lower()
    url_lower = item.url.lower()
    section_lower = section.lower()

    # Klassiske debatmarkører.
    if any(term in title_lower for term in ["debat:", "kronik:", "kommentar:", "læserbrev:", "laeserbrev:"]):
        return True

    # Altingets debatindlæg har ofte afsender/rolle før kolon:
    # "Ida Auken:", "Konsulent:", "Tidligere fagboss:" osv.
    if ":" in title:
        prefix = title.split(":", 1)[0].strip().lower()
        if prefix and prefix not in ["analyse", "#dkpol", "overblik"]:
            return True

    # URL-slugs der tydeligt handler om debat/opinion, ikke bare analyse.
    if any(term in url_lower for term in ["debat", "kronik", "kommentar", "laeserbrev", "opinion"]):
        return True

    # Metadata kan også bekræfte det.
    if any(term in section_lower for term in ["debat", "opinion", "kronik", "kommentar"]):
        return True

    return False

def metadata_supports_debate(item: DebateItem, section: str, source: Source, source_method: str) -> bool:
    if is_unwanted_analysis(item, section, source):
        return False

    if any(bad.lower() in item.title.lower() for bad in source.exclude_title_contains):
        return False

    if source_method == "section_page":
        return True

    if any(item.title.startswith(prefix) for prefix in source.title_prefixes):
        return True

    return url_has_any_segment_or_marker(item.url, source.allowed_path_segments)

def extract_article_metadata(client: httpx.Client, source: Source, url: str, source_method: str) -> Optional[DebateItem]:
    html_text = fetch_text(client, url)
    if not html_text:
        return None

    soup = BeautifulSoup(html_text, "lxml")
    json_ld = extract_json_ld(soup)

    article_ld = {}
    for ld_item in json_ld:
        item_type = ld_item.get("@type")
        if isinstance(item_type, list):
            is_article = any("Article" in str(t) for t in item_type)
        else:
            is_article = "Article" in str(item_type)
        if is_article:
            article_ld = ld_item
            break

    title = first_nonempty(
        article_ld.get("headline"),
        meta_content(soup, 'meta[property="og:title"]', 'meta[name="twitter:title"]'),
        soup.title.get_text(strip=True) if soup.title else "",
    )

    if not title:
        return None

    deck = first_nonempty(
        article_ld.get("description"),
        meta_content(soup, 'meta[property="og:description"]', 'meta[name="description"]', 'meta[name="twitter:description"]'),
    )

    published_raw = first_nonempty(
        article_ld.get("datePublished"),
        meta_content(soup, 'meta[property="article:published_time"]', 'meta[name="date"]'),
    )

    published_at = ""
    if published_raw:
        try:
            published_at = dateparser.parse(published_raw).isoformat()
        except Exception:
            published_at = published_raw

    section = first_nonempty(article_ld.get("articleSection"), meta_content(soup, 'meta[property="article:section"]'))
    author = normalize_author(article_ld.get("author")) or meta_content(soup, 'meta[name="author"]')
    debate_type = infer_debate_type(url, title, section)

    if source.name == "Altinget" and not debate_type:
        debate_type = altinget_type_from_title_or_slug(title, url)

    item = DebateItem(
        discovered_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        published_at=published_at,
        media=source.name,
        media_type=source.media_type,
        region=source.region,
        title=title,
        deck=deck,
        author=author,
        debate_type=debate_type,
        url=url,
        source_method=source_method,
        status="new",
    )

    if not metadata_supports_debate(item, section, source, source_method):
        return None

    return item



def build_source_status(items: List[DebateItem], expected_sources: List[Source]) -> List[dict]:
    """
    Opsummerer status pr. kilde til JSON-output og senere appvisning.
    """
    counts = {}
    for item in items:
        counts[item.media] = counts.get(item.media, 0) + 1

    statuses = []
    for source in expected_sources:
        found = counts.get(source.name, 0)
        statuses.append({
            "medie": source.name,
            "medietype": source.media_type,
            "region": source.region,
            "fundet": found,
            "status": "OK" if found > 0 else "INGEN_FUND",
        })

    return statuses



THEME_KEYWORDS = {
    "politik": [
        "folketing", "regering", "minister", "parti", "partier", "politiker",
        "valg", "valgkamp", "borgmester", "byråd", "kommunal", "venstre",
        "socialdemokratiet", "moderaterne", "enhedslisten", "radikale",
        "konservative", "liberal alliance", "df", "sf",
    ],
    "klima_og_miljø": [
        "klima", "miljø", "natur", "co2", "grøn", "grønne", "havvind",
        "vindmølle", "solcelle", "energi", "forsyning", "drikkevand",
        "grundvand", "landbrug", "dyrevelfærd", "udledning", "limfjorden",
        "forurening", "nitrat", "biodiversitet",
    ],
    "velfærd": [
        "ældre", "plejehjem", "sundhed", "hospital", "læge", "patient",
        "psykiatri", "handicap", "fødtidspension", "førtidspension",
        "social", "udsatte", "børn", "dagtilbud", "pædagog", "velfærd",
        "kommune", "kommuner",
    ],
    "uddannelse": [
        "skole", "uddannelse", "gymnasium", "universitet", "studerende",
        "elev", "elever", "lærer", "underviser", "cbs", "ai i undervisning",
        "eksamen", "minuttyrani",
    ],
    "arbejdsmarked": [
        "arbejdsmarked", "fagbevægelse", "fagforening", "løn", "overenskomst",
        "arbejder", "arbejdsgiver", "rekruttering", "medlemskrise",
        "praktikant", "arbejde", "job",
    ],
    "udlændinge_og_integration": [
        "udlænding", "udvisning", "integration", "asyl", "flygtning",
        "indvandring", "strasbourg", "menneskerettigheder", "håndtryk",
        "fundamentalisme",
    ],
    "eu_og_udland": [
        "eu", "bruxelles", "nato", "sverige", "trump", "cuba", "assad",
        "grønland", "arktis", "palæstina", "international", "udland",
        "hizbollah", "black panthers",
    ],
    "teknologi_og_ai": [
        "ai", "kunstig intelligens", "algoritme", "digital", "teknologi",
        "skærm", "sociale medier", "influencer", "subscribe",
    ],
    "kultur_og_medier": [
        "kultur", "medier", "journalistik", "presse", "kritiske medier",
        "folkestyret", "bog", "historie", "historiestuderende",
    ],
    "økonomi_og_erhverv": [
        "skat", "afgift", "benzin", "diesel", "erhverv", "virksomhed",
        "formueskat", "økonomi", "finans", "lobbyisme", "powerpoints",
    ],
    "ret_og_retsstat": [
        "retssikkerhed",
        "retsstat",
        "domstol",
        "domstole",
        "jura",
        "juridisk",
        "lovgivning",
        "lov",
        "menneskerettigheder",
        "strafferet",
        "straf",
        "politi",
        "anklager",
        "anklagemyndighed",
        "forfatning",
        "grundlov",
        "udvisning",
        "strasbourg",
    ],
    "lokalsamfund_og_landdistrikter": [
        "nordjylland", "udkantsdanmark", "landdistrikter", "jernbane",
        "egholm", "limfjorden", "københavnere", "foreningsdanmark",
        "lokal", "nordjysk",
    ],
}


def classify_themes(title: str, deck: str = "") -> list[str]:
    """
    Første regelbaserede temaklassifikation.

    Transparent og let at justere:
    - kigger på rubrik + manchet
    - matcher mod nøgleord
    - returnerer 0, 1 eller flere temaer
    """
    text = f"{title or ''} {deck or ''}".lower()
    themes = []

    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            themes.append(theme)

    return themes


def themes_as_text(title: str, deck: str = "") -> str:
    return ", ".join(classify_themes(title, deck))



ENTITY_KEYWORDS = {
    "personer": {
        "Lars Løkke Rasmussen": ["løkke", "lars løkke"],
        "Mette Frederiksen": ["mette frederiksen", "statsministeren"],
        "Dan Jørgensen": ["dan jørgensen"],
        "Ida Auken": ["ida auken"],
        "Svend Brinkmann": ["svend brinkmann", "brinkmann"],
        "Pernille Vermund": ["vermund", "pernille vermund"],
        "Jakob Ellemann-Jensen": ["jakob ellemann", "ellemann"],
        "Troels Lund Poulsen": ["troels lund poulsen", "lund poulsen"],
        "Halime Oguz": ["halime oguz"],
        "Lars Boje Mathiesen": ["lars boje", "lars bojes"],
    },
    "partier": {
        "Socialdemokratiet": ["socialdemokratiet", "s-forfattere", "s-ledelse"],
        "Venstre": ["venstre", "v-minister", "v-formænd"],
        "Moderaterne": ["moderaterne"],
        "Liberal Alliance": ["liberal alliance", "la "],
        "Konservative": ["konservative"],
        "Dansk Folkeparti": ["dansk folkeparti", "df "],
        "SF": ["sf "],
        "Enhedslisten": ["enhedslisten", "el-veteran"],
        "Radikale Venstre": ["radikale"],
        "Alternativet": ["alternativet"],
    },
    "organisationer": {
        "EU": ["eu ", "bruxelles"],
        "NATO": ["nato"],
        "KL": ["kl "],
        "Højesteret": ["højesteret"],
        "CBS": ["cbs"],
        "Folketinget": ["folketinget"],
        "Fagbevægelsen": ["fagbevægelse", "fagforening", "fagboss"],
        "Altinget": ["altinget"],
    },
    "steder": {
        "Grønland": ["grønland", "grønlands"],
        "Palæstina": ["palæstina"],
        "Nordjylland": ["nordjylland", "nordjysk"],
        "København": ["københavn", "københavnere"],
        "Limfjorden": ["limfjorden"],
        "Egholm": ["egholm"],
        "Sverige": ["sverige"],
        "Cuba": ["cuba"],
        "Strasbourg": ["strasbourg"],
        "Bruxelles": ["bruxelles"],
    },
}


def extract_entities(title: str, deck: str = "") -> dict:
    """
    Første regelbaserede entity extraction.

    Returnerer entiteter grupperet efter type:
    - personer
    - partier
    - organisationer
    - steder
    """
    text = f" {title or ''} {deck or ''} ".lower()
    result = {}

    for group, entities in ENTITY_KEYWORDS.items():
        found = []
        for entity_name, keywords in entities.items():
            for keyword in keywords:
                keyword_l = keyword.lower()
                if keyword_l in text:
                    found.append(entity_name)
                    break
        result[group] = sorted(set(found))

    return result


def entities_as_text(title: str, deck: str = "") -> str:
    entities = extract_entities(title, deck)
    parts = []
    for group, names in entities.items():
        for name in names:
            parts.append(f"{group}:{name}")
    return ", ".join(parts)



CONFLICT_KEYWORDS = [
    "kritik", "kritiserer", "angreb", "taber", "svækker", "krise", "skandale",
    "konflikt", "oprør", "fejl", "bluff", "pres", "advarer", "raser", "opgør",
    "fyring", "afviser", "formynderi", "kontrol", "tvang", "forbud",
    "problem", "udfordring", "svigt", "svigter", "forkert",
    "farligt", "farlig", "skader", "ødelægger", "taber",
    "tåbelig", "illusion", "løgn", "vildledning", "uacceptabelt",
    "uretfærdigt", "uværdigt", "mislykket", "fiasko", "katastrofe",
    "bekymrende", "alvorligt", "galt", "galer", "forrådt",
    "svigtet", "nedskæringer", "sparer", "lukker", "nedlægger",
]

JP_VALUE_KEYWORDS = {
    "frihed_og_frit_valg": [
        "frihed", "frit valg", "frie valg", "selvbestemmelse", "ansvar for eget liv",
        "drikke", "ryge", "spise", "leve sit liv", "bestemme selv", "hvis hun vil",
    ],
    "kritik_af_formynderstat": [
        "formynderi", "formynderstat", "sindelagskontrol", "kontrol", "tvang",
        "forbud", "nægte", "skal have lov", "staten", "systemet",
    ],
    "velfærdsstatens_grænser": [
        "velfærdsstat", "velfærd", "plejehjem", "ældre", "kommune", "kommuner",
        "offentlig sektor", "bureaukrati", "pædagog", "dagtilbud",
    ],
    "borger_mod_system": [
        "borger", "borgere", "fru jensen", "retssikkerhed", "menneskerettigheder",
        "system", "styrelse", "myndighed", "staten som modpart",
    ],
    "skat_og_afgifter": [
        "skat", "afgift", "afgifter", "benzin", "diesel", "formueskat",
        "straffetold", "betaling", "dyrere",
    ],
    "værdikamp": [
        "værdikamp", "liberalt", "liberale", "håndtryk", "fundamentalisme",
        "ytringsfrihed", "frihedsrettigheder", "kulturkamp",
    ],
    "personligt_ansvar": [
        "personligt ansvar", "ansvar for sig selv", "eget ansvar", "selvforsørgelse",
        "tage ansvar", "ansvar for eget", "ansvarlig", "selvstændighed",
    ],
    "erhvervsliv_og_vækst": [
        "erhvervsliv", "vækst", "konkurrenceevne", "iværksætteri", "virksomheder",
        "investeringer", "eksport", "arbejdspladser", "regulering",
    ],
}

HIGH_VALUE_THEMES = [
    "politik",
    "ret_og_retsstat",
    "velfærd",
    "økonomi_og_erhverv",
    "udlændinge_og_integration",
]

HIGH_VALUE_ENTITIES = [
    "Mette Frederiksen",
    "Lars Løkke Rasmussen",
    "Moderaterne",
    "Socialdemokratiet",
    "Venstre",
    "EU",
    "NATO",
    "Folketinget",
    "Højesteret",
]


def detect_jp_value_signals(text: str) -> list[str]:
    """
    Finder signaler, der passer særligt godt til JP-relevante debathistorier.
    """
    found = []
    for signal, keywords in JP_VALUE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            found.append(signal)
    return found


def calculate_story_potential(item: DebateItem) -> tuple[int, list[str]]:
    """
    JP-orienteret historiepotentiale-score.
    7 faktorer: JP-værdier, navngiven aktør, regional medie, mikroemner,
    konflikt, debatformat og manglende forfatter.
    """
    score = 0
    reasons = []

    text = f"{item.title or ''} {item.deck or ''}".lower()

    entities = extract_entities(item.title, item.deck)
    micro_topics = detect_micro_topics(item.title, item.deck)

    # Faktor 1: JP-kerneværdier (+20)
    jp_signals = detect_jp_value_signals(text)
    core_jp_signals = {
        "frihed_og_frit_valg", "personligt_ansvar", "erhvervsliv_og_vækst",
        "skat_og_afgifter",
    }
    if any(s in core_jp_signals for s in jp_signals):
        score += 20
        readable = {
            "frihed_og_frit_valg": "Frit valg",
            "personligt_ansvar": "Personligt ansvar",
            "erhvervsliv_og_vækst": "Erhvervsliv/vækst",
            "skat_og_afgifter": "Skat/afgifter",
        }
        hits = [readable[s] for s in jp_signals if s in readable]
        if hits:
            reasons.append(f"JP-kerneværdi: {', '.join(hits)}")

    # Faktor 2: Navngiven aktør (+15)
    if item.author and item.author.strip():
        score += 15
        reasons.append("Navngiven aktør")
    elif entities.get("personer") or entities.get("organisationer"):
        score += 15
        reasons.append("Navngiven aktør")

    # Faktor 3: Regionalt medie (+10)
    if item.media_type == "regional":
        score += 10
        reasons.append("Regionalt medie")

    # Faktor 4: Aktive mikroemner (+10 pr. emne, maks +30)
    micro_bonus = min(len(micro_topics) * 10, 30)
    if micro_bonus > 0:
        score += micro_bonus
        labels = [t["mikroemne"].replace("_", " ") for t in micro_topics[:3]]
        reasons.append(f"Mikroemne: {', '.join(labels)}")

    # Faktor 5: Konflikt/uenighed (+10)
    conflict_hits = sum(1 for keyword in CONFLICT_KEYWORDS if keyword in text)
    if conflict_hits:
        score += 10
        reasons.append("Konflikt/uenighed")

    # Faktor 6: Debatformat (+10)
    debate_formats = {"kronik", "kommentar", "læserbrev", "debat", "analyse", "leder"}
    if item.debate_type and item.debate_type.lower() in debate_formats:
        score += 10
        reasons.append(f"Format: {item.debate_type}")

    # Faktor 7: Manglende forfatter (-10), undtagen ledere og redaktionelle
    exempt_types = {"leder", "redaktionel"}
    if not item.author and (not item.debate_type or item.debate_type.lower() not in exempt_types):
        score -= 10
        reasons.append("Mangler forfatter")

    # Begræns til 0-100 og fjern dubletter
    score = max(0, min(score, 100))
    deduped_reasons = []
    for reason in reasons:
        if reason not in deduped_reasons:
            deduped_reasons.append(reason)

    return score, deduped_reasons


def story_potential_reason_text(item: DebateItem) -> str:
    return ", ".join(calculate_story_potential(item)[1])



MICRO_TOPIC_PATTERNS = {
    "frit_valg_på_plejehjem": [
        "plejehjem",
        "ældre",
        "selvbestemmelse",
        "frihed",
        "drikke",
        "ryge",
        "madstrategi",
        "målsætninger",
    ],
    "drikkevand_og_landbrug": [
        "drikkevand",
        "grundvand",
        "nitrat",
        "landbrug",
        "dyrevelfærd",
        "sprøjteforbud",
        "forbrugere",
    ],
    "ai_og_arbejdsmarked": [
        "ai",
        "ai-",
        "kunstig intelligens",
        "kunstig",
        "chatgpt",
        "sprogmodel",
        "arbejdsmarked",
        "teknologi",
        "lønninger",
        "magtstrukturer",
        "studerende",
        "undervise",
        "kandidatreform",
    ],
    "skærme_sociale_medier_og_børn": [
        "skærme",
        "skærm",
        "sociale medier",
        "børn",
        "unge",
        "mistrivsel",
        "statistikker",
    ],
    "retssikkerhed_og_udvisning": [
        "retssikkerhed",
        "udvisning",
        "menneskerettigheder",
        "strasbourg",
        "hård udlændingepolitik",
        "rettigheder",
    ],
    "fagbevægelse_og_medlemskrise": [
        "fagbevægelse",
        "fagforening",
        "medlemskrise",
        "hovedorganisationer",
        "arbejdsmarked",
    ],
    "grønland_og_rigsfællesskab": [
        "grønland",
        "grønlands",
        "arktis",
        "rigsfællesskab",
        "selvstændighed",
    ],
    "ulvedebat": [
        "ulv",
        "ulve",
        "landmænd",
        "hegn",
    ],
    "arv_og_arveafgift": [
        "arv",
        "arveafgift",
        "arveafgifter",
        "testamente",
        "boafgift",
        "generationsskifte",
        "arvinger",
    ],
    "land_og_by": [
        "landdistrikter",
        "udkantsdanmark",
        "landsbyerne",
        "provinsen",
        "centralisering",
        "affolkning",
        "udkanten",
    ],
    "folkeskolen_og_faglighed": [
        "folkeskole",
        "folkeskolen",
        "faglighed",
        "karakterer",
        "lærere",
        "læseindlæring",
        "matematik",
    ],
    "opdragelse_og_forældreskab": [
        "opdragelse",
        "børneopdragelse",
        "forældreskab",
        "forældreansvar",
        "helikopterforældre",
        "curlingforældre",
        "konsekvenspædagogik",
        "fri opdragelse",
        "forældrerolle",
        "opdrage",
        "opdragelsesmetoder",
        "kærlighed og grænser",
        "selvstændige børn",
        "opdragelsesfilosofi",
    ],
    "boligkrise_og_lokalplaner": [
        "boligkrise",
        "boligmangel",
        "lokalplan",
        "boligpriser",
        "lejeboliger",
        "almene boliger",
        "huslejer",
    ],
    "energi_og_forsyning": [
        "el-priser",
        "fjernvarme",
        "forsyning",
        "vindenergi",
        "solceller",
        "energiselskaber",
        "energipriser",
    ],
    "asbestforbud_og_boligejere": [
        "asbest",
        "asbestforbud",
        "boligejere",
        "renovering",
        "husejere",
        "eternit",
    ],
    "lobbyisme_og_demokrati": [
        "lobbyisme",
        "lobbyister",
        "interesseorganisationer",
        "demokrati",
        "magt",
        "gennemsigtighed",
        "indflydelse",
    ],
    "ældreplejen_og_kommuner": [
        "ældrepleje",
        "hjemmehjælp",
        "plejecentre",
        "sosu",
        "normeringer",
        "ældreområdet",
        "ældre",
        "plejehjem",
        "ældrebolig",
    ],
    "psykiatri_og_unge": [
        "psykiatri",
        "psykisk",
        "angst",
        "depression",
        "ventelister",
        "mistrivsel",
        "unge",
    ],
    "integration_og_danskhed": [
        "integration",
        "danskhed",
        "parallelsamfund",
        "dansk kultur",
        "dansk",
        "danskhed",
        "muslimer",
        "islam",
        "værdier",
        "indvandrere",
        "flygtninge",
        "sprogkrav",
    ],
    "erhvervsliv_og_iværksættere": [
        "iværksætteri",
        "iværksættere",
        "virksomheder",
        "virksomhed",
        "erhvervsliv",
        "erhverv",
        "startup",
        "konkurrenceevne",
        "regulering",
        "vækst",
    ],
    "skat_og_afgifter": [
        "skat",
        "skatter",
        "skattelettelse",
        "skattelettelser",
        "skattereform",
        "afgift",
        "afgifter",
        "benzin",
        "diesel",
        "formueskat",
        "beskatning",
    ],
}

def detect_micro_topics(title: str, deck: str = "") -> list[dict]:
    """
    Finder konkrete debatspor baseret på keyword-clusters.
    """
    text = f"{title or ''} {deck or ''}".lower()
    found = []

    for topic_name, keywords in MICRO_TOPIC_PATTERNS.items():
        hits = [kw for kw in keywords if kw in text]

        # Som udgangspunkt kræver vi mindst to hits.
        # Enkelte meget præcise mikroemner kan accepteres med ét stærkt hit,
        # hvis rubrikken/manchetten tydeligt bærer emnet.
        strong_single_hit_topics = {
            "drikkevand_og_landbrug",
            "retssikkerhed_og_udvisning",
            "fagbevægelse_og_medlemskrise",
            "ulvedebat",
            "arv_og_arveafgift",
            "asbestforbud_og_boligejere",
            "psykiatri_og_unge",
            "ældreplejen_og_kommuner",
            "lobbyisme_og_demokrati",
            "ai_og_arbejdsmarked",
            "grønland_og_rigsfællesskab",
            "boligkrise_og_lokalplaner",
            "energi_og_forsyning",
            "opdragelse_og_forældreskab",
        }

        if len(hits) >= 2 or (topic_name in strong_single_hit_topics and len(hits) >= 1):
            found.append({
                "mikroemne": topic_name,
                "keywords": sorted(set(hits)),
                "score": len(hits),
            })

    found.sort(key=lambda x: x["score"], reverse=True)
    return found

def micro_topics_as_text(title: str, deck: str = "") -> str:
    topics = detect_micro_topics(title, deck)
    return ", ".join([t["mikroemne"] for t in topics])


def item_to_app_dict(item: DebateItem) -> dict:
    """
    App-venlig datastruktur.
    Bruges til JSON-output og senere backend/frontend.
    """
    return {
        "artikel_id": article_id_from_url(item.url),
        "fundet_tidspunkt": normalize_timestamp(item.discovered_at),
        "udgivelsestidspunkt": normalize_timestamp(item.published_at),
        "medie": item.media,
        "medietype": item.media_type,
        "region": item.region,
        "rubrik": item.title,
        "manchet": item.deck,
        "forfatter": item.author,
        "debat_type": item.debate_type,
        "debat_type_standard": standardize_debate_type(item.debate_type),
        "temaer": classify_themes(item.title, item.deck),
        "entiteter": extract_entities(item.title, item.deck),
        "historiepotentiale_score": calculate_story_potential(item)[0],
        "historiepotentiale_begrundelse": calculate_story_potential(item)[1],
        "mikroemner": detect_micro_topics(item.title, item.deck),
        "feedback_score": "",
        "feedback_label": "",
        "url": item.url,
        "fundet_via": item.source_method,
        "status": item.status,
    }


def write_items_to_json(items: List[DebateItem], output_path: str, source_status: Optional[List[dict]] = None) -> None:
    """
    Skriver fundne artikler til JSON-fil.

    JSON-outputtet er tænkt som bro til en senere app.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    sorted_items = sorted(
        items,
        key=lambda item: normalize_timestamp(item.published_at) or normalize_timestamp(item.discovered_at),
        reverse=True,
    )

    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(sorted_items),
        "sources": source_status or [],
        "articles": [item_to_app_dict(item) for item in sorted_items],
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Skrev {len(sorted_items)} poster til JSON: {path}")



def write_new_items_to_json(items: List[DebateItem], output_path: str, source_status: Optional[List[dict]] = None) -> None:
    """
    Skriver kun nye artikler til separat realtime-feed.

    Bruges senere til:
    - frontend-opdateringer
    - realtime-feed
    - AI-analyse af nye artikler
    - push-notifikationer
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(items),
        "sources": source_status or [],
        "articles": [item_to_app_dict(item) for item in items],
    }

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Skrev {len(items)} nye poster til JSON: {path}")


def write_items_to_csv(items: List[DebateItem], output_path: str) -> None:
    """
    Skriver resultatet til CSV med danske kolonnenavne.
    CSV er vores stabile mellemtrin før Google Sheets.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Sortér nogenlunde læsbart: nyeste først, hvis dato findes.
    sorted_items = sorted(
        items,
        key=lambda item: item.published_at or item.discovered_at,
        reverse=True,
    )

    fieldnames = [
        "fundet_tidspunkt",
        "udgivelsestidspunkt",
        "medie",
        "medietype",
        "region",
        "rubrik",
        "manchet",
        "forfatter",
        "debat_type",
        "url",
        "fundet_via",
        "status",
        "ny_i_denne_kørsel",
        "artikel_id",
        "debat_type_standard",
        "temaer",
        "entiteter",
        "historiepotentiale_score",
        "historiepotentiale_begrundelse",
        "mikroemner",
        "feedback_score",
        "feedback_label",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for item in sorted_items:
            writer.writerow({
                "fundet_tidspunkt": item.discovered_at,
                "udgivelsestidspunkt": item.published_at,
                "medie": item.media,
                "medietype": item.media_type,
                "region": item.region,
                "rubrik": item.title,
                "manchet": item.deck,
                "forfatter": item.author,
                "debat_type": item.debate_type,
                "url": item.url,
                "fundet_via": item.source_method,
                "status": item.status,
                "ny_i_denne_kørsel": "",
                "artikel_id": article_id_from_url(item.url),
                "debat_type_standard": standardize_debate_type(item.debate_type),
                "temaer": themes_as_text(item.title, item.deck),
                "entiteter": entities_as_text(item.title, item.deck),
                "historiepotentiale_score": calculate_story_potential(item)[0],
                "historiepotentiale_begrundelse": story_potential_reason_text(item),
                "mikroemner": micro_topics_as_text(item.title, item.deck),
                "feedback_score": "",
                "feedback_label": "",
            })

    print(f"Skrev {len(sorted_items)} poster til CSV: {path}")



MEDIA_RULES_FILE = Path(__file__).resolve().parent / "config" / "media_rules.yaml"


def load_media_rules() -> Dict[str, Any]:
    """
    Læser mediespecifikke regler fra config/media_rules.yaml.
    Første stabiliseringstrin: reglerne er nu samlet uden for run_scraper.py.
    """
    try:
        if not MEDIA_RULES_FILE.exists():
            return {}
        with MEDIA_RULES_FILE.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception as exc:
        print(f"[WARN] Kunne ikke læse media_rules.yaml: {exc}")
        return {}


def load_env_file(path: str = ".env") -> None:
    """
    Læser kun .env fra den faste config-mappe.

    Lokal .env i versionsmappen bruges ikke længere.
    """
    env_path = CONFIG_DIR / ".env"

    if not env_path.exists():
        raise RuntimeError(f"Fandt ikke .env i config-mappen: {env_path}")

    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def connect_spreadsheet():
    """
    Åbner hele Google Sheet-filen.

    Bruger kun den faste config-mappe:
    C:/Users/Esben.L.Mikkelsen/OneDrive - JP Politikens Hus/Jyllands-Posten/Scrapere/Config-filer
    """
    sheet_name = os.getenv("GOOGLE_SHEET_NAME")
    credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE")

    if not sheet_name:
        raise RuntimeError(f"GOOGLE_SHEET_NAME mangler i {CONFIG_DIR / '.env'}")

    if not credentials_file:
        credentials_file = str(CONFIG_DIR / "credentials.json")

    credentials_path = Path(credentials_file)
    if not credentials_path.is_absolute():
        credentials_path = CONFIG_DIR / credentials_file

    if not credentials_path.exists():
        raise RuntimeError(f"Fandt ikke credentials.json: {credentials_path}")

    gc = gspread.service_account(filename=str(credentials_path))
    return gc.open(sheet_name)


def get_or_create_worksheet(spreadsheet, title: str, rows: int = 1000, cols: int = 20):
    """
    Finder et faneblad. Opretter det, hvis det ikke findes.
    """
    try:
        return spreadsheet.worksheet(title)
    except Exception:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def append_log_row(status: str, fundne_artikler: int, nye_artikler: int, dubletter: int, fejl: str = "") -> None:
    """
    Skriver én række i log-fanebladet.
    Loggen er vigtig, når scraperen senere skal køre automatisk.
    """
    try:
        spreadsheet = connect_spreadsheet()
        log_ws = get_or_create_worksheet(spreadsheet, "log", rows=1000, cols=6)

        header = [
            "kørsel_tidspunkt",
            "status",
            "fundne_artikler",
            "nye_artikler",
            "dubletter",
            "fejl",
        ]

        first_row = log_ws.row_values(1)
        if first_row != header:
            log_ws.update(values=[header], range_name="A1:F1")
            try:
                log_ws.freeze(rows=1)
            except Exception:
                pass

        log_ws.append_row([
            dt.datetime.now(dt.timezone.utc).isoformat(),
            status,
            fundne_artikler,
            nye_artikler,
            dubletter,
            fejl,
        ], value_input_option="USER_ENTERED")

    except Exception as exc:
        print(f"[WARN] Kunne ikke skrive til log-ark: {exc}")


def connect_sheet():
    spreadsheet = connect_spreadsheet()
    return spreadsheet.sheet1

def ensure_sheet_header(ws):
    """
    Sikrer danske kolonneoverskrifter.
    Overskriftsrækken sættes hver gang, så gamle engelske overskrifter ikke vender tilbage.
    """
    header = [
        "fundet_tidspunkt",
        "udgivelsestidspunkt",
        "medie",
        "medietype",
        "region",
        "rubrik",
        "manchet",
        "forfatter",
        "debat_type",
        "url",
        "fundet_via",
        "status",
        "ny_i_denne_kørsel",
        "artikel_id",
        "debat_type_standard",
        "temaer",
        "entiteter",
        "historiepotentiale_score",
        "historiepotentiale_begrundelse",
        "mikroemner",
        "feedback_score",
        "feedback_label",
    ]
    ws.update(values=[header], range_name="A1:V1")

    # Frys overskriftsrækken, så kolonnenavne altid er synlige.
    try:
        ws.freeze(rows=1)
    except Exception:
        pass

def extract_url_from_sheet_cell(value: str) -> str:
    """
    Henter URL ud af enten rå URL eller HYPERLINK-formel.
    Eksempel:
    =HYPERLINK("https://example.dk", "Læs artikel")
    """
    value = str(value or "").strip()

    if value.upper().startswith("=HYPERLINK("):
        first_quote = value.find('"')
        second_quote = value.find('"', first_quote + 1)
        if first_quote != -1 and second_quote != -1:
            return value[first_quote + 1:second_quote]

    return value


def existing_urls(ws) -> set:
    """
    Læser eksisterende URL'er fra Google Sheet.
    Bruger formlavisning, så vi kan læse URL'en bag 'Læs artikel'.
    """
    try:
        values = ws.get("J2:J", value_render_option="FORMULA")
    except TypeError:
        values = ws.get("J2:J")

    urls = set()
    for row in values:
        if not row:
            continue
        raw = row[0]
        url = extract_url_from_sheet_cell(raw)
        if url:
            urls.add(canonicalize_url_for_dedupe(url))

    return urls


def sheet_hyperlink(url: str, text: str = "Læs artikel") -> str:
    """
    Returnerer en Google Sheets HYPERLINK-formel.
    """
    safe_url = str(url).replace('"', '""')
    safe_text = str(text).replace('"', '""')
    return f'=HYPERLINK("{safe_url}"; "{safe_text}")'



def format_sheet_columns(ws) -> None:
    """
    Gør Google Sheet mere læsbart.
    Kolonnebredderne er faste og forsigtige, så vi ikke ændrer data.
    """
    try:
        # Kolonneindeks er 0-baserede i batch_update:
        # A=0, B=1, C=2 osv.
        requests = [
            # fundet_tidspunkt + udgivelsestidspunkt
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 2},
                "properties": {"pixelSize": 155},
                "fields": "pixelSize"
            }},
            # medie, medietype, region
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 5},
                "properties": {"pixelSize": 120},
                "fields": "pixelSize"
            }},
            # rubrik
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6},
                "properties": {"pixelSize": 420},
                "fields": "pixelSize"
            }},
            # manchet
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7},
                "properties": {"pixelSize": 520},
                "fields": "pixelSize"
            }},
            # forfatter, debat_type
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 7, "endIndex": 9},
                "properties": {"pixelSize": 150},
                "fields": "pixelSize"
            }},
            # url/Læs artikel
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 9, "endIndex": 10},
                "properties": {"pixelSize": 110},
                "fields": "pixelSize"
            }},
            # fundet_via, status
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 10, "endIndex": 12},
                "properties": {"pixelSize": 110},
                "fields": "pixelSize"
            }},
            # ny_i_denne_kørsel
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 12, "endIndex": 13},
                "properties": {"pixelSize": 130},
                "fields": "pixelSize"
            }},
            # artikel_id
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 13, "endIndex": 14},
                "properties": {"pixelSize": 135},
                "fields": "pixelSize"
            }},
            # debat_type_standard
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 14, "endIndex": 15},
                "properties": {"pixelSize": 150},
                "fields": "pixelSize"
            }},
            # temaer
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 15, "endIndex": 16},
                "properties": {"pixelSize": 220},
                "fields": "pixelSize"
            }},
            # entiteter
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 16, "endIndex": 17},
                "properties": {"pixelSize": 320},
                "fields": "pixelSize"
            }},
        ]
        # Feedback-kolonner
        requests.extend([
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 20, "endIndex": 21},
                "properties": {"pixelSize": 110},
                "fields": "pixelSize"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 21, "endIndex": 22},
                "properties": {"pixelSize": 130},
                "fields": "pixelSize"
            }},
        ])

        ws.spreadsheet.batch_update({"requests": requests})
    except Exception as exc:
        print(f"[WARN] Kunne ikke sætte kolonnebredder: {exc}")



def column_number_to_letters(number: int) -> str:
    """
    1 -> A, 2 -> B, 27 -> AA
    """
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def column_index_from_header(header: List[str], column_name: str) -> Optional[int]:
    """
    Finder 1-baseret kolonneindeks ud fra headernavn.
    """
    try:
        normalized = [str(h or "").strip() for h in header]
        return normalized.index(column_name) + 1
    except ValueError:
        return None


def load_sheet_sort_settings() -> Dict[str, Any]:
    """
    Læser sortering fra config/sheet_rules.yaml.
    """
    default = {"column_name": "udgivelsestidspunkt", "descending": True}
    path = Path(__file__).resolve().parent / "config" / "sheet_rules.yaml"

    try:
        if not path.exists():
            return default

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        sort = data.get("sort", {}) or {}

        return {
            "column_name": sort.get("column_name", default["column_name"]),
            "descending": bool(sort.get("descending", default["descending"])),
        }

    except Exception as exc:
        print(f"[WARN] Kunne ikke læse sheet_rules.yaml: {exc}")
        return default


def sort_sheet_by_datetime(ws) -> None:
    """
    Sorterer Google Sheet efter et kolonnenavn i headeren.

    Tidligere brugte den et fast område A2:V.
    Det kunne fejle, hvis arket havde flere/færre kolonner.
    """
    try:
        sort_settings = load_sheet_sort_settings()
        column_name = sort_settings["column_name"]
        descending = sort_settings["descending"]

        header = ws.row_values(1)
        sort_col = column_index_from_header(header, column_name)

        if not sort_col:
            print(f"[WARN] Kunne ikke sortere arket: fandt ikke kolonnen '{column_name}'")
            return

        values = ws.get_all_values()
        row_count = max(len(values), 2)
        col_count = max(len(header), 1)

        sort_order = "des" if descending else "asc"
        sort_range = f"A2:{column_number_to_letters(col_count)}{row_count}"

        ws.sort(
            (sort_col, sort_order),
            range=sort_range,
        )

    except Exception as exc:
        print(f"[WARN] Kunne ikke sortere arket: {exc}")



def clear_new_flags(ws) -> None:
    """
    Nulstiller 'ny_i_denne_kørsel' for gamle rækker, før nye rækker skrives.
    """
    try:
        existing_rows = len(ws.get_all_values())
        if existing_rows >= 2:
            blanks = [[""] for _ in range(existing_rows - 1)]
            ws.update(values=blanks, range_name=f"M2:M{existing_rows}")
    except Exception as exc:
        print(f"[WARN] Kunne ikke nulstille ny-markeringer: {exc}")


def highlight_new_rows(ws) -> None:
    """
    Farvemarkerer rækker, hvor kolonnen 'ny_i_denne_kørsel' er JA.
    Rydder først farve på dataområdet, så gamle markeringer ikke bliver hængende.
    """
    try:
        values = ws.get_all_values()
        row_count = max(len(values), 2)

        requests = []

        # Ryd baggrundsfarve på alle datarækker A:M.
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,
                    "endRowIndex": row_count,
                    "startColumnIndex": 0,
                    "endColumnIndex": 22,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": 1,
                            "green": 1,
                            "blue": 1,
                        }
                    }
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

        # Marker nye rækker svagt grønt.
        for idx, row in enumerate(values[1:], start=2):
            flag = row[12] if len(row) >= 13 else ""
            if flag == "JA":
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": idx - 1,
                            "endRowIndex": idx,
                            "startColumnIndex": 0,
                            "endColumnIndex": 22,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": 0.85,
                                    "green": 0.95,
                                    "blue": 0.85,
                                }
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                })

        if requests:
            ws.spreadsheet.batch_update({"requests": requests})
    except Exception as exc:
        print(f"[WARN] Kunne ikke farvemarkere nye rækker: {exc}")



SHARED_DATA_DIR = Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Fælles-data")
SHARED_FEEDBACK_FILE = SHARED_DATA_DIR / "feedback.json"


def export_feedback_from_sheet(ws) -> None:
    """
    Eksporterer feedback fra Google Sheet til fælles feedback.json.
    """
    try:
        SHARED_DATA_DIR.mkdir(parents=True, exist_ok=True)

        values = ws.get_all_values()
        if not values:
            return

        header = values[0]
        rows = values[1:]

        def col(name):
            try:
                return header.index(name)
            except ValueError:
                return -1

        url_col = col("url")
        score_col = col("feedback_score")
        label_col = col("feedback_label")

        if url_col == -1:
            return

        feedback = {}

        for row in rows:
            if len(row) <= url_col:
                continue

            raw_url = row[url_col]
            url = extract_url_from_sheet_cell(raw_url)

            if not url:
                continue

            score = row[score_col].strip() if score_col != -1 and len(row) > score_col else ""
            label = row[label_col].strip() if label_col != -1 and len(row) > label_col else ""

            opened = score in ["1", "2"] or label in ["åbnet", "aabnet", "interessant"]
            interesting = score == "2" or label == "interessant"

            if opened or interesting:
                feedback[url] = {
                    "opened": opened,
                    "interesting": interesting,
                    "feedback_score": score,
                    "feedback_label": label,
                }

        with SHARED_FEEDBACK_FILE.open("w", encoding="utf-8") as f:
            json.dump(feedback, f, ensure_ascii=False, indent=2)

        print(f"Skrev feedback til fælles fil: {SHARED_FEEDBACK_FILE}")

    except Exception as exc:
        print(f"[WARN] Kunne ikke eksportere feedback fra Google Sheet: {exc}")



def load_shared_feedback() -> dict:
    """
    Læser feedback fra fælles feedback.json.
    Bruges til at synkronisere app-feedback tilbage til Google Sheet.
    """
    try:
        if not SHARED_FEEDBACK_FILE.exists():
            return {}
        with SHARED_FEEDBACK_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[WARN] Kunne ikke læse fælles feedback-fil: {exc}")
        return {}


def sync_feedback_to_sheet(ws) -> None:
    """
    Skriver feedback_score og feedback_label fra fælles feedback.json tilbage til Google Sheet.

    Feedbackmodel:
    0 / ikke_åbnet
    1 / åbnet
    2 / interessant
    """
    try:
        feedback = load_shared_feedback()
        if not feedback:
            return

        values = ws.get_all_values()
        if not values:
            return

        header = values[0]
        rows = values[1:]

        def col(name):
            try:
                return header.index(name)
            except ValueError:
                return -1

        url_col = col("url")
        score_col = col("feedback_score")
        label_col = col("feedback_label")

        if url_col == -1 or score_col == -1 or label_col == -1:
            print("[WARN] Kan ikke synkronisere feedback: mangler url/feedback_score/feedback_label-kolonner")
            return

        score_updates = []
        label_updates = []

        for row in rows:
            if len(row) <= url_col:
                score_updates.append([""])
                label_updates.append([""])
                continue

            raw_url = row[url_col]
            url = extract_url_from_sheet_cell(raw_url)
            item = feedback.get(url, {})

            if item.get("interesting"):
                score_updates.append(["2"])
                label_updates.append(["interessant"])
            elif item.get("opened"):
                score_updates.append(["1"])
                label_updates.append(["åbnet"])
            else:
                score_updates.append(["0"])
                label_updates.append(["ikke_åbnet"])

        if rows:
            # Kolonner er 1-baserede i A1-notation.
            score_letter = chr(ord("A") + score_col)
            label_letter = chr(ord("A") + label_col)

            ws.update(
                values=score_updates,
                range_name=f"{score_letter}2:{score_letter}{len(rows)+1}",
            )
            ws.update(
                values=label_updates,
                range_name=f"{label_letter}2:{label_letter}{len(rows)+1}",
            )

        print("Synkroniserede feedback fra app til Google Sheet.")

    except Exception as exc:
        print(f"[WARN] Kunne ikke synkronisere feedback til Google Sheet: {exc}")


def append_items_to_sheet(items: List[DebateItem]) -> tuple[int, int, List[DebateItem]]:
    """
    Skriver kun nye artikler til Google Sheet.
    Dubletter afgøres på URL uden tracking-parametre.
    """
    ws = connect_sheet()
    ensure_sheet_header(ws)
    format_sheet_columns(ws)
    clear_new_flags(ws)

    seen = existing_urls(ws)
    new_items = []
    skipped = 0

    for item in items:
        key = canonicalize_url_for_dedupe(item.url)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        new_items.append(item)

    if not new_items:
        highlight_new_rows(ws)
        sync_feedback_to_sheet(ws)
        export_feedback_from_sheet(ws)
        print(f"Ingen nye rækker at skrive. Sprang {skipped} dubletter over.")
        return 0, skipped, []

    rows = [[
        normalize_timestamp(item.discovered_at),
        normalize_timestamp(item.published_at),
        item.media,
        item.media_type,
        item.region,
        item.title,
        item.deck,
        item.author,
        item.debate_type,
        sheet_hyperlink(item.url),
        item.source_method,
        item.status,
        "JA",
        article_id_from_url(item.url),
        standardize_debate_type(item.debate_type),
        themes_as_text(item.title, item.deck),
        entities_as_text(item.title, item.deck),
        calculate_story_potential(item)[0],
        story_potential_reason_text(item),
        micro_topics_as_text(item.title, item.deck),
        "",
        "",
    ] for item in new_items]

    ws.append_rows(rows, value_input_option="USER_ENTERED")

    # Hold nyeste artikler øverst i arket.
    sort_sheet_by_datetime(ws)

    # Farvemarker nye artikler efter sortering.
    highlight_new_rows(ws)

    sync_feedback_to_sheet(ws)
    export_feedback_from_sheet(ws)
    print(f"Skrev {len(rows)} nye rækker til Google Sheet. Sprang {skipped} dubletter over.")
    return len(rows), skipped, new_items



def media_rule(media_name: str) -> Dict[str, Any]:
    return load_media_rules().get(media_name, {})


def media_rule_labels(media_name: str) -> Dict[str, str]:
    return media_rule(media_name).get("labels", {}) or {}


def media_rule_segments(media_name: str, key: str = "accepted_url_segments") -> List[str]:
    return media_rule(media_name).get(key, []) or []


def label_from_rules(media_name: str, text: str) -> str:
    """
    Matcher labeltekst mod config/media_rules.yaml.

    Eksempel:
    Berlingske:
      "kommentatorer" -> "Kommentar"
      "synspunkter" -> "Debat"
    """
    value = normalize_label_text(text)
    labels = media_rule_labels(media_name)

    # Længste labels først, så "berlingske mener" matcher før "leder".
    for raw_label, debate_type in sorted(labels.items(), key=lambda item: len(item[0]), reverse=True):
        raw = normalize_label_text(raw_label)
        if raw and raw in value:
            return debate_type

    return ""




def diagnose_politiken_top(client: httpx.Client, source: Source, max_items: int = 60) -> None:
    """
    Diagnose af den øverste del af Politikens debatforside.

    Printer:
    - links i rækkefølge
    - nærmeste container-type
    - eventuel label
    - linktekst
    - URL
    - korttekst

    Bruges kun til at forstå Politiken-strukturen.
    """
    if not source.section_urls:
        print("[POLITIKEN TOP DEBUG] Ingen section_urls.")
        return

    section_url = source.section_urls[0]
    html_text = fetch_text(client, section_url)

    if not html_text:
        print(f"[POLITIKEN TOP DEBUG] Kunne ikke hente {section_url}")
        return

    soup = BeautifulSoup(html_text, "lxml")

    print(f"[POLITIKEN TOP DEBUG] Hentede {len(html_text)} tegn fra {section_url}")
    print(f"[POLITIKEN TOP DEBUG] Antal <article>-kort: {len(soup.find_all('article'))}")
    print(f"[POLITIKEN TOP DEBUG] Første {max_items} relevante links på siden:")

    printed = 0

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        absolute = canonicalize_url_for_dedupe(clean_url(urljoin(section_url, href)))

        if not absolute.startswith("http"):
            continue
        if not same_domain_or_subdomain(absolute, source.base_url):
            continue

        # Vis bredt for Politiken, men prioriter debat/art-links.
        if "politiken.dk" not in absolute:
            continue

        link_text = a.get_text(" ", strip=True)
        if not link_text:
            continue

        # Find nærmeste container
        container = a
        container_name = getattr(a, "name", "-")
        article_parent = a.find_parent("article")

        if article_parent:
            container = article_parent
            container_name = "article"
        else:
            for parent in a.parents:
                if not getattr(parent, "name", None):
                    continue
                if parent.name in ["div", "li", "section"]:
                    text = parent.get_text(" ", strip=True)
                    if 15 <= len(text) <= 2500:
                        container = parent
                        container_name = parent.name
                        break

        label = politiken_card_label(container)
        debate_type = politiken_label_to_debate_type(label)
        card_text = container.get_text(" ", strip=True)

        looks_article = politiken_url_looks_like_article(absolute)
        has_debat = "/debat/" in absolute.lower()
        has_art = "/art" in absolute.lower()

        printed += 1
        print(f"[POLITIKEN TOP DEBUG] {printed}.")
        print(f"[POLITIKEN TOP DEBUG]    container={container_name}")
        print(f"[POLITIKEN TOP DEBUG]    label={label or '-'}")
        print(f"[POLITIKEN TOP DEBUG]    debat_type={debate_type or '-'}")
        print(f"[POLITIKEN TOP DEBUG]    has_debat={has_debat} has_art={has_art} accepted_url_shape={looks_article}")
        print(f"[POLITIKEN TOP DEBUG]    linktekst={link_text[:180]}")
        print(f"[POLITIKEN TOP DEBUG]    url={absolute}")
        print(f"[POLITIKEN TOP DEBUG]    korttekst={card_text[:320]}")

        if printed >= max_items:
            break






def nordjyske_deck_from_article_page(client: httpx.Client, url: str, title: str = "") -> str:
    """
    Henter manchet direkte fra Nordjyske-artikelsiden.

    Nordjyske giver ofte ikke manchetten med via sitemap/forside.
    Derfor prøver vi flere lag:
    - meta description
    - og/twitter description
    - JSON-LD description
    - første relevante brødtekst/summary-afsnit
    """
    try:
        html_text = fetch_text(client, url)
        if not html_text:
            return ""

        soup = BeautifulSoup(html_text, "lxml")

        candidates = []

        # Meta-tags
        for selector in [
            'meta[property="og:description"]',
            'meta[name="description"]',
            'meta[name="twitter:description"]',
        ]:
            tag = soup.select_one(selector)
            if tag and tag.get("content"):
                candidates.append(tag.get("content", ""))

        # JSON-LD
        for data in extract_json_ld(soup):
            if isinstance(data, dict):
                desc = data.get("description")
                if isinstance(desc, str):
                    candidates.append(desc)

        # Særlige tekstblokke og første relevante afsnit
        for selector in [
            '[class*="lead"]',
            '[class*="intro"]',
            '[class*="summary"]',
            '[class*="article__intro"]',
            '[class*="article-intro"]',
            'article p',
        ]:
            for tag in soup.select(selector)[:8]:
                text = tag.get_text(" ", strip=True)
                if text:
                    candidates.append(text)

        title_norm = clean_text(title).lower()

        for candidate in candidates:
            deck = clean_text(candidate)

            if not deck:
                continue

            # Drop rubrik, cookie-tekst, navigation osv.
            lower = deck.lower()

            if title_norm and lower == title_norm:
                continue

            bad_fragments = [
                "cookie",
                "privatlivspolitik",
                "abonnement",
                "log ind",
                "læs også",
                "annonce",
                "nordjyske.dk",
            ]

            if any(fragment in lower for fragment in bad_fragments):
                continue

            if len(deck) < 25:
                continue

            if len(deck) > 500:
                deck = deck[:500].rsplit(" ", 1)[0]

            return deck

    except Exception as exc:
        print(f"[WARN] Kunne ikke hente Nordjyske-manchet fra artikelside: {exc}")

    return ""



def nordjyske_card_has_debate_label(card) -> bool:
    """
    Nordjyske debatforside viser typisk 'Debat' over rubrikken.
    Vi accepterer kun kort, hvor 'Debat' står i kortteksten.
    """
    try:
        text = normalize_label_text(card.get_text(" ", strip=True))
        return "debat" in text
    except Exception:
        return False


def nordjyske_url_looks_like_article(url: str) -> bool:
    value = (url or "").lower()

    if "nordjyske.dk" not in value:
        return False

    if "/nyheder/debat" in value and value.rstrip("/").endswith("/nyheder/debat"):
        return False

    # Nordjyske debatartikler kan ligge bredere, men de skal være egentlige artikler.
    # Accepterer nyheds/debat-URL'er og klassiske artikel-URL'er.
    if "/nyheder/debat" in value:
        return True

    if "/debat/" in value:
        return True

    return False


def enrich_missing_deck_from_article_page(client: httpx.Client, item: DebateItem, source: Source) -> DebateItem:
    """
    Hvis en artikel mangler manchet, åbnes selve artikelsiden og metadata hentes igen.
    """
    if not item:
        return item

    if item.deck and item.deck.strip():
        return item

    try:
        # Nordjyske kræver ofte særskilt manchet-logik.
        if source.name == "Nordjyske":
            deck = nordjyske_deck_from_article_page(client, item.url, item.title)
            if deck:
                item.deck = deck
                return item

        enriched = extract_article_metadata(client, source, item.url, item.source_method)

        if enriched and enriched.deck and enriched.deck.strip():
            item.deck = enriched.deck

        if enriched and enriched.published_at and not item.published_at:
            item.published_at = enriched.published_at

        if enriched and enriched.author and not item.author:
            item.author = enriched.author

    except Exception as exc:
        print(f"[WARN] Kunne ikke hente manchet fra artikelside for {item.url}: {exc}")

    return item



BERLINGSKE_ALLOWED_LABEL_PATTERNS = [
    r"\bkommentar\b",
    r"\bkronik\b",
    r"\bleder\b",
    r"\bdebat\b",
    r"\banalyse\b",
    r"\bberlingske mener\b",
]







def build_scraper_helpers() -> Dict[str, Any]:
    """
    Samler de funktioner/klasser, som mediescrapere i media_scrapers/ må bruge.

    Selve listen bygges nu i media_scrapers/helpers.py.
    Det gør run_scraper.py lidt renere og gør næste refaktor lettere.
    """
    return build_media_scraper_helpers({
        "DebateItem": DebateItem,
        "fetch_text": fetch_text,
        "clean_text": clean_text,
        "clean_url": clean_url,
        "canonicalize_url_for_dedupe": canonicalize_url_for_dedupe,
        "same_domain_or_subdomain": same_domain_or_subdomain,
        "extract_article_metadata": extract_article_metadata,
        "normalize_label_text": normalize_label_text,
        "label_from_rules": label_from_rules,
        "media_rule_segments": media_rule_segments,
        "media_rule": media_rule,
        "politiken_card_label": politiken_card_label,
        "politiken_label_to_debate_type": politiken_label_to_debate_type,
        "BERLINGSKE_ALLOWED_LABEL_PATTERNS": BERLINGSKE_ALLOWED_LABEL_PATTERNS,
        "discover_urls_from_section_pages": discover_urls_from_section_pages,
        "enrich_missing_deck_from_article_page": enrich_missing_deck_from_article_page,
        "re": re,
    })


def run(dry_run: bool, limit_per_source: int, only: Optional[str], min_section_results: int, show_urls: bool, csv_output: Optional[str], json_output: Optional[str], new_json_output: Optional[str]) -> List[DebateItem]:
    load_env_file()
    sources = load_sources()
    if only:
        sources = [s for s in sources if s.name.lower() == only.lower()]
        if not sources:
            raise RuntimeError(f"Fandt ikke kilden: {only}")

    items: List[DebateItem] = []
    seen_urls = set()
    seen_titles_by_source = set()
    headers = {"User-Agent": USER_AGENT}

    with httpx.Client(headers=headers, timeout=DEFAULT_TIMEOUT) as client:
        for source in sources:
            print(f"\n=== {source.name} ===")

            kept = 0

            external_scraper = get_external_scraper(source.name)

            if external_scraper:
                external_items = external_scraper(
                    client,
                    source,
                    show_urls=show_urls,
                    limit=limit_per_source,
                    helpers=build_scraper_helpers(),
                )

                for item in external_items:
                    items.append(item)
                    kept += 1

                continue

            if source.section_urls:
                politiken_type_by_url = {}
                if source.name == "Politiken":
                    politiken_type_by_url = discover_politiken_urls_from_section_pages(client, source)
                    section_urls = list(politiken_type_by_url.keys())
                else:
                    section_urls = discover_urls_from_section_pages(client, source)

                if limit_per_source:
                    section_urls = section_urls[:limit_per_source]

                print(f"Fundet {len(section_urls)} artikel-lignende URL'er via debatforside")

                for url in section_urls:
                    item = extract_article_metadata(client, source, url, "section_page")
                    if item:
                        if source.name == "Politiken" and politiken_type_by_url.get(url):
                            item.debate_type = politiken_type_by_url[url]
                        items.append(item)
                        kept += 1
                        print(f"- {item.media}: {item.title}" + (f"\n  {item.url}" if show_urls else ""))
                print(f"Beholdt {kept} poster fra debatforside")
            else:
                print("Ingen debatforside angivet. Går direkte til sitemap.")

            if kept < min_section_results and source.sitemap_urls:
                print(f"Debatforside gav kun {kept} poster. Prøver sitemap som backup.")
                already_seen_urls = {item.url for item in items if item.media == source.name}

                sitemap_urls = discover_urls_from_sitemaps(client, source)
                candidate_urls = [u for u in sitemap_urls if url_is_probably_article(u, source) and url_is_in_strict_sitemap_section(u, source)]
                candidate_urls = [u for u in candidate_urls if u not in already_seen_urls]

                if limit_per_source:
                    candidate_urls = candidate_urls[:limit_per_source]

                print(f"Fundet {len(candidate_urls)} mulige debat-URL'er via sitemap")
                sitemap_kept = 0
                for url in candidate_urls:
                    item = extract_article_metadata(client, source, url, "sitemap")
                    if item:
                        url_key = canonicalize_url_for_dedupe(item.url)
                        title_key = (item.media, item.title.lower())
                        if url_key in seen_urls or title_key in seen_titles_by_source:
                            continue
                        seen_urls.add(url_key)
                        seen_titles_by_source.add(title_key)
                        items.append(item)
                        sitemap_kept += 1
                        print(f"- {item.media}: {item.title}" + (f"\n  {item.url}" if show_urls else ""))
                print(f"Beholdt {sitemap_kept} poster fra sitemap-backup")

    source_status = build_source_status(items, sources)

    if csv_output:
        write_items_to_csv(items, csv_output)

    if json_output:
        write_items_to_json(items, json_output, source_status=source_status)

    if dry_run:
        if new_json_output:
            write_new_items_to_json(items, new_json_output, source_status=source_status)

        print(f"\nDry run færdig. {len(items)} poster fundet.")
        return items

    # SQLite skrives før Google Sheets, så artikler gemmes lokalt selv hvis Sheets fejler.
    try:
        from db.database import write_items_to_sqlite
        write_items_to_sqlite([item_to_app_dict(i) for i in items])
    except Exception as db_exc:
        print(f"[ADVARSEL] SQLite-skrivning fejlede: {db_exc}")

    try:
        nye_artikler, dubletter, new_items = append_items_to_sheet(items)

        if new_json_output:
            write_new_items_to_json(new_items, new_json_output, source_status=source_status)

        append_log_row(
            status="OK",
            fundne_artikler=len(items),
            nye_artikler=nye_artikler,
            dubletter=dubletter,
            fejl="",
        )
    except Exception as exc:
        append_log_row(
            status="FEJL",
            fundne_artikler=len(items),
            nye_artikler=0,
            dubletter=0,
            fejl=str(exc),
        )
        raise

    return items

def print_db_stats() -> None:
    """
    Viser database-statistik og stopper. Kører ingen scraping.
    Læser kun fra databasen — skriver aldrig.
    """
    from db.database import get_stats, get_count_by_source, get_recent_articles, get_duplicates
    from db.database import get_db_path

    db_path = get_db_path()
    print(f"\nSQLite-database: {db_path}")

    if not db_path.exists():
        print("Databasen er ikke oprettet endnu. Kør scraperen uden --db-stats først.")
        return

    stats = get_stats()
    print(f"\n--- Overordnet statistik ---")
    print(f"Artikler i alt:             {stats.get('total', 0)}")
    print(f"Artikler fundet i dag:      {stats.get('i_dag', 0)}")
    print(f"Artikler seneste 7 dage:    {stats.get('seneste_7_dage', 0)}")

    print(f"\n--- Artikler pr. medie ---")
    for medie, antal in get_count_by_source():
        print(f"  {medie:<35} {antal}")

    print(f"\n--- Seneste 10 artikler ---")
    for a in get_recent_articles(limit=10):
        dato = (a.get("udgivet_kl") or "")[:10]
        score = str(a.get("story_score") or "").rjust(3)
        medie = (a.get("medie") or "")[:20]
        rubrik = (a.get("rubrik") or "")[:60]
        print(f"  {dato}  score={score}  {medie:<20}  {rubrik}")

    dupes = get_duplicates()

    url_dupes = dupes.get("url", [])
    print(f"\n--- Dubletter på URL: {len(url_dupes)} ---")
    for url, antal in url_dupes[:10]:
        print(f"  ({antal}x) {url[:80]}")

    mr_dupes = dupes.get("medie_rubrik", [])
    print(f"\n--- Dubletter på medie + rubrik: {len(mr_dupes)} ---")
    for medie, rubrik, antal in mr_dupes[:10]:
        print(f"  ({antal}x) {medie}: {rubrik[:60]}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debatstof-scraper")
    parser.add_argument("--db-stats", action="store_true", help="Vis database-statistik og stop. Kører ingen scraping.")
    parser.add_argument("--dry-run", action="store_true", help="Skriv ikke til Google Sheet")
    parser.add_argument("--limit-per-source", type=int, default=30, help="Maks antal URL'er pr. kilde i denne kørsel")
    parser.add_argument("--only", type=str, default=None, help="Test kun én kilde, fx Altinget")
    parser.add_argument("--min-section-results", type=int, default=5, help="Hvis debatforsiden giver færre fund end dette, prøves sitemap som backup")
    parser.add_argument("--show-urls", action="store_true", help="Vis URL under hver rubrik")
    parser.add_argument("--csv", type=str, default=None, help="Skriv resultatet til en CSV-fil, fx output/debatstof.csv")
    parser.add_argument("--json", type=str, default=DEFAULT_JSON_OUTPUT, help="Skriv resultatet til en JSON-fil, fx output/latest/articles.json")
    parser.add_argument("--new-json", type=str, default=DEFAULT_NEW_JSON_OUTPUT, help="Skriv nye artikler til JSON, fx output/latest/new_articles.json")
    args = parser.parse_args()

    if args.db_stats:
        try:
            load_env_file()
        except RuntimeError:
            pass  # Ingen .env — get_db_path() bruger fallback-stien
        print_db_stats()
    else:
        run(
            dry_run=args.dry_run,
            limit_per_source=args.limit_per_source,
            only=args.only,
            min_section_results=args.min_section_results,
            show_urls=args.show_urls,
            csv_output=args.csv,
            json_output=args.json,
            new_json_output=args.new_json,
        )
