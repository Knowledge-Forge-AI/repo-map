"""Real offline feed publications for SQLite Local source/feed parity (PRODUCT3-SQLITE-LOCAL5).

``acquire_feed_runs`` runs the production feed acquisition
(``ingest_feed_source``) four times with an offline fetcher returning the
checked-in ``feed_static_basic`` bodies and fixed clocks. Nothing is fetched;
artifacts are retained under the caller's temporary root. The runs are:

* ``rss1`` -- the RSS source's first run (five items, links, an enclosure,
  authors, categories, duplicate and weak identity, undated items);
* ``atom1`` -- a second source type with the ``allowed`` policy status;
* ``secret1`` -- the secret-bearing config (a ``[credentials]`` table the
  loader redacts) over a body carrying a secret-looking description;
* ``rss2`` -- the RSS source's later run over the malformed body, a real
  ``feed.parse_error`` and the RSS source's newest acquisition.

``feed_bundle`` canonicalizes observations through the production
``build_staged_rows`` into one validated portable bundle. Generation 1 is
rss1 + atom1 + secret1; generation 2 re-extracts those and adds rss2, the way
a refresh re-reads every retained artifact. Nothing here writes a row by hand.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.extractors.documents.feed import extract_feed_file_observations
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.source import FeedFetchResponse, FeedIngestionSummary, ingest_feed_source
from repomap_kg.storage.staged_ingestion import build_staged_rows
from repomap_kg.storage.staging_family_contracts import PrivacyClassification

FIXTURES = Path(__file__).parents[3] / "fixtures"
FEED_BODIES = FIXTURES / "discovery" / "feed_static_basic"
FEED_CONFIGS = FIXTURES / "source_ingestion" / "feed_sources"
RSS, ATOM, SECRET = "example-rss-feed", "example-atom-feed", "example-secret-bearing-feed"
# (run name, config, body, content type, acquisition clock)
FEED_RUNS: tuple[tuple[str, str, str, str, datetime], ...] = (
    ("rss1", "allowed-rss.toml", "rss.xml", "application/rss+xml", datetime(2026, 6, 30, 12, tzinfo=UTC)),
    ("atom1", "allowed-atom.toml", "atom.xml", "application/atom+xml", datetime(2026, 6, 29, 8, tzinfo=UTC)),
    ("secret1", "secret-bearing.toml", "secret-feed.xml", "application/rss+xml",
     datetime(2026, 6, 28, 8, tzinfo=UTC)),
    ("rss2", "allowed-rss.toml", "malformed-rss.xml", "application/rss+xml",
     datetime(2026, 7, 1, 12, tzinfo=UTC)),
)
GENERATIONS = {1: ("rss1", "atom1", "secret1"), 2: ("rss1", "atom1", "secret1", "rss2")}
# Strings the read path must never return.
SECRET_MARKERS = ("fixture-feed-secret", "fixture-secret-placeholder")


def _offline(response: FeedFetchResponse) -> Callable[[Any], FeedFetchResponse]:
    def fetch(_config: Any) -> FeedFetchResponse:
        return response

    return fetch


def _fixed(when: datetime) -> Callable[[], datetime]:
    def now() -> datetime:
        return when

    return now


def acquire_feed_runs(root: Path) -> dict[str, FeedIngestionSummary]:
    """The four offline acquisitions, retained under ``root/.repomap/source-artifacts``."""
    root.mkdir(parents=True, exist_ok=True)
    runs: dict[str, FeedIngestionSummary] = {}
    for name, config, body, content_type, when in FEED_RUNS:
        response = FeedFetchResponse(
            status=200,
            headers={"content-type": content_type},
            body=(FEED_BODIES / body).read_bytes(),
        )
        runs[name] = ingest_feed_source(
            FEED_CONFIGS / config,
            root_path=root,
            fetcher=_offline(response),
            clock=_fixed(when),
        )
    return runs


def generation_observations(
    runs: dict[str, FeedIngestionSummary], generation: int
) -> tuple[RawObservation, ...]:
    return tuple(
        observation for name in GENERATIONS[generation] for observation in runs[name].raw_observations
    )


def _crafted_metadata(index: int, observation: RawObservation, *, alpha: bool) -> dict[str, object]:
    """Comparison-only source metadata: NULLs, text-vs-number spellings, filters, flags."""
    metadata: dict[str, object] = {
        **observation.metadata,
        "source_id_configured": "crafted-alpha" if alpha else "crafted-beta",
        "source_type": "feed.atom" if index == 1 else "feed.rss",
        "source_policy_status": "allowed" if index % 2 else "allowed_with_limits",
        "source_artifact_path": f"crafted/{'alpha' if alpha else 'beta'}/rss.xml",
        "acquisition_url_summary": "https://example.invalid/crafted.xml",
    }
    if alpha:
        run = ("r1", "r2", None)[index % 3]
        metadata["source_display_name"] = "Crafted Alpha"
        if run is not None:
            metadata["source_run_id"] = run
            metadata["source_artifact_id"] = f"artifact-{run}-{index % 2}"
        if run == "r1":  # numeric MAX differs from text MAX; one HTTP status spelled as text
            metadata["source_acquired_at"] = "2026-01-02T00:00:00Z"
            metadata["source_artifact_bytes"] = "999" if index % 2 else 1000
            metadata["acquisition_http_status"] = "201" if index % 2 else 200
        elif run is None:  # the newest rows carry no run id, so latest_source_run_id is NULL
            metadata["source_acquired_at"] = "2026-01-03T00:00:00Z"
    if observation.kind in {"feed.link", "feed.enclosure"}:
        metadata["scope"] = "link" if observation.kind == "feed.link" else "enclosure"
        spelling = ("yes", "off", None)[index % 3]
        if spelling is None:
            metadata.pop("not_fetched", None)
        else:
            metadata["not_fetched"] = spelling
    if observation.kind == "feed.item":
        metadata["duplicate_identity"] = ("t", "0", "on")[index % 3]
    return metadata


def crafted_feed_observations() -> tuple[RawObservation, ...]:
    """Comparison-only corpus (never acceptance data) for differential edge cases.

    Real extraction of the RSS body under two paths, re-annotated with crafted
    source metadata: missing acquisition times and run ids, byte lengths and
    HTTP statuses spelled as text or numbers, ``link``/``enclosure`` reference
    scopes (the current extractor only writes ``item``/``channel``), missing or
    spelled ``not_fetched`` and ``duplicate_identity`` values.
    """
    body = (FEED_BODIES / "rss.xml").read_text(encoding="utf-8")
    crafted: list[RawObservation] = []
    for alpha in (True, False):
        path = f"crafted/{'alpha' if alpha else 'beta'}/rss.xml"
        for index, observation in enumerate(extract_feed_file_observations(path, body)):
            crafted.append(replace(observation, metadata=_crafted_metadata(index, observation, alpha=alpha)))
    return tuple(crafted)


def feed_bundle(
    graph_id: str, generation: int, observations: Sequence[RawObservation]
) -> PublicationBundle:
    """Production canonicalization of ``observations`` as generation ``generation``'s bundle."""
    prepared = build_staged_rows(tuple(observations), repository_name=graph_id, stage_id="stage-unassigned")
    try:
        families = {
            family: tuple(dict(row) for row in prepared.family_rows[family])
            for family in PUBLICATION_FAMILIES
        }
    finally:
        prepared.close()
    digit = str(generation)
    return PublicationBundle.create(
        request_id=f"job-{graph_id}-{generation}",
        job_id=f"job-{graph_id}-{generation}",
        attempt=1,
        graph_id=graph_id,
        candidate_id="cand1:" + digit * 64,
        snapshot_manifest_id="snapmanifest1:" + digit * 64,
        snapshot_vector=(("bind1:" + "3" * 64, generation, "snap1:" + digit * 64),),
        source_generation="sg1:" + digit * 64,
        config_generation="cg1:" + "6" * 64,
        extractor_generation="eg1:" + "7" * 64,
        canonicalizer_generation="kg1:" + "8" * 64,
        extractor_capability_identity="cap1:python-static-v1",
        resolver_identity="resolver1:nix-static-v2",
        canonicalizer_identity="canon1:graph-key-v1-binding-path",
        semantic_contract_identity="semantic1:multi-source-v1",
        quality_rule_identity="quality1:default",
        privacy=PrivacyClassification.CANONICAL_PROVENANCE,
        families=families,
        row_stage_contract="stage-unassigned-v1",
    )


__all__ = (
    "ATOM",
    "FEED_RUNS",
    "GENERATIONS",
    "RSS",
    "SECRET",
    "SECRET_MARKERS",
    "acquire_feed_runs",
    "crafted_feed_observations",
    "feed_bundle",
    "generation_observations",
)
