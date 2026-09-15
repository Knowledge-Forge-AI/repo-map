"""Static local RSS, Atom, and JSON Feed extraction."""

from __future__ import annotations

import json
import re
from typing import Any
from xml.etree import ElementTree
from repomap_kg.extractors.documents.feed_data import (
    _atom_channel_info,
    _atom_item_data,
    _json_channel_info,
    _json_item_data,
    _rss_channel_info,
    _rss_item_data,
)

from repomap_kg.extractors.documents.feed_support import (
    DYNAMIC_REFERENCE_PATTERN,
    EMAIL_PATTERN,
    SAFE_SUMMARY_LIMIT,
    SCRIPT_STYLE_PATTERN,
    SECRET_MARKERS,
    TAG_PATTERN,
    WHITESPACE_PATTERN,
    _atom_link,
    _child_text,
    _children,
    _collapse_text,
    _contains_secret_marker,
    _element_text,
    _first_child,
    _item_identity,
    _local_name,
    _parse_date,
    _reference_target,
    _rss_author,
    _safe_label,
    _safe_summary,
    _slug,
    _strip_html,
    _text_value,
    _title_date_identity,
)
from repomap_kg.graph.keys import (
    feed_author_key,
    feed_category_key,
    feed_channel_key,
    feed_document_key,
    feed_item_key,
)
from repomap_kg.observations.raw import RawObservation


EXTRACTOR_NAME = "repo-feed"
EXTRACTOR_VERSION = "0.1.0"
FEED_XML_SAFETY_MODE = "stdlib-elementtree-prescan-no-external-entities"
JSON_FEED_PARSER = "stdlib-json-local-feed-shape"

UNSAFE_XML_DECLARATION_PATTERN = re.compile(
    r"<!\s*(?:DOCTYPE|ENTITY)\b",
    re.IGNORECASE,
)
UNSAFE_PROCESSING_INSTRUCTION_PATTERN = re.compile(
    r"<\?(?!xml(?:\s|\?>))",
    re.IGNORECASE,
)
FEED_ROOT_PATTERN = re.compile(r"<\s*(?:rss|feed)(?:\s|>|/)", re.IGNORECASE)


def extract_feed_file_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    """Extract feed observations from a local RSS, Atom, or JSON Feed artifact."""
    if _looks_like_feed_xml(content):
        return _extract_xml_feed(relative_path, content)
    json_payload = _parse_json_feed_payload(content)
    if json_payload is None:
        return ()
    return _extract_json_feed(relative_path, json_payload)


def _extract_xml_feed(relative_path: str, content: str) -> tuple[RawObservation, ...]:
    if UNSAFE_XML_DECLARATION_PATTERN.search(content):
        return (
            _parse_error_observation(
                relative_path,
                "unsafe-xml-declaration",
                "feed XML contains a DOCTYPE or ENTITY declaration",
            ),
        )
    if UNSAFE_PROCESSING_INSTRUCTION_PATTERN.search(content):
        return (
            _parse_error_observation(
                relative_path,
                "unsafe-processing-instruction",
                "feed XML contains a non-XML processing instruction",
            ),
        )
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        return (
            _parse_error_observation(
                relative_path,
                "xml-parse-error",
                str(error),
            ),
        )

    root_name = _local_name(root.tag)
    if root_name == "rss":
        return _extract_rss(relative_path, root)
    if root_name == "feed":
        return _extract_atom(relative_path, root)
    return ()


def _extract_rss(relative_path: str, root: ElementTree.Element) -> tuple[RawObservation, ...]:
    channel = _first_child(root, "channel")
    if channel is None:
        return (
            _parse_error_observation(
                relative_path,
                "rss-missing-channel",
                "RSS feed is missing a channel element",
            ),
        )
    document_key = feed_document_key(relative_path)
    channel_info = _rss_channel_info(relative_path, document_key, channel)
    observations = [
        _feed_document_observation(
            relative_path,
            feed_format="rss",
            document_key=document_key,
            top_level_type="rss",
        ),
        _feed_channel_observation(relative_path, channel_info),
    ]
    channel_link = _child_text(channel, "link")
    if channel_link:
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=channel_info["channel_key"],
                raw_target=channel_link,
                target=_reference_target(relative_path, channel_link),
                source_id=f"{relative_path}#feed-channel-link",
                name=channel_link,
                metadata={
                    "feed_format": "rss",
                    "scope": "channel",
                    "attribute": "link",
                    "not_fetched": True,
                },
            )
        )

    items = [_rss_item_data(relative_path, channel_info["channel_key"], item, index) for index, item in enumerate(_children(channel, "item"), start=1)]
    observations.extend(_item_observations(relative_path, "rss", channel_info["channel_key"], items))
    return tuple(observations)


