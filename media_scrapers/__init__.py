"""
Media scraper registry.

This module knows which media source should use which scraper.
run_scraper.py asks this registry instead of keeping the list itself.
"""

from .politiken import scrape_politiken_direct
from .berlingske import scrape_berlingske_direct
from .nordjyske import scrape_nordjyske_direct
from .altinget import scrape_altinget_direct
from .information import scrape_information_direct
from .kristeligt_dagblad import scrape_kristeligt_dagblad_direct
from .avisen_danmark import scrape_avisen_danmark_direct
from .stiften import scrape_stiften_direct
from .fyens import scrape_fyens_direct
from .jydskevestkysten import scrape_jv_direct
from .viborg_folkeblad import scrape_viborg_direct
from .sjaellandske_nyheder import scrape_sn_direct


SCRAPER_REGISTRY = {
    "Politiken": scrape_politiken_direct,
    "Berlingske": scrape_berlingske_direct,
    "Nordjyske": scrape_nordjyske_direct,
    "Altinget": scrape_altinget_direct,
    "Information": scrape_information_direct,
    "Kristeligt Dagblad": scrape_kristeligt_dagblad_direct,
    "Avisen Danmark": scrape_avisen_danmark_direct,
    "Århus Stiftstidende": scrape_stiften_direct,
    "Fyens Stiftstidende": scrape_fyens_direct,
    "JydskeVestkysten": scrape_jv_direct,
    "Viborg Folkeblad": scrape_viborg_direct,
    "Sjællandske Nyheder": scrape_sn_direct,
}


def get_external_scraper(source_name: str):
    """
    Return the scraper function for a source name, if one exists.
    """
    return SCRAPER_REGISTRY.get(source_name)
