from pathlib import Path
import sys
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, render_template, request, redirect
import os
from db.database import get_db_path, save_feedback_to_db, get_all_feedback_from_db


from core.settings import DATA_DIR
from app.security import protect_app

BASE_DIR = PROJECT_ROOT
DATA_FILE = DATA_DIR / "articles.json"
FEEDBACK_FILE = DATA_DIR / "feedback.json"

app = Flask(__name__)
protect_app(app)

from app.rss import register as register_rss
register_rss(app)


MICRO_TOPIC_LABELS = {
    "frit_valg_og_privatisering":    "Frit valg og privatisering",
    "ældreplejen_og_kommuner":        "Ældrepleje og kommuner",
    "psykiatri_og_mental_sundhed":    "Psykiatri og mental sundhed",
    "unges_trivsel_og_skærme":        "Unges trivsel og skærme",
    "drikkevand_og_landbrug":         "Drikkevand og landbrug",
    "ai_og_digitalisering":           "AI og digitalisering",
    "arbejdsmarked_og_uddannelse":    "Arbejdsmarked og uddannelse",
    "retssikkerhed_og_udvisning":     "Retssikkerhed og udvisning",
    "fagbevægelse_og_medlemskrise":   "Fagbevægelse og medlemskrise",
    "grønland_og_rigsfællesskab":     "Grønland og rigsfællesskab",
    "ulvedebat":                       "Ulvedebat",
    "arv_og_arveafgift":              "Arv og arveafgift",
    "land_og_by":                      "Land og by",
    "folkeskolen_og_faglighed":       "Folkeskolen og faglighed",
    "boligkrise_og_lokalplaner":      "Boligkrise og lokalplaner",
    "energi_og_forsyning":            "Energi og forsyning",
    "klima_og_bæredygtighed":         "Klima og bæredygtighed",
    "asbestforbud_og_boligejere":     "Asbestforbud og boligejere",
    "lobbyisme_og_demokrati":         "Lobbyisme og demokrati",
    "integration_og_danskhed":        "Integration og danskhed",
    "erhvervsliv_og_iværksættere":    "Erhvervsliv og iværksættere",
    "skat_og_afgifter":               "Skat og afgifter",
    "håndtryk_ligestilling_og_religion": "Håndtryk, ligestilling og religion",
    "sundhedsvæsen_og_patientrettigheder": "Sundhedsvæsen og patientrettigheder",
    "trafik_og_infrastruktur":        "Trafik og infrastruktur",
    "udenrigspolitik_og_sikkerhed":   "Udenrigspolitik og sikkerhed",
    "socialpolitik_og_fattigdom":     "Socialpolitik og fattigdom",
    "ytringsfrihed_og_medier":        "Ytringsfrihed og medier",
    "opdragelse_og_forældreskab":     "Opdragelse og forældreskab",
}


def load_feedback():
    if not FEEDBACK_FILE.exists():
        return {}

    with FEEDBACK_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_feedback(data):
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)

    with FEEDBACK_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def human_micro_label(value: str) -> str:
    return MICRO_TOPIC_LABELS.get(
        str(value),
        str(value).replace("_", " ").capitalize()
    )


def load_data():
    if not DATA_FILE.exists():
        return {
            "generated_at": "",
            "count": 0,
            "sources": [],
            "articles": [],
            "error": f"Fandt ikke datafilen: {DATA_FILE}",
        }

    with DATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_data_from_db():
    import sqlite3
    from datetime import date, timedelta

    db_path = get_db_path()

    if not db_path.exists():
        return None

    week_ago = (date.today() - timedelta(days=7)).isoformat()

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM artikler WHERE fundet_kl >= ? ORDER BY fundet_kl DESC",
            (week_ago,),
        ).fetchall()
        conn.close()
    except Exception as exc:
        print(f"[WARN] SQLite-læsning fejlede: {exc}")
        return None

    articles = []
    for row in rows:
        d = dict(row)
        d["temaer"]                         = json.loads(d.get("temaer")      or "[]")
        d["mikroemner"]                     = json.loads(d.get("mikroemner")   or "[]")
        d["entiteter"]                      = json.loads(d.get("entiteter")    or "{}")
        d["historiepotentiale_score"]       = d.pop("story_score", 0)
        d["historiepotentiale_begrundelse"] = json.loads(d.pop("jp_signaler")  or "[]")
        articles.append(d)

    return {
        "generated_at": articles[0]["fundet_kl"][:10] if articles else "",
        "count": len(articles),
        "sources": [],
        "articles": articles,
    }


def score_level(score):
    try:
        score = int(score)
    except Exception:
        score = 0

    if score >= 80:
        return "høj"
    if score >= 60:
        return "interessant"
    if score >= 40:
        return "overvåg"
    return "lav"


