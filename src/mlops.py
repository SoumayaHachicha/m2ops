from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.quality import title_normalized


@dataclass
class ClusteringConfig:
    n_clusters: int = 4
    min_cluster_size: int = 1
    random_state: int = 42
    max_articles_hours: int = 24


DEFAULT_CONFIG = ClusteringConfig()


THEME_KEYWORDS = {
    "Politique": {
        "politique", "gouvernement", "president", "presidence", "election",
        "depute", "senat", "ministre", "assemblee", "parlement",
    },
    "Économie": {
        "economie", "budget", "finance", "marche", "entreprise", "emploi",
        "inflation", "banque", "industrie", "commerce",
    },
    "Sport": {
        "sport", "football", "rugby", "tennis", "match", "club", "joueur",
        "equipe", "championnat", "olympique",
    },
    "Culture": {
        "culture", "film", "cinema", "musique", "livre", "artiste",
        "exposition", "theatre", "festival", "serie",
    },
    "Société": {
        "societe", "ecole", "sante", "logement", "transport", "social",
        "famille", "hopital", "education", "manifestation",
    },
    "Sciences": {
        "science", "recherche", "climat", "environnement", "energie",
        "technologie", "espace", "medecine", "numerique", "innovation",
    },
}


def choose_theme_name(
    title_tokens: list[str],
    summary_tokens: list[str],
) -> str:
    tokens = []
    for token in title_tokens + summary_tokens:
        token = token.strip().lower()
        if token and len(token) > 2:
            tokens.append(token)
    if not tokens:
        return "thème général"

    preferred = [
        "politique",
        "economie",
        "sport",
        "culture",
        "société",
        "justice",
        "sciences",
    ]
    for token in preferred:
        if token in tokens:
            return token.capitalize()

    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0]),
    )
    return ranked[0][0].capitalize()


def cluster_articles(
    articles: list[dict[str, Any]],
    config: ClusteringConfig = DEFAULT_CONFIG,
) -> list[dict[str, Any]]:
    if not articles:
        return []

    groups: dict[str, list[dict[str, Any]]] = {}
    for article in articles:
        title = str(article.get("titre") or article.get("title") or "")
        summary = str(
            article.get("resume") or article.get("description") or ""
        )
        tokens = set(title_normalized(f"{title} {summary}").split())
        scores = {
            theme: len(tokens.intersection(keywords))
            for theme, keywords in THEME_KEYWORDS.items()
        }
        best_theme = max(scores, key=scores.get)
        if scores[best_theme] == 0:
            best_theme = "Autres"
        groups.setdefault(best_theme, []).append(article)

    return [
        {
            "nom": theme,
            "cluster": index,
            "taille": len(members),
            "articles": members,
        }
        for index, (theme, members) in enumerate(groups.items())
    ]


def init_ml_tables(db_path: str | Path) -> None:
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            run_date TEXT NOT NULL,
            date_debut TEXT NOT NULL,
            date_fin TEXT NOT NULL,
            nombre_articles INTEGER NOT NULL,
            n_clusters INTEGER NOT NULL,
            model_version TEXT NOT NULL,
            config_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            artefacts_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS themes (
            run_id TEXT NOT NULL,
            theme_id TEXT NOT NULL,
            nom TEXT NOT NULL,
            mots_cles TEXT NOT NULL,
            taille INTEGER NOT NULL,
            PRIMARY KEY (run_id, theme_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles_themes (
            run_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            theme_id TEXT NOT NULL,
            PRIMARY KEY (run_id, article_id)
        )
        """
    )
    conn.commit()
    conn.close()


def compute_run(
    articles: list[dict[str, Any]],
    db_path: str | Path,
    config: ClusteringConfig = DEFAULT_CONFIG,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    init_ml_tables(db_path)
    run_id = str(uuid.uuid4())
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    run_date = current_time.isoformat()
    start = current_time - timedelta(
        hours=config.max_articles_hours
    )
    filtered = []
    for article in articles:
        published = (
            article.get("publie_le") or article.get("published_at") or ""
        )
        if published and published.endswith("Z"):
            published = published[:-1] + "+00:00"
        if not published:
            continue
        try:
            dt = datetime.fromisoformat(published)
        except ValueError:
            continue
        if dt.tzinfo is None:
            continue
        dt = dt.astimezone(timezone.utc)
        if start <= dt <= current_time:
            filtered.append(article)

    themes = cluster_articles(filtered, config=config)
    metrics = {
        "nombre_themes": len(themes),
        "taille_mediane": (
            median([theme["taille"] for theme in themes]) if themes else 0
        ),
        "nombre_articles": len(filtered),
    }
    config_json = json.dumps(
        {
            "classifier": "keyword-rules-v1",
            "max_articles_hours": config.max_articles_hours,
        },
        ensure_ascii=False,
    )
    artefacts = {
        "themes": [theme["nom"] for theme in themes],
        "articles": [
            a.get("lien") or a.get("link") or "" for a in filtered
        ],
    }

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, run_date, date_debut, date_fin, "
        "nombre_articles, n_clusters, model_version, config_json, "
        "metrics_json, artefacts_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            run_date,
            start.isoformat(),
            current_time.isoformat(),
            len(filtered),
            len(themes),
            "keyword-rules-v1",
            config_json,
            json.dumps(metrics, ensure_ascii=False),
            json.dumps(artefacts, ensure_ascii=False),
        ),
    )

    for index, theme in enumerate(themes):
        theme_id = f"{run_id}-{index}"
        tokens = sorted(
            {token for token in theme["nom"].lower().split()}
        )
        conn.execute(
            "INSERT INTO themes (run_id, theme_id, nom, mots_cles, taille) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                theme_id,
                theme["nom"],
                ", ".join(tokens),
                theme["taille"],
            ),
        )
        for article in theme["articles"]:
            article_id = str(
                article.get("id")
                or article.get("lien")
                or article.get("link")
                or uuid.uuid4()
            )
            conn.execute(
                "INSERT OR IGNORE INTO articles_themes "
                "(run_id, article_id, theme_id) VALUES (?, ?, ?)",
                (run_id, article_id, theme_id),
            )
    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "date": run_date,
        "themes": themes,
        "metrics": metrics,
        "artefacts": artefacts,
    }


def median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 0:
        return (ordered[middle - 1] + ordered[middle]) / 2
    return float(ordered[middle])
