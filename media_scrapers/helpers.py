"""
Helper bundle for media scrapers.

Media scrapers receive a helpers dictionary instead of importing directly
from run_scraper.py. This keeps the media files decoupled while we refactor.
"""


def build_helpers(context: dict) -> dict:
    """
    Build the helpers dictionary used by media_scrapers/*.py.

    The context is supplied by run_scraper.py because most core functions
    still live there during the refactor.
    """
    return {
        "DebateItem": context["DebateItem"],
        "fetch_text": context["fetch_text"],
        "clean_text": context["clean_text"],
        "clean_url": context["clean_url"],
        "canonicalize_url_for_dedupe": context["canonicalize_url_for_dedupe"],
        "same_domain_or_subdomain": context["same_domain_or_subdomain"],
        "extract_article_metadata": context["extract_article_metadata"],
        "normalize_label_text": context["normalize_label_text"],
        "label_from_rules": context["label_from_rules"],
        "media_rule_segments": context["media_rule_segments"],
        "media_rule": context["media_rule"],
        "politiken_card_label": context["politiken_card_label"],
        "politiken_label_to_debate_type": context["politiken_label_to_debate_type"],
        "BERLINGSKE_ALLOWED_LABEL_PATTERNS": context["BERLINGSKE_ALLOWED_LABEL_PATTERNS"],
        "discover_urls_from_section_pages": context["discover_urls_from_section_pages"],
        "enrich_missing_deck_from_article_page": context["enrich_missing_deck_from_article_page"],
        "re": context["re"],
    }