def micro_topics_to_display(value):
    if not value:
        return []

    topics = []

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                raw = item.get("mikroemne")
            else:
                raw = item

            if raw:
                topics.append({
                    "raw": str(raw),
                    "label": human_micro_label(str(raw)),
                })

    return topics



def build_feedback_signals(raw_articles, feedback):
    """
    Beregner simple feedbacksignaler pr. debatspor.

    Regler:
    - interessant i samme debatspor giver stærkt positivt signal
    - åbnet i samme debatspor giver svagt positivt signal
    - mange ignorerede artikler i samme debatspor dæmper lidt
    """
    topic_stats = {}

    for article in raw_articles:
        url = article.get("url", "")
        item_feedback = feedback.get(url, {})
        topics = micro_topics_to_display(article.get("mikroemner"))

        for topic in topics:
            raw = topic["raw"]

            if raw not in topic_stats:
                topic_stats[raw] = {
                    "label": topic["label"],
                    "total": 0,
                    "opened": 0,
                    "interesting": 0,
                }

            topic_stats[raw]["total"] += 1

            if item_feedback.get("opened"):
                topic_stats[raw]["opened"] += 1

            if item_feedback.get("interesting"):
                topic_stats[raw]["interesting"] += 1

    signals = {}

    for raw, stats in topic_stats.items():
        score = 0
        reasons = []

        if stats["interesting"]:
            bonus = min(stats["interesting"] * 10, 25)
            score += bonus
            reasons.append(f"{stats['interesting']} interessant i samme debatspor")

        if stats["opened"]:
            bonus = min(stats["opened"] * 3, 12)
            score += bonus
            reasons.append(f"{stats['opened']} åbnet i samme debatspor")

        ignored = stats["total"] - stats["opened"]
        if stats["total"] >= 3 and ignored == stats["total"]:
            score -= 5
            reasons.append("debatspor er hidtil ignoreret")

        signals[raw] = {
            "score": score,
            "reasons": reasons,
            "stats": stats,
        }

    return signals


def feedback_signal_for_article(article, feedback_signals):
    """
    Samler feedbacksignal for en artikel ud fra dens debatspor.
    """
    topics = micro_topics_to_display(article.get("mikroemner"))
    total = 0
    reasons = []

    for topic in topics:
        raw = topic["raw"]
        signal = feedback_signals.get(raw)

        if not signal:
            continue

        total += signal["score"]
        reasons.extend(signal["reasons"])

    # Feedback skal justere, ikke overtage.
    total = max(min(total, 25), -10)

    # Fjern dubletter
    unique_reasons = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    return total, unique_reasons


DANISH_MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun",
                  "jul", "aug", "sep", "okt", "nov", "dec"]

