"""Builds the chat editions: start.md, and per course an index plus one page per lesson.

Usage: python3 build.py OUT_DIR
"""
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

ORG = "things-they-dont-teach-you"
SITE = f"https://{ORG}.github.io"
HERE = pathlib.Path(__file__).parent


def course_url(name):
    return f"{SITE}/{name}.md"


def lesson_title(text):
    return text.splitlines()[0].lstrip("# ").strip()


def facts_for(lesson_text, facts):
    """Keeps only the facts.md sections a lesson names in a <!-- facts: A; B --> line.

    No such line keeps every section; "none" keeps only the intro. An unknown name fails the build,
    so a renamed section can't silently drop a figure a lesson relies on.
    """
    m = re.search(r"<!--\s*facts:\s*(.*?)\s*-->", lesson_text, re.S)
    if not m:
        return facts
    intro, *sections = facts.split("\n## ")
    keep = []
    for want in (w.strip().lower() for w in m.group(1).split(";")):
        if want == "none":
            continue
        found = [sec for sec in sections if sec.lower().startswith(want)]
        if not found:
            raise ValueError(f"facts.md has no section starting {want!r}")
        keep += [sec for sec in found if sec not in keep]
    return "\n\n".join([intro.strip(), *("## " + sec.strip() for sec in keep)]) + "\n"


# Diagrams are served from the site's own origin, so only plain drawing elements are allowed:
# nothing that can run script, load other content, or link anywhere.
SVG_ELEMENTS = {"svg", "title", "desc", "defs", "marker", "g", "path", "rect", "line", "polyline",
                "polygon", "circle", "ellipse", "text", "tspan"}


def read_safe(path, course_dir):
    """Reads a course file, refusing symlinks or anything outside the course, which a contributor's
    PR could otherwise use to publish files from the build machine."""
    path = pathlib.Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(pathlib.Path(course_dir).resolve()):
        raise ValueError(f"refusing to publish {path}: not a plain file inside the course")
    return path.read_text()


SAME_DOC_URL = re.compile(r"url\(#[\w-]+\)")
ET.register_namespace("", "http://www.w3.org/2000/svg")


def clean_svg(text, path):
    """Allowlist check, then returns the SVG rebuilt from the parsed tree, so anything the parser
    skips (processing instructions, comments) is never published. Refuses anything but plain
    drawing elements, any DOCTYPE or entity, on*, *href and style attributes, and any value with a
    bracket or backslash other than url(#id)."""
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        raise ValueError(f"refusing to publish {path}: SVG has a DOCTYPE or entity")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"refusing to publish {path}: not valid XML ({e})")
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in SVG_ELEMENTS:
            raise ValueError(f"refusing to publish {path}: <{tag}> is not an allowed SVG element")
        for attr, value in el.attrib.items():
            name = attr.split("}")[-1].lower()
            if name.startswith("on") or "href" in name or name == "style":
                raise ValueError(f"refusing to publish {path}: attribute {name!r} is not allowed")
            # Presentation attributes are parsed as CSS, where escapes can spell url( in disguise, so
            # any value with a bracket or backslash must be exactly url(#id).
            if ("(" in value or "\\" in value) and not SAME_DOC_URL.fullmatch(value.strip()):
                raise ValueError(f"refusing to publish {path}: {name}={value!r} points outside the diagram")
    return ET.tostring(root, encoding="unicode") + "\n"


def read_svg(path, course_dir):
    return clean_svg(read_safe(path, course_dir), path)


def chat_rules(rules):
    """Drops the parts of a course's AGENTS.md marked as only for learners with files on a computer."""
    return re.sub(r"\n?<!-- terminal-only -->.*?<!-- /terminal-only -->\n?", "\n", rules, flags=re.S)