def _extract_atom(relative_path: str, root: ElementTree.Element) -> tuple[RawObservation, ...]:
    document_key = feed_document_key(relative_path)
    channel_info = _atom_channel_info(relative_path, document_key, root)
    observations = [
        _feed_document_observation(
            relative_path,
            feed_format="atom",
            document_key=document_key,
            top_level_type="atom",
        ),
        _feed_channel_observation(relative_path, channel_info),
    ]
    for link in _children(root, "link"):
        href = link.attrib.get("href", "").strip()
        if not href:
            continue
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=channel_info["channel_key"],
                raw_target=href,
                target=_reference_target(relative_path, href),
                source_id=f"{relative_path}#feed-channel-link:{len(observations)}",
                name=href,
                metadata={
                    "feed_format": "atom",
                    "scope": "channel",
                    "attribute": "href",
                    "rel": link.attrib.get("rel", "alternate"),
                    "not_fetched": True,
                },
            )
        )

    entries = [
        _atom_item_data(relative_path, channel_info["channel_key"], entry, index)
        for index, entry in enumerate(_children(root, "entry"), start=1)
    ]
    observations.extend(_item_observations(relative_path, "atom", channel_info["channel_key"], entries))
    return tuple(observations)


def _extract_json_feed(
    relative_path: str,
    payload: dict[str, Any],
) -> tuple[RawObservation, ...]:
    document_key = feed_document_key(relative_path)
    channel_info = _json_channel_info(relative_path, document_key, payload)
    observations = [
        _feed_document_observation(
            relative_path,
            feed_format="json-feed",
            document_key=document_key,
            top_level_type="object",
        ),
        _feed_channel_observation(relative_path, channel_info),
    ]
    for field in ("feed_url", "home_page_url"):
        value = _text_value(payload.get(field))
        if value is None:
            continue
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=channel_info["channel_key"],
                raw_target=value,
                target=_reference_target(relative_path, value),
                source_id=f"{relative_path}#feed-channel-link:{field}",
                name=value,
                metadata={
                    "feed_format": "json-feed",
                    "scope": "channel",
                    "field": field,
                    "not_fetched": True,
                },
            )
        )

    items = [
        _json_item_data(relative_path, channel_info["channel_key"], item, index)
        for index, item in enumerate(payload.get("items", []), start=1)
        if isinstance(item, dict)
    ]
    observations.extend(_item_observations(relative_path, "json-feed", channel_info["channel_key"], items))
    return tuple(observations)