DANISH_MONTH_NAMES = {
    "januar": 1, "februar": 2, "marts": 3, "april": 4,
    "maj": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def format_pub_dato(value: str) -> str:
    if not value or not value.strip():
        return ""
    value = value.strip()

    # ISO-format: "2026-06-17T..." eller "2026-06-17"
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        try:
            day = int(value[8:10])
            month = int(value[5:7])
            year = int(value[0:4])
            return f"{day}/{month}/{year}"
        except Exception:
            pass

    # Dansk fritekst: "17. juni 2026, 15:01"
    try:
        parts = value.split()
        day = int(parts[0].rstrip("."))
        month = DANISH_MONTH_NAMES.get(parts[1].lower())
        year = int(parts[2].rstrip(",")) if len(parts) > 2 else ""
        if month:
            return f"{day}/{month}/{year}" if year else f"{day}/{month}"
    except Exception:
        pass

    return ""


def prepare_article(article, feedback, feedback_signals):
    score = article.get("historiepotentiale_score") or 0
    url = article.get("url", "")

    item_feedback = feedback.get(url, {})

    prepared = dict(article)
    feedback_bonus, feedback_reasons = feedback_signal_for_article(article, feedback_signals)
    adjusted_score = max(min(int(score or 0) + feedback_bonus, 100), 0)

    prepared["base_score"] = int(score or 0)
    prepared["feedback_signal_score"] = feedback_bonus
    prepared["score_adjusted"] = adjusted_score
    prepared["score_level"] = score_level(adjusted_score)
    prepared["feedback_reasons"] = feedback_reasons
    prepared["micro_topics_display"] = micro_topics_to_display(article.get("mikroemner"))
    prepared["opened"] = item_feedback.get("opened", False)
    prepared["interesting"] = item_feedback.get("interesting", False)
    prepared["pub_dato"] = format_pub_dato(article.get("udgivet_kl") or "")

    return prepared


def collect_micro_options(articles):
    options = {}

    for article in articles:
        for topic in article.get("micro_topics_display") or []:
            options[topic["raw"]] = topic["label"]

    return sorted(options.items(), key=lambda item: item[1])


ALLE_MEDIER = [
    "Altinget", "Information", "Politiken", "Berlingske",
    "Kristeligt Dagblad", "Avisen Danmark", "Nordjyske",
    "Århus Stiftstidende", "Fyens Stiftstidende",
    "JydskeVestkysten", "Viborg Folkeblad", "Sjællandske Nyheder",
]


def filter_articles(articles, micro="", level="", interesting_only=False, medie_filter=""):
    micro = (micro or "").strip()
    medie_filter = (medie_filter or "").strip()

    filtered = []

    for article in articles:
        raw_micro_topics = [t["raw"] for t in article.get("micro_topics_display") or []]

        if micro and micro not in raw_micro_topics:
            continue

        if level == "prioriteret":
            if article.get("score_adjusted", 0) <= 50:
                continue
        elif level and level != article.get("score_level"):
            continue

        if interesting_only and not article.get("interesting"):
            continue

        if medie_filter and article.get("medie") != medie_filter:
            continue

        filtered.append(article)

    return filtered


def _shared_template_vars(articles, micro, level, interesting_only, medie_filter):
    """Variabler der bruges i både index og base-templaten."""
    micro_options = collect_micro_options(articles)
    return dict(
        micro_options=micro_options,
        alle_medier=ALLE_MEDIER,
        micro=micro,
        level=level,
        interesting_only=interesting_only,
        medie_filter=medie_filter,
    )


def _load_articles():
    data = load_data_from_db()
    if data is None:
        print("[WARN] SQLite utilgængelig — falder tilbage til articles.json")
        data = load_data()
    feedback = get_all_feedback_from_db()
    if not feedback:
        feedback = load_feedback()

    raw_articles = data.get("articles", [])
    feedback_signals = build_feedback_signals(raw_articles, feedback)
    articles = [prepare_article(a, feedback, feedback_signals) for a in raw_articles]
    return data, articles


@app.route("/")
@app.route("/arkiv")
def index():
    archive = request.path == "/arkiv"
    data, articles = _load_all_articles() if archive else _load_articles()

    micro           = request.args.get("micro", "")
    level           = request.args.get("level", "")
    interesting_only = request.args.get("interesting", "") == "1"
    medie_filter    = request.args.get("medie", "")
    sort_dir        = request.args.get("sort", "desc")
    sort_by         = request.args.get("sort_by", "score")

    filtered = filter_articles(
        articles,
        micro=micro,
        level=level,
        interesting_only=interesting_only,
        medie_filter=medie_filter,
    )
    if sort_by == "dato":
        filtered.sort(key=lambda a: a.get("fundet_kl") or "", reverse=(sort_dir != "asc"))
    else:
        filtered.sort(key=lambda a: int(a.get("score_adjusted") or 0), reverse=(sort_dir != "asc"))

    # Bestem aktivt navigationspunkt
    if interesting_only:
        nav_active = "interessante"
    elif level == "prioriteret":
        nav_active = "prioriterede"
    elif medie_filter:
        nav_active = "medier"
    elif micro:
        nav_active = "debatspor"
    else:
        nav_active = "overblik"

    if archive:
        nav_active = "arkiv"
    shared = _shared_template_vars(articles, micro, level, interesting_only, medie_filter)
    page = max(1, request.args.get("page", 1, type=int))
    pages = max(1, (len(filtered) + 99) // 100) if archive else 1
    page = min(page, pages)
    if archive:
        filtered = filtered[(page - 1) * 100:page * 100]

    return render_template(
        "index.html",
        data=data,
        articles=filtered,
        total_count=len(articles),
        nav_active=nav_active,
        sort_dir=sort_dir,
        sort_by=sort_by,
        page=page,
        pages=pages,
        **shared,
    )


def _load_all_articles():
    """Loader ALLE artikler fra DB uden datobegrænsning til Topscorere-visningen."""
    import sqlite3
    db_path = get_db_path()
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM artikler ORDER BY fundet_kl DESC"
            ).fetchall()
            conn.close()
            articles_raw = []
            for row in rows:
                d = dict(row)
                d["temaer"]                         = json.loads(d.get("temaer")    or "[]")
                d["mikroemner"]                     = json.loads(d.get("mikroemner") or "[]")
                d["entiteter"]                      = json.loads(d.get("entiteter")  or "{}")
                d["historiepotentiale_score"]       = d.pop("story_score", 0)
                d["historiepotentiale_begrundelse"] = json.loads(d.pop("jp_signaler") or "[]")
                articles_raw.append(d)
            data = {
                "generated_at": articles_raw[0]["fundet_kl"][:10] if articles_raw else "",
                "count": len(articles_raw),
                "sources": [],
                "articles": articles_raw,
            }
        except Exception as exc:
            print(f"[WARN] SQLite-læsning fejlede: {exc}")
            data = load_data()
    else:
        data = load_data()
    feedback = get_all_feedback_from_db()
    if not feedback:
        feedback = load_feedback()
    raw_articles = data.get("articles", [])
    feedback_signals = build_feedback_signals(raw_articles, feedback)
    articles = [prepare_article(a, feedback, feedback_signals) for a in raw_articles]
    return data, articles


@app.route("/topscorere")
def topscorere():
    data, articles = _load_all_articles()
    sort_dir = request.args.get("sort", "desc")
    sort_by  = request.args.get("sort_by", "score")
    filtered = [a for a in articles if (a.get("score_adjusted") or 0) > 60]
    if sort_by == "dato":
        filtered.sort(key=lambda a: a.get("fundet_kl") or "", reverse=(sort_dir != "asc"))
    else:
        filtered.sort(key=lambda a: int(a.get("score_adjusted") or 0), reverse=(sort_dir != "asc"))
    shared = _shared_template_vars(articles, "", "", False, "")
    return render_template(
        "index.html",
        data=data,
        articles=filtered,
        total_count=len(articles),
        nav_active="topscorere",
        sort_dir=sort_dir,
        sort_by=sort_by,
        **shared,
    )


@app.route("/statistik")
def statistik():
    from db.database import get_stats, get_count_by_source, get_recent_korsler
    _, articles = _load_articles()
    shared = _shared_template_vars(articles, "", "", False, "")
    return render_template(
        "statistik.html",
        stats=get_stats(),
        count_by_source=get_count_by_source(),
        recent_korsler=get_recent_korsler(),
        nav_active="statistik",
        **shared,
    )


@app.route("/open")
def mark_open():
    url = request.args.get("url", "")

    feedback = {**load_feedback(), **get_all_feedback_from_db()}

    item = feedback.get(url, {})
    item["opened"] = True

    if item.get("interesting"):
        item["feedback_score"] = "2"
        item["feedback_label"] = "interessant"
    else:
        item["feedback_score"] = "1"
        item["feedback_label"] = "åbnet"

    feedback[url] = item
    save_feedback(feedback)
    save_feedback_to_db(
        url=url,
        interesting=int(bool(item.get("interesting", False))),
        opened=int(bool(item.get("opened", False))),
        feedback_score=int(item.get("feedback_score") or 0),
        feedback_label=item.get("feedback_label") or "",
    )

    return redirect(url)


@app.route("/interesting", methods=["POST"])
def mark_interesting():
    url = request.form.get("url", "")

    feedback = {**load_feedback(), **get_all_feedback_from_db()}

    item = feedback.get(url, {})
    item["interesting"] = not item.get("interesting", False)

    if item["interesting"]:
        item["opened"] = True
        item["feedback_score"] = "2"
        item["feedback_label"] = "interessant"
    else:
        if item.get("opened"):
            item["feedback_score"] = "1"
            item["feedback_label"] = "åbnet"
        else:
            item["feedback_score"] = "0"
            item["feedback_label"] = "ikke_åbnet"

    feedback[url] = item
    save_feedback(feedback)
    save_feedback_to_db(
        url=url,
        interesting=int(bool(item.get("interesting", False))),
        opened=int(bool(item.get("opened", False))),
        feedback_score=int(item.get("feedback_score") or 0),
        feedback_label=item.get("feedback_label") or "",
    )

    target = request.form.get("return_to", "/")
    if not (target == "/arkiv" or target.startswith("/arkiv?")):
        target = "/"
    return redirect(target)


# A short-lived form token protects database uploads, including older browsers.
import secrets
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
_import_tokens = URLSafeTimedSerializer(secrets.token_hex(32), salt="database-import")


@app.route("/import", methods=["GET", "POST"])
def import_old_database():
    import sqlite3
    import tempfile
    from flask import abort
    from db.import_database import import_database
    request.max_content_length = 32 * 1024 * 1024
    result = None
    error = None
    if request.method == "POST":
        try:
            _import_tokens.loads(request.form.get("token", ""), max_age=3600)
        except (BadSignature, SignatureExpired):
            abort(400, "Formularen er udløbet. Åbn importsiden igen.")
        upload = request.files.get("database")
        if upload is None or not upload.filename:
            error = "Vælg din gamle databasefil først."
        else:
            try:
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "import.db"
                    upload.save(path)
                    result = import_database(path)
            except ValueError as exc:
                error = str(exc)
            except (OSError, sqlite3.DatabaseError):
                app.logger.exception("Databaseimport fejlede")
                error = "Importen mislykkedes. Dine eksisterende data er bevaret. Se serverens log."
    shared = _shared_template_vars([], "", "", False, "")
    return render_template("import.html", nav_active="import", result=result, error=error,
                           token=_import_tokens.dumps("upload"), **shared), (400 if error else 200)


if __name__ == "__main__":
    app.run(debug=True, port=5057)
