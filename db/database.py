"""
SQLite-output til debatstof-scraperen.

Gemmer alle artikler lokalt parallelt med Google Sheets.
Databasestien hentes fra .env (SQLITE_DB_PATH) med fallback til Fælles-data/debatstof.db.

Modtager en liste af dicts på samme format som item_to_app_dict() i run_scraper.py.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import List

FALLBACK_PATH = (
    Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Fælles-data")
    / "debatstof.db"
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS artikler (
    artikel_id      TEXT PRIMARY KEY,
    fundet_kl       TEXT,
    udgivet_kl      TEXT,
    medie           TEXT,
    medietype       TEXT,
    region          TEXT,
    rubrik          TEXT,
    manchet         TEXT,
    forfatter       TEXT,
    debat_type      TEXT,
    url             TEXT,
    fundet_via      TEXT,
    temaer          TEXT,
    entiteter       TEXT,
    jp_signaler     TEXT,
    story_score     INTEGER,
    status          TEXT,
    kørsel_id       TEXT
);
"""

UPSERT_SQL = """
INSERT INTO artikler (
    artikel_id, fundet_kl, udgivet_kl, medie, medietype, region,
    rubrik, manchet, forfatter, debat_type, url, fundet_via,
    temaer, entiteter, jp_signaler, story_score, status, kørsel_id
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(artikel_id) DO UPDATE SET
    udgivet_kl  = COALESCE(NULLIF(excluded.udgivet_kl,  ''), udgivet_kl),
    rubrik      = COALESCE(NULLIF(excluded.rubrik,      ''), rubrik),
    manchet     = COALESCE(NULLIF(excluded.manchet,     ''), manchet),
    forfatter   = COALESCE(NULLIF(excluded.forfatter,   ''), forfatter),
    debat_type  = excluded.debat_type,
    fundet_via  = excluded.fundet_via,
    temaer      = excluded.temaer,
    entiteter   = excluded.entiteter,
    jp_signaler = excluded.jp_signaler,
    story_score = excluded.story_score,
    status      = excluded.status,
    kørsel_id   = excluded.kørsel_id;
"""


def get_db_path() -> Path:
    env_val = os.environ.get("SQLITE_DB_PATH")
    return Path(env_val) if env_val else FALLBACK_PATH


def write_items_to_sqlite(items: List[dict], kørsel_id: str = "") -> None:
    """
    Gemmer eller opdaterer artikler i SQLite-databasen.

    Modtager en liste af dicts fra item_to_app_dict().
    Eksisterende rækker opdateres, men tomme værdier overskriver ikke gode data.
    Fejler funktionen, skal kalderen håndtere undtagelsen.
    """
    if not items:
        return

    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for d in items:
        artikel_id = d.get("artikel_id", "")
        if not artikel_id:
            continue

        rows.append((
            artikel_id,
            d.get("fundet_tidspunkt", "") or "",
            d.get("udgivelsestidspunkt", "") or "",
            d.get("medie", "") or "",
            d.get("medietype", "") or "",
            d.get("region", "") or "",
            d.get("rubrik", "") or "",
            d.get("manchet", "") or "",
            d.get("forfatter", "") or "",
            d.get("debat_type", "") or "",
            d.get("url", "") or "",
            d.get("fundet_via", "") or "",
            json.dumps(d.get("temaer") or [], ensure_ascii=False),
            json.dumps(d.get("entiteter") or [], ensure_ascii=False),
            json.dumps(d.get("historiepotentiale_begrundelse") or [], ensure_ascii=False),
            d.get("historiepotentiale_score"),
            d.get("status", "") or "",
            kørsel_id,
        ))

    if not rows:
        return

    with sqlite3.connect(db_path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.executemany(UPSERT_SQL, rows)
        conn.commit()

    print(f"Skrev {len(rows)} poster til SQLite: {db_path}")
