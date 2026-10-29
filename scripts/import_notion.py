#!/usr/bin/env python3
"""Import a Notion database-page export (Markdown & CSV) into labs/<slug>/.

Run from the repo root:
    python3 scripts/import_notion.py ~/Downloads/Export-xxxx.zip

What it does:
  - names the folder from the page title ("Day 11 - Static Routes" -> labs/day-11-static-routes)
  - turns the exported properties into a header table (hides the ones in HIDE)
  - copies referenced images into images/ with clean names and fixes the links
  - saves any existing README.md as README.md.bak (gitignored)
  - refreshes the lab index in the root README.md between the LABS markers
Accepts a .zip or an unzipped export folder.
"""
import re
import shutil
import sys
import tempfile
import urllib.parse
import zipfile
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
    if len(sys.argv) != 2:
        sys.exit("Usage: import_notion.py <export.zip|folder>")
    if not Path(".git").exists():
        sys.exit("Run this from the repo root (the folder containing .git).")

    with tempfile.TemporaryDirectory() as tmp:
        root = extract(sys.argv[1], tmp)
        pages = sorted(root.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
        if not pages:
            sys.exit("No .md file found in the export.")
        page = pages[0]
        if len(pages) > 1:
            print(f"Note: {len(pages)} pages found, using the largest: {page.name}")

        title, props, body = split_page(page.read_text(encoding="utf-8"))
        target = Path("labs") / slugify(title)
        img_dir = target / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        used, done, copied = set(), {}, 0

        def fix(m: re.Match) -> str:
            nonlocal copied
            alt, url = m.group(1), m.group(2)
            if url.startswith(("http://", "https://", "data:")):
                return m.group(0)
            f = (page.parent / urllib.parse.unquote(url)).resolve()
            if not f.is_file() or f.suffix.lower() not in IMG:
                return m.group(0)
            if f not in done:
                done[f] = clean_name(f.name, used)
                shutil.copy2(f, img_dir / done[f])
                copied += 1
            return f"![{alt}](images/{done[f]})"

        out = f"# {title}\n\n{header_table(props)}\n\n{LINK.sub(fix, body)}".rstrip() + "\n"
        readme = target / "README.md"
        if readme.exists():
            shutil.copy2(readme, target / "README.md.bak")
        readme.write_text(out, encoding="utf-8")

    update_index()
    print(f"Wrote {readme} and copied {copied} image(s).")
    if "notion.so" in out or "notion.site" in out:
        print("Warning: Notion links found in the file. Review before pushing.")
    print("Next: check it renders, add your .pkt to the folder, then commit and push.")


if __name__ == "__main__":
    main()
