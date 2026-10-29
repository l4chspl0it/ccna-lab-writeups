#!/usr/bin/env python3
"""Import a Notion "Markdown & CSV" export into a day folder.

Run from the repo root:
    python3 scripts/import_notion.py ~/Downloads/Export-xxxx.zip 11

It will: find labs/day-11*/, write the page as README.md (old one saved as
README.md.bak), copy referenced images into images/ with clean names, and
rewrite the image links. Accepts a .zip or an unzipped export folder.
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


def extract(src: str, tmp: str) -> Path:
    p = Path(src).expanduser()
    if p.is_dir():
        return p
    with zipfile.ZipFile(p) as z:
        z.extractall(tmp)
    # Newer Notion exports put a zip inside the zip.
    for inner in list(Path(tmp).glob("*.zip")):
        with zipfile.ZipFile(inner) as z:
            z.extractall(tmp)
        inner.unlink()
    return Path(tmp)


def clean_name(name: str, used: set) -> str:
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    base = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "image"
    new, i = base + ext, 2
    while new in used:
        new, i = f"{base}-{i}{ext}", i + 1
    used.add(new)
    return new


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("Usage: import_notion.py <export.zip|folder> <day-number>")
    src, day = sys.argv[1], sys.argv[2].zfill(2)

    matches = sorted(Path("labs").glob(f"day-{day}*"))
    if len(matches) != 1:
        sys.exit(f"Expected one labs/day-{day}* folder, found {len(matches)}. Run from the repo root.")
    target = matches[0]

    with tempfile.TemporaryDirectory() as tmp:
        root = extract(src, tmp)
        pages = sorted(root.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
        if not pages:
            sys.exit("No .md file found in the export.")
        page = pages[0]
        if len(pages) > 1:
            print(f"Note: {len(pages)} pages found, using the largest: {page.name}")

        text = page.read_text(encoding="utf-8")
        img_dir = target / "images"
        img_dir.mkdir(exist_ok=True)
        used = set()  # re-importing a page overwrites its images, no duplicates
        done, copied = {}, 0

        def fix(m: re.Match) -> str:
            alt, url = m.group(1), m.group(2)
            if url.startswith(("http://", "https://", "data:")):
                return m.group(0)
            f = (page.parent / urllib.parse.unquote(url)).resolve()
            if not f.is_file() or f.suffix.lower() not in IMG:
                return m.group(0)
            nonlocal copied
            if f not in done:
                done[f] = clean_name(f.name, used)
                shutil.copy2(f, img_dir / done[f])
                copied += 1
            return f"![{alt}](images/{done[f]})"

        text = LINK.sub(fix, text)

        readme = target / "README.md"
        if readme.exists():
            shutil.copy2(readme, target / "README.md.bak")
        readme.write_text(text, encoding="utf-8")

    print(f"Wrote {readme} and copied {copied} image(s) to {img_dir}/")
    if "notion.so" in text or "notion.site" in text:
        print("Warning: Notion links found in the file. Review before pushing.")
    print("Next: check it renders, add your .pkt, tick the day in the root README, then commit.")


if __name__ == "__main__":
    main()
