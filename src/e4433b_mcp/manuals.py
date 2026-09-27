"""Offline Markdown reference library; never connects to hardware or the web."""

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).with_name("manuals")


def catalog():
    result = json.loads((ROOT / "index.json").read_text())
    for entry in result["manuals"]:
        entry.pop("source_pages", None)  # Per-page hashes remain in the local manifest.
        entry["available"] = (ROOT / entry["file"]).is_file()
    return result


def _entry(manual_id):
    for entry in catalog()["manuals"]:
        if entry["id"] == manual_id:
            return entry
    raise ValueError("Unknown manual_id; use list_manuals")


def markdown(manual_id):
    path = ROOT / _entry(manual_id)["file"]
    if not path.is_file():
        raise ValueError("Manual text is not installed. From the checkout run: "
                         "uv run python scripts/fetch_manuals.py")
    return path.read_text()


@lru_cache(maxsize=8)
def _pages(manual_id):
    chunks = re.split(r"^## Source page (\d+)\s*$", markdown(manual_id), flags=re.MULTILINE)
    return {int(chunks[i]): chunks[i + 1].strip() for i in range(1, len(chunks), 2)}


def read_pages(manual_id, page, page_count=1):
    if not 1 <= page_count <= 5:
        raise ValueError("page_count must be 1–5")
    pages = _pages(manual_id)
    if page < 1 or page + page_count - 1 > len(pages):
        raise ValueError(f"Source page range must be within 1–{len(pages)}")
    return {"manual_id": manual_id, "source": _entry(manual_id)["source_url"],
            "numbering": "1-based source document pages; printed labels remain in text",
            "pages": [{"page": p, "markdown": pages[p]}
                      for p in range(page, page + page_count)]}


def search(query, manual_id=None, max_results=10, offset=0):
    needle = " ".join(query.casefold().split())
    if not needle or len(needle) > 200:
        raise ValueError("Search needs 1–200 characters")
    if not 1 <= max_results <= 30 or offset < 0:
        raise ValueError("max_results must be 1–30; offset must be nonnegative")
    entries = [_entry(manual_id)] if manual_id else catalog()["manuals"]
    missing = [entry["id"] for entry in entries if not entry["available"]]
    entries = [entry for entry in entries if entry["available"]]
    if not entries:
        raise ValueError("Manual text is not installed. From the checkout run: "
                         "uv run python scripts/fetch_manuals.py")
    matches = []
    for entry in entries:
        for page, body in _pages(entry["id"]).items():
            normalized = " ".join(body.split())
            position = normalized.casefold().find(needle)
            if position >= 0:
                matches.append({"manual_id": entry["id"], "page": page,
                                "excerpt": normalized[max(0, position - 180):position + 600],
                                "uri": f"e4433b://manuals/{entry['id']}/pages/{page}"})
    end = offset + max_results
    return {"query": query, "matching_pages": len(matches),
            "results": matches[offset:end], "next_offset": end if end < len(matches) else None,
            "unavailable_manuals": missing,
            "note": "Literal, case-insensitive search with whitespace normalized. "
                    "Search long SCPI spellings or keywords; abbreviations may not appear."}
