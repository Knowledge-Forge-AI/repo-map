"""30-task W4 context-v1 evaluation catalog, 7-arm matrix, and freeze models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from common_lore_index.retrieval.intent_policy import NAVIGATION_INTENTS, NavigationIntent
from repomap_test_support.context_fixture import BINDING_CORE, BINDING_DOCS

CONTEXT_CATALOG_SCHEMA_VERSION = "cloe-context-task-catalog-v1"
CONTEXT_FREEZE_SCHEMA_VERSION = "cloe-context-freeze-v1"
CONTEXT_DECLARATION_SCHEMA_VERSION = "cloe-context-attempt-declaration-v1"
CONTEXT_FIXTURE_ID = "context-v1"
DEFAULT_ATTEMPT_ID = "w4-context-calibration-attempt-1"

TASK_FAMILIES: tuple[str, ...] = (
    "definition",
    "implementation",
    "tests",
    "docs",
    "messages",
    "ambiguous",
    "duplicate_path_identity",
    "relation_expansion",
    "budget_multibyte",
)

EVALUATION_ARMS: tuple[str, ...] = (
    "native_tools_baseline",
    "current_graph_navigation_sqlite",
    "current_graph_navigation_postgres",
    "intent_navigation_sqlite",
    "intent_navigation_postgres",
    "compact_context_16k_sqlite",
    "compact_context_16k_postgres",
)


def canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ContextGoldTarget:
    """One pre-authored gold subject/location target with relevance grade (1..3)."""

    canonical_key: str
    source_binding_id: str
    source_relative_path: str
    relevance_grade: int
    role_expectation: str = "seed_or_neighbor"

    def validate(self) -> "ContextGoldTarget":
        if (
            not self.canonical_key
            or not self.source_binding_id
            or not self.source_relative_path
            or not isinstance(self.relevance_grade, int)
            or isinstance(self.relevance_grade, bool)
            or not (1 <= self.relevance_grade <= 3)
            or self.role_expectation not in {"seed", "neighbor", "seed_or_neighbor"}
        ):
            raise ValueError("invalid ContextGoldTarget")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "canonical_key": self.canonical_key,
            "source_binding_id": self.source_binding_id,
            "source_relative_path": self.source_relative_path,
            "relevance_grade": self.relevance_grade,
            "role_expectation": self.role_expectation,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ContextGoldTarget":
        return cls(
            canonical_key=str(data["canonical_key"]),
            source_binding_id=str(data["source_binding_id"]),
            source_relative_path=str(data["source_relative_path"]),
            relevance_grade=int(data["relevance_grade"]),
            role_expectation=str(data.get("role_expectation", "seed_or_neighbor")),
        ).validate()


@dataclass(frozen=True)
class ContextEvaluationTask:
    """One task in the 30-task context-v1 catalog (20 calibration, 10 held_out)."""

    task_id: str
    task_family: str
    intent: NavigationIntent
    split: str
    query: str | None
    canonical_key: str | None
    mode: str
    scope: str
    kind: str | None
    expand_depth: int
    budget_bytes: int
    expect_ambiguous: bool
    expect_duplicate_path: bool
    gold_targets: tuple[ContextGoldTarget, ...]

    def validate(self) -> "ContextEvaluationTask":
        if not self.task_id or self.intent not in NAVIGATION_INTENTS:
            raise ValueError(f"invalid task_id or intent on {self.task_id!r}")
        if self.task_family not in TASK_FAMILIES:
            raise ValueError(f"invalid task_family {self.task_family!r}")
        if self.split not in {"calibration", "held_out"}:
            raise ValueError(f"invalid split: {self.split!r}")
        if self.mode not in {"exact_identity", "ranked_discovery", "graph_investigation"}:
            raise ValueError(f"invalid mode: {self.mode!r}")
        if not (4096 <= self.budget_bytes <= 65536):
            raise ValueError(f"invalid budget_bytes: {self.budget_bytes}")
        if not self.gold_targets:
            raise ValueError(f"task {self.task_id!r} requires gold_targets")
        for g in self.gold_targets:
            g.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "task_id": self.task_id,
            "task_family": self.task_family,
            "intent": self.intent,
            "split": self.split,
            "query": self.query,
            "canonical_key": self.canonical_key,
            "mode": self.mode,
            "scope": self.scope,
            "kind": self.kind,
            "expand_depth": self.expand_depth,
            "budget_bytes": self.budget_bytes,
            "expect_ambiguous": self.expect_ambiguous,
            "expect_duplicate_path": self.expect_duplicate_path,
            "gold_targets": [g.to_dict() for g in self.gold_targets],
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ContextEvaluationTask":
        return cls(
            task_id=str(data["task_id"]),
            task_family=str(data["task_family"]),
            intent=NavigationIntent(data["intent"]),
            split=str(data["split"]),
            query=data.get("query"),
            canonical_key=data.get("canonical_key"),
            mode=str(data.get("mode", "ranked_discovery")),
            scope=str(data.get("scope", "all")),
            kind=data.get("kind"),
            expand_depth=int(data.get("expand_depth", 0)),
            budget_bytes=int(data.get("budget_bytes", 16384)),
            expect_ambiguous=bool(data.get("expect_ambiguous", False)),
            expect_duplicate_path=bool(data.get("expect_duplicate_path", False)),
            gold_targets=tuple(
                ContextGoldTarget.from_mapping(g) for g in (data.get("gold_targets") or ())
            ),
        ).validate()


@dataclass(frozen=True)
class ContextTaskCatalog:
    """Frozen 30-task (20 calibration, 10 held-out) W4 context evaluation catalog."""

    schema_version: str
    fixture_id: str
    tasks: tuple[ContextEvaluationTask, ...]

    def validate(self) -> "ContextTaskCatalog":
        if self.schema_version != CONTEXT_CATALOG_SCHEMA_VERSION:
            raise ValueError("invalid ContextTaskCatalog schema_version")
        if self.fixture_id != CONTEXT_FIXTURE_ID:
            raise ValueError("invalid ContextTaskCatalog fixture_id")
        if len(self.tasks) != 30:
            raise ValueError(f"expected 30 tasks, got {len(self.tasks)}")
        seen: set[str] = set()
        families: set[str] = set()
        for t in self.tasks:
            t.validate()
            if t.task_id in seen:
                raise ValueError(f"duplicate task_id: {t.task_id}")
            seen.add(t.task_id)
            families.add(t.task_family)
        if families != set(TASK_FAMILIES):
            raise ValueError(f"missing task families: {set(TASK_FAMILIES) - families}")
        if len(self.calibration_tasks()) != 20 or len(self.held_out_tasks()) != 10:
            raise ValueError("expected 20 calibration and 10 held_out tasks")
        return self

    def calibration_tasks(self) -> tuple[ContextEvaluationTask, ...]:
        return tuple(t for t in self.tasks if t.split == "calibration")

    def held_out_tasks(self) -> tuple[ContextEvaluationTask, ...]:
        return tuple(t for t in self.tasks if t.split == "held_out")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "tasks": [t.to_dict() for t in self.tasks],
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ContextTaskCatalog":
        return cls(
            schema_version=str(data["schema_version"]),
            fixture_id=str(data["fixture_id"]),
            tasks=tuple(
                ContextEvaluationTask.from_mapping(item) for item in (data.get("tasks") or ())
            ),
        ).validate()


@dataclass(frozen=True)
class ContextFreezeManifest:
    """Cryptographic freeze manifest for context-v1 and unchanged mixed-v1."""

    schema_version: str
    fixture_id: str
    catalog_sha256: str
    mixed_v1_freeze_sha256: str
    committed_fixture_files: Mapping[str, str]
    policy_digest: str

    def validate(self) -> "ContextFreezeManifest":
        if self.schema_version != CONTEXT_FREEZE_SCHEMA_VERSION:
            raise ValueError("invalid ContextFreezeManifest schema_version")
        for val in (self.catalog_sha256, self.mixed_v1_freeze_sha256, self.policy_digest):
            if not isinstance(val, str) or not val.startswith("sha256:"):
                raise ValueError("expected sha256: digest in ContextFreezeManifest")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "catalog_sha256": self.catalog_sha256,
            "mixed_v1_freeze_sha256": self.mixed_v1_freeze_sha256,
            "committed_fixture_files": dict(sorted(self.committed_fixture_files.items())),
            "policy_digest": self.policy_digest,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ContextFreezeManifest":
        return cls(
            schema_version=str(data["schema_version"]),
            fixture_id=str(data["fixture_id"]),
            catalog_sha256=str(data["catalog_sha256"]),
            mixed_v1_freeze_sha256=str(data["mixed_v1_freeze_sha256"]),
            committed_fixture_files=dict(data["committed_fixture_files"]),
            policy_digest=str(data["policy_digest"]),
        ).validate()


@dataclass(frozen=True)
class ContextAttemptDeclaration:
    """Pre-execution attempt declaration for W4 context-v1 evaluation."""

    schema_version: str
    attempt_id: str
    phase_id: str
    split: str
    freeze_sha256: str
    catalog_sha256: str
    ordered_task_ids: tuple[str, ...]
    arms: tuple[str, ...]
    repetitions_per_task: int
    budget_tiers: tuple[int, ...]

    def validate(self) -> "ContextAttemptDeclaration":
        if self.schema_version != CONTEXT_DECLARATION_SCHEMA_VERSION:
            raise ValueError("invalid ContextAttemptDeclaration schema_version")
        if self.split != "calibration":
            raise ValueError("held_out split is forbidden in attempt declarations")
        if len(self.ordered_task_ids) != 20:
            raise ValueError("calibration attempt requires all 20 calibration task_ids")
        if tuple(self.arms) != EVALUATION_ARMS:
            raise ValueError("attempt declaration must declare all 7 arms")
        if self.repetitions_per_task != 3:
            raise ValueError("w4 calibration requires 3 repetitions per task (420 obs)")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "phase_id": self.phase_id,
            "split": self.split,
            "freeze_sha256": self.freeze_sha256,
            "catalog_sha256": self.catalog_sha256,
            "ordered_task_ids": list(self.ordered_task_ids),
            "arms": list(self.arms),
            "repetitions_per_task": self.repetitions_per_task,
            "budget_tiers": list(self.budget_tiers),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ContextAttemptDeclaration":
        return cls(
            schema_version=str(data["schema_version"]),
            attempt_id=str(data["attempt_id"]),
            phase_id=str(data["phase_id"]),
            split=str(data["split"]),
            freeze_sha256=str(data["freeze_sha256"]),
            catalog_sha256=str(data["catalog_sha256"]),
            ordered_task_ids=tuple(str(x) for x in data["ordered_task_ids"]),
            arms=tuple(str(x) for x in data["arms"]),
            repetitions_per_task=int(data["repetitions_per_task"]),
            budget_tiers=tuple(int(x) for x in data.get("budget_tiers", (4096, 16384, 65536))),
        ).validate()


def _gt(ck: str, bid: str, path: str, grade: int = 3, role: str = "seed_or_neighbor") -> ContextGoldTarget:
    return ContextGoldTarget(ck, bid, path, grade, role)


def build_default_context_v1_catalog() -> ContextTaskCatalog:
    """Construct the canonical 30-task (20 calibration, 10 held-out) context-v1 catalog."""
    g_inv = _gt("py:pkg.billing.InvoiceService", BINDING_CORE, "src/billing/invoice.py", 3, "seed")
    g_tot = _gt("py:pkg.billing.InvoiceService.compute_total", BINDING_CORE, "src/billing/invoice.py", 3, "seed")
    g_val = _gt("py:pkg.billing.validate_invoice", BINDING_CORE, "src/billing/invoice.py", 2, "seed_or_neighbor")
    g_mod = _gt("py:pkg.billing", BINDING_CORE, "src/billing/invoice.py", 2, "seed")
    g_pyt = _gt("py:tests.test_invoice.test_invoice_service", BINDING_CORE, "tests/test_invoice.py", 3, "seed")
    g_bat = _gt("bats.test_case:tests/cli.bats#invokes%20InvoiceService", BINDING_CORE, "tests/cli.bats", 3, "seed")
    g_zun = _gt("zunit.test_case:tests/billing.zunit#InvoiceService", BINDING_CORE, "tests/billing.zunit", 3, "seed")
    g_nix = _gt("nix.check:checks.x86_64-linux.billing", BINDING_CORE, "nix/default.nix", 3, "seed")
    g_adr = _gt("doc:adr/0010-billing-architecture", BINDING_DOCS, "adr/0010-billing.md", 3, "seed")
    g_skl = _gt("doc:skill/billing-ops", BINDING_DOCS, "skills/billing-ops.md", 3, "seed")
    g_pag = _gt("doc:page/billing-guide", BINDING_DOCS, "guides/billing.md", 3, "seed")
    g_sec = _gt("doc:section/billing-guide#invoicing", BINDING_DOCS, "guides/billing.md", 3, "seed")
    g_eml = _gt("email.message:msg-billing-alert", BINDING_DOCS, "messages/rollout.eml", 3, "seed")
    g_fed = _gt("feed.item:feed-billing-release", BINDING_DOCS, "messages/releases.xml", 3, "seed")
    g_amb = _gt("py:pkg.ambig.AlphaHandler", BINDING_CORE, "src/billing/invoice.py", 3, "seed")
    g_dup = _gt("doc:shared/readme-core", BINDING_CORE, "shared/README.md", 3, "seed")
    g_utf = _gt("doc:page/multibyte-Δ-guide", BINDING_DOCS, "guides/billing.md", 3, "seed")

    rows: list[tuple[str, str, str, str, str, tuple[ContextGoldTarget, ...], int, int, bool, bool]] = [
        ("CTX-CAL-01", "definition", "definition", "calibration", "InvoiceService", (g_inv,), 0, 16384, False, False),
        ("CTX-CAL-02", "definition", "definition", "calibration", "validate_invoice", (g_val,), 0, 16384, False, False),
        ("CTX-CAL-03", "definition", "definition", "calibration", "pkg.billing", (g_mod,), 0, 16384, False, False),
        ("CTX-CAL-04", "implementation", "implementation", "calibration", "compute_total", (g_tot,), 0, 16384, False, False),
        ("CTX-CAL-05", "implementation", "implementation", "calibration", "InvoiceService", (g_inv, g_tot), 0, 16384, False, False),
        ("CTX-CAL-06", "tests", "tests", "calibration", "test_invoice_service", (g_pyt,), 0, 16384, False, False),
        ("CTX-CAL-07", "tests", "tests", "calibration", "InvoiceService", (g_bat, g_zun), 0, 16384, False, False),
        ("CTX-CAL-08", "tests", "tests", "calibration", "billing check", (g_nix,), 0, 16384, False, False),
        ("CTX-CAL-09", "docs", "docs", "calibration", "ADR 0010", (g_adr,), 0, 16384, False, False),
        ("CTX-CAL-10", "docs", "docs", "calibration", "Billing Ops Skill", (g_skl,), 0, 16384, False, False),
        ("CTX-CAL-11", "docs", "docs", "calibration", "InvoiceService", (g_sec,), 0, 16384, False, False),
        ("CTX-CAL-12", "messages", "messages", "calibration", "InvoiceService", (g_eml, g_fed), 0, 16384, False, False),
        ("CTX-CAL-13", "messages", "messages", "calibration", "rollout notice", (g_eml,), 0, 16384, False, False),
        ("CTX-CAL-14", "ambiguous", "definition", "calibration", "AlphaHandler", (g_amb,), 0, 16384, True, False),
        ("CTX-CAL-15", "ambiguous", "general", "calibration", "AlphaHandler", (g_amb,), 0, 16384, True, False),
        ("CTX-CAL-16", "duplicate_path_identity", "docs", "calibration", "SharedReadme", (g_dup,), 0, 16384, False, True),
        ("CTX-CAL-17", "relation_expansion", "implementation", "calibration", "compute_total", (g_tot, g_val), 1, 16384, False, False),
        ("CTX-CAL-18", "relation_expansion", "definition", "calibration", "InvoiceService", (g_inv, g_tot), 1, 16384, False, False),
        ("CTX-CAL-19", "budget_multibyte", "docs", "calibration", "Δ-quorum", (g_utf,), 0, 4096, False, False),
        ("CTX-CAL-20", "budget_multibyte", "general", "calibration", "InvoiceService", (g_inv, g_sec), 0, 4096, False, False),
        ("CTX-HELD-01", "definition", "definition", "held_out", "InvoiceService", (g_inv,), 0, 16384, False, False),
        ("CTX-HELD-02", "implementation", "implementation", "held_out", "validate_invoice", (g_val,), 0, 16384, False, False),
        ("CTX-HELD-03", "tests", "tests", "held_out", "cli.bats", (g_bat,), 0, 16384, False, False),
        ("CTX-HELD-04", "docs", "docs", "held_out", "Billing Guide", (g_pag,), 0, 16384, False, False),
        ("CTX-HELD-05", "messages", "messages", "held_out", "v1 release", (g_fed,), 0, 16384, False, False),
        ("CTX-HELD-06", "ambiguous", "implementation", "held_out", "AlphaHandler", (g_amb,), 0, 16384, True, False),
        ("CTX-HELD-07", "duplicate_path_identity", "general", "held_out", "SharedReadme", (g_dup,), 0, 16384, False, True),
        ("CTX-HELD-08", "relation_expansion", "docs", "held_out", "Billing Guide", (g_pag, g_adr), 1, 16384, False, False),
        ("CTX-HELD-09", "budget_multibyte", "docs", "held_out", "Δ-quorum", (g_utf,), 0, 4096, False, False),
        ("CTX-HELD-10", "general" if "general" in TASK_FAMILIES else "definition", "general", "held_out", "InvoiceService", (g_inv,), 0, 16384, False, False),
    ]
    tasks = tuple(
        ContextEvaluationTask(
            task_id=tid, task_family=fam, intent=NavigationIntent(intent), split=split, query=q,
            canonical_key=None, mode="ranked_discovery", scope="all", kind=None,
            expand_depth=exp, budget_bytes=b_bytes, expect_ambiguous=amb,
            expect_duplicate_path=dup, gold_targets=golds,
        ).validate()
        for tid, fam, intent, split, q, golds, exp, b_bytes, amb, dup in rows
    )
    return ContextTaskCatalog(
        schema_version=CONTEXT_CATALOG_SCHEMA_VERSION,
        fixture_id=CONTEXT_FIXTURE_ID,
        tasks=tasks,
    ).validate()
