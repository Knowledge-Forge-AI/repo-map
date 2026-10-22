"""Strict forward-only replay of exact historical projection edges (ADR 0084)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from ci.public_author_correction_history import load_author_correction
from ci.retained_python_comparison import selection_delta
from ci.retained_python_git import blob, is_ancestor, parents
from ci.retained_python_projection_evidence import (
    EVIDENCE_PATH, authenticate, document, read_file, require, state_document,
)
from ci.retained_python_projection_history import (
    load_history, projection_governing_paths as projection_governing_paths,
)
from ci.retained_python_records import (
    BaselineDocument, ScopeTransitionRecord, scope_record_key, validate_scope_registry_records,
)
from ci.retained_python_selection import selection_digest

Key = tuple[str, str, str, str]
Audit = Callable[[BaselineDocument, BaselineDocument, object, Callable[[str], str | None]], Key | None]


def _key(before: BaselineDocument, after: BaselineDocument) -> Key:
    return (before["ownership"]["sha256"], after["ownership"]["sha256"],
            selection_digest(before), selection_digest(after))


def _unique_chain(records: Sequence[ScopeTransitionRecord], start: tuple[str, str],
                  end: tuple[str, str]) -> list[Key]:
    graph: dict[tuple[str, str], list[tuple[tuple[str, str], Key]]] = {}
    for record in records:
        a, b, c, d = scope_record_key(record)
        graph.setdefault((a, c), []).append(((b, d), (a, b, c, d)))
    paths: list[list[Key]] = []

    def walk(node: tuple[str, str], seen: set[tuple[str, str]], chain: list[Key]) -> None:
        require(node not in seen, "record chain contains a cycle")
        if node == end:
            paths.append(chain)
            require(len(paths) <= 1, "record chain is ambiguous")
        for target, key in graph.get(node, []):
            walk(target, seen | {node}, [*chain, key])

    walk(start, set(), [])
    require(len(paths) == 1, "record chain is discontinuous")
    return paths[0]


class ProjectionProofLedger:
    def __init__(self, root: Path, head: str, genesis: str, baseline: str, scopes: str,
                 audit: Audit) -> None:
        self.root, self.baseline, self.scopes, self.audit = root, baseline, scopes, audit
        proofs = load_history(root, head, genesis)
        # Original edge strings stay immutable; only authenticated corrected IDs are looked up.
        correction = load_author_correction(root, head)
        self.proofs = {(correction.resolve(p["commit"]), correction.resolve(p["parent"])): p
                       for p in proofs}
        require(len(self.proofs) == len(proofs), "edge is ambiguous after author correction")
        self.consumed: set[tuple[str, str]] = set()
        self.proof_keys: set[Key] = set()
        self.direct_keys: set[Key] = set()
        for commit, parent in self.proofs:
            require(is_ancestor(root, genesis, commit) and is_ancestor(root, genesis, parent),
                    "edge is outside genesis history")
            require(parent in parents(root, commit), "edge parent mismatch")

    def direct(self, before: BaselineDocument, after: BaselineDocument, registry: object,
               authority: Callable[[str], str | None]) -> Key | None:
        result = self.audit(before, after, registry, authority)
        if result is not None:
            require(result not in self.proof_keys, "record consumed twice")
            self.direct_keys.add(result)
        return result

    def _state(self, revision: str, declaration: dict) -> BaselineDocument:
        raw = blob(self.root, revision, self.baseline)
        require(raw is not None, "endpoint baseline is missing")
        assert raw is not None
        ownership_path = document(raw).get("ownership", {}).get("manifest_path")
        require(isinstance(ownership_path, str), "endpoint ownership path is invalid")
        ownership = blob(self.root, revision, ownership_path)
        require(ownership is not None, "endpoint ownership is missing")
        assert ownership is not None
        return state_document(raw, ownership, declaration)

    def _intermediate(self, declaration: dict, hop: dict) -> BaselineDocument:
        raw = read_file(self.root, f"{EVIDENCE_PATH}/{declaration['baseline_sha256']}.json")
        ownership = read_file(self.root, f"{EVIDENCE_PATH}/{declaration['ownership_sha256']}.json")
        state = state_document(raw, ownership, declaration)
        ownership_path = state["ownership"]["manifest_path"]
        require(ownership_path != self.baseline, "ownership path overlaps baseline")
        authenticate(self.root, hop["source_commit"], hop["source_objects"],
                     {self.baseline: raw, ownership_path: ownership})
        return state

    def authorize(self, commit: str, parent: str, before: BaselineDocument,
                  after: BaselineDocument, registry: object,
                  authority: Callable[[str], str | None]) -> set[Key]:
        edge = (commit, parent)
        proof = self.proofs.get(edge)
        if proof is None:
            result = self.direct(before, after, registry, authority)
            return {result} if result is not None else set()
        require(edge not in self.consumed, "edge consumed twice")
        records = list(validate_scope_registry_records(registry))
        # Count exact direct matches without invoking an audit that must reject the projection.
        require(not any(scope_record_key(r) == _key(before, after) for r in records),
                "conflicts with direct authority")
        changes, _, restricted = selection_delta(before, after)
        require(restricted or before["ownership"] != after["ownership"], "edge needs no authority")
        # Replay the edge's policy/debt checks using no authority requirement: a temporary
        # exact record is NEVER used. Per-hop replay below and explicit checks own policy.
        from ci.retained_python_comparison import additions_have_debt, has_upward_debt
        require(before["tools"] == after["tools"], "edge tool policy changed")
        require(before["selection"]["tiers"] == after["selection"]["tiers"]
                and before["selection"]["ownership_classes"] == after["selection"]["ownership_classes"],
                "edge selection policy changed")
        require(not additions_have_debt(selection_delta(before, after)[1], after)
                and not has_upward_debt(before, after), "edge increased debt")
        declarations, hops = proof["states"], proof["hops"]
        states = [self._state(parent, declarations[0])]
        states.extend(self._intermediate(state, hops[i])
                      for i, state in enumerate(declarations[1:-1], 1))
        states.append(self._state(commit, declarations[-1]))
        require(states[0] == before and states[-1] == after, "endpoint states mismatch")
        inherited: set[Key] = set()
        for prior in parents(self.root, commit):
            raw = blob(self.root, prior, self.scopes)
            if raw is not None:
                inherited.update(scope_record_key(r) for r in validate_scope_registry_records(document(raw)))
        candidates = [r for r in records if scope_record_key(r) not in inherited]
        actual = [_key(a, b) for a, b in zip(states, states[1:])]
        chain = _unique_chain(candidates, (actual[0][0], actual[0][2]),
                              (actual[-1][1], actual[-1][3]))
        require(chain == actual and len(set(actual)) == len(actual), "declared record chain mismatch")
        require(set(chain) == {scope_record_key(r) for r in candidates}, "contains unused records")
        all_changes: list[dict] = []
        modules: set[str] = set()
        for a, b, hop, key in zip(states, states[1:], hops, actual):
            matches = [r for r in candidates if scope_record_key(r) == key]
            require(len(matches) == 1, "record match is ambiguous")
            record = matches[0]
            require(record["phase"] == hop["phase"] and record.get("source_commit") == hop["source_commit"]
                    and record.get("source_manifest_sha256") == a["ownership"]["sha256"],
                    "record source binding mismatch")
            require(key not in self.proof_keys | self.direct_keys, "record consumed twice")
            require(self.audit(a, b, registry, authority) == key, "hop lacks exact authority")
            delta = selection_delta(a, b)[0]
            for change in delta:
                item = change["old"] or change["new"]
                assert item is not None
                require(item["module"] not in modules, "hop changes overlap")
                modules.add(item["module"])
                all_changes.append(dict(change))
            self.proof_keys.add(key)
        order = lambda change: (change["old"] or change["new"])["module"]
        require(sorted(all_changes, key=order) == sorted(changes, key=order), "hop union differs from edge")
        self.consumed.add(edge)
        return set(actual)

    def finish(self) -> None:
        require(self.consumed == set(self.proofs), "contains unused authority")


def load_projection_proofs(repo_root: Path, *, head: str, genesis: str, baseline: str,
                           scopes: str, audit: Audit) -> ProjectionProofLedger:
    return ProjectionProofLedger(repo_root, head, genesis, baseline, scopes, audit)
