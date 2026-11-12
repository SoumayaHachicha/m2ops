from __future__ import annotations

import argparse
import csv
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.collector import (
    SourceRecord,
    collect_from_source,
    init_sources_table,
    purge_expired_articles,
    reactivate_sources,
)
from src.mlops import ClusteringConfig, compute_run


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        details = getattr(record, "details", None)
        if details is not None:
            entry["details"] = details
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("m2ops")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
    return logger


def load_sources(path: str | Path) -> list[SourceRecord]:
    sources: list[SourceRecord] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as source_file:
        reader = csv.DictReader(source_file)
        required = {"nom", "type", "url_flux"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Colonnes manquantes dans {path}: "
                f"{', '.join(sorted(missing))}"
            )
        for line_number, row in enumerate(reader, start=2):
            name = (row.get("nom") or "").strip()
            source_type = (row.get("type") or "").strip()
            feed_url = (row.get("url_flux") or "").strip()
            if not name or not source_type or not feed_url:
                raise ValueError(
                    f"Source incomplète à la ligne {line_number} de {path}"
                )
            sources.append(
                SourceRecord(
                    nom=name,
                    type=source_type,
                    url_flux=feed_url,
                )
            )
    if not sources:
        raise ValueError(f"Aucune source configurée dans {path}")
    return sources


def _append_alert(
    alert_path: Path,
    *,
    code: str,
    message: str,
    severity: str = "error",
    source: str | None = None,
) -> None:
    alert_path.parent.mkdir(parents=True, exist_ok=True)
    alert = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "code": code,
        "message": message,
    }
    if source:
        alert["source"] = source
    with alert_path.open("a", encoding="utf-8") as alert_file:
        alert_file.write(json.dumps(alert, ensure_ascii=False) + "\n")


def _load_recent_articles(
    db_path: str | Path,
    *,
    now: datetime,
    max_age_hours: int,
) -> list[dict[str, Any]]:
    cutoff = (now - timedelta(hours=max_age_hours)).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, source, lien, titre, resume, publie_le "
            "FROM articles WHERE publie_le >= ? AND publie_le <= ? "
            "ORDER BY publie_le DESC",
            (cutoff, now.isoformat()),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row[0],
            "source": row[1],
            "link": row[2],
            "title": row[3],
            "description": row[4],
            "published_at": row[5],
        }
        for row in rows
    ]


