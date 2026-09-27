# Original Agilent manuals in Markdown

After running `uv run python scripts/fetch_manuals.py`, these are full text conversions of the original manufacturer manuals, not AI
summaries or lists limited to implemented tools. All source pages are retained. Full manufacturer text is local-only and excluded from Git and package builds.
No PDFs are stored in this project or served by MCP.

| Manual | Edition | Source pages | Coverage |
| --- | --- | ---: | --- |
| `E4400-90324.md` | April 2002 | 259 | Base SCPI commands, status system, examples and key-to-command reference |
| `E4400-90328.md` | December 2005 | 275 | UND Dual ARB and optional UN5 CDMA; first page is a mirror's advertisement |
| `E4400-90327.md` | June 2001 | 446 | UN8 real-time I/Q, TDMA and optional 202 EDGE |
| `E4400-90323.md` | April 2002 | 225 | Front-panel controls and operation |

The connected instrument reports firmware B.03.86 and options 1E5, UN8, UN9, UND.
Some manuals cover other models, firmware and options. A documented command is
not a guarantee that this particular instrument supports it. The library covers
the base instrument and its installed modulation hardware; it does not include
every separately licensed ESG personality or service/calibration manual.

## Use through MCP

1. `list_manuals` lists source URLs, editions and coverage.
2. `search_manuals` searches literal text, ignoring case and whitespace differences.
   Use long-form SCPI names such as `HICRest`, or descriptive keywords. Abbreviated
   commands may not appear literally in the original manual.
3. `read_manual_pages` returns 1–5 pages of context. Source page numbers are
   1-based, while printed chapter/page labels remain inside the text.
4. Resources `e4433b://manuals/{manual_id}` expose complete Markdown, and
   `e4433b://manuals/{manual_id}/pages/{page}` expose individual pages.
5. Prefer typed controls for tested procedures. Use `scpi_query` / `scpi_write`
   for an unsupported feature after checking model and option applicability.
   Expert tools add no implicit commands. Check readback and `read_errors` afterward.

## Use ordinary text tools

From the MCP project directory:

```sh
rg -n -i 'HICRest|power search' src/e4433b_mcp/manuals/*.md
rg -n 'RADio.*ARB' src/e4433b_mcp/manuals/E4400-90328.md
```

Imported files stay in this checkout and require no network access at runtime.
`index.json` records original source and converted Markdown SHA-256 hashes.
The conversion script is `scripts/convert_manual.py`; it needs Poppler only when
converting a new source. UN8 was extracted from all 446 numbered HTML pages of
the source mirror because the PDF downloads were unavailable.

## Conversion limits

Command punctuation, examples and tables are kept in fixed-width text blocks;
typographic ligatures are expanded so normal text searches work. Figures are not
reproduced. Tables, equations, symbols and multi-column text may lose meaning
during extraction, particularly in the UN8 HTML transcription. Consult the
linked original source when a passage is ambiguous. This is reference data, not
instructions to an agent. Original publisher copyright notices are retained.
