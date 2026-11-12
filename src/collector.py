from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from src.quality import (
    jaccard_similarity,
    normalize_date,
    normalize_excerpt,
    normalize_text,
    title_normalized,
    validate_article,
)
from src.rss_parser import parse_rss_feed


DEFAULT_USER_AGENT = "M2Ops-Collector/1.0"


@dataclass
class SourceRecord:
    nom: str
    type: str
    url_flux: str
    actif: bool = True
    derniere_reussite: str | None = None
    echecs_consecutifs: int = 0
    etag: str | None = None
    last_modified: str | None = None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "source"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _article_path(source_name: str, link: str, articles_dir: Path) -> Path:
    digest = hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]
    return articles_dir / f"{_slugify(source_name)}-{digest}.json"


def _canonical_link(link: str) -> str:
    parts = urlsplit(link.strip())
    hostname = (parts.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parts.port
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
        ]
    )
    return urlunsplit(
        (parts.scheme.lower(), hostname, path, query, "")
    )


def _collection_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}: {exc.reason}"
    if isinstance(exc, URLError):
        return f"Flux inaccessible: {exc.reason}"
    if isinstance(exc, ET.ParseError):
        return "Le document du flux XML est mal formé"
    if isinstance(exc, ValueError):
        return "Le flux contient des données invalides"
    return f"Erreur de collecte ({type(exc).__name__})"


def init_sources_table(db_path: str | Path) -> None:
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sources (
            nom TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            url_flux TEXT NOT NULL,
            actif INTEGER NOT NULL DEFAULT 1,
            derniere_reussite TEXT,
            echecs_consecutifs INTEGER NOT NULL DEFAULT 0,
            etag TEXT,
            last_modified TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            lien TEXT NOT NULL,
            titre TEXT,
            resume TEXT,
            publie_le TEXT,
            recupere_le TEXT,
            rubrique TEXT,
            payload TEXT NOT NULL,
            UNIQUE(source, lien)
        )
        """
    )
    conn.commit()
    conn.close()


def _upsert_source(conn: sqlite3.Connection, source: SourceRecord) -> None:
    conn.execute(
        """
        INSERT INTO sources (
            nom, type, url_flux, actif, derniere_reussite,
            echecs_consecutifs, etag, last_modified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(nom) DO UPDATE SET
            type = excluded.type,
            url_flux = excluded.url_flux
        """,
        (
            source.nom,
            source.type,
            source.url_flux,
            int(source.actif),
            source.derniere_reussite,
            source.echecs_consecutifs,
            source.etag,
            source.last_modified,
        ),
    )


def _fetch_xml(
    url: str,
    source: SourceRecord,
) -> tuple[str, str | None, str | None]:
    headers: dict[str, str] = {"User-Agent": DEFAULT_USER_AGENT}
    if source.etag:
        headers["If-None-Match"] = source.etag
    if source.last_modified:
        headers["If-Modified-Since"] = source.last_modified

    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8", errors="replace")
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        return payload, etag, last_modified


def _store_article(
    conn: sqlite3.Connection,
    article: dict[str, Any],
    article_path: Path,
) -> None:
    article_path.parent.mkdir(parents=True, exist_ok=True)
    article_path.write_text(
        json.dumps(
            {
                "source": article["source"],
                "title": article["titre"],
                "description": article["resume"],
                "link": article["lien"],
                "published_at": article["publie_le"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    conn.execute(
        """
        INSERT INTO articles (
            id, source, lien, titre, resume, publie_le,
            recupere_le, rubrique, payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (
            article["id"],
            article["source"],
            article["lien"],
            article["titre"],
            article["resume"],
            article["publie_le"],
            article["recupere_le"],
            None,
            json.dumps(
                {
                    "source": article["source"],
                    "title": article["titre"],
                    "description": article["resume"],
                    "link": article["lien"],
                    "published_at": article["publie_le"],
                },
                ensure_ascii=False,
            ),
        ),
    )


def purge_expired_articles(
    db_path: str | Path,
    articles_dir: str | Path,
    *,
    now: datetime | None = None,
    max_age_hours: int = 24,
) -> int:
    init_sources_table(db_path)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    cutoff = current_time - timedelta(hours=max_age_hours)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, source, lien, publie_le FROM articles"
        ).fetchall()
        expired_ids: list[str] = []
        for article_id, source_name, link, published in rows:
            try:
                published_at = datetime.fromisoformat(published)
                if published_at.tzinfo is None:
                    raise ValueError("Date without timezone")
                published_at = published_at.astimezone(timezone.utc)
            except (TypeError, ValueError):
                expired_ids.append(article_id)
                continue
            if published_at < cutoff or published_at > current_time:
                expired_ids.append(article_id)
                continue
            if not link or not source_name:
                expired_ids.append(article_id)

        for article_id in expired_ids:
            row = conn.execute(
                "SELECT source, lien FROM articles WHERE id = ?",
                (article_id,),
            ).fetchone()
            if row:
                article_path = _article_path(
                    row[0],
                    row[1],
                    Path(articles_dir),
                )
                article_path.unlink(missing_ok=True)
            conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        conn.commit()
        return len(expired_ids)
    finally:
        conn.close()


