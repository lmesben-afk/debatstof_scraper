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
    temaer, mikroemner, entiteter, jp_signaler, story_score, status, kørsel_id
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(artikel_id) DO UPDATE SET
    udgivet_kl  = COALESCE(NULLIF(excluded.udgivet_kl,  ''), udgivet_kl),
    rubrik      = COALESCE(NULLIF(excluded.rubrik,      ''), rubrik),
    manchet     = COALESCE(NULLIF(excluded.manchet,     ''), manchet),
    forfatter   = COALESCE(NULLIF(excluded.forfatter,   ''), forfatter),
    debat_type  = excluded.debat_type,
    fundet_via  = excluded.fundet_via,
    temaer      = excluded.temaer,
    mikroemner  = COALESCE(NULLIF(excluded.mikroemner, '[]'), mikroemner),
    entiteter   = excluded.entiteter,
    jp_signaler = excluded.jp_signaler,
    story_score = excluded.story_score,
    status      = excluded.status,
    kørsel_id   = excluded.kørsel_id;
"""


CREATE_FEEDBACK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS feedback (
    url             TEXT PRIMARY KEY,
    interesting     INTEGER NOT NULL DEFAULT 0,
    opened          INTEGER NOT NULL DEFAULT 0,
    feedback_score  INTEGER NOT NULL DEFAULT 0,
    feedback_label  TEXT NOT NULL DEFAULT '',
    opdateret_kl    TEXT NOT NULL
);
"""

CREATE_KORSELSLOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS korselslog (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    korsel_tidspunkt TEXT NOT NULL,
    status           TEXT,
    fundne_artikler  INTEGER,
    nye_artikler     INTEGER,
    dubletter        INTEGER,
    fejl             TEXT
);
"""


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Tilføjer nye kolonner til eksisterende databaser uden at slette data."""
    try:
        conn.execute("ALTER TABLE artikler ADD COLUMN mikroemner TEXT")
    except sqlite3.OperationalError:
        pass  # Kolonnen eksisterer allerede
    conn.commit()


def _ensure_feedback_table(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_FEEDBACK_TABLE_SQL)
    conn.commit()


def _ensure_korselslog_table(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_KORSELSLOG_TABLE_SQL)
    conn.commit()


def log_korsel(
    status: str,
    fundne_artikler: int,
    nye_artikler: int,
    dubletter: int,
    fejl: str = "",
) -> None:
    import datetime as dt
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_korselslog_table(conn)
            conn.execute(
                """
                INSERT INTO korselslog
                    (korsel_tidspunkt, status, fundne_artikler, nye_artikler, dubletter, fejl)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                    status,
                    fundne_artikler,
                    nye_artikler,
                    dubletter,
                    fejl or "",
                ),
            )
    except Exception as exc:
        print(f"[WARN] log_korsel fejlede: {exc}")


def save_feedback_to_db(
    url: str,
    interesting: int,
    opened: int,
    feedback_score: int,
    feedback_label: str,
) -> None:
    import datetime as dt
    db_path = get_db_path()
    if not db_path.exists():
        return
    try:
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_feedback_table(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO feedback
                    (url, interesting, opened, feedback_score, feedback_label, opdateret_kl)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    int(interesting),
                    int(opened),
                    int(feedback_score),
                    feedback_label or "",
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                ),
            )
    except Exception as exc:
        print(f"[WARN] save_feedback_to_db fejlede: {exc}")


def get_feedback_bonus_by_topic() -> dict:
    """
    Tæller stjernemarkeringer pr. mikroemne og returnerer bonus pr. emne.

    Bonusskala: 1 stjerne → +5, 2 stjerner → +10, 3+ stjerner → +15 (maks).
    Returnerer {} hvis feedback-tabellen er tom eller ikke eksisterer.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return {}

    try:
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_feedback_table(conn)
            rows = conn.execute(
                """
                SELECT a.mikroemner
                FROM feedback f
                JOIN artikler a ON f.url = a.url
                WHERE f.interesting = 1
                  AND a.mikroemner IS NOT NULL
                  AND a.mikroemner != '[]'
                """
            ).fetchall()
    except Exception as exc:
        print(f"[WARN] get_feedback_bonus_by_topic fejlede: {exc}")
        return {}

    topic_counts: dict = {}
    for (mikroemner_json,) in rows:
        try:
            emner = json.loads(mikroemner_json or "[]")
        except Exception:
            continue
        for emne in emner:
            if emne:
                topic_counts[emne] = topic_counts.get(emne, 0) + 1

    bonuses = {}
    for emne, count in topic_counts.items():
        if count >= 3:
            bonuses[emne] = 15
        elif count == 2:
            bonuses[emne] = 10
        else:
            bonuses[emne] = 5

    return bonuses


def get_all_feedback_from_db() -> dict:
    """
    Returnerer feedback-dict med url som nøgle — samme format som load_feedback().

    Kører automatisk migration fra feedback.json første gang tabellen er tom.
    """
    import datetime as dt
    from pathlib import Path as _Path

    db_path = get_db_path()
    if not db_path.exists():
        return {}

    try:
        with sqlite3.connect(str(db_path)) as conn:
            _ensure_feedback_table(conn)
            rows = conn.execute(
                "SELECT url, interesting, opened, feedback_score, feedback_label FROM feedback"
            ).fetchall()
    except Exception as exc:
        print(f"[WARN] get_all_feedback_from_db fejlede: {exc}")
        return {}

    if rows:
        return {
            row[0]: {
                "interesting": bool(row[1]),
                "opened": bool(row[2]),
                "feedback_score": str(row[3]),
                "feedback_label": row[4],
            }
            for row in rows
        }

    # Tabel er tom — forsøg migration fra feedback.json
    feedback_json = (
        _Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus"
              r"\Jyllands-Posten\Scrapere\Fælles-data") / "feedback.json"
    )
    if not feedback_json.exists():
        return {}

    try:
        import json as _json
        data = _json.loads(feedback_json.read_text(encoding="utf-8"))
        migrated = 0
        for url, item in data.items():
            save_feedback_to_db(
                url=url,
                interesting=int(bool(item.get("interesting", False))),
                opened=int(bool(item.get("opened", False))),
                feedback_score=int(item.get("feedback_score") or 0),
                feedback_label=item.get("feedback_label") or "",
            )
            migrated += 1
        if migrated:
            print(f"[INFO] Migrerede {migrated} feedback-poster fra feedback.json til SQLite")
        return data
    except Exception as exc:
        print(f"[WARN] Migration fra feedback.json fejlede: {exc}")
        return {}


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
            json.dumps(
                [t["mikroemne"] for t in (d.get("mikroemner") or [])],
                ensure_ascii=False,
            ),
            json.dumps(d.get("entiteter") or {}, ensure_ascii=False),
            json.dumps(d.get("historiepotentiale_begrundelse") or [], ensure_ascii=False),
            d.get("historiepotentiale_score"),
            d.get("status", "") or "",
            kørsel_id,
        ))

    if not rows:
        return

    with sqlite3.connect(db_path) as conn:
        conn.execute(CREATE_TABLE_SQL)
        _migrate_schema(conn)
        conn.executemany(UPSERT_SQL, rows)
        conn.commit()

    print(f"Skrev {len(rows)} poster til SQLite: {db_path}")


