import sqlite3
from datetime import datetime, timezone

from src.mlops import (
    ClusteringConfig,
    choose_theme_name,
    cluster_articles,
    compute_run,
)


def test_theme_name_is_based_on_keywords():
    name = choose_theme_name(
        ["politique", "france"],
        ["politique", "gouvernement"],
    )
    assert name.lower() == "politique"


def test_cluster_articles_groups_by_vector_pattern():
    articles = [
        {
            "id": "1",
            "titre": "Le gouvernement annonce une réforme",
            "resume": "La politique reprend la priorité.",
            "publie_le": "2026-11-12T08:00:00+00:00",
        },
        {
            "id": "2",
            "titre": "Le budget du pays",
            "resume": "Les finances publiques sont au centre du débat.",
            "publie_le": "2026-11-12T09:00:00+00:00",
        },
        {
            "id": "3",
            "titre": "Le Real gagne encore",
            "resume": "Le football domine les discussions.",
            "publie_le": "2026-11-12T10:00:00+00:00",
        },
        {
            "id": "4",
            "titre": "Un film récompensé",
            "resume": "La culture fait parler.",
            "publie_le": "2026-11-12T11:00:00+00:00",
        },
    ]

    config = ClusteringConfig(n_clusters=4, min_cluster_size=1)
    themes = cluster_articles(articles, config=config)
    assert len(themes) >= 2
    names = {theme["nom"].lower() for theme in themes}
    assert names.intersection({"politique", "culture", "sport"})


def test_cluster_with_empty_input_returns_empty_list():
    assert cluster_articles([]) == []


def test_compute_run_keeps_only_recent_dated_articles(tmp_path):
    now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
    articles = [
        {
            "id": "recent",
            "title": "Le gouvernement annonce une réforme",
            "published_at": "2026-11-12T11:00:00+00:00",
        },
        {
            "id": "old",
            "title": "Ancien article",
            "published_at": "2026-11-11T11:59:00+00:00",
        },
        {
            "id": "future",
            "title": "Article futur",
            "published_at": "2026-11-12T12:01:00+00:00",
        },
        {"id": "missing", "title": "Date absente"},
    ]

    result = compute_run(
        articles,
        tmp_path / "m2ops.db",
        now=now,
    )

    assert result["metrics"]["nombre_articles"] == 1
    with sqlite3.connect(tmp_path / "m2ops.db") as conn:
        row = conn.execute(
            "SELECT nombre_articles, n_clusters FROM runs"
        ).fetchone()
    assert row == (1, 1)
