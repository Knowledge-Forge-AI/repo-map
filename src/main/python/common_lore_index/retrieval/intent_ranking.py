"""Six-tier deterministic intent ranking and byte tie-breaking (W4 Epic A §3.3)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from common_lore_index.retrieval.intent_policy import compute_affinity_tier

CANONICAL_KEY_ORDER_VERSION = "canonical-key-asc-v1"
CANONICAL_KEY_ASC_POLICY_VERSION = CANONICAL_KEY_ORDER_VERSION

MATCH_CLASS_REASONS: dict[int, str] = {
    0: "display_exact",
    1: "display_casefold_exact",
    2: "key_terminal_exact",
    3: "display_prefix",
    4: "display_substring",
    5: "key_substring",
    6: "kind_only",
}

EVIDENCE_TIER_REASONS: dict[int, str] = {
    0: "direct_verified",
    1: "direct_unverified",
    2: "no_direct_evidence",
    3: "identity_withheld",
}

PUBLICATION_TIER_REASONS: dict[int, str] = {
    0: "current_publication",
    1: "historical_publication",
}


def _is_non_word_boundary(text: str, suffix_len: int) -> bool:
    if len(text) == suffix_len:
        return True
    if len(text) < suffix_len:
        return False
    prev = text[len(text) - suffix_len - 1]
    return not (prev.isalnum() or prev == "_")


def classify_match_class(
    *,
    query_text: str | None,
    canonical_key: str,
    display_name: str | None,
) -> tuple[int, str]:
    """Return (match_class_tier, match_class_code) for a candidate node."""
    q = (query_text or "").strip()
    if not q:
        return 6, "kind_only"
    q_cf = q.casefold()
    ck_cf = canonical_key.casefold()

    if display_name is not None and display_name != "":
        if display_name == q:
            return 0, "display_exact"
        disp_cf = display_name.casefold()
        if disp_cf == q_cf:
            return 1, "display_casefold_exact"
    else:
        disp_cf = ""

    if (canonical_key.endswith(q) and _is_non_word_boundary(canonical_key, len(q))) or (
        ck_cf.endswith(q_cf) and _is_non_word_boundary(ck_cf, len(q_cf))
    ):
        return 2, "key_terminal_exact"

    if disp_cf:
        if disp_cf.startswith(q_cf):
            return 3, "display_prefix"
        if q_cf in disp_cf:
            return 4, "display_substring"

    if q_cf in ck_cf:
        return 5, "key_substring"
    return 6, "kind_only"


def first_verified_destination_tuple(
    verified_destinations: Sequence[Mapping[str, Any]],
) -> tuple[Any, ...]:
    """Return the minimum deterministic byte/int tuple over verified _destination dicts."""
    if not verified_destinations:
        return (1, b"", 0, b"", b"", 0, b"", b"", b"", 2**31 - 1, 2**31 - 1)
    tuples: list[tuple[Any, ...]] = []
    for dest in verified_destinations:
        s_line = dest.get("start_line")
        e_line = dest.get("end_line")
        tuples.append(
            (
                0,
                str(dest.get("source_binding_id") or "").encode("utf-8"),
                int(dest.get("binding_revision") or 0),
                str(dest.get("snapshot_id") or "").encode("utf-8"),
                str(dest.get("source_relative_path") or "").encode("utf-8"),
                int(dest.get("run_id") or 0),
                str(dest.get("publication_relation") or "").encode("utf-8"),
                str(dest.get("path_namespace") or "").encode("utf-8"),
                str(dest.get("graph_path") or "").encode("utf-8"),
                int(s_line) if isinstance(s_line, int) else 2**31 - 1,
                int(e_line) if isinstance(e_line, int) else 2**31 - 1,
            )
        )
    return min(tuples)


@dataclass(frozen=True, slots=True)
class CandidateRankingInput:
    """Normalized candidate input for deterministic W4 ranking."""

    canonical_key: str
    kind: str
    display_name: str | None
    subject_family: str
    has_direct_evidence: bool
    has_verified_direct_location: bool
    identity_withheld: bool
    is_current_publication: bool
    first_verified_destination: tuple[Any, ...] = (1, b"", 0, b"", b"", 0, b"", b"", b"", 2**31 - 1, 2**31 - 1)
    payload: dict[str, Any] | None = None

    @property
    def tie_break_key(self) -> tuple[bytes, tuple[Any, ...]]:
        return (self.canonical_key.encode("utf-8"), self.first_verified_destination)


@dataclass(frozen=True, slots=True)
class RankTiers:
    """5-tier ordinal tuple for one ranked seed candidate."""

    exactness_tier: int
    affinity_tier: int
    match_class_tier: int
    evidence_tier: int
    publication_tier: int

    def as_tuple(self) -> tuple[int, int, int, int, int]:
        return (
            self.exactness_tier,
            self.affinity_tier,
            self.match_class_tier,
            self.evidence_tier,
            self.publication_tier,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "exactness_tier": self.exactness_tier,
            "affinity_tier": self.affinity_tier,
            "match_class_tier": self.match_class_tier,
            "evidence_tier": self.evidence_tier,
            "publication_tier": self.publication_tier,
        }


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """Candidate paired with its 1-based rank, tiers, and closed explanation codes."""

    candidate: CandidateRankingInput
    rank: int
    match_class: str
    tiers: RankTiers
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AmbiguityDisclosure:
    """Ambiguity disclosure for top tied candidates."""

    status: str
    tied_top_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "tied_top_count": self.tied_top_count}


def _evaluate_candidate(
    cand: CandidateRankingInput, *, query: str, intent: str | None
) -> tuple[RankTiers, str, tuple[str, ...]]:
    aff_tier, aff_reason = compute_affinity_tier(intent, cand.kind, cand.subject_family)
    mc_tier, mc_reason = classify_match_class(
        query_text=query, canonical_key=cand.canonical_key, display_name=cand.display_name
    )
    ex_tier = 0 if mc_tier in {0, 1, 2} else 1
    ex_reason = "exact_match_group" if ex_tier == 0 else "partial_match_group"

    if cand.identity_withheld:
        ev_tier = 3
    elif cand.has_verified_direct_location:
        ev_tier = 0
    elif cand.has_direct_evidence:
        ev_tier = 1
    else:
        ev_tier = 2
    ev_reason = EVIDENCE_TIER_REASONS[ev_tier]

    pub_tier = 0 if cand.is_current_publication else 1
    pub_reason = PUBLICATION_TIER_REASONS[pub_tier]

    tiers = RankTiers(
        exactness_tier=ex_tier,
        affinity_tier=aff_tier,
        match_class_tier=mc_tier,
        evidence_tier=ev_tier,
        publication_tier=pub_tier,
    )
    return tiers, mc_reason, (ex_reason, aff_reason, mc_reason, ev_reason, pub_reason)


def rank_candidates(
    candidates: Sequence[CandidateRankingInput],
    *,
    query: str,
    intent: str | None = "general",
) -> tuple[tuple[RankedCandidate, ...], AmbiguityDisclosure]:
    """Order candidates under cloe-intent-rank-v1 and compute top-tier ambiguity."""
    scored = [
        (cand, *_evaluate_candidate(cand, query=query, intent=intent))
        for cand in candidates
    ]
    scored.sort(key=lambda item: (item[1].as_tuple(), item[0].tie_break_key))
    ranked = tuple(
        RankedCandidate(
            candidate=cand, rank=idx + 1, match_class=mc_reason, tiers=tiers, reasons=reasons
        )
        for idx, (cand, tiers, mc_reason, reasons) in enumerate(scored)
    )
    if len(ranked) >= 2:
        top3 = (
            ranked[0].tiers.exactness_tier,
            ranked[0].tiers.affinity_tier,
            ranked[0].tiers.match_class_tier,
        )
        tied = sum(
            1
            for rc in ranked
            if (rc.tiers.exactness_tier, rc.tiers.affinity_tier, rc.tiers.match_class_tier) == top3
        )
        if tied >= 2:
            return ranked, AmbiguityDisclosure(status="ambiguous", tied_top_count=tied)
    return ranked, AmbiguityDisclosure(status="unambiguous", tied_top_count=0)


def order_candidates_canonical_key_asc(
    candidates: Sequence[CandidateRankingInput],
) -> tuple[tuple[RankedCandidate, ...], AmbiguityDisclosure]:
    """Order candidates strictly by cloe-intent-tiebreak-v1 (canonical-key-asc-v1)."""
    ordered_in = sorted(candidates, key=lambda c: c.tie_break_key)
    ranked = tuple(
        RankedCandidate(
            candidate=cand,
            rank=idx + 1,
            match_class="kind_only",
            tiers=RankTiers(1, 1, 6, 0 if cand.has_verified_direct_location else 2, 0 if cand.is_current_publication else 1),
            reasons=("canonical_key_asc",),
        )
        for idx, cand in enumerate(ordered_in)
    )
    return ranked, AmbiguityDisclosure(status="unambiguous", tied_top_count=0)
