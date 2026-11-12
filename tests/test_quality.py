from datetime import datetime, timezone

from src.quality import (
    build_quality_report,
    jaccard_similarity,
    normalize_excerpt,
    normalize_text,
    reject_for_rule,
    validate_article,
)


def test_normalize_text_and_excerpt():
    raw = "&lt;b&gt;Bonjour &amp; bienvenue&lt;/b&gt;   "
    assert normalize_text(raw) == "Bonjour & bienvenue"
    text = "A very long description " * 10
    assert normalize_excerpt(text, max_length=20) == ("A very long descri…")


def test_reject_rules_detect_invalid_content():
    article = {
        "title": "Horoscope du mois",
        "description": "Les signes et les jeux vous attendent.",
        "source": "Le Monde",
        "published_at": "2099-01-01T00:00:00+00:00",
    }

    rules = reject_for_rule(article)
    ids = {r.rule_id for r in rules}
    assert "R02_horoscope" in ids
    assert "R05_date_future" in ids


def test_quality_report_counts_rejections():
    data = [
        {
            "title": "Bonne actualité",
            "description": "Tout va bien.",
            "source": "Le Monde",
            "published_at": "2026-11-12T10:00:00+00:00",
        },
        {
            "title": "Horoscope du mois",
            "description": "Votre signe est fort.",
            "source": "Le Monde",
            "published_at": "2026-11-12T10:00:00+00:00",
        },
        {
            "title": "Programme TV",
            "description": "Liste des émissions.",
            "source": "Le Télégramme",
            "published_at": "2026-11-12T10:00:00+00:00",
        },
    ]

    report = build_quality_report(data)
    assert report["entries"] == 3
    assert report["kept"] == 1
    assert report["rejected"] == 2
    assert report["by_rule"]["R02_horoscope"] == 1
    assert report["by_rule"]["R03_programme_tv"] == 1


def test_jaccard_similarity_basic():
    assert jaccard_similarity("chat chien lion", "chat lion") > 0.4


def test_validate_article_enforces_freshness_and_required_fields():
    now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
    article = {
        "title": "Article ancien",
        "description": "Extrait.",
        "source": "Le Monde",
        "link": "https://example.com/article",
        "published_at": "2026-11-11T11:59:00+00:00",
    }

    rules = validate_article(article, now=now)

    assert {rule.rule_id for rule in rules} == {"R08_article_perime"}


def test_validate_article_rejects_missing_date_and_link():
    article = {
        "title": "Article sans métadonnées",
        "description": "Extrait.",
        "source": "Le Monde",
    }

    rules = validate_article(
        article,
        now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
    )

    assert {rule.rule_id for rule in rules} == {
        "R06_lien_vide",
        "R07_date_invalide",
    }


def test_validate_article_rejects_non_http_links():
    article = {
        "title": "Article",
        "description": "Extrait.",
        "source": "Le Monde",
        "link": "ftp://example.com/article",
        "published_at": "2026-11-12T11:00:00+00:00",
    }

    rules = validate_article(
        article,
        now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
    )

    assert {rule.rule_id for rule in rules} == {"R09_lien_invalide"}
