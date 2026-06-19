"""
Genscorer alle artikler i debatstof.db med det aktuelle keyword-sæt.

Opdaterer pr. artikel:
  - mikroemner  (detect_micro_topics)
  - temaer      (themes_as_text via classify_themes)
  - story_score (calculate_story_potential)
  - jp_signaler (calculate_story_potential)

Kør med: python rescore_db.py
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.database import get_db_path, get_feedback_bonus_by_topic
from core.models import DebateItem
from run_scraper import detect_micro_topics, calculate_story_potential, classify_themes

UPDATE_SQL = """
UPDATE artikler
SET
    mikroemner  = ?,
    temaer      = ?,
    story_score = ?,
    jp_signaler = ?
WHERE artikel_id = ?
"""


def rescore_all() -> None:
    db_path = get_db_path()

    if not db_path.exists():
        print(f"Fandt ikke databasen: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT artikel_id, rubrik, manchet, forfatter, medie, medietype, region, debat_type FROM artikler"
    ).fetchall()

    total = len(rows)
    topic_bonus = get_feedback_bonus_by_topic()
    if topic_bonus:
        print(f"Læringsbonus aktiv for {len(topic_bonus)} mikroemner: {topic_bonus}")
    print(f"Fandt {total} artikler — starter rescoring ...")

    updates = []
    for row in rows:
        item = DebateItem(
            discovered_at="",
            published_at="",
            media=row["medie"] or "",
            media_type=row["medietype"] or "",
            region=row["region"] or "",
            title=row["rubrik"] or "",
            deck=row["manchet"] or "",
            author=row["forfatter"] or "",
            debate_type=row["debat_type"] or "",
            url="",
            source_method="",
            status="",
        )

        micro = detect_micro_topics(item.title, item.deck)
        temaer = classify_themes(item.title, item.deck)
        score, signals = calculate_story_potential(item, topic_bonus=topic_bonus)

        updates.append((
            json.dumps([t["mikroemne"] for t in micro], ensure_ascii=False),
            json.dumps(temaer, ensure_ascii=False),
            score,
            json.dumps(signals, ensure_ascii=False),
            row["artikel_id"],
        ))

    with conn:
        conn.executemany(UPDATE_SQL, updates)

    conn.close()
    print(f"Opdaterede {total} artikler i {db_path.name}")


if __name__ == "__main__":
    rescore_all()
