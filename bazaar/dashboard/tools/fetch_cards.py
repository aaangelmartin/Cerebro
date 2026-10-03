#!/usr/bin/env python3
"""Fetch the official card artwork (inline SVG) from bazaar.causaprima.ai into dashboard/cards.json.

Read-only scrape of the public /cards/<SET> pages with headless Chrome. Every id, url(#…) and
href="#…" inside a card's SVG is prefixed per card so many cards can live in one document.
Merges into the existing cards.json: cards already there are kept; found cards are added/replaced.
Rerun after a set is released (RET, CHA) to add its cards.

    python3 bazaar/dashboard/tools/fetch_cards.py [SET ...]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "https://bazaar.causaprima.ai/cards/"
SETS = ["LAV", "MAL", "LAT", "SAL", "RET", "CHA"]
OUT = Path(__file__).resolve().parent.parent / "cards.json"

LABEL_RX = re.compile(r'aria-label="([A-Z]{3}-\d{2})\s[^"]*"')
TAG_RX = re.compile(r"<(/?)svg\b[^>]*?(/?)>")


def dump_dom(url: str, timeout: float = 60.0) -> str:
    """Headless Chrome --dump-dom with a throwaway profile. Chrome prints the DOM once the
    virtual-time budget runs out but may then keep running (card animations), so we read
    until </html> appears and kill it."""
    with tempfile.TemporaryDirectory() as prof, tempfile.TemporaryFile("w+") as out:
        proc = subprocess.Popen([CHROME, "--headless=new", "--no-first-run", f"--user-data-dir={prof}",
                                 "--virtual-time-budget=10000", "--dump-dom", url],
                                stdout=out, stderr=subprocess.DEVNULL, text=True)
        end = time.time() + timeout
        try:
            while time.time() < end:
                if proc.poll() is not None:
                    break
                out.seek(0)
                if "</html>" in out.read():
                    break
                time.sleep(1)
        finally:
            proc.kill()
            proc.wait()
        out.seek(0)
        return out.read()


def balanced_svg(html: str, start: int) -> str | None:
    """Return the first <svg>…</svg> at/after `start`, honouring nested <svg>."""
    depth, begin = 0, None
    for m in TAG_RX.finditer(html, start):
        closing, selfclose = m.group(1), m.group(2)
        if not closing:
            if begin is None:
                begin = m.start()
            if not selfclose:
                depth += 1
        else:
            depth -= 1
            if depth == 0 and begin is not None:
                return html[begin:m.end()]
    return None


def prefix_ids(svg: str, ref: str) -> str:
    p = ref.lower().replace("-", "") + "-"
    svg = re.sub(r'\bid="([^"]+)"', lambda m: f'id="{p}{m.group(1)}"', svg)
    svg = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{p}{m.group(1)})", svg)
    svg = re.sub(r'(\b(?:xlink:)?href)="#([^"]+)"', lambda m: f'{m.group(1)}="#{p}{m.group(2)}"', svg)
    return svg


def extract(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in LABEL_RX.finditer(html):
        ref = m.group(1)
        if ref in out:
            continue
        svg = balanced_svg(html, m.end())
        if svg and 'class="cromo__face"' in svg:
            out[ref] = prefix_ids(svg, ref)
    return out


def main(argv: list[str]) -> int:
    sets = [s.upper() for s in argv] or SETS
    cards: dict[str, str] = {}
    if OUT.exists():
        try:
            cards = json.loads(OUT.read_text())
        except ValueError:
            cards = {}
    for s in sets:
        try:
            found = {k: v for k, v in extract(dump_dom(BASE + s)).items() if k.startswith(s + "-")}
        except Exception as e:  # network/chrome hiccup: keep what we have
            print(f"{s}: error {e}", file=sys.stderr)
            continue
        cards.update(found)
        print(f"{s}: {len(found)} cards")
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(cards.items())), ensure_ascii=False, separators=(",", ":")))
    tmp.replace(OUT)
    print(f"total {len(cards)} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