def run_daily_pipeline(
    *,
    sources_path: str | Path = "sources.csv",
    articles_dir: str | Path = "articles_bruts",
    db_path: str | Path = "data/m2ops.sqlite3",
    reports_dir: str | Path = "reports",
    now: datetime | None = None,
) -> dict[str, Any]:
    logger = configure_logging()
    fixed_time = now is not None
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)

    sources = load_sources(sources_path)
    init_sources_table(db_path)
    reactivated = reactivate_sources(db_path)
    if reactivated:
        logger.info(
            "sources_reactivated_for_daily_retry",
            extra={"details": {"count": reactivated}},
        )
    expired = purge_expired_articles(
        db_path,
        articles_dir,
        now=current_time,
    )
    if expired:
        logger.info(
            "articles_expired",
            extra={"details": {"count": expired}},
        )

    reports_path = Path(reports_dir)
    alert_path = reports_path / "alerts.jsonl"
    totals = {
        "sources": len(sources),
        "written": 0,
        "duplicates": 0,
        "rejected": 0,
        "failed_sources": 0,
        "by_rule": {},
        "by_source": {},
    }
    errors: list[dict[str, str]] = []
    for source in sources:
        result = collect_from_source(
            source,
            articles_dir,
            db_path,
            now=current_time if fixed_time else None,
        )
        totals["written"] += result.get("written", 0)
        totals["duplicates"] += result.get("duplicates", 0)
        totals["rejected"] += result.get("rejected", 0)
        for rule_id, count in result.get("rejected_by_rule", {}).items():
            totals["by_rule"][rule_id] = (
                totals["by_rule"].get(rule_id, 0) + count
            )

        if result.get("error"):
            totals["failed_sources"] += 1
            error = {
                "source": source.nom,
                "message": result["error"],
            }
            errors.append(error)
            _append_alert(
                alert_path,
                code="SOURCE_COLLECTION_FAILED",
                message=error["message"],
                source=source.nom,
            )
            logger.error("source_collection_failed", extra={"details": error})
        elif result.get("ignored"):
            totals["failed_sources"] += 1
            message = "Source désactivée après des échecs répétés"
            error = {"source": source.nom, "message": message}
            errors.append(error)
            _append_alert(
                alert_path,
                code="SOURCE_DISABLED",
                message=message,
                source=source.nom,
            )
            logger.error("source_disabled", extra={"details": error})
        else:
            logger.info(
                "source_collection_completed",
                extra={
                    "details": {
                        "source": source.nom,
                        "written": result["written"],
                        "duplicates": result["duplicates"],
                        "rejected": result["rejected"],
                    }
                },
            )
            if not result.get("entries") and not result.get("not_modified"):
                message = "Le flux ne contient aucun article"
                _append_alert(
                    alert_path,
                    code="SOURCE_FEED_EMPTY",
                    message=message,
                    severity="warning",
                    source=source.nom,
                )
                logger.warning(
                    "source_feed_empty",
                    extra={
                        "details": {
                            "source": source.nom,
                        }
                    },
                )

        if result.get("rejected"):
            totals["by_source"][source.nom] = result["rejected"]
            logger.warning(
                "source_articles_rejected",
                extra={
                    "details": {
                        "source": source.nom,
                        "count": result["rejected"],
                        "by_rule": result["rejected_by_rule"],
                    }
                },
            )

    if not fixed_time:
        current_time = datetime.now(timezone.utc)
        expired += purge_expired_articles(
            db_path,
            articles_dir,
            now=current_time,
        )
    articles = _load_recent_articles(
        db_path,
        now=current_time,
        max_age_hours=24,
    )
    run = compute_run(
        articles,
        db_path,
        ClusteringConfig(max_articles_hours=24),
        now=current_time,
    )
    edition = {
        "generated_at": current_time.isoformat(),
        "window_start": (
            current_time - timedelta(hours=24)
        ).isoformat(),
        "article_count": len(articles),
        "themes": [
            {
                "name": theme["nom"],
                "articles": [
                    {
                        "source": article["source"],
                        "title": article["title"],
                        "description": article["description"],
                        "link": article["link"],
                        "published_at": article["published_at"],
                    }
                    for article in theme["articles"]
                ],
            }
            for theme in run["themes"]
        ],
    }
    reports_path.mkdir(parents=True, exist_ok=True)
    (reports_path / "edition.json").write_text(
        json.dumps(edition, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    quality_report = {
        "generated_at": current_time.isoformat(),
        "sources": totals["sources"],
        "articles_written": totals["written"],
        "duplicates_skipped": totals["duplicates"],
        "articles_rejected": totals["rejected"],
        "rejections_by_rule": totals["by_rule"],
        "rejections_by_source": totals["by_source"],
        "recent_articles_in_edition": len(articles),
        "themes": len(run["themes"]),
        "failed_sources": errors,
    }
    (reports_path / "quality.json").write_text(
        json.dumps(quality_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not articles:
        _append_alert(
            alert_path,
            code="EMPTY_EDITION",
            message="Aucun article valide dans la fenêtre des 24 heures",
            severity="warning",
        )
        logger.warning("edition_empty")

    summary = {
        "edition": str(reports_path / "edition.json"),
        "quality_report": str(reports_path / "quality.json"),
        "articles": len(articles),
        "themes": len(run["themes"]),
        "failed_sources": len(errors),
    }
    logger.info("pipeline_completed", extra={"details": summary})
    return {
        **summary,
        "errors": errors,
        "quality": quality_report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exécute une collecte et produit l'édition du jour."
    )
    parser.add_argument("--sources", default="sources.csv")
    parser.add_argument("--articles-dir", default="articles_bruts")
    parser.add_argument("--db", default="data/m2ops.sqlite3")
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()
    result = run_daily_pipeline(
        sources_path=args.sources,
        articles_dir=args.articles_dir,
        db_path=args.db,
        reports_dir=args.reports_dir,
    )
    if result["failed_sources"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
