"""
Generic frontpage scraper wrapper for media that do not yet need a fully custom scraper.

Used for:
- Altinget
- Information

It delegates to the existing generic helper functions in run_scraper.py.
"""

from typing import List, Optional


def scrape_generic_frontpage_media(client, source, show_urls: bool = False, limit: Optional[int] = None, helpers=None) -> List:
    if helpers is None:
        raise RuntimeError("Generic media scraper mangler helpers")

    items = []
    kept = 0

    if not source.section_urls:
        return items

    section_urls = helpers["discover_urls_from_section_pages"](client, source)

    if limit:
        section_urls = section_urls[:limit]

    print(f"Fundet {len(section_urls)} artikel-lignende URL'er via debatforside")

    for url in section_urls:
        item = helpers["extract_article_metadata"](client, source, url, "section_page")
        if item:
            items.append(item)
            kept += 1
            print(f"- {item.media}: {item.title}" + (f"\\n  {item.url}" if show_urls else ""))

    print(f"Beholdt {kept} poster fra debatforside")
    return items