def _item_observations(
    relative_path: str,
    feed_format: str,
    channel_key: str,
    items: list[dict[str, Any]],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    counts: dict[str, int] = {}
    for item in items:
        counts[item["base_item_id"]] = counts.get(item["base_item_id"], 0) + 1
    seen: dict[str, int] = {}
    for item in items:
        base_item_id = item["base_item_id"]
        seen[base_item_id] = seen.get(base_item_id, 0) + 1
        duplicate_identity = counts[base_item_id] > 1
        if duplicate_identity:
            item_id = f"{base_item_id}:duplicate-{seen[base_item_id]}"
        else:
            item_id = base_item_id
        item_key = feed_item_key(channel_key, item_id)
        item_metadata = {
            key: value
            for key, value in item["metadata"].items()
            if value is not None
        }
        item_metadata["channel_key"] = channel_key
        item_metadata["identity_source"] = item["identity_source"]
        item_metadata["identity_strength"] = item["identity_strength"]
        if duplicate_identity:
            item_metadata["duplicate_identity"] = True
            item_metadata["duplicate_disambiguator"] = f"duplicate-{seen[base_item_id]}"
        observations.append(
            _obs(
                kind="feed.item",
                source_id=f"{relative_path}#feed-item:{item['ordinal']}",
                path=relative_path,
                target=item_key,
                name=item.get("title") or item_id,
                confidence="extracted",
                metadata=item_metadata,
            )
        )
        observations.extend(
            _item_reference_observations(
                relative_path,
                feed_format,
                item_key,
                item,
            )
        )
    return observations


def _item_reference_observations(
    relative_path: str,
    feed_format: str,
    item_key: str,
    item: dict[str, Any],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for index, link in enumerate(item["links"], start=1):
        observations.append(
            _reference_observation(
                kind="feed.link",
                relative_path=relative_path,
                source_key=item_key,
                raw_target=link["value"],
                target=_reference_target(relative_path, link["value"]),
                source_id=f"{relative_path}#feed-item:{item['ordinal']}:link:{index}",
                name=link["value"],
                metadata={
                    "feed_format": feed_format,
                    "scope": "item",
                    "attribute": link.get("attribute", "link"),
                    "rel": link.get("rel"),
                    "not_fetched": True,
                },
            )
        )
    for index, enclosure in enumerate(item["enclosures"], start=1):
        observations.append(
            _reference_observation(
                kind="feed.enclosure",
                relative_path=relative_path,
                source_key=item_key,
                raw_target=enclosure["url"],
                target=_reference_target(relative_path, enclosure["url"]),
                source_id=f"{relative_path}#feed-item:{item['ordinal']}:enclosure:{index}",
                name=enclosure["url"],
                metadata={
                    "feed_format": feed_format,
                    "scope": "item",
                    "attribute": enclosure.get("attribute", "url"),
                    "mime_type": enclosure.get("mime_type"),
                    "length": enclosure.get("length"),
                    "not_fetched": True,
                },
            )
        )
    for index, author in enumerate(item["authors"], start=1):
        observations.append(
            _feed_author_observation(
                relative_path,
                channel_key=item["channel_key"],
                item_key=item_key,
                feed_format=feed_format,
                ordinal=item["ordinal"],
                index=index,
                author=author,
            )
        )
    for index, category in enumerate(item["categories"], start=1):
        observations.append(
            _feed_category_observation(
                relative_path,
                channel_key=item["channel_key"],
                item_key=item_key,
                feed_format=feed_format,
                ordinal=item["ordinal"],
                index=index,
                category=category,
            )
        )
    if item.get("content"):
        observations.append(
            _feed_content_observation(
                relative_path,
                item_key=item_key,
                feed_format=feed_format,
                ordinal=item["ordinal"],
                content=item["content"],
                content_kind=item["content_kind"],
            )
        )
    return observations


def _feed_document_observation(
    relative_path: str,
    *,
    feed_format: str,
    document_key: str,
    top_level_type: str,
) -> RawObservation:
    return _obs(
        kind="feed.document",
        source_id=f"{relative_path}#feed-document",
        path=relative_path,
        target=document_key,
        name=relative_path,
        confidence="extracted",
        metadata={
            "feed_format": feed_format,
            "parser": EXTRACTOR_NAME,
            "parser_mode": FEED_XML_SAFETY_MODE if feed_format in ("rss", "atom") else JSON_FEED_PARSER,
            "top_level_type": top_level_type,
        },
    )


def _feed_channel_observation(relative_path: str, channel_info: dict[str, Any]) -> RawObservation:
    metadata = {
        "feed_format": channel_info["feed_format"],
        "document_key": channel_info["document_key"],
        "identity_source": channel_info["identity_source"],
        "identity_strength": channel_info["identity_strength"],
        "title": _safe_summary(channel_info.get("title")),
        "updated_at": channel_info.get("updated_at"),
    }
    return _obs(
        kind="feed.channel",
        source_id=f"{relative_path}#feed-channel",
        path=relative_path,
        target=channel_info["channel_key"],
        name=channel_info.get("title") or relative_path,
        confidence="extracted",
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _feed_author_observation(
    relative_path: str,
    *,
    channel_key: str,
    item_key: str,
    feed_format: str,
    ordinal: int,
    index: int,
    author: dict[str, Any],
) -> RawObservation:
    name = _safe_label(author.get("name")) or "unknown-author"
    return _obs(
        kind="feed.author",
        source_id=f"{relative_path}#feed-item:{ordinal}:author:{index}",
        path=relative_path,
        target=feed_author_key(channel_key, name),
        name=name,
        confidence="extracted",
        metadata={
            "feed_format": feed_format,
            "channel_key": channel_key,
            "item_key": item_key,
            "name": name,
            "email_redacted": bool(author.get("email_redacted")),
        },
    )


def _feed_category_observation(
    relative_path: str,
    *,
    channel_key: str,
    item_key: str,
    feed_format: str,
    ordinal: int,
    index: int,
    category: str,
) -> RawObservation:
    label = _safe_label(category) or "unknown-category"
    return _obs(
        kind="feed.category",
        source_id=f"{relative_path}#feed-item:{ordinal}:category:{index}",
        path=relative_path,
        target=feed_category_key(channel_key, label),
        name=label,
        confidence="extracted",
        metadata={
            "feed_format": feed_format,
            "channel_key": channel_key,
            "item_key": item_key,
            "name": label,
        },
    )


def _feed_content_observation(
    relative_path: str,
    *,
    item_key: str,
    feed_format: str,
    ordinal: int,
    content: str,
    content_kind: str,
) -> RawObservation:
    summary = _safe_summary(content)
    redacted = summary is None and bool(content)
    metadata: dict[str, Any] = {
        "feed_format": feed_format,
        "item_key": item_key,
        "content_kind": content_kind,
        "content_policy": "summarized-not-rendered",
        "redacted": redacted,
        "original_length": len(content),
    }
    if summary is not None:
        metadata["value_summary"] = summary
    if redacted:
        metadata["redaction_reason"] = "secret-prone-content"
    return _obs(
        kind="feed.content",
        source_id=f"{relative_path}#feed-item:{ordinal}:content",
        path=relative_path,
        confidence="extracted",
        metadata=metadata,
    )


def _reference_observation(
    *,
    kind: str,
    relative_path: str,
    source_key: str,
    raw_target: str,
    target: str,
    source_id: str,
    name: str,
    metadata: dict[str, Any],
) -> RawObservation:
    safe_metadata = {
        key: value for key, value in metadata.items() if value is not None
    }
    safe_metadata["source_key"] = source_key
    safe_metadata["raw_target_summary"] = _safe_summary(raw_target)
    safe_metadata["target_kind"] = target.partition(":")[0]
    return _obs(
        kind=kind,
        source_id=source_id,
        path=relative_path,
        target=target,
        name=name,
        confidence="extracted",
        metadata=safe_metadata,
    )


def _parse_error_observation(
    relative_path: str,
    error_kind: str,
    message: str,
) -> RawObservation:
    return _obs(
        kind="feed.parse_error",
        source_id=f"{relative_path}#feed-parse-error:{error_kind}",
        path=relative_path,
        confidence="unknown",
        metadata={
            "feed_format": "unknown",
            "error_kind": error_kind,
            "message": _safe_summary(message) or error_kind,
            "raw_only": True,
        },
    )


def _obs(
    *,
    kind: str,
    source_id: str,
    path: str,
    confidence: str,
    metadata: dict[str, Any],
    name: str | None = None,
    target: str | None = None,
) -> RawObservation:
    return RawObservation(
        kind=kind,
        source_id=source_id,
        path=path,
        confidence=confidence,
        extractor=EXTRACTOR_NAME,
        extractor_version=EXTRACTOR_VERSION,
        name=name,
        target=target,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _parse_json_feed_payload(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if not _is_json_feed_payload(payload):
        return None
    return payload


def _is_json_feed_payload(payload: dict[str, Any]) -> bool:
    version = payload.get("version")
    title = payload.get("title")
    items = payload.get("items")
    return (
        isinstance(version, str)
        and "jsonfeed" in version.lower()
        and isinstance(title, str)
        and isinstance(items, list)
    )


def _looks_like_feed_xml(content: str) -> bool:
    return bool(FEED_ROOT_PATTERN.search(content))
