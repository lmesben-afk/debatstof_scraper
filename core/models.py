"""
Fælles datamodeller for debatstof-scraperen.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class Source:
    name: str
    media_type: str
    region: str
    base_url: str
    section_urls: List[str]
    sitemap_urls: List[str]
    article_path_markers: List[str]
    strict_sitemap_sections: List[str]
    allowed_path_segments: List[str]
    title_prefixes: List[str]
    exclude_path_segments: List[str]
    exclude_title_contains: List[str]

@dataclass
class DebateItem:
    discovered_at: str
    published_at: str
    media: str
    media_type: str
    region: str
    title: str
    deck: str
    author: str
    debate_type: str
    url: str
    source_method: str
    status: str
