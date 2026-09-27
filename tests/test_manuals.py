import hashlib

import pytest

from e4433b_mcp import manuals


def test_all_source_pages_present_and_markdown_hashes_match():
    if not all(entry["available"] for entry in manuals.catalog()["manuals"]):
        pytest.skip("Full manufacturer texts are optional local data; run fetch_manuals.py")
    for entry in manuals.catalog()["manuals"]:
        text = manuals.markdown(entry["id"])
        assert hashlib.sha256(text.encode()).hexdigest() == entry["markdown_sha256"]
        assert len(manuals._pages(entry["id"])) == entry["pages"]
        assert set(manuals._pages(entry["id"])) == set(range(1, entry["pages"] + 1))
        nonempty = [p for p in manuals._pages(entry["id"]).values()
                    if len(p.removeprefix("```text").removesuffix("```").strip()) > 0]
        assert len(nonempty) >= 0.95 * entry["pages"]
        assert entry["id"] in text
    assert not list(manuals.ROOT.glob("*.pdf"))


def test_search_returns_original_syntax_and_readable_page(sample_manuals):
    result = manuals.search("HICRest", "E4400-90324", 1)
    assert result["matching_pages"] > 0
    first = result["results"][0]
    page = manuals.read_pages(first["manual_id"], first["page"])
    assert "hicrest" in page["pages"][0]["markdown"].casefold()
    assert manuals.search("hicrest", "E4400-90324", 1)["results"] == result["results"]
    assert manuals.search("definitely-no-such-command")["results"] == []


def test_search_pagination_is_stable(sample_manuals):
    first = manuals.search("SCPI", max_results=1)
    second = manuals.search("SCPI", max_results=1, offset=first["next_offset"])
    assert first["results"] != second["results"]


@pytest.mark.parametrize("manual_id,page,count", [
    ("../../driver.py", 1, 1), ("E4400-90324", 0, 1),
    ("E4400-90324", 999999, 1), ("E4400-90324", 1, 6)])
def test_manual_lookup_cannot_escape_library_or_exceed_bounds(
        sample_manuals, manual_id, page, count):
    with pytest.raises(ValueError):
        manuals.read_pages(manual_id, page, count)


def test_missing_manual_has_setup_instructions(sample_manuals):
    (sample_manuals / "E4400-90324.md").unlink()
    assert manuals.catalog()["manuals"][0]["available"] is False
    for operation in (lambda: manuals.markdown("E4400-90324"),
                      lambda: manuals.search("HICRest")):
        with pytest.raises(ValueError, match="fetch_manuals.py"):
            operation()
