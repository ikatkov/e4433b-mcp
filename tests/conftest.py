"""Small original fixture texts allow CI without redistributing manufacturer manuals."""

import json

import pytest

from e4433b_mcp import manuals


@pytest.fixture
def sample_manuals(tmp_path, monkeypatch):
    root = tmp_path / "manuals"
    root.mkdir()
    body = ("# Programming Guide fixture\n\n## Source page 1\n\n"
            "Programming Guide test text: SCPI HICRest example.\n\n"
            "## Source page 2\n\nSCPI second example for pagination.\n")
    (root / "E4400-90324.md").write_text(body)
    (root / "README.md").write_text("# Test manual catalog\n")
    (root / "index.json").write_text(json.dumps({"manuals": [{
        "id": "E4400-90324", "file": "E4400-90324.md", "pages": 2,
        "source_url": "https://example.com/manual"}]}))
    manuals._pages.cache_clear()
    monkeypatch.setattr(manuals, "ROOT", root)
    yield root
    manuals._pages.cache_clear()
