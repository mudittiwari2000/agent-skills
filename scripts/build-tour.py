#!/usr/bin/env python3
"""Build the interactive skills tour (docs/tour/index.html).

  python3 scripts/build-tour.py          # rebuild docs/tour/index.html
  python3 scripts/build-tour.py --check  # exit 1 if the tour is stale or incomplete

The tour is generated, never hand-edited:
- skills/*/SKILL.md gives each skill's name and description;
- docs/tour/tour.json gives what a reader needs that SKILL.md does not say
  (lifecycle stage, one-line pitch, example prompt, what it needs, how generic
  it is today, what it hands off to) plus the roadmap;
- docs/tour/template.html is the page; the data is injected at /*TOUR_DATA*/.

--check fails when a skill has no tour.json entry, when tour.json names a
skill that no longer exists, or when index.html differs from a fresh build.
The pre-commit hook runs it, so the tour can't drift from the skills.
"""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
tour_dir = root / "docs" / "tour"
template_path = tour_dir / "template.html"
data_path = tour_dir / "tour.json"
out_path = tour_dir / "index.html"


def frontmatter(text: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    meta = {}
    if not match:
        return meta
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            meta[key.strip()] = value.strip().strip('"')
    return meta


def build() -> tuple[str, list[str]]:
    curated = json.loads(data_path.read_text())
    entries = curated.get("skills", {})
    problems = []
    skills = []
    names = []
    for skill_md in sorted(root.glob("skills/*/SKILL.md")):
        name = skill_md.parent.name
        names.append(name)
        meta = frontmatter(skill_md.read_text())
        entry = entries.get(name)
        if entry is None:
            problems.append(f"skills/{name} has no entry in docs/tour/tour.json")
            continue
        skills.append({
            "name": name,
            "description": meta.get("description", ""),
            **entry,
        })
    for name in entries:
        if name not in names:
            problems.append(f"docs/tour/tour.json names '{name}', which has no skills/{name}/SKILL.md")
    data = {k: v for k, v in curated.items() if k != "skills"}
    data["skills"] = skills
    # The as-of date comes from tour.json, not git or the clock, so a rebuild
    # with nothing changed is byte-identical and --check stays green.
    data["generated"] = curated.get("asOf", "")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # keep </script> out of the data
    html = template_path.read_text().replace("/*TOUR_DATA*/{}", payload)
    return html, problems


def main() -> int:
    html, problems = build()
    if "--check" in sys.argv:
        current = out_path.read_text() if out_path.exists() else ""
        if current != html:
            problems.append("docs/tour/index.html is stale; run python3 scripts/build-tour.py")
        for problem in problems:
            print(f"build-tour: {problem}", file=sys.stderr)
        if not problems:
            print("build-tour: tour up to date")
        return 1 if problems else 0
    for problem in problems:
        print(f"build-tour: {problem}", file=sys.stderr)
    out_path.write_text(html)
    print(f"build-tour: wrote {out_path.relative_to(root)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
