"""
Information scraper.

Currently uses the generic frontpage scraper.
This file exists so Information has its own place in the new structure.
"""

from .generic_frontpage import scrape_generic_frontpage_media


def scrape_information_direct(client, source, show_urls=False, limit=None, helpers=None):
    return scrape_generic_frontpage_media(
        client,
        source,
        show_urls=show_urls,
        limit=limit,
        helpers=helpers,
    )
