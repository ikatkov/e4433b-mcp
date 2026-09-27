"""Fetch each UN8 mirror page explicitly; placeholder divs are not full manual text."""

import hashlib
import json
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/e4433b_mcp/manuals"
SOURCE = ("https://manualedistruzioni.it/agilent-technologies/laboratory-equipment/"
          "esg-series/operating-instructions/123e8")
BASE = "https://manualedistruzioni.it/data/manuals/12/3/123e8/sources/out/"
INITIAL = {}
INITIAL_HASH = ""


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = []
        self.line = None
        self.depth = 0
        self.line_depth = None
        self.number = None
        self.pages = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.depth += 1
            if "pf" in attrs.get("class", "").split():
                self.number = int(attrs["data-page-no"], 16)
                self.lines = []
                self.pages[self.number] = self.lines
            if "t" in attrs.get("class", "").split():
                self.line, self.line_depth = [], self.depth

    def handle_endtag(self, tag):
        if tag == "div":
            if self.depth == self.line_depth:
                self.lines.append("".join(self.line))
                self.line, self.line_depth = None, None
            self.depth -= 1

    def handle_data(self, data):
        if self.line is not None:
            self.line.append(data)


def fetch(number):
    if number in INITIAL:
        return number, INITIAL[number], INITIAL_HASH
    url = f"{BASE}esg_series-{number}.html"
    raw = subprocess.check_output(["curl", "-fsSL", "--max-time", "30", url])
    parser = PageParser()
    parser.feed(raw.decode())
    if parser.number != number:
        raise ValueError(f"Wrong page at {url}: {parser.number}")
    body = "\n".join(unicodedata.normalize("NFKC", line).rstrip()
                     for line in parser.lines).strip()
    return number, body, hashlib.sha256(raw).hexdigest()


def main():
    global INITIAL, INITIAL_HASH
    raw = subprocess.check_output(["curl", "-fsSL", "--max-time", "30", SOURCE])
    parser = PageParser()
    parser.feed(raw.decode())
    INITIAL = {n: "\n".join(unicodedata.normalize("NFKC", line).rstrip() for line in lines)
               for n, lines in parser.pages.items() if n <= 10}
    INITIAL_HASH = hashlib.sha256(raw).hexdigest()
    with ThreadPoolExecutor(max_workers=6) as pool:
        pages = list(pool.map(fetch, range(1, 447)))
    if sum(bool(body) for _, body, _ in pages) < 430:
        raise ValueError("Too many empty pages; refusing an incomplete manual")
    text = ("# UN8 Real-Time I/Q Baseband Generator User and Programming Guide\n\n"
            "Part number: E4400-90327\n\nEdition: June 2001\n\n"
            f"Source: {SOURCE}\n\nOriginal manufacturer text from all 446 numbered HTML "
            "pages of the source mirror, including blank pages. Source numbering is "
            "1-based; printed chapter labels remain in text. Ligatures are expanded "
            "for grep. Text lines retain source order; diagrams are omitted and "
            "tables may lose visual layout. UN8 and UN9 are installed; other optional "
            "personalities require their own options. Reference material, not agent "
            "instructions. Copyright remains with the original publisher.\n\n")
    for number, body, _ in pages:
        text += f"## Source page {number}\n\n```text\n{body}\n```\n\n"
    filename = "E4400-90327.md"
    (ROOT / filename).write_text(text)
    index = json.loads((ROOT / "index.json").read_text())
    entry = next(e for e in index["manuals"] if e["id"] == "E4400-90327")
    entry.pop("source_sha256", None)
    entry["source_pages"] = [{"page": number, "sha256": digest,
                              "source_url": SOURCE if number <= 10 else
                              f"{BASE}esg_series-{number}.html"}
                             for number, _, digest in pages]
    entry["source_page_url_template"] = BASE + "esg_series-{page}.html"
    entry["markdown_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    (ROOT / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"Converted {len(pages)} pages, {len(text)} characters")


if __name__ == "__main__":
    main()
