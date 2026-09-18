"""Unit tests for ``main()`` in .github/scripts/docs-checks.py.

``main()`` is the entry point the docs-checks CI workflow invokes, and it was
the only part of the validator with no executed coverage: tests/unit/
test_docs_checks.py drives the helpers (load_fm, validate_frontmatter,
check_budget, check_stale_flags, check_internal_links, validate_skill)
directly and never runs the orchestration around them.

That orchestration is what makes the gate a gate:

* which files are budget-checked, and with which limits
* that *every* skill under docs/skills/ is validated and link-checked
* that the top-level docs are stale-flag and link-checked
* the process contract: exit 1 and a ``FAIL`` line when anything errored,
  exit 0 with ``WARN`` lines when only warnings accumulated

A regression in any of those keeps the workflow green while silently
checking less, which is the failure mode this file exists to catch.
"""

import pytest


BUDGET_TARGETS = [
    # (relative path, hard limit, warning threshold) as passed by main()
    ("AGENTS.md", 200, 150),
    ("README.md", 200, 150),
    ("CONTRIBUTING.md", 100, 80),
    ("docs/MVP_1_0_READINESS.md", 250, 200),
    ("docs/DOCUMENTATION_OVERHAUL_PLAN.md", 3000, 2500),
]


def write(root, relpath, text):
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def skill_text(name, description="A skill.", meta_type="how-to",
               status="stable", body="Body text.\n"):
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "metadata:\n"
        f"  type: {meta_type}\n"
        f"  status: {status}\n"
        "---\n"
        f"\n{body}"
    )


@pytest.fixture
def tree(docs_checks, tmp_path):
    """A minimal repo tree that ``main()`` passes cleanly on.

    ``docs_checks`` already repoints ROOT/DOCS_DIR/SKILLS_DIR at tmp_path and
    creates docs/skills/, so this only has to supply the documents main()
    unconditionally reads.
    """
    for relpath, _limit, _warn in BUDGET_TARGETS:
        write(tmp_path, relpath, "# Doc\n\nclean body\n")
    return docs_checks


def run(module):
    """Run main() and return (exit_code, stdout) instead of raising."""
    try:
        module.main()
    except SystemExit as exc:
        return exc.code
    return 0


# --- clean tree ------------------------------------------------------------

def test_main_passes_on_a_clean_tree(tree, capsys):
    write(tree.SKILLS_DIR, "good-skill.md", skill_text("good-skill"))

    assert run(tree) == 0
    out = capsys.readouterr().out
    assert "Docs checks passed." in out
    assert "FAIL" not in out
    assert "WARN" not in out


def test_main_passes_with_no_skills_at_all(tree, capsys):
    # Empty docs/skills/ must not be an error — the loop is a glob, not a
    # required-at-least-one assertion.
    assert run(tree) == 0
    assert "Docs checks passed." in capsys.readouterr().out


# --- failure contract ------------------------------------------------------

def test_main_exits_1_and_prints_fail_when_a_skill_is_invalid(tree, capsys):
    write(tree.SKILLS_DIR, "bad-skill.md", skill_text("bad-skill", status="draft"))

    assert run(tree) == 1
    out = capsys.readouterr().out
    assert "Errors:" in out
    assert "FAIL" in out
    assert "bad-skill.md" in out
    assert "Docs checks passed." not in out


def test_main_exits_1_when_a_skill_has_no_front_matter(tree, capsys):
    write(tree.SKILLS_DIR, "raw.md", "# No front matter\n")

    assert run(tree) == 1
    assert "missing YAML front-matter" in capsys.readouterr().out


def test_main_validates_every_skill_not_just_the_first(tree, capsys):
    write(tree.SKILLS_DIR, "aaa-ok.md", skill_text("aaa-ok"))
    write(tree.SKILLS_DIR, "mmm-ok.md", skill_text("mmm-ok"))
    write(tree.SKILLS_DIR, "zzz-bad.md", skill_text("zzz-bad", meta_type="nonsense"))

    assert run(tree) == 1
    out = capsys.readouterr().out
    assert "zzz-bad.md" in out
    assert "aaa-ok.md" not in out
    assert "mmm-ok.md" not in out


# --- warnings are non-fatal ------------------------------------------------

def test_main_prints_warnings_but_still_exits_0(tree, capsys):
    # AGENTS.md warns above 150 lines and only errors above 200.
    write(tree.ROOT, "AGENTS.md", "# Doc\n" + "line\n" * 160)

    assert run(tree) == 0
    out = capsys.readouterr().out
    assert "Warnings:" in out
    assert "WARN" in out
    assert "AGENTS.md" in out
    assert "Docs checks passed." in out


