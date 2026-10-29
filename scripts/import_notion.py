#!/usr/bin/env python3
"""Import finished labs from a Notion database export (Markdown & CSV).

Run from the repo root:
    python3 scripts/import_notion.py ~/Downloads/Export-xxxx.zip [--force]

Works for one lab or all of them. Export the Labs database only, not the
parent page, so your theory notes never end up in the export.

A page is imported only if:
  - "Lab Done" is ticked in Notion, and
  - "GitHub Write-up" is NOT ticked (already published), unless you pass --force.
So theory notes, unfinished labs and already-pushed labs are skipped.

For each imported page it:
  - names the folder from the title ("Day 11 - Static Routes" -> labs/day-11-static-routes)
  - turns the exported properties into a header table (hides the ones in HIDE)
  - copies referenced images into images/ with clean names and fixes the links
  - saves any existing README.md as README.md.bak (gitignored)
Then it refreshes the lab index in the root README.md between the LABS markers.
Accepts a .zip or an unzipped export folder.
"""
import re
import shutil
import sys
import tempfile
import urllib.parse
import zipfile
from collections import Counter
from pathlib import Path

IMG = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
LINK = re.compile(r"!\[([^\]]*)\]\(((?:[^()]|\([^()]*\))+)\)")
PROP = re.compile(r"^([A-Za-z][^:\n]{0,40}):\s*(.*)$")

# Database properties Notion exports as "Name: value" lines under the title.
# Edit these to match your database.
HIDE = {"day #", "lab done", "github write-up", "packet tracer file"}  # not shown in the repo
SHOW = {"lab date", "status", "tool", "time taken"}                    # shown in the header table
COURSE = "Jeremy's IT Lab – CCNA 200-301"

START, END = "<!-- LABS:START -->", "<!-- LABS:END -->"


def extract(src: str, tmp: str) -> Path:
    p = Path(src).expanduser()
    if not p.exists():
        sys.exit(f"Can't find {p}")
    if p.is_dir():
        return p
    with zipfile.ZipFile(p) as z:
        z.extractall(tmp)
    for inner in list(Path(tmp).glob("*.zip")):  # newer exports nest a zip
        with zipfile.ZipFile(inner) as z:
            z.extractall(tmp)
        inner.unlink()
    return Path(tmp)


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "lab"
    return re.sub(r"^day-(\d)(?=-|$)", r"day-0\1", s)  # day-1 -> day-01


def clean_name(name: str, used: set) -> str:
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    base = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "image"
    new, i = base + ext, 2
    while new in used:
        new, i = f"{base}-{i}{ext}", i + 1
    used.add(new)
    return new


def split_page(text: str):
    lines = text.lstrip("\ufeff").splitlines()
    title = "Untitled"
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
    i = 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    props = []
    known = HIDE | SHOW
    while i < len(lines):
        m = PROP.match(lines[i])
        if not m or m.group(1).strip().lower() not in known:
            break
        props.append((m.group(1).strip(), m.group(2).strip().lstrip("@")))
        i += 1
    return title, props, "\n".join(lines[i:]).lstrip("\n")


def header_table(props) -> str:
    rows = [("Course", COURSE)]
    rows += [(k, v) for k, v in props if k.lower() not in HIDE and v]
    return "| | |\n|---|---|\n" + "\n".join(f"| **{k}** | {v} |" for k, v in rows)


def import_page(page: Path, force: bool):
    """Returns (status, title). status is 'ok' or a skip reason."""
    title, props, body = split_page(page.read_text(encoding="utf-8"))
    flags = {k.lower(): v.lower() for k, v in props}
    if flags.get("lab done") != "yes":
        return "not marked Lab Done", title
    if flags.get("github write-up") == "yes" and not force:
        return "already published", title

    target = Path("labs") / slugify(title)
    img_dir = target / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    used, done = set(), {}

    def fix(m: re.Match) -> str:
        alt, url = m.group(1), m.group(2)
        if url.startswith(("http://", "https://", "data:")):
            return m.group(0)
        f = (page.parent / urllib.parse.unquote(url)).resolve()
        if not f.is_file() or f.suffix.lower() not in IMG:
            return m.group(0)
        if f not in done:
            done[f] = clean_name(f.name, used)
            shutil.copy2(f, img_dir / done[f])
        return f"![{alt}](images/{done[f]})"

    out = f"# {title}\n\n{header_table(props)}\n\n{LINK.sub(fix, body)}".rstrip() + "\n"
    readme = target / "README.md"
    if readme.exists():
        shutil.copy2(readme, target / "README.md.bak")
    readme.write_text(out, encoding="utf-8")
    if "notion.so" in out or "notion.site" in out:
        print(f"  Warning: Notion links in {readme}. Review before pushing.")
    if not done and "![" in body:
        print(f"  Note: {readme} has images that were not found in the export.")
    print(f"  + {readme}  ({len(done)} image(s))")
    return "ok", title


def update_index() -> None:
    readme = Path("README.md")
    if not readme.exists():
        return
    text = readme.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print("README.md has no LABS markers, so the index was not updated.")
        return
    rows = []
    for page in sorted(Path("labs").glob("*/README.md")):
        content = page.read_text(encoding="utf-8")
        first = content.splitlines()[0].lstrip("# ").strip() if content else page.parent.name
        m = re.search(r"\|\s*\*\*Lab Date\*\*\s*\|\s*(.+?)\s*\|", content)
        rows.append(f"| [{first}]({page.parent.as_posix()}/README.md) | {m.group(1) if m else ''} |")
    block = "| Lab | Date |\n|---|---|\n" + "\n".join(rows) if rows else "_No labs published yet._"
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    readme.write_text(f"{head}{START}\n{block}\n{END}{tail}", encoding="utf-8")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv[1:]
    if len(args) != 1:
        sys.exit("Usage: import_notion.py <export.zip|folder> [--force]")
    if not Path(".git").exists():
        sys.exit("Run this from the repo root (the folder containing .git).")

    results = Counter()
    with tempfile.TemporaryDirectory() as tmp:
        root = extract(args[0], tmp)
        pages = sorted(root.rglob("*.md"))
        if not pages:
            sys.exit("No .md files found in the export.")
        print(f"Found {len(pages)} page(s) in the export.")
        for page in pages:
            status, _title = import_page(page, force)
            results[status] += 1

    update_index()
    print(f"\nImported: {results['ok']}")
    for reason, n in results.items():
        if reason != "ok":
            print(f"Skipped ({reason}): {n}")
    if results["ok"]:
        print("Next: check a few render, add your .pkt files to the lab folders, commit and push,")
        print("then tick GitHub Write-up on those rows in Notion.")
    else:
        print("Nothing imported. Tick Lab Done on finished labs (and untick GitHub Write-up to re-import).")


if __name__ == "__main__":
    main()
