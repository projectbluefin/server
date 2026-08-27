"""Unit tests for .github/scripts/docs-checks.py.

Covers the validator helpers that gate every docs pull request:
load_fm, validate_frontmatter, check_budget, check_stale_flags,
check_internal_links and validate_skill.
"""

import pytest


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def skill_text(name="my-skill", description="A skill.", meta_type="how-to",
                status="stable", extra_top="", extra_meta="", body="Body text.\n"):
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{extra_top}"
        "metadata:\n"
        f"  type: {meta_type}\n"
        f"  status: {status}\n"
        f"{extra_meta}"
        "---\n"
        f"\n{body}"
    )


# --- load_fm ---------------------------------------------------------------

def test_load_fm_returns_none_when_no_front_matter(docs_checks):
    fm, rest = docs_checks.load_fm("# Title\n\nno front-matter here\n")
    assert fm is None
    assert rest == "# Title\n\nno front-matter here\n"


def test_load_fm_extracts_front_matter_and_body(docs_checks):
    fm, rest = docs_checks.load_fm("---\nname: a\n---\nbody\n")
    assert fm == "name: a"
    assert rest.strip() == "body"


def test_load_fm_returns_none_for_unterminated_front_matter(docs_checks):
    fm, rest = docs_checks.load_fm("---\nname: a\nbody\n")
    assert fm is None
    assert rest == "---\nname: a\nbody\n"


# --- validate_frontmatter --------------------------------------------------

def test_valid_front_matter_produces_no_errors(docs_checks, tmp_path):
    path = tmp_path / "my-skill.md"
    docs_checks.validate_frontmatter(path, "name: my-skill\ndescription: ok\nmetadata:\n  type: how-to\n  status: stable")
    assert docs_checks.errors == []


def test_invalid_yaml_front_matter_is_reported(docs_checks, tmp_path):
    path = tmp_path / "my-skill.md"
    docs_checks.validate_frontmatter(path, "name: [unclosed\n")
    assert any("invalid YAML front-matter" in e for e in docs_checks.errors)


def test_non_mapping_front_matter_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(tmp_path / "my-skill.md", "- just\n- a list\n")
    assert any("must be a YAML mapping" in e for e in docs_checks.errors)


def test_unknown_top_level_key_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "name: my-skill\ndescription: ok\nowner: nobody\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("unknown top-level front-matter key: owner" in e for e in docs_checks.errors)


def test_missing_name_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "description: ok\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("missing required 'name'" in e for e in docs_checks.errors)


@pytest.mark.parametrize("name", ["My_Skill", "my skill", "MySkill"])
def test_non_kebab_case_name_is_reported(docs_checks, tmp_path, name):
    docs_checks.validate_frontmatter(
        tmp_path / f"{name}.md",
        f"name: {name}\ndescription: ok\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("must be kebab-case" in e for e in docs_checks.errors)


def test_name_must_match_filename_stem(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "other-name.md",
        "name: my-skill\ndescription: ok\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("must match filename stem" in e for e in docs_checks.errors)


def test_name_over_64_chars_is_reported(docs_checks, tmp_path):
    long_name = "a" * 65
    docs_checks.validate_frontmatter(
        tmp_path / f"{long_name}.md",
        f"name: {long_name}\ndescription: ok\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("exceeds 64 chars" in e for e in docs_checks.errors)


def test_missing_description_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "name: my-skill\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("missing required 'description'" in e for e in docs_checks.errors)


def test_description_over_1024_chars_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        f"name: my-skill\ndescription: {'d' * 1025}\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("exceeds 1024 chars" in e for e in docs_checks.errors)


def test_non_string_description_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "name: my-skill\ndescription: 42\nmetadata:\n  type: how-to\n  status: stable",
    )
    assert any("'description' must be a string" in e for e in docs_checks.errors)


def test_non_mapping_metadata_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "name: my-skill\ndescription: ok\nmetadata: nope",
    )
    assert any("'metadata' must be a mapping" in e for e in docs_checks.errors)


def test_unknown_metadata_key_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "name: my-skill\ndescription: ok\nmetadata:\n  type: how-to\n  status: stable\n  author: nobody",
    )
    assert any("unknown metadata key: author" in e for e in docs_checks.errors)


