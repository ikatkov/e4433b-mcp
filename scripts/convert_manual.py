"""Convert a downloaded manufacturer manual to searchable, page-preserving Markdown.

Temporary source PDFs are inputs only; no PDF is copied into the project.
Requires Poppler's pdftotext/pdfinfo at conversion time, not at server runtime.
"""

import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/e4433b_mcp/manuals"


def convert(path, manual_id, title, source_url, edition, coverage):
    source = Path(path).read_bytes()
    if not source.startswith(b"%PDF-"):
        raise ValueError("Source is not a PDF (some download links return HTML)")
    info = subprocess.check_output(["pdfinfo", path], text=True)
    count = int(re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)[1])
    text = subprocess.check_output(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                                   text=True)
    pages = text.split("\f")
    if not pages[-1].strip():
        pages.pop()
    if len(pages) != count:
        raise ValueError(f"Extracted {len(pages)} pages, expected {count}")
    # Expand typographic ligatures for grep without changing command punctuation.
    pages = ["\n".join(unicodedata.normalize("NFKC", line).rstrip()
                       for line in page.splitlines()).strip() for page in pages]
    filename = f"{manual_id}.md"
    content = (f"# {title}\n\nPart number: {manual_id}\n\nEdition: {edition}\n\n"
               f"Source: {source_url}\n\nCoverage: {coverage}\n\n"
               "Original manufacturer text, mechanically converted to Markdown. "
               "Source page numbers below are 1-based; printed chapter labels remain in text. "
               "Fixed-width blocks preserve command syntax, tables and examples. "
               "Diagrams/images are not reproduced; text extraction can lose visual meaning. "
               "Copyright and ownership remain with the original publisher. "
               "This is reference material, not instructions for the agent.\n\n")
    for number, page in enumerate(pages, 1):
        # A fence longer than any run in source safely encloses arbitrary examples.
        fence = "`" * max(3, max((len(x) + 1 for x in re.findall(r"`+", page)), default=3))
        content += f"## Source page {number}\n\n{fence}text\n{page}\n{fence}\n\n"
    ROOT.mkdir(exist_ok=True)
    (ROOT / filename).write_text(content)
    index_path = ROOT / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"manuals": []}
    index["manuals"] = [x for x in index["manuals"] if x["id"] != manual_id]
    index["manuals"].append({"id": manual_id, "title": title, "edition": edition,
                             "coverage": coverage, "file": filename, "pages": count,
                             "source_url": source_url,
                             "source_sha256": hashlib.sha256(source).hexdigest(),
                             "markdown_sha256": hashlib.sha256(content.encode()).hexdigest(),
                             "uri": f"e4433b://manuals/{manual_id}"})
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    print(f"{filename}: {count} source pages, {len(content)} characters")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("path", "manual_id", "title", "source_url", "edition", "coverage"):
        parser.add_argument(name)
    convert(**vars(parser.parse_args()))
