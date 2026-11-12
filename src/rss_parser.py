from __future__ import annotations

import argparse
import email.utils
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.quality import (
    normalize_date,
    normalize_excerpt,
    normalize_text,
    validate_article,
)


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _find_text(element: ET.Element, tag: str) -> str | None:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] != tag:
            continue
        text = _clean_text("".join(child.itertext()))
        if text:
            return text
    return None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(iso_value)
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _entry_link(entry: ET.Element) -> str | None:
    for child in entry:
        if child.tag.rsplit("}", 1)[-1] != "link":
            continue
        href = child.attrib.get("href")
        rel = child.attrib.get("rel", "alternate")
        if href and rel == "alternate":
            return href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return None


def parse_rss_feed(
    xml_content: str,
    source_name: str | None = None,
) -> list[dict]:
    root = ET.fromstring(xml_content)
    items = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] in {"item", "entry"}
    ]

    records: list[dict] = []
    for item in items:
        title = _find_text(item, "title")
        link = _entry_link(item)
        description = (
            _find_text(item, "description")
            or _find_text(item, "summary")
            or _find_text(item, "content")
        )
        published = (
            _find_text(item, "pubDate")
            or _find_text(item, "published")
            or _find_text(item, "updated")
            or _find_text(item, "date")
        )
        records.append(
            {
                "title": title or "",
                "link": link or "",
                "description": description or "",
                "published_at": _parse_date(published) or "",
                "source": source_name or "unknown",
            }
        )
    return records


def download_feed(url: str) -> str:
    request = Request(url, headers={"User-Agent": "M2Ops-Collector/1.0"})
    with urlopen(request, timeout=20) as response:
        content = response.read().decode("utf-8", errors="replace")
    return content


def export_feed_to_json(
    url: str,
    output_path: str | Path,
    source_name: str | None = None,
) -> list[dict]:
    xml_content = download_feed(url)
    parsed_entries = parse_rss_feed(xml_content, source_name=source_name)
    now = datetime.now(timezone.utc)
    entries = []
    rejected = 0
    for entry in parsed_entries:
        normalized = {
            "title": normalize_text(entry.get("title")),
            "description": normalize_excerpt(entry.get("description")),
            "link": str(entry.get("link") or "").strip(),
            "published_at": normalize_date(entry.get("published_at")),
            "source": entry.get("source") or source_name or "unknown",
        }
        if validate_article(normalized, now=now):
            rejected += 1
            continue
        entries.append(normalized)
    if rejected:
        logging.getLogger("m2ops").warning(
            "Rejected %s invalid or out-of-window entries from %s",
            rejected,
            source_name or url,
        )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return entries


def main() -> None:
    description = (
        "Collecte et sérialisation d’un flux RSS/Atom pour La Gazette."
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--source", default="Le Monde")
    parser.add_argument(
        "--url",
        default="https://www.lemonde.fr/rss/une.xml",
    )
    parser.add_argument(
        "--output",
        default="./tmp/edition.json",
    )
    args = parser.parse_args()

    try:
        entries = export_feed_to_json(
            args.url,
            args.output,
            source_name=args.source,
        )
    except URLError as exc:
        raise SystemExit(
            f"Erreur lors de la récupération du flux RSS/Atom : {exc}"
        ) from exc

    print(f"{len(entries)} articles exportés dans {args.output}")


if __name__ == "__main__":
    main()
