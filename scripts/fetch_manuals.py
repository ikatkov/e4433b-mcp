"""Build the original-manual Markdown library locally; source PDFs are temporary."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from convert_manual import ROOT, convert
from convert_un8_html import main as convert_un8


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild already installed manuals")
    args = parser.parse_args()
    entries = json.loads((ROOT / "index.json").read_text())["manuals"]
    pending = [e for e in entries if args.force or not (ROOT / e["file"]).is_file()]
    if not pending:
        print("All four Markdown manuals are already installed.")
        return
    for command in ("curl", "pdftotext", "pdfinfo"):
        if not shutil.which(command):
            raise SystemExit(f"Missing {command}. Install curl and Poppler, then retry.")
    original_index = (ROOT / "index.json").read_bytes()
    try:
        install(pending)
    finally:
        # The committed source manifest is stable; imports only add local text.
        (ROOT / "index.json").write_bytes(original_index)


def install(pending):
    with tempfile.TemporaryDirectory(prefix="e4433b-manuals-") as temporary:
        for entry in pending:
            if entry["id"] == "E4400-90327":
                convert_un8()
                continue
            path = Path(temporary) / f"{entry['id']}.pdf"
            subprocess.run(["curl", "-fsSL", "--max-time", "120", entry["source_url"],
                            "-o", str(path)], check=True)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry["source_sha256"]:
                raise SystemExit(f"{entry['id']}: source hash changed; inspect the new edition "
                                 "before updating the manifest. Nothing was converted.")
            convert(str(path), entry["id"], entry["title"], entry["source_url"],
                    entry["edition"], entry["coverage"])


if __name__ == "__main__":
    main()
