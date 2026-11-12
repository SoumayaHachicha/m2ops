from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PUBLI_REJECT_PATTERNS = [
    "publi-reportage",
    "partenaires",
    "contenu sponsorisé",
    "coup de projecteur",
]

HOROSCOPE_KEYWORDS = ["horoscope", "zodiaque", "signes", "taureau", "gemeaux"]
TV_KEYWORDS = ["programme tv", "tv guide", "grille tv", "émission tv"]
GAME_KEYWORDS = ["jeu", "concours", "tombola", "loto", "quiz"]


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    text = unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text


def normalize_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def normalize_excerpt(value: str | None, max_length: int = 220) -> str:
    text = normalize_text(value)
    if len(text) > max_length:
        if max_length <= 1:
            return "…"[:max_length]
        text = text[: max_length - 2].rstrip() + "…"
    return text


def is_future_date(value: str | None) -> bool:
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return dt > now


def title_normalized(title: str | None) -> str:
    text = normalize_text(title).lower()
    text = text.translate(str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc"))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def jaccard_similarity(a: str, b: str) -> float:
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    union = set_a | set_b
    inter = set_a & set_b
    return len(inter) / len(union)


@dataclass
class RuleResult:
    rule_id: str
    source: str
    reason: str


def reject_for_rule(article: dict[str, Any]) -> list[RuleResult]:
    results: list[RuleResult] = []
    title = normalize_text(
        article.get("title") or article.get("titre") or ""
    )
    summary = normalize_text(
        article.get("description") or article.get("resume") or ""
    )
    source_name = article.get("source", "unknown")

    if not title:
        results.append(
            RuleResult("R00_titre_vide", source_name, "Titre vide")
        )
    if is_future_date(article.get("published_at") or article.get("publie_le")):
        if not any(result.rule_id == "R05_date_future" for result in results):
            results.append(
                RuleResult(
                    "R05_date_future",
                    source_name,
                    "Date postérieure au moment actuel",
                )
            )

    combined = (title + " " + summary).lower()
    for pattern in PUBLI_REJECT_PATTERNS:
        if pattern in combined:
            results.append(
                RuleResult(
                    "R01_publi",
                    source_name,
                    f"Motif de publireportage: {pattern}",
                )
            )
            break

    if any(word in combined for word in HOROSCOPE_KEYWORDS):
        results.append(
            RuleResult("R02_horoscope", source_name, "Horoscope ou zodiaque")
        )
    if any(word in combined for word in TV_KEYWORDS):
        results.append(
            RuleResult("R03_programme_tv", source_name, "Programme TV")
        )
    if any(word in combined for word in GAME_KEYWORDS):
        results.append(
            RuleResult("R04_jeu", source_name, "Jeu ou concours")
        )

    return results


def validate_article(
    article: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_hours: int = 24,
) -> list[RuleResult]:
    results = [
        result
        for result in reject_for_rule(article)
        if result.rule_id != "R05_date_future"
    ]
    source_name = article.get("source", "unknown")
    link = str(article.get("link") or article.get("lien") or "").strip()
    if not link:
        results.append(
            RuleResult("R06_lien_vide", source_name, "Lien vide")
        )
    else:
        try:
            parsed_link = urlsplit(link)
            valid_link = (
                parsed_link.scheme in {"http", "https"}
                and parsed_link.hostname is not None
                and parsed_link.username is None
                and parsed_link.password is None
                and (
                    parsed_link.port is None
                    or 1 <= parsed_link.port <= 65535
                )
            )
        except ValueError:
            valid_link = False
        if not valid_link:
            results.append(
                RuleResult(
                    "R09_lien_invalide",
                    source_name,
                    "Le lien doit être une URL HTTP ou HTTPS valide",
                )
            )

    published = article.get("published_at") or article.get("publie_le")
    try:
        published_at = datetime.fromisoformat(str(published))
        if published_at.tzinfo is None:
            raise ValueError("Date without timezone")
        published_at = published_at.astimezone(timezone.utc)
    except (TypeError, ValueError):
        results.append(
            RuleResult(
                "R07_date_invalide",
                source_name,
                "Date absente ou invalide",
            )
        )
        return results

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    if published_at > current_time:
        results.append(
            RuleResult(
                "R05_date_future",
                source_name,
                "Date postérieure au moment actuel",
            )
        )
    elif published_at < current_time - timedelta(hours=max_age_hours):
        results.append(
            RuleResult(
                "R08_article_perime",
                source_name,
                f"Article publié il y a plus de {max_age_hours} heures",
            )
        )
    return results


def build_quality_report(articles: list[dict[str, Any]]) -> dict[str, Any]:
    counts_by_rule: dict[str, int] = {}
    counts_by_source: dict[str, int] = {}
    kept = 0
    rejected = 0

    for article in articles:
        rules = reject_for_rule(article)
        if rules:
            rejected += 1
            for rule in rules:
                counts_by_rule[rule.rule_id] = (
                    counts_by_rule.get(rule.rule_id, 0) + 1
                )
                counts_by_source[rule.source] = (
                    counts_by_source.get(rule.source, 0) + 1
                )
        else:
            kept += 1

    return {
        "entries": len(articles),
        "kept": kept,
        "rejected": rejected,
        "by_rule": counts_by_rule,
        "by_source": counts_by_source,
    }


def write_quality_report(
    report: dict[str, Any],
    output_path: str | Path,
) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