# ---------------------------------------------------------------------------
# Læsefunktioner — skriver aldrig til databasen
# ---------------------------------------------------------------------------

def _connect_readonly() -> sqlite3.Connection:
    """Åbner databasen i read-only tilstand via URI."""
    db_path = get_db_path()
    uri = db_path.as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def get_stats() -> dict:
    """
    Returnerer overordnet statistik om databasens indhold.

    Returnerer en tom dict hvis databasen ikke eksisterer endnu.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return {}

    today = __import__("datetime").date.today().isoformat()
    week_ago = (__import__("datetime").date.today() - __import__("datetime").timedelta(days=7)).isoformat()

    with _connect_readonly() as conn:
        (total,) = conn.execute("SELECT COUNT(*) FROM artikler").fetchone()
        (i_dag,) = conn.execute(
            "SELECT COUNT(*) FROM artikler WHERE fundet_kl >= ?", (today,)
        ).fetchone()
        (seneste_7_dage,) = conn.execute(
            "SELECT COUNT(*) FROM artikler WHERE fundet_kl >= ?", (week_ago,)
        ).fetchone()

    return {
        "total": total,
        "i_dag": i_dag,
        "seneste_7_dage": seneste_7_dage,
    }


def get_count_by_source() -> list[tuple[str, int]]:
    """
    Returnerer antal artikler pr. medie, sorteret faldende.

    Returnerer tom liste hvis databasen ikke eksisterer.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return []

    with _connect_readonly() as conn:
        rows = conn.execute(
            "SELECT medie, COUNT(*) AS antal FROM artikler GROUP BY medie ORDER BY antal DESC"
        ).fetchall()

    return rows


def get_recent_articles(limit: int = 10) -> list[dict]:
    """
    Returnerer de seneste artikler sorteret efter fundet_kl faldende.

    Returnerer tom liste hvis databasen ikke eksisterer.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return []

    with _connect_readonly() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT udgivet_kl, medie, story_score, rubrik
            FROM artikler
            ORDER BY fundet_kl DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(r) for r in rows]


def get_recent_korsler(limit: int = 10) -> list[dict]:
    db_path = get_db_path()
    if not db_path.exists():
        return []

    try:
        with _connect_readonly() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT korsel_tidspunkt, status, fundne_artikler,
                       nye_artikler, dubletter, fejl
                FROM korselslog
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_duplicates() -> dict:
    """
    Finder mulige dubletter på URL og på medie+rubrik.

    Returnerer en dict med to lister: 'url' og 'medie_rubrik'.
    Returnerer tomme lister hvis databasen ikke eksisterer.
    """
    db_path = get_db_path()
    if not db_path.exists():
        return {"url": [], "medie_rubrik": []}

    with _connect_readonly() as conn:
        url_dupes = conn.execute(
            """
            SELECT url, COUNT(*) AS antal
            FROM artikler
            GROUP BY url
            HAVING antal > 1
            ORDER BY antal DESC
            """
        ).fetchall()

        medie_rubrik_dupes = conn.execute(
            """
            SELECT medie, rubrik, COUNT(*) AS antal
            FROM artikler
            GROUP BY medie, rubrik
            HAVING antal > 1
            ORDER BY antal DESC
            """
        ).fetchall()

    return {
        "url": url_dupes,
        "medie_rubrik": medie_rubrik_dupes,
    }