def test_unknown_metadata_type_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "name: my-skill\ndescription: ok\nmetadata:\n  type: tutorial\n  status: stable",
    )
    assert any("metadata.type must be one of" in e for e in docs_checks.errors)


def test_non_stable_status_is_reported(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(
        tmp_path / "my-skill.md",
        "name: my-skill\ndescription: ok\nmetadata:\n  type: how-to\n  status: wip",
    )
    assert any("metadata.status must be 'stable'" in e for e in docs_checks.errors)


def test_missing_metadata_block_reports_type_and_status(docs_checks, tmp_path):
    docs_checks.validate_frontmatter(tmp_path / "my-skill.md", "name: my-skill\ndescription: ok")
    assert any("metadata.type must be one of" in e for e in docs_checks.errors)
    assert any("metadata.status must be 'stable'" in e for e in docs_checks.errors)


# --- check_budget ----------------------------------------------------------

def test_budget_under_limit_is_silent(docs_checks, tmp_path):
    path = write(tmp_path / "doc.md", "line\n" * 10)
    docs_checks.check_budget(path, 200, 150)
    assert docs_checks.errors == []
    assert docs_checks.warnings == []


def test_budget_between_warning_and_max_warns_only(docs_checks, tmp_path):
    path = write(tmp_path / "doc.md", "line\n" * 160)
    docs_checks.check_budget(path, 200, 150)
    assert docs_checks.errors == []
    assert any("exceeds 150 lines (160)" in w for w in docs_checks.warnings)


def test_budget_over_max_errors_and_does_not_warn(docs_checks, tmp_path):
    path = write(tmp_path / "doc.md", "line\n" * 201)
    docs_checks.check_budget(path, 200, 150)
    assert any("exceeds 200 lines (201)" in e for e in docs_checks.errors)
    assert docs_checks.warnings == []


def test_budget_at_exact_max_is_accepted(docs_checks, tmp_path):
    path = write(tmp_path / "doc.md", "line\n" * 200)
    docs_checks.check_budget(path, 200)
    assert docs_checks.errors == []


# --- check_stale_flags -----------------------------------------------------

@pytest.mark.parametrize("marker", ["TODO:", "FIXME:", "XXX", "HACK"])
def test_stale_markers_are_reported(docs_checks, tmp_path, marker):
    path = write(tmp_path / "doc.md", f"text {marker} more text\n")
    docs_checks.check_stale_flags(path)
    assert any("TODO/FIXME/XXX/HACK" in e for e in docs_checks.errors)


def test_draft_marker_is_reported_in_normal_docs(docs_checks, tmp_path):
    path = write(tmp_path / "doc.md", "This page is a Draft.\n")
    docs_checks.check_stale_flags(path)
    assert any("'draft' marker" in e for e in docs_checks.errors)


@pytest.mark.parametrize(
    "name",
    ["DOCUMENTATION_OVERHAUL_PLAN.md", "MVP_1_0_READINESS.md", "skill-improvement.md"],
)
def test_draft_marker_allowed_in_exempt_files(docs_checks, tmp_path, name):
    path = write(tmp_path / name, "This plan is still a draft.\n")
    docs_checks.check_stale_flags(path)
    assert docs_checks.errors == []


def test_exempt_files_still_reject_todo_markers(docs_checks, tmp_path):
    path = write(tmp_path / "MVP_1_0_READINESS.md", "TODO: finish this\n")
    docs_checks.check_stale_flags(path)
    assert any("TODO/FIXME/XXX/HACK" in e for e in docs_checks.errors)


def test_clean_doc_produces_no_stale_errors(docs_checks, tmp_path):
    path = write(tmp_path / "doc.md", "All good here.\n")
    docs_checks.check_stale_flags(path)
    assert docs_checks.errors == []


# --- check_internal_links --------------------------------------------------

def test_external_and_anchor_links_are_skipped(docs_checks, tmp_path):
    path = write(
        tmp_path / "doc.md",
        "[a](https://example.com) [b](http://example.com) [c](mailto:x@example.com) [d](#section)\n",
    )
    docs_checks.check_internal_links(path, set())
    assert docs_checks.errors == []


def test_valid_relative_markdown_link_passes(docs_checks, tmp_path):
    target = write(tmp_path / "docs" / "other.md", "other\n")
    path = write(tmp_path / "docs" / "doc.md", "[other](other.md)\n")
    docs_checks.check_internal_links(path, {target.resolve()})
    assert docs_checks.errors == []


def test_broken_markdown_link_is_reported(docs_checks, tmp_path):
    path = write(tmp_path / "docs" / "doc.md", "[gone](missing.md)\n")
    docs_checks.check_internal_links(path, set())
    assert any("broken internal link: [gone](missing.md)" in e for e in docs_checks.errors)


def test_root_absolute_link_resolves_against_repo_root(docs_checks, tmp_path):
    target = write(tmp_path / "docs" / "other.md", "other\n")
    path = write(tmp_path / "docs" / "skills" / "doc.md", "[other](/docs/other.md)\n")
    docs_checks.check_internal_links(path, {target.resolve()})
    assert docs_checks.errors == []


def test_directory_link_requires_index(docs_checks, tmp_path):
    (tmp_path / "docs" / "guide").mkdir(parents=True)
    path = write(tmp_path / "docs" / "doc.md", "[guide](guide)\n")
    docs_checks.check_internal_links(path, set())
    assert any("no index.md" in e for e in docs_checks.errors)


@pytest.mark.parametrize("index_name", ["index.md", "INDEX.md"])
def test_directory_link_with_index_passes(docs_checks, tmp_path, index_name):
    write(tmp_path / "docs" / "guide" / index_name, "index\n")
    path = write(tmp_path / "docs" / "doc.md", "[guide](guide)\n")
    docs_checks.check_internal_links(path, set())
    assert docs_checks.errors == []


def test_link_to_existing_non_markdown_file_passes(docs_checks, tmp_path):
    write(tmp_path / "docs" / "justfile", "recipe:\n")
    path = write(tmp_path / "docs" / "doc.md", "[justfile](justfile)\n")
    docs_checks.check_internal_links(path, set())
    assert docs_checks.errors == []


def test_link_to_missing_non_markdown_file_is_reported(docs_checks, tmp_path):
    path = write(tmp_path / "docs" / "doc.md", "[script](bin/nope)\n")
    docs_checks.check_internal_links(path, set())
    assert any("broken internal link: [script](bin/nope)" in e for e in docs_checks.errors)


# --- validate_skill --------------------------------------------------------

def test_skill_without_front_matter_is_reported(docs_checks):
    path = write(docs_checks.SKILLS_DIR / "my-skill.md", "# No front-matter\n")
    docs_checks.validate_skill(path)
    assert any("missing YAML front-matter" in e for e in docs_checks.errors)


def test_well_formed_skill_passes(docs_checks):
    path = write(docs_checks.SKILLS_DIR / "my-skill.md", skill_text())
    docs_checks.validate_skill(path)
    assert docs_checks.errors == []
    assert docs_checks.warnings == []


def test_oversized_skill_reports_budget_error(docs_checks):
    path = write(docs_checks.SKILLS_DIR / "my-skill.md", skill_text(body="line\n" * 600))
    docs_checks.validate_skill(path)
    assert any("exceeds 500 lines" in e for e in docs_checks.errors)


def test_long_skill_between_300_and_500_lines_only_warns(docs_checks):
    path = write(docs_checks.SKILLS_DIR / "my-skill.md", skill_text(body="line\n" * 350))
    docs_checks.validate_skill(path)
    assert docs_checks.errors == []
    assert any("exceeds 300 lines" in w for w in docs_checks.warnings)


def test_skill_with_stale_marker_is_reported(docs_checks):
    path = write(docs_checks.SKILLS_DIR / "my-skill.md", skill_text(body="TODO: write this\n"))
    docs_checks.validate_skill(path)
    assert any("TODO/FIXME/XXX/HACK" in e for e in docs_checks.errors)


# --- repository invariant --------------------------------------------------

def test_repository_docs_pass_the_real_checker():
    """The checked-in docs must satisfy the validator the CI gate runs."""
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(repo_root / ".github" / "scripts" / "docs-checks.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