def test_main_prints_both_warnings_and_errors_when_both_accumulate(tree, capsys):
    write(tree.ROOT, "README.md", "# Doc\n" + "line\n" * 160)
    write(tree.SKILLS_DIR, "bad.md", skill_text("bad", status="draft"))

    assert run(tree) == 1
    out = capsys.readouterr().out
    assert "Warnings:" in out
    assert "Errors:" in out


# --- budget targets --------------------------------------------------------

@pytest.mark.parametrize("relpath,limit,warn_at", BUDGET_TARGETS)
def test_main_enforces_the_line_budget_of_each_tracked_doc(tree, capsys, relpath, limit, warn_at):
    write(tree.ROOT, relpath, "# Doc\n" + "line\n" * (limit + 5))

    assert run(tree) == 1
    out = capsys.readouterr().out
    assert relpath.rsplit("/", 1)[-1] in out
    assert f"exceeds {limit} lines" in out


@pytest.mark.parametrize("relpath,limit,warn_at", BUDGET_TARGETS)
def test_main_accepts_a_doc_exactly_at_its_hard_budget(tree, capsys, relpath, limit, warn_at):
    # The hard limit is inclusive: check_budget errors only on `> max_lines`,
    # so a doc of exactly `limit` lines must not fail the gate. It is still
    # over the warning threshold, so only the error path is asserted here.
    write(tree.ROOT, relpath, "line\n" * limit)

    assert run(tree) == 0
    out = capsys.readouterr().out
    assert f"exceeds {limit} lines" not in out
    assert "Docs checks passed." in out


@pytest.mark.parametrize("relpath,limit,warn_at", BUDGET_TARGETS)
def test_main_warns_between_the_warning_threshold_and_the_hard_limit(tree, capsys, relpath, limit, warn_at):
    write(tree.ROOT, relpath, "line\n" * (warn_at + 1))

    assert run(tree) == 0
    out = capsys.readouterr().out
    assert f"exceeds {warn_at} lines" in out
    assert "Errors:" not in out


@pytest.mark.parametrize("relpath,limit,warn_at", BUDGET_TARGETS)
def test_main_is_silent_at_the_warning_threshold(tree, capsys, relpath, limit, warn_at):
    write(tree.ROOT, relpath, "line\n" * warn_at)

    assert run(tree) == 0
    out = capsys.readouterr().out
    assert relpath.rsplit("/", 1)[-1] not in out
    assert "Docs checks passed." in out


# --- stale flags on top-level docs ----------------------------------------

@pytest.mark.parametrize("relpath", ["AGENTS.md", "README.md", "CONTRIBUTING.md"])
def test_main_rejects_stale_markers_in_top_level_docs(tree, capsys, relpath):
    write(tree.ROOT, relpath, "# Doc\n\nTODO: finish this section\n")

    assert run(tree) == 1
    assert "contains TODO/FIXME/XXX/HACK" in capsys.readouterr().out


@pytest.mark.parametrize("relpath", ["AGENTS.md", "README.md", "CONTRIBUTING.md"])
def test_main_rejects_draft_markers_in_top_level_docs(tree, capsys, relpath):
    write(tree.ROOT, relpath, "# Doc\n\nThis is a draft document.\n")

    assert run(tree) == 1
    assert "contains 'draft' marker" in capsys.readouterr().out


def test_main_allows_draft_wording_in_the_exempt_planning_docs(tree, capsys):
    # check_stale_flags exempts MVP_1_0_READINESS.md and
    # DOCUMENTATION_OVERHAUL_PLAN.md from the draft rule by filename.
    write(tree.ROOT, "docs/MVP_1_0_READINESS.md", "# Readiness\n\nStill a draft plan.\n")

    assert run(tree) == 0
    assert "draft" not in capsys.readouterr().out


# --- internal links --------------------------------------------------------

def test_main_rejects_a_broken_link_in_a_skill(tree, capsys):
    write(tree.SKILLS_DIR, "linky.md",
          skill_text("linky", body="See [gone](./nowhere.md).\n"))

    assert run(tree) == 1
    assert "broken internal link" in capsys.readouterr().out


def test_main_rejects_a_broken_link_in_a_top_level_doc(tree, capsys):
    write(tree.ROOT, "README.md", "# Doc\n\nSee [gone](docs/nowhere.md).\n")

    assert run(tree) == 1
    assert "broken internal link" in capsys.readouterr().out


def test_main_accepts_a_link_that_resolves_to_a_tracked_markdown_file(tree, capsys):
    write(tree.ROOT, "README.md", "# Doc\n\nSee [agents](AGENTS.md).\n")

    assert run(tree) == 0
    assert "Docs checks passed." in capsys.readouterr().out


def test_main_accepts_external_and_anchor_links(tree, capsys):
    write(tree.ROOT, "README.md",
          "# Doc\n\n[web](https://example.com) [mail](mailto:a@b.c) [anchor](#section)\n")

    assert run(tree) == 0
    assert "Docs checks passed." in capsys.readouterr().out
