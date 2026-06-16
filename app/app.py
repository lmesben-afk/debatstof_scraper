from pathlib import Path
import json

from flask import Flask, render_template, request, redirect
import os
import gspread


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Fælles-data") / "articles.json"
FEEDBACK_FILE = Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Fælles-data") / "feedback.json"

app = Flask(__name__)

CONFIG_DIR = Path(r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Config-filer")


def load_env_file():
    env_path = CONFIG_DIR / ".env"

    if not env_path.exists():
        print(f"[WARN] Fandt ikke .env: {env_path}")
        return

    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def connect_sheet():
    load_env_file()

    sheet_name = os.getenv("GOOGLE_SHEET_NAME")
    credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE")

    if not sheet_name:
        print("[WARN] GOOGLE_SHEET_NAME mangler")
        return None

    if not credentials_file:
        credentials_path = CONFIG_DIR / "credentials.json"
    else:
        credentials_path = Path(credentials_file)
        if not credentials_path.is_absolute():
            credentials_path = CONFIG_DIR / credentials_file

    if not credentials_path.exists():
        print(f"[WARN] Fandt ikke credentials.json: {credentials_path}")
        return None

    gc = gspread.service_account(filename=str(credentials_path))
    spreadsheet = gc.open(sheet_name)
    return spreadsheet.sheet1


def extract_url_from_sheet_cell(value: str) -> str:
    value = str(value or "").strip()

    if value.upper().startswith("=HYPERLINK("):
        first_quote = value.find('"')
        second_quote = value.find('"', first_quote + 1)
        if first_quote != -1 and second_quote != -1:
            return value[first_quote + 1:second_quote]

    return value


def column_letter(index_zero_based: int) -> str:
    number = index_zero_based + 1
    letters = ""

    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters

    return letters


def update_feedback_in_sheet(url: str, score: str, label: str) -> None:
    """
    Skriver app-feedback direkte til Google Sheet.
    """
    try:
        ws = connect_sheet()
        if ws is None:
            return

        values = ws.get("A1:Z", value_render_option="FORMULA")
        if not values:
            return

        header = values[0]

        def col(name):
            try:
                return header.index(name)
            except ValueError:
                return -1

        url_col = col("url")
        score_col = col("feedback_score")
        label_col = col("feedback_label")

        if url_col == -1 or score_col == -1 or label_col == -1:
            print("[WARN] Mangler url/feedback_score/feedback_label i Google Sheet")
            return

        target_row_number = None

        for row_index, row in enumerate(values[1:], start=2):
            if len(row) <= url_col:
                continue

            sheet_url = extract_url_from_sheet_cell(row[url_col])

            if sheet_url == url:
                target_row_number = row_index
                break

        if not target_row_number:
            print("[WARN] Fandt ikke artiklen i Google Sheet")
            return

        score_cell = f"{column_letter(score_col)}{target_row_number}"
        label_cell = f"{column_letter(label_col)}{target_row_number}"

        ws.update(values=[[score]], range_name=score_cell)
        ws.update(values=[[label]], range_name=label_cell)

        print(f"Skrev feedback til Google Sheet: {score} / {label}")

    except Exception as exc:
        print(f"[WARN] Kunne ikke skrive feedback til Google Sheet: {exc}")




MICRO_TOPIC_LABELS = {
    "frit_valg_på_plejehjem": "Frit valg på plejehjem",
    "drikkevand_og_landbrug": "Drikkevand og landbrug",
    "håndtryk_ligestilling_og_religion": "Håndtryk, ligestilling og religion",
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

    env_val = os.environ.get("SQLITE_DB_PATH")
    db_path = Path(env_val) if env_val else Path(
        r"C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus"
        r"\Jyllands-Posten\Scrapere\Fælles-data\debatstof.db"
    )

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

    return prepared


def collect_micro_options(articles):
    options = {}

    for article in articles:
        for topic in article.get("micro_topics_display") or []:
            options[topic["raw"]] = topic["label"]

    return sorted(options.items(), key=lambda item: item[1])


def filter_articles(articles, micro="", level=""):
    micro = (micro or "").strip()
    level = (level or "").strip()

    filtered = []

    for article in articles:
        raw_micro_topics = [t["raw"] for t in article.get("micro_topics_display") or []]

        if micro and micro not in raw_micro_topics:
            continue

        if level and level != article.get("score_level"):
            continue

        filtered.append(article)

    return filtered


@app.route("/")
def index():
    data = load_data_from_db()
    if data is None:
        print("[WARN] SQLite utilgængelig — falder tilbage til articles.json")
        data = load_data()
    feedback = load_feedback()

    raw_articles = data.get("articles", [])
    feedback_signals = build_feedback_signals(raw_articles, feedback)
    articles = [prepare_article(a, feedback, feedback_signals) for a in raw_articles]

    micro = request.args.get("micro", "")
    level = request.args.get("level", "")

    micro_options = collect_micro_options(articles)
    filtered = filter_articles(articles, micro=micro, level=level)

    filtered.sort(
        key=lambda a: int(a.get("score_adjusted") or 0),
        reverse=True,
    )

    return render_template(
        "index.html",
        data=data,
        articles=filtered,
        total_count=len(articles),
        micro_options=micro_options,
        micro=micro,
        level=level,
    )


@app.route("/open")
def mark_open():
    url = request.args.get("url", "")

    feedback = load_feedback()

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
    update_feedback_in_sheet(url, item.get("feedback_score", "1"), item.get("feedback_label", "åbnet"))

    return redirect(url)


@app.route("/interesting", methods=["POST"])
def mark_interesting():
    url = request.form.get("url", "")

    feedback = load_feedback()

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
    update_feedback_in_sheet(url, item.get("feedback_score", "0"), item.get("feedback_label", "ikke_åbnet"))

    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True, port=5057)
