import pathlib
import tempfile

import build

SITE = "https://things-they-dont-teach-you.github.io"


def make_course(root):
    course = pathlib.Path(root, "demo-tax")
    (course / "lessons").mkdir(parents=True)
    (course / "AGENTS.md").write_text("# Demo tutor rules\n")
    (course / "facts.md").write_text("# Facts\nRate: 18%\n")
    (course / "lessons/02-second.md").write_text("# Lesson 2: Second\n")
    (course / "lessons/01-first.md").write_text("# Lesson 1: First\n")
    return course


def test_course_pages():
    with tempfile.TemporaryDirectory() as root:
        pages = build.course_pages(make_course(root), "demo-tax")
    assert set(pages) == {"demo-tax.md", "demo-tax/facts.md", "demo-tax/01-first.md", "demo-tax/02-second.md"}

    index = pages["demo-tax.md"]
    assert f"{SITE}/demo-tax/01-first.md" in index and f"{SITE}/demo-tax/02-second.md" in index
    assert "Lesson 1: First" in index
    assert "Rate: 18%" not in index  # the index stays small: no facts, no lesson text

    first = pages["demo-tax/01-first.md"]
    for part in ["# Demo tutor rules", "Rate: 18%", "# Lesson 1", "PROGRESS CARD", "words"]:
        assert part in first
    assert "# Lesson 2" not in first
    assert f"{SITE}/demo-tax/02-second.md" in first  # where the progress card sends them next
    assert "last lesson" in pages["demo-tax/02-second.md"]
    assert pages["demo-tax/facts.md"].startswith("# Facts")


FACTS = "# Facts\nIntro line.\n\n## Income tax brackets\n18%\n\n## Rebates\nR17 820\n\n## Filing season 2026\nJuly\n"


def test_facts_for_lesson():
    picked = build.facts_for("# Lesson\n<!-- facts: Income tax brackets; filing season -->\nText", FACTS)
    assert "Intro line." in picked and "18%" in picked and "July" in picked
    assert "R17 820" not in picked
    assert build.facts_for("<!-- facts: none -->", FACTS).strip() == "# Facts\nIntro line."
    assert build.facts_for("# Lesson without a facts line", FACTS) == FACTS
    try:
        build.facts_for("<!-- facts: Shoe sizes -->", FACTS)
        raise AssertionError("an unknown section must fail the build")
    except ValueError:
        pass


def test_diagrams_published_with_absolute_links():
    with tempfile.TemporaryDirectory() as root:
        course = make_course(root)
        (course / "diagrams").mkdir()
        (course / "diagrams/brackets.svg").write_text("<svg/>")
        (course / "lessons/01-first.md").write_text("# Lesson 1: First\n![Brackets](../diagrams/brackets.svg)\n")
        pages = build.course_pages(course, "demo-tax")
    assert pages["demo-tax/diagrams/brackets.svg"].startswith("<svg")
    assert f"![Brackets]({SITE}/demo-tax/diagrams/brackets.svg)" in pages["demo-tax/01-first.md"]


def test_unsafe_course_files_fail_the_build():
    for svg in ['<svg><script>alert(1)</script></svg>', '<svg onload="x()"/>',
                '<svg><a href="javascript:x()"/></svg>', '<svg><foreignObject/></svg>',
                '<svg/onload="x()"/>', '<svg xmlns="http://www.w3.org/2000/svg"><a href="&#106;avascript:x()"/></svg>',
                '<!DOCTYPE svg [<!ENTITY e "x">]><svg>&e;</svg>', '<svg><style>*{}</style></svg>',
                '<svg><image href="https://example.com/x.png"/></svg>', 'not xml at all <',
                '<svg><rect style="fill:red"/></svg>', '<svg><rect fill="url(https://example.com/x)"/></svg>',
                '<svg><rect fill="\\75 rl(https://example.com/x)"/></svg>', '<svg><rect fill="u\\rl(x)"/></svg>',
                '<svg><rect fill="image(https://example.com/x)"/></svg>']:
        with tempfile.TemporaryDirectory() as root:
            course = make_course(root)
            (course / "diagrams").mkdir()
            (course / "diagrams/bad.svg").write_text(svg)
            try:
                build.course_pages(course, "demo-tax")
                raise AssertionError(f"unsafe SVG published: {svg}")
            except ValueError:
                pass
    with tempfile.TemporaryDirectory() as root, tempfile.NamedTemporaryFile() as secret:
        course = make_course(root)
        (course / "facts.md").unlink()
        (course / "facts.md").symlink_to(secret.name)
        try:
            build.course_pages(course, "demo-tax")
            raise AssertionError("symlink followed")
        except ValueError:
            pass


