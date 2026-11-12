import json
import threading
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.pipeline import run_daily_pipeline


class FeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        published = format_datetime(
            datetime.now(timezone.utc) - timedelta(seconds=5)
        )
        payload = (
            "<rss><channel><item>"
            "<title>Le gouvernement annonce une réforme</title>"
            "<link>https://example.com/reforme</link>"
            "<description>Une réforme politique.</description>"
            f"<pubDate>{published}</pubDate>"
            "</item></channel></rss>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


class FailureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_error(503, "temporarily unavailable")

    def log_message(self, format, *args):
        return


def test_pipeline_collects_validates_and_writes_edition(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FeedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sources = tmp_path / "sources.csv"
        sources.write_text(
            "nom,type,url_flux\n"
            f"Test,PQN,http://127.0.0.1:{server.server_port}/feed\n",
            encoding="utf-8",
        )
        reports = tmp_path / "reports"
        result = run_daily_pipeline(
            sources_path=sources,
            articles_dir=tmp_path / "articles",
            db_path=tmp_path / "data.sqlite3",
            reports_dir=reports,
        )

        edition = json.loads((reports / "edition.json").read_text())
        quality = json.loads((reports / "quality.json").read_text())
        assert result["articles"] == 1
        assert edition["article_count"] == 1
        assert edition["themes"][0]["name"] == "Politique"
        assert set(edition["themes"][0]["articles"][0]) == {
            "source",
            "title",
            "description",
            "link",
            "published_at",
        }
        assert quality["failed_sources"] == []
        assert quality["articles_written"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_pipeline_persists_alerts_for_failed_source(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FailureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sources = tmp_path / "sources.csv"
        sources.write_text(
            "nom,type,url_flux\n"
            f"Broken,PQN,http://127.0.0.1:{server.server_port}/feed\n",
            encoding="utf-8",
        )
        reports = tmp_path / "reports"
        result = run_daily_pipeline(
            sources_path=sources,
            articles_dir=tmp_path / "articles",
            db_path=tmp_path / "data.sqlite3",
            reports_dir=reports,
        )
        alerts = [
            json.loads(line)
            for line in (reports / "alerts.jsonl").read_text().splitlines()
        ]

        assert result["failed_sources"] == 1
        assert {alert["code"] for alert in alerts} == {
            "SOURCE_COLLECTION_FAILED",
            "EMPTY_EDITION",
        }
        source_alert = next(
            alert
            for alert in alerts
            if alert["code"] == "SOURCE_COLLECTION_FAILED"
        )
        assert source_alert["severity"] == "error"
    finally:
        server.shutdown()
        server.server_close()
