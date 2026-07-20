#!/usr/bin/env python3
"""Lightweight docs validator for the Bluefin Server repo.

Enforces:
- Skill front-matter schema and budgets
- Line budgets on AGENTS.md, README.md, CONTRIBUTING.md, and skills
- No stale TODO/FIXME/draft markers in docs on main
- Internal link validity
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
SKILLS_DIR = DOCS_DIR / "skills"

ALLOWED_TOP_KEYS = {"name", "description", "metadata"}
ALLOWED_METADATA_KEYS = {"type", "status", "last_updated", "context7-sources"}
ALLOWED_SKILL_TYPES = {"index", "how-to", "reference", "meta-skill"}
STALERE = re.compile(r"TODO:|FIXME:|XXX|HACK")
DRAFT_RE = re.compile(r"\bdraft\b", re.IGNORECASE)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

errors = []
warnings = []


def err(path, msg):
    errors.append(f"{path}: {msg}")


def warn(path, msg):
    warnings.append(f"{path}: {msg}")


def load_fm(text):
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    return parts[1].strip(), parts[2]


def validate_frontmatter(path, fm):
    try:
        import yaml
        data = yaml.safe_load(fm)
    except Exception as exc:
        err(path, f"invalid YAML front-matter: {exc}")
        return
    if not isinstance(data, dict):
        err(path, "front-matter must be a YAML mapping")
        return

    for key in data:
        if key not in ALLOWED_TOP_KEYS:
            err(path, f"unknown top-level front-matter key: {key}")

    if "name" not in data:
        err(path, "missing required 'name' in front-matter")
    else:
        name = data["name"]
        if not isinstance(name, str) or not re.match(r"^[a-z0-9-]+$", name):
            err(path, f"'name' must be kebab-case: {name}")
        if len(name) > 64:
            err(path, f"'name' exceeds 64 chars: {len(name)}")
        if name != path.stem:
            err(path, f"'name' ({name}) must match filename stem ({path.stem})")

    if "description" not in data:
        err(path, "missing required 'description' in front-matter")
    else:
        desc = data["description"]
        if not isinstance(desc, str):
            err(path, "'description' must be a string")
        elif len(desc) > 1024:
            err(path, f"'description' exceeds 1024 chars: {len(desc)}")

    meta = data.get("metadata", {})
    if not isinstance(meta, dict):
        err(path, "'metadata' must be a mapping")
        return
    for key in meta:
        if key not in ALLOWED_METADATA_KEYS:
            err(path, f"unknown metadata key: {key}")
    if meta.get("type") not in ALLOWED_SKILL_TYPES:
        err(path, f"metadata.type must be one of {ALLOWED_SKILL_TYPES}")
    if meta.get("status") != "stable":
        err(path, "metadata.status must be 'stable' on the main branch")


def check_budget(path, max_lines, warning_lines=None):
    lines = path.read_text().splitlines()
    line_count = len(lines)
    if line_count > max_lines:
        err(path, f"exceeds {max_lines} lines ({line_count})")
    elif warning_lines and line_count > warning_lines:
        warn(path, f"exceeds {warning_lines} lines ({line_count})")


def validate_skill(path):
    text = path.read_text()
    fm, _ = load_fm(text)
    if fm is None:
        err(path, "missing YAML front-matter")
        return
    validate_frontmatter(path, fm)
    check_budget(path, 500, 300)
    check_stale_flags(path)


def check_stale_flags(path):
    text = path.read_text()
    # Allow "draft" in planning/reference files and in the meta-skill that defines the rule
    if path.name in {"DOCUMENTATION_OVERHAUL_PLAN.md", "MVP_1_0_READINESS.md", "skill-improvement.md"}:
        if STALERE.search(text):
            err(path, "contains TODO/FIXME/XXX/HACK")
        return
    if STALERE.search(text):
        err(path, "contains TODO/FIXME/XXX/HACK")
    if DRAFT_RE.search(text):
        err(path, "contains 'draft' marker")


def check_internal_links(path, md_files):
    text = path.read_text()
    for label, target in LINK_RE.findall(text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("#"):
            continue
        # Resolve relative to the current file's directory
        if target.startswith("/"):
            resolved = ROOT / target.lstrip("/")
        else:
            resolved = path.parent / target
        resolved = resolved.resolve()
        # Accept a link to a Markdown file or a directory with an INDEX.md
        if resolved.suffix == ".md":
            if resolved not in md_files:
                err(path, f"broken internal link: [{label}]({target})")
        elif resolved.is_dir():
            if not (resolved / "index.md").exists() and not (resolved / "INDEX.md").exists():
                err(path, f"broken internal link (no index.md): [{label}]({target})")
        else:
            # Link points to a source file or directory without .md extension
            if not resolved.exists():
                err(path, f"broken internal link: [{label}]({target})")


def main():
    import yaml  # noqa: F401 - imported where available

    md_files = set(ROOT.rglob("*.md"))

    for skill in SKILLS_DIR.glob("*.md"):
        validate_skill(skill)
        check_internal_links(skill, md_files)

    check_budget(ROOT / "AGENTS.md", 200, 150)
    check_budget(ROOT / "README.md", 200, 150)
    check_budget(ROOT / "CONTRIBUTING.md", 100, 80)
    check_budget(DOCS_DIR / "MVP_1_0_READINESS.md", 250, 200)
    check_budget(DOCS_DIR / "DOCUMENTATION_OVERHAUL_PLAN.md", 3000, 2500)

    for doc in [ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "CONTRIBUTING.md", DOCS_DIR / "MVP_1_0_READINESS.md"]:
        check_stale_flags(doc)
        check_internal_links(doc, md_files)

    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  WARN {w}")
    if errors:
        print("Errors:")
        for e in errors:
            print(f"  FAIL {e}")
        sys.exit(1)
    print("Docs checks passed.")


if __name__ == "__main__":
    main()
