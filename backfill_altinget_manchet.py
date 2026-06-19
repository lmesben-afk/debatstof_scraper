"""
Henter manchet (og:description) for Altinget-artikler med tom manchet
og opdaterer databasen.

Kør med: python backfill_altinget_manchet.py
"""

import sqlite3
import sys
import time
import io

import httpx
from bs4 import BeautifulSoup
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from db.database import get_db_path

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_manchet(client: httpx.Client, url: str) -> str:
    try:
        r = client.get(url, headers=HEADERS, follow_redirects=True, timeout=15)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")
        for attr in [("property", "og:description"), ("name", "description")]:
            m = soup.find("meta", attrs={attr[0]: attr[1]})
            if m and m.get("content", "").strip():
                return m["content"].strip()
    except Exception as exc:
        print(f"  [FEJL] {url}: {exc}")
    return ""


def backfill():
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT artikel_id, url, rubrik
        FROM artikler
        WHERE medie = 'Altinget'
          AND (manchet IS NULL OR manchet = '')
          AND url != ''
        ORDER BY fundet_kl DESC
        """
    ).fetchall()

    total = len(rows)
    print(f"Fandt {total} Altinget-artikler uden manchet — starter backfill ...")

    updated = 0
    skipped = 0

    with httpx.Client() as client:
        for i, row in enumerate(rows, 1):
            manchet = fetch_manchet(client, row["url"])
            if manchet:
                conn.execute(
                    "UPDATE artikler SET manchet = ? WHERE artikel_id = ?",
                    (manchet, row["artikel_id"]),
                )
                conn.commit()
                updated += 1
                print(f"  [{i}/{total}] ✓ {row['rubrik'][:60]}")
            else:
                skipped += 1
                print(f"  [{i}/{total}] – ingen manchet: {row['rubrik'][:60]}")

            time.sleep(0.3)

    conn.close()
    print(f"\nFærdig: {updated} opdateret, {skipped} uden manchet.")

    if updated:
        print("Kører rescore ...")
        from rescore_db import rescore_all
        rescore_all()


if __name__ == "__main__":
    backfill()
