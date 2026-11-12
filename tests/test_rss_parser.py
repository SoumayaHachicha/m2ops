from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from pathlib import Path

from src import rss_parser
from src.rss_parser import parse_rss_feed


def test_parse_rss_feed_extracts_expected_fields():
    fixture_path = (
        Path(__file__).with_name("fixtures") / "le_monde_sample.xml"
    )
    xml = fixture_path.read_text(encoding="utf-8")

    entries = parse_rss_feed(xml, source_name="Le Monde")

    assert len(entries) == 2
    assert entries[0]["title"] == "La météo s’annonce chaude"
    assert entries[0]["link"] == (
        "https://www.lemonde.fr/monde/article/2026/11/12/"
        "la-meteo-s-annonce-chaude_1234567890.html"
    )
    assert entries[0]["source"] == "Le Monde"
    assert entries[0]["published_at"] == "2026-11-12T08:15:00+00:00"
    desc = "Les élus annoncent des mesures de soutien."
    assert entries[1]["description"] == desc


def test_parse_atom_feed_with_namespaces():
    xml = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Un article</title>
        <link rel="alternate" href="https://example.com/article"/>
        <summary>Un extrait.</summary>
        <published>2026-11-12T08:15:00+01:00</published>
      </entry>
    </feed>
    """

    entries = parse_rss_feed(xml, source_name="Source Atom")

    assert entries == [
        {
            "title": "Un article",
            "link": "https://example.com/article",
            "description": "Un extrait.",
            "published_at": "2026-11-12T07:15:00+00:00",
            "source": "Source Atom",
        }
    ]


def test_parser_keeps_incomplete_items_for_quality_rejection():
    xml = (
        "<rss><channel><item><title>Sans lien</title></item></channel></rss>"
    )

    entries = parse_rss_feed(xml, source_name="Source")

    assert len(entries) == 1
    assert entries[0]["title"] == "Sans lien"
    assert entries[0]["link"] == ""


def test_export_filters_stale_articles_and_limits_excerpt(
    tmp_path,
    monkeypatch,
):
    now = datetime.now(timezone.utc)
    feed = f"""<rss><channel>
      <item>
        <title>Recent article</title>
        <link>https://example.com/recent</link>
        <description>{"extrait " * 60}</description>
        <pubDate>{format_datetime(now)}</pubDate>
      </item>
      <item>
        <title>Old article</title>
        <link>https://example.com/old</link>
        <description>Ancien.</description>
        <pubDate>{format_datetime(now - timedelta(days=2))}</pubDate>
      </item>
    </channel></rss>"""
    monkeypatch.setattr(rss_parser, "download_feed", lambda _: feed)
    output = tmp_path / "edition.json"

    entries = rss_parser.export_feed_to_json(
        "https://example.com/feed.xml",
        output,
        source_name="Source",
    )

    assert len(entries) == 1
    assert len(entries[0]["description"]) <= 220
    assert json.loads(output.read_text(encoding="utf-8")) == entries