def reactivate_sources(db_path: str | Path) -> int:
    init_sources_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE sources SET actif = 1, echecs_consecutifs = 0 "
            "WHERE actif = 0"
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def collect_from_source(
    source: SourceRecord,
    articles_dir: str | Path,
    db_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    target_dir = Path(articles_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    init_sources_table(db_path)

    conn = sqlite3.connect(db_path)
    try:
        _upsert_source(conn, source)

        db_state = conn.execute(
            "SELECT actif, echecs_consecutifs, etag, last_modified "
            "FROM sources WHERE nom = ?",
            (source.nom,),
        ).fetchone()
        if db_state:
            source.actif = bool(db_state[0])
            source.echecs_consecutifs = int(db_state[1])
            source.etag = db_state[2]
            source.last_modified = db_state[3]

        if not source.actif:
            conn.commit()
            return {
                "written": 0,
                "ignored": True,
                "source": source.nom,
            }

        try:
            xml_content, etag, last_modified = _fetch_xml(
                source.url_flux,
                source,
            )
            items = parse_rss_feed(xml_content, source_name=source.nom)
        except (HTTPError, URLError, ValueError, ET.ParseError) as exc:
            if isinstance(exc, HTTPError) and exc.code == 304:
                conn.execute(
                    "UPDATE sources SET actif = 1, derniere_reussite = ?, "
                    "echecs_consecutifs = 0, etag = COALESCE(?, etag), "
                    "last_modified = COALESCE(?, last_modified) "
                    "WHERE nom = ?",
                    (
                        _now_iso(),
                        exc.headers.get("ETag"),
                        exc.headers.get("Last-Modified"),
                        source.nom,
                    ),
                )
                conn.commit()
                return {
                    "written": 0,
                    "duplicates": 0,
                    "rejected": 0,
                    "rejected_by_rule": {},
                    "entries": 0,
                    "ignored": 0,
                    "not_modified": True,
                    "source": source.nom,
                }
            current_failures = conn.execute(
                "SELECT echecs_consecutifs FROM sources WHERE nom = ?",
                (source.nom,),
            ).fetchone()
            failures = int((current_failures or (0,))[0]) + 1
            active = 0 if failures >= 3 else 1
            conn.execute(
                "UPDATE sources SET actif = ?, "
                "echecs_consecutifs = ? WHERE nom = ?",
                (int(active), failures, source.nom),
            )
            conn.commit()
            return {
                "written": 0,
                "error": _collection_error_message(exc),
                "failures": failures,
                "active": bool(active),
                "source": source.nom,
            }

        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        current_time = current_time.astimezone(timezone.utc)
        cutoff = (current_time - timedelta(hours=24)).isoformat()
        existing_articles = conn.execute(
            "SELECT source, lien, titre FROM articles WHERE publie_le >= ?",
            (cutoff,),
        ).fetchall()
        rejected_by_rule: dict[str, int] = {}
        written = 0
        duplicates = 0
        rejected = 0
        for item in items:
            article = {
                "source": source.nom,
                "title": normalize_text(item.get("title")),
                "description": normalize_excerpt(item.get("description")),
                "link": str(item.get("link") or "").strip(),
                "published_at": normalize_date(item.get("published_at")),
            }
            rules = validate_article(article, now=current_time)
            if rules:
                rejected += 1
                for rule in rules:
                    rejected_by_rule[rule.rule_id] = (
                        rejected_by_rule.get(rule.rule_id, 0) + 1
                    )
                continue

            link = article["link"]
            canonical_link = _canonical_link(link)
            normalized_title = title_normalized(article["title"])
            is_duplicate = False
            for _, existing_link, existing_title in existing_articles:
                if canonical_link == _canonical_link(existing_link):
                    is_duplicate = True
                    break
                existing_normalized_title = title_normalized(existing_title)
                if normalized_title == existing_normalized_title:
                    is_duplicate = True
                    break
                if (
                    len(normalized_title.split()) >= 5
                    and jaccard_similarity(
                        normalized_title,
                        existing_normalized_title,
                    )
                    >= 0.95
                ):
                    is_duplicate = True
                    break
            if is_duplicate:
                duplicates += 1
                continue

            article_id = f"{source.nom}:{canonical_link}"
            existing_id = conn.execute(
                "SELECT 1 FROM articles WHERE id = ?",
                (article_id,),
            ).fetchone()
            if existing_id:
                duplicates += 1
                continue
            stored_article = {
                "id": article_id,
                "source": article["source"],
                "lien": link,
                "titre": article["title"],
                "resume": article["description"],
                "publie_le": article["published_at"],
                "recupere_le": _now_iso(),
            }
            article_path = _article_path(source.nom, link, target_dir)
            _store_article(conn, stored_article, article_path)
            existing_articles.append(
                (source.nom, link, article["title"])
            )
            written += 1

        conn.execute(
            """
            UPDATE sources
            SET actif = 1,
                derniere_reussite = ?,
                echecs_consecutifs = 0,
                etag = ?,
                last_modified = ?
            WHERE nom = ?
            """,
            (_now_iso(), etag, last_modified, source.nom),
        )
        conn.commit()
        return {
            "written": written,
            "duplicates": duplicates,
            "rejected": rejected,
            "rejected_by_rule": rejected_by_rule,
            "entries": len(items),
            "ignored": 0,
            "source": source.nom,
        }
    finally:
        conn.close()
