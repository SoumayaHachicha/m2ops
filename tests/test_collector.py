import json
import sqlite3
import threading
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.collector import (
    SourceRecord,
    collect_from_source,
    init_sources_table,
    purge_expired_articles,
)


XML_SAMPLE = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<rss version=\"2.0\">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Article 1</title>
      <link>https://example.com/articles/1</link>
      <description>Premier article.</description>
      <pubDate>{published_at}</pubDate>
    </item>
  </channel>
</rss>
"""


def _feed_xml():
    return XML_SAMPLE.format(
        published_at=format_datetime(datetime.now(timezone.utc))
    )


class ServiceUnavailableHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(503)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"temporarily unavailable")

    def log_message(self, format, *args):
        return


class FeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = _feed_xml().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


class ConditionalFeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("If-None-Match") == '"test-v1"':
            self.send_response(304)
            self.send_header("ETag", '"test-v1"')
            self.end_headers()
            return
        payload = _feed_xml().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("ETag", '"test-v1"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def _start_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def test_two_passes_no_duplicate(tmp_path):
    articles_dir = tmp_path / "articles_bruts"
    db_path = tmp_path / "m2ops.db"
    init_sources_table(db_path)

    server, port, _ = _start_server(FeedHandler)
    try:
        source = SourceRecord(
            nom="Test feed",
            type="PQN",
            url_flux=f"http://127.0.0.1:{port}/feed.xml",
            actif=True,
            derniere_reussite=None,
            echecs_consecutifs=0,
            etag=None,
            last_modified=None,
        )

        first = collect_from_source(source, articles_dir, db_path)
        second = collect_from_source(source, articles_dir, db_path)
        other_source = SourceRecord(
            nom="Other source",
            type="PQN",
            url_flux=f"http://127.0.0.1:{port}/feed.xml",
        )
        cross_source = collect_from_source(
            other_source,
            articles_dir,
            db_path,
        )

        assert first["written"] == 1
        assert second["written"] == 0
        assert second["duplicates"] == 1
        assert cross_source["written"] == 0
        assert cross_source["duplicates"] == 1
        assert len(list(articles_dir.glob("*.json"))) == 1
        article = json.loads(next(articles_dir.glob("*.json")).read_text())
        assert set(article) == {
            "source",
            "title",
            "description",
            "link",
            "published_at",
        }
    finally:
        server.shutdown()
        server.server_close()


class StaleFeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = XML_SAMPLE.format(
            published_at="Thu, 01 Jan 2000 00:00:00 +0000"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


def test_collector_rejects_articles_older_than_24_hours(tmp_path):
    articles_dir = tmp_path / "articles_bruts"
    db_path = tmp_path / "m2ops.db"
    server, port, _ = _start_server(StaleFeedHandler)
    try:
        result = collect_from_source(
            SourceRecord(
                nom="Stale feed",
                type="PQN",
                url_flux=f"http://127.0.0.1:{port}/feed.xml",
            ),
            articles_dir,
            db_path,
        )

        assert result["written"] == 0
        assert result["rejected"] == 1
        assert result["rejected_by_rule"]["R08_article_perime"] == 1
        with sqlite3.connect(db_path) as conn:
            assert (
                conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
                == 0
            )
    finally:
        server.shutdown()
        server.server_close()


def test_conditional_request_treats_not_modified_as_success(tmp_path):
    server, port, _ = _start_server(ConditionalFeedHandler)
    source = SourceRecord(
        nom="Conditional feed",
        type="PQN",
        url_flux=f"http://127.0.0.1:{port}/feed.xml",
    )
    try:
        first = collect_from_source(
            source,
            tmp_path / "articles",
            tmp_path / "m2ops.db",
        )
        second = collect_from_source(
            source,
            tmp_path / "articles",
            tmp_path / "m2ops.db",
        )

        assert first["written"] == 1
        assert second["not_modified"] is True
        assert "error" not in second
        with sqlite3.connect(tmp_path / "m2ops.db") as conn:
            row = conn.execute(
                "SELECT echecs_consecutifs, actif FROM sources "
                "WHERE nom = ?",
                ("Conditional feed",),
            ).fetchone()
        assert row == (0, 1)
    finally:
        server.shutdown()
        server.server_close()


def test_source_sleep_after_three_failures(tmp_path):
    articles_dir = tmp_path / "articles_bruts"
    db_path = tmp_path / "m2ops.db"
    init_sources_table(db_path)

    server, port, _ = _start_server(ServiceUnavailableHandler)
    try:
        source = SourceRecord(
            nom="Broken feed",
            type="PQR",
            url_flux=f"http://127.0.0.1:{port}/broken.xml",
            actif=True,
            derniere_reussite=None,
            echecs_consecutifs=0,
            etag=None,
            last_modified=None,
        )

        for _ in range(3):
            result = collect_from_source(source, articles_dir, db_path)
            assert result["written"] == 0

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT actif, echecs_consecutifs FROM sources WHERE nom = ?",
                ("Broken feed",),
            ).fetchone()

        assert row is not None
        assert row[0] == 0
        assert row[1] >= 3
    finally:
        server.shutdown()
        server.server_close()


def test_purge_removes_expired_database_articles(tmp_path):
    db_path = tmp_path / "m2ops.db"
    init_sources_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO articles "
            "(id, source, lien, titre, resume, publie_le, recupere_le, "
            "rubrique, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "expired",
                "Test",
                "https://example.com/expired",
                "Expired article",
                "",
                "2026-11-11T11:00:00+00:00",
                "2026-11-11T11:00:00+00:00",
                None,
                "{}",
            ),
        )

    removed = purge_expired_articles(
        db_path,
        tmp_path / "articles",
        now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
    )

    assert removed == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
