"""Feed channel and item data normalization."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

from repomap_kg.extractors.documents.feed_support import (
    _atom_link,
    _child_text,
    _children,
    _element_text,
    _item_identity,
    _parse_date,
    _rss_author,
    _safe_label,
    _safe_summary,
    _slug,
    _text_value,
    _title_date_identity,
)
from repomap_kg.graph.keys import feed_channel_key


def _rss_channel_info(
    relative_path: str,
    document_key: str,
    channel: ElementTree.Element,
) -> dict[str, Any]:
    title = _child_text(channel, "title")
    link = _child_text(channel, "link")
    if link:
        channel_id = f"link:{link}"
        identity_source = "link"
        identity_strength = "strong"
    elif title:
        channel_id = f"title:{_slug(title)}:{document_key}"
        identity_source = "title+document"
        identity_strength = "weak"
    else:
        channel_id = "self"
        identity_source = "document"
        identity_strength = "structural"
    return _channel_info(
        relative_path,
        document_key,
        channel_id,
        title,
        "rss",
        identity_source,
        identity_strength,
    )


def _atom_channel_info(
    relative_path: str,
    document_key: str,
    feed: ElementTree.Element,
) -> dict[str, Any]:
    title = _child_text(feed, "title")
    self_link = _atom_link(feed, "self")
    feed_id = _child_text(feed, "id")
    alternate_link = _atom_link(feed, "alternate")
    if self_link:
        channel_id = f"self:{self_link}"
        identity_source = "self-link"
        identity_strength = "strong"
    elif feed_id:
        channel_id = f"id:{feed_id}"
        identity_source = "id"
        identity_strength = "strong"
    elif alternate_link:
        channel_id = f"link:{alternate_link}"
        identity_source = "link"
        identity_strength = "strong"
    elif title:
        channel_id = f"title:{_slug(title)}:{document_key}"
        identity_source = "title+document"
        identity_strength = "weak"
    else:
        channel_id = "self"
        identity_source = "document"
        identity_strength = "structural"
    return _channel_info(
        relative_path,
        document_key,
        channel_id,
        title,
        "atom",
        identity_source,
        identity_strength,
        updated_at=_parse_date(_child_text(feed, "updated")),
    )


def _json_channel_info(
    relative_path: str,
    document_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    title = _text_value(payload.get("title"))
    feed_url = _text_value(payload.get("feed_url"))
    home_page_url = _text_value(payload.get("home_page_url"))
    if feed_url:
        channel_id = f"self:{feed_url}"
        identity_source = "feed_url"
        identity_strength = "strong"
    elif home_page_url:
        channel_id = f"link:{home_page_url}"
        identity_source = "home_page_url"
        identity_strength = "strong"
    elif title:
        channel_id = f"title:{_slug(title)}:{document_key}"
        identity_source = "title+document"
        identity_strength = "weak"
    else:
        channel_id = "self"
        identity_source = "document"
        identity_strength = "structural"
    return _channel_info(
        relative_path,
        document_key,
        channel_id,
        title,
        "json-feed",
        identity_source,
        identity_strength,
    )


def _channel_info(
    relative_path: str,
    document_key: str,
    channel_id: str,
    title: str | None,
    feed_format: str,
    identity_source: str,
    identity_strength: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    channel_key = feed_channel_key(document_key, channel_id)
    return {
        "channel_key": channel_key,
        "document_key": document_key,
        "title": title,
        "feed_format": feed_format,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "updated_at": updated_at,
        "relative_path": relative_path,
    }


def _rss_item_data(
    relative_path: str,
    channel_key: str,
    item: ElementTree.Element,
    ordinal: int,
) -> dict[str, Any]:
    title = _child_text(item, "title")
    link = _child_text(item, "link")
    guid = _child_text(item, "guid")
    pub_date = _child_text(item, "pubDate")
    base_item_id, identity_source, identity_strength = _item_identity(
        ("guid", guid),
        ("link", link),
        ("title+pubDate", _title_date_identity(title, pub_date)),
        ordinal=ordinal,
    )
    enclosures = []
    for enclosure in _children(item, "enclosure"):
        url = enclosure.attrib.get("url", "").strip()
        if not url:
            continue
        enclosures.append(
            {
                "url": url,
                "mime_type": enclosure.attrib.get("type"),
                "length": enclosure.attrib.get("length"),
                "attribute": "url",
            }
        )
    author = _rss_author(_child_text(item, "author"))
    authors = [author] if author else []
    categories = [_safe_label(_element_text(category)) for category in _children(item, "category")]
    content = _child_text(item, "description") or _child_text(item, "encoded")
    return {
        "ordinal": ordinal,
        "channel_key": channel_key,
        "base_item_id": base_item_id,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "title": title,
        "links": [{"value": link, "attribute": "link"}] if link else [],
        "enclosures": enclosures,
        "authors": [author for author in authors if author],
        "categories": [category for category in categories if category],
        "content": content,
        "content_kind": "description",
        "metadata": {
            "feed_format": "rss",
            "title": _safe_summary(title),
            "published_at": _parse_date(pub_date),
        },
    }


def _atom_item_data(
    relative_path: str,
    channel_key: str,
    entry: ElementTree.Element,
    ordinal: int,
) -> dict[str, Any]:
    title = _child_text(entry, "title")
    entry_id = _child_text(entry, "id")
    alternate_link = _atom_link(entry, "alternate")
    updated = _child_text(entry, "updated")
    published = _child_text(entry, "published")
    base_item_id, identity_source, identity_strength = _item_identity(
        ("id", entry_id),
        ("alternate-link", alternate_link),
        ("title+updated", _title_date_identity(title, updated or published)),
        ordinal=ordinal,
    )
    links = []
    for link in _children(entry, "link"):
        href = link.attrib.get("href", "").strip()
        if href:
            links.append(
                {
                    "value": href,
                    "attribute": "href",
                    "rel": link.attrib.get("rel", "alternate"),
                }
            )
    authors = []
    for author in _children(entry, "author"):
        name = _child_text(author, "name")
        uri = _child_text(author, "uri")
        authors.append({"name": _safe_label(name or uri or "unknown-author")})
    categories = [
        _safe_label(category.attrib.get("term") or category.attrib.get("label"))
        for category in _children(entry, "category")
    ]
    content = _child_text(entry, "summary") or _child_text(entry, "content")
    return {
        "ordinal": ordinal,
        "channel_key": channel_key,
        "base_item_id": base_item_id,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "title": title,
        "links": links,
        "enclosures": [],
        "authors": [author for author in authors if author.get("name")],
        "categories": [category for category in categories if category],
        "content": content,
        "content_kind": "summary",
        "metadata": {
            "feed_format": "atom",
            "title": _safe_summary(title),
            "updated_at": _parse_date(updated),
            "published_at": _parse_date(published),
        },
    }


def _json_item_data(
    relative_path: str,
    channel_key: str,
    item: dict[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    title = _text_value(item.get("title"))
    url = _text_value(item.get("url"))
    external_url = _text_value(item.get("external_url"))
    published = _text_value(item.get("date_published"))
    modified = _text_value(item.get("date_modified"))
    base_item_id, identity_source, identity_strength = _item_identity(
        ("id", _text_value(item.get("id"))),
        ("url", url or external_url),
        ("title+date", _title_date_identity(title, published or modified)),
        ordinal=ordinal,
    )
    links = []
    for field, value in (("url", url), ("external_url", external_url)):
        if value:
            links.append({"value": value, "attribute": field})
    enclosures = []
    for attachment in item.get("attachments", []):
        if not isinstance(attachment, dict):
            continue
        attachment_url = _text_value(attachment.get("url"))
        if attachment_url:
            enclosures.append(
                {
                    "url": attachment_url,
                    "mime_type": _text_value(attachment.get("mime_type")),
                    "length": attachment.get("size_in_bytes"),
                    "attribute": "url",
                }
            )
    authors = []
    for author in item.get("authors", []):
        if isinstance(author, dict):
            name = _text_value(author.get("name")) or _text_value(author.get("url"))
            if name:
                authors.append({"name": _safe_label(name)})
    categories = [_safe_label(tag) for tag in item.get("tags", []) if isinstance(tag, str)]
    content = (
        _text_value(item.get("summary"))
        or _text_value(item.get("content_text"))
        or _text_value(item.get("content_html"))
    )
    return {
        "ordinal": ordinal,
        "channel_key": channel_key,
        "base_item_id": base_item_id,
        "identity_source": identity_source,
        "identity_strength": identity_strength,
        "title": title,
        "links": links,
        "enclosures": enclosures,
        "authors": authors,
        "categories": [category for category in categories if category],
        "content": content,
        "content_kind": "content",
        "metadata": {
            "feed_format": "json-feed",
            "title": _safe_summary(title),
            "published_at": _parse_date(published),
            "updated_at": _parse_date(modified),
        },
    }
