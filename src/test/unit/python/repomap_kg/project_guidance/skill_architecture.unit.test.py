import ast
import os
import re
from pathlib import Path

from repomap_kg.extractors.documents.markdown_structure import parse_frontmatter
from repomap_kg.graph.discovery import discover_repository


REPO_ROOT = Path(__file__).resolve().parents[6]
CANONICAL_ROOTS = (
    REPO_ROOT / "docs/ops/skills",
    REPO_ROOT / "docs/contrib/skills",
)
PROJECTION_ROOTS = (
    REPO_ROOT / ".agents/skills",
    REPO_ROOT / ".claude/skills",
)
EXPECTED_SKILLS = frozenset(
    {
        "repomap-cli-workflow",
        "repomap-mcp-configuration",
        "repomap-mcp-readback",
        "repomap-mcp-smoke-test",
        "repomap-phase-hygiene",
        "repo-map-development-standards",
        "repo-map-testing-standards",
    }
)
ROOT_GUIDANCE = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "README.md",
)
PRIVATE_BOUNDARY_GUIDANCE = ROOT_GUIDANCE + (
    REPO_ROOT / "docs/ops/container-lifecycle-requirements.md",
    REPO_ROOT / "docs/ops/skills/README.md",
    REPO_ROOT / "docs/contrib/coding-standards.md",
    REPO_ROOT / "docs/contrib/testing-standards.md",
    REPO_ROOT / "docs/contrib/skills/README.md",
)
PUBLIC_IDENTITY_ALLOWLIST = {
    REPO_ROOT / "README.md": (
        "lair001/repo-map_apache-2.0-final",
    ),
}
PRIVATE_BOUNDARY_PATTERNS = {
    "absolute macOS user path": re.compile(r"/Users/"),
    "absolute Linux user path": re.compile(r"/home/[^/\s]+/"),
    "private installation root": re.compile(r"~/.local/share/repo-map"),
    "private agent repository": re.compile(
        r"\b(?:agent-vc|codex-vc|claude-vc|common-vc)\b"
    ),
    "private graph identity": re.compile(r"\bargo-cd\b", re.IGNORECASE),
    "personal identity": re.compile(r"\b(?:lair001|Samuel Lair)\b"),
    "agent role assignment": re.compile(
        r"\b(?:Codex Sol|Claude Fable|Fable 5|Opus)\b"
    ),
}


def canonical_skill_directories() -> dict[str, Path]:
    return {
        path.name: path
        for root in CANONICAL_ROOTS
        for path in root.iterdir()
        if path.is_dir()
    }


def live_guidance_files() -> tuple[Path, ...]:
    files = list(ROOT_GUIDANCE)
    for root in (REPO_ROOT / "docs/ops", REPO_ROOT / "docs/contrib"):
        files.extend(root.rglob("*.md"))
    return tuple(sorted(set(files)))


def parse_openai_interface(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "interface:"
    values = {}
    for line in lines[1:]:
        match = re.fullmatch(r"  ([a-z_]+): (\".*\")", line)
        assert match is not None, f"unexpected openai.yaml line: {line!r}"
        values[match.group(1)] = ast.literal_eval(match.group(2))
    return values


def test_canonical_catalog_has_exact_unique_frontmatter_identities():
    catalog = canonical_skill_directories()

    assert set(catalog) == EXPECTED_SKILLS
    assert len(catalog) == sum(
        1
        for root in CANONICAL_ROOTS
        for path in root.iterdir()
        if path.is_dir()
    )
    for identity, directory in catalog.items():
        skill_file = directory / "SKILL.md"
        frontmatter = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        assert frontmatter is not None
        assert frontmatter.parse_status == "parsed"
        assert frontmatter.values["name"] == identity
        assert isinstance(frontmatter.values["description"], str)
        assert frontmatter.values["description"].strip()


def test_projection_catalogs_are_exact_direct_relative_symlinks():
    canonical = canonical_skill_directories()
    canonical_paths = set(canonical.values())

    for root in PROJECTION_ROOTS:
        assert root.is_dir()
        entries = tuple(root.iterdir())
        assert {entry.name for entry in entries} == EXPECTED_SKILLS
        for entry in entries:
            assert entry.is_symlink()
            target_text = os.readlink(entry)
            assert not Path(target_text).is_absolute()
            direct_target = entry.parent / target_text
            assert not direct_target.is_symlink()
            resolved = direct_target.resolve(strict=True)
            assert resolved.is_relative_to(REPO_ROOT)
            assert resolved in canonical_paths
            assert resolved.is_dir()
            assert (resolved / "SKILL.md").is_file()


def test_projection_catalogs_have_identical_identity_sets():
    identity_sets = [
        {entry.name for entry in root.iterdir()}
        for root in PROJECTION_ROOTS
    ]

    assert identity_sets == [EXPECTED_SKILLS, EXPECTED_SKILLS]


def test_live_guidance_has_no_retired_docs_skills_reference():
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in live_guidance_files()
        if "docs/skills" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_root_guidance_budgets_and_routes_are_current():
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert len(agents.splitlines()) <= 160
    assert len(claude.splitlines()) <= 40
    for root in ("docs/ops/skills", "docs/contrib/skills"):
        assert root in agents
        assert root in claude
    for root in (".agents/skills", ".claude/skills"):
        assert root in agents
    assert ".claude/skills" in claude
    assert "planned discovery" not in agents
    assert "population deferred" not in agents
    assert "once its symlink projection is populated" not in claude
    assert "exactly one skill" not in claude


def test_current_public_guidance_respects_private_boundary():
    files = set(PRIVATE_BOUNDARY_GUIDANCE)
    files.update(path / "SKILL.md" for path in canonical_skill_directories().values())
    offenders = {}
    for path in sorted(files):
        content = path.read_text(encoding="utf-8")
        for allowed in PUBLIC_IDENTITY_ALLOWLIST.get(path, ()):
            content = content.replace(allowed, "<public-repository>")
        matches = [
            label
            for label, pattern in PRIVATE_BOUNDARY_PATTERNS.items()
            if pattern.search(content)
        ]
        if matches:
            offenders[path.relative_to(REPO_ROOT).as_posix()] = matches

    assert offenders == {}


def test_real_discovery_classifies_canon_fixture_and_projections_separately():
    discovered = discover_repository(REPO_ROOT)
    skill_paths = {
        item.path for item in discovered if item.path.endswith("/SKILL.md")
    }
    canonical = {
        path
        for path in skill_paths
        if path.startswith(("docs/ops/skills/", "docs/contrib/skills/"))
    }
    projections = {
        path
        for path in skill_paths
        if path.startswith((".agents/skills/", ".claude/skills/"))
    }
    fixtures = {
        path
        for path in skill_paths
        if path.startswith("src/test/fixtures/")
    }

    assert {Path(path).parent.name for path in canonical} == EXPECTED_SKILLS
    assert projections == set()
    assert fixtures == {
        "src/test/fixtures/discovery/markdown_docs_basic/docs/skills/example/SKILL.md"
    }
    assert skill_paths == canonical | fixtures


def test_codex_metadata_uses_verified_minimal_interface():
    for identity, directory in canonical_skill_directories().items():
        metadata = parse_openai_interface(directory / "agents/openai.yaml")
        assert set(metadata) == {
            "display_name",
            "short_description",
            "default_prompt",
        }
        assert 25 <= len(metadata["short_description"]) <= 64
        assert f"${identity}" in metadata["default_prompt"]