def course_pages(course_dir, name):
    """Returns {published path: text}: a small index, then one self-contained page per lesson."""
    course_dir = pathlib.Path(course_dir)
    rules = chat_rules(read_safe(course_dir / "AGENTS.md", course_dir)).strip()
    facts = read_safe(course_dir / "facts.md", course_dir).strip()
    lessons = sorted((course_dir / "lessons").glob("*.md"))
    texts = {lesson: read_safe(lesson, course_dir).strip() for lesson in lessons}
    paths = [f"{name}/{lesson.name}" for lesson in lessons]
    header = (HERE / "chat/lesson-header.md").read_text()

    index = (HERE / "chat/course-index.md").read_text().replace("{course}", name).replace(
        "{lessons}", "\n".join(f"- {lesson_title(texts[l])}: {SITE}/{p}" for l, p in zip(lessons, paths)))
    pages = {f"{name}.md": index, f"{name}/facts.md": facts + "\n"}
    for diagram in sorted((course_dir / "diagrams").glob("*.svg")):
        pages[f"{name}/diagrams/{diagram.name}"] = read_svg(diagram, course_dir)
    for i, (lesson, path) in enumerate(zip(lessons, paths)):
        last = i == len(lessons) - 1
        next_url = f"{SITE}/{path}" if last else f"{SITE}/{paths[i + 1]}"
        nxt = ("this is the last lesson of the course; congratulate them, and suggest another course "
               f"from {SITE}/start.md") if last else f"{lesson_title(texts[lessons[i + 1]])}, at {next_url}"
        top = (header.replace("{course}", name).replace("{title}", lesson_title(texts[lesson]))
               .replace("{url}", f"{SITE}/{path}").replace("{next_url}", next_url).replace("{next}", nxt)
               .replace("{facts_url}", f"{SITE}/{name}/facts.md"))
        text = texts[lesson].replace("](../diagrams/", f"]({SITE}/{name}/diagrams/")
        pages[path] = f"{top}{rules}\n\n---\n\n{facts_for(text, facts).strip()}\n\n---\n\n{text}\n"
    return pages


def html_edition(text):
    """The same page as plain HTML: some chat apps' browsing tools (ChatGPT's) won't read text/markdown.
    Links to other chat pages point at their HTML editions too."""
    text = re.sub(rf"({re.escape(SITE)}/[\w/.-]+)\.md\b", r"\1.html", text)
    title = html.escape(text.splitlines()[0].lstrip("# ").strip())
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title}</title></head>\n<body><pre style=\"white-space:pre-wrap;font:16px/1.5 system-ui,sans-serif;"
            f'max-width:44rem;margin:2rem auto;padding:0 16px">{html.escape(text)}</pre></body></html>\n')


def write_page(out, path, text):
    (out / path).parent.mkdir(parents=True, exist_ok=True)
    (out / path).write_text(text)
    if path.endswith(".md"):
        (out / (path[:-3] + ".html")).write_text(html_edition(text))


def has_subject(repo):
    return not repo["archived"] and any(t.startswith("subject-") for t in repo["topics"])


def is_course(repo):
    return has_subject(repo) and "planned" not in repo["topics"]


def is_planned(repo):
    return has_subject(repo) and "planned" in repo["topics"]


STATUSES = ("planned", "draft", "published")


def course_status(repo):
    """planned: not written; draft: written, not yet reviewed by a professional; published: reviewed.
    No status topic counts as draft, so an unreviewed course can never show as published."""
    return next((s for s in STATUSES if s in repo["topics"]), "draft")


def start_page(courses, planned=()):
    lines = [f"- **{c['name']}**: {c['description']} ({', '.join(t for t in c['topics'] if t not in STATUSES)}). "
             f"Status: {course_status(c)}. Address: {course_url(c['name'])}" for c in courses]
    planned_lines = [f"- **{p['name']}** ({', '.join(t for t in p['topics'] if t != 'planned')}): https://github.com/{ORG}/{p['name']}" for p in planned]
    return ((HERE / "chat/start.md").read_text()
            .replace("{courses}", "\n".join(lines) or "None yet.")
            .replace("{planned}", "\n".join(planned_lines) or "None."))


def main(out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(f"https://api.github.com/orgs/{ORG}/repos?per_page=100")
    if os.environ.get("GITHUB_TOKEN"):  # anonymous calls share a low rate limit on CI runners
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req) as r:
        repos = json.load(r)
    courses = [repo for repo in repos if is_course(repo)]
    planned = [repo for repo in repos if is_planned(repo)]
    with tempfile.TemporaryDirectory() as tmp:
        for c in courses:
            dest = pathlib.Path(tmp, c["name"])
            subprocess.run(["git", "-c", "core.symlinks=false", "clone", "-q", "--depth", "1", c["clone_url"], str(dest)], check=True)
            for path, text in course_pages(dest, c["name"]).items():
                write_page(out, path, text)
    write_page(out, "start.md", start_page(courses, planned))
    print(f"built start.md and {len(courses)} course(s) in {out}")


if __name__ == "__main__":
    main(sys.argv[1])