def test_published_svg_is_rebuilt_from_the_checked_tree():
    svg = ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg">'
           '<?xml-stylesheet href="https://example.com/x.css"?><!-- note -->'
           '<line marker-end="url(#a)"/><text>R1 000 − R310</text></svg>')
    out = build.clean_svg(svg, "test.svg")
    assert "<?" not in out and "<!--" not in out and "example.com" not in out
    assert 'marker-end="url(#a)"' in out and "R1 000 − R310" in out
    assert out.startswith('<svg xmlns="http://www.w3.org/2000/svg"')


def test_real_diagrams_are_allowed():
    for svg in pathlib.Path(__file__).parent.parent.glob("south-african-tax/diagrams/*.svg"):
        build.clean_svg(svg.read_text(), svg)


def test_chat_rules_drop_terminal_only_parts():
    rules = "# Rules\nKeep.\n<!-- terminal-only -->\nRead ../profile.md\n<!-- /terminal-only -->\nAlso keep.\n"
    chat = build.chat_rules(rules)
    assert "Keep." in chat and "Also keep." in chat
    assert "profile.md" not in chat and "terminal-only" not in chat


def test_html_edition():
    page = build.html_edition("# Start <here>\nGo to https://things-they-dont-teach-you.github.io/demo-tax/01-first.md now.\n"
                              "Diagram: https://things-they-dont-teach-you.github.io/demo-tax/diagrams/b.svg")
    assert page.startswith("<!doctype html>")
    assert "<title>Start &lt;here&gt;</title>" in page and "# Start &lt;here&gt;" in page
    assert f"{SITE}/demo-tax/01-first.html" in page and "01-first.md" not in page
    assert f"{SITE}/demo-tax/diagrams/b.svg" in page


def test_is_course():
    assert build.is_course({"topics": ["subject-tax", "country-za"], "archived": False})
    assert not build.is_course({"topics": ["subject-tax"], "archived": True})
    assert not build.is_course({"topics": [], "archived": False})
    planned = {"topics": ["subject-tax", "country-gb", "planned"], "archived": False}
    assert not build.is_course(planned)
    assert build.is_planned(planned)
    assert not build.is_planned({"topics": ["subject-tax", "country-za"], "archived": False})


def test_course_status():
    assert build.course_status({"topics": ["subject-tax", "planned"]}) == "planned"
    assert build.course_status({"topics": ["subject-tax", "published"]}) == "published"
    assert build.course_status({"topics": ["subject-tax", "draft"]}) == "draft"
    # A course with no status topic is unreviewed, so it must never show as published.
    assert build.course_status({"topics": ["subject-tax"]}) == "draft"


def test_start_page_lists_courses():
    page = build.start_page(
        [{"name": "demo-tax", "description": "Demo", "topics": ["subject-tax", "country-za"]}],
        [{"name": "uk-tax", "topics": ["subject-tax", "country-gb", "planned"]}],
    )
    assert f"{SITE}/demo-tax.md" in page
    assert "Demo" in page and "country-za" in page
    assert "Status: draft" in page
    ready, planned = page.split("## Planned courses")
    assert "uk-tax" not in ready
    assert "https://github.com/things-they-dont-teach-you/uk-tax" in planned


if __name__ == "__main__":
    test_course_pages()
    test_facts_for_lesson()
    test_chat_rules_drop_terminal_only_parts()
    test_diagrams_published_with_absolute_links()
    test_unsafe_course_files_fail_the_build()
    test_published_svg_is_rebuilt_from_the_checked_tree()
    test_real_diagrams_are_allowed()
    test_html_edition()
    test_is_course()
    test_course_status()
    test_start_page_lists_courses()
    print("ok")
