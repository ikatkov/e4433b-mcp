# E4433B MCP server

Control an **HP/Agilent E4433B ESG signal generator** from an MCP client through
an **AR488 USB–GPIB adapter**. Includes RF settings, analog AM, arbitrary waveform
playback, verified WAV upload, expert SCPI query/write tools, and searchable
original documentation converted to Markdown locally. No VISA runtime is needed.

Bench-tested with an E4433B identifying as `ESG-D4000B`, firmware B.03.86, options
1E5/UN8/UN9/UND, and AR488 0.55.22. Supports macOS and POSIX Linux; the process
lock currently uses `fcntl`, so native Windows is not supported.

## Install

Install [uv](https://docs.astral.sh/uv/), then:

```sh
git clone https://github.com/ikatkov/e4433b-mcp.git
cd e4433b-mcp
./setup
```

`setup` installs Python into `.python/` and dependencies into `.venv/`, both inside
this checkout. It copies dependencies instead of linking to another project's
files. The stable MCP entry point is **`run-mcp`**; clients need not know the
virtual environment path. Nothing opens the instrument during startup/discovery.
After relocating the checkout, rerun setup to regenerate environment paths.

The server has no network listener. Once installed, hardware control and manual
search work offline. Hardware serial access and operating-system libraries remain
normal external system interfaces.

## Connect a client

From the project directory, register the absolute launcher path.

Claude Code:

```sh
claude mcp add --scope user --transport stdio e4433b --env E4433B_ADDRESS=30 -- "$(pwd)/run-mcp"
```

Codex:

```sh
codex mcp add e4433b --env E4433B_ADDRESS=30 -- "$(pwd)/run-mcp"
```

Configure the client's tool-call timeout to **900 seconds** for waveform transfers.
For Codex this is `tool_timeout_sec = 900` in `[mcp_servers.e4433b]`.
See the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).
Reload the MCP connection or start a new client session after changing registration.

Any stdio MCP client can use this configuration, with its own timeout setting:

```json
{
  "mcpServers": {
    "e4433b": {
      "command": "/absolute/path/to/e4433b-mcp/run-mcp",
      "env": {"E4433B_ADDRESS": "30"}
    }
  }
}
```

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `E4433B_PORT` | automatic | Select the only CH340 adapter; set explicitly for other adapters or ambiguity. |
| `E4433B_ADDRESS` | `30` | Generator GPIB primary address. |
| `E4433B_SERIAL` | unset | Optional check against your generator's serial number. |

The adapter link is 115200 baud. Start with `get_status`. Only one client may own
an adapter at a time; call `disconnect` before using it from another session.

## Original documentation as Markdown

The catalog covers four original Agilent manuals, **1,205 source pages**:
base SCPI, front-panel operation, UND Dual ARB and UN8 real-time I/Q.

To build the local Markdown library, install `curl` and Poppler (`pdftotext` and
`pdfinfo`), then run:

```sh
uv run python scripts/fetch_manuals.py
```

Source PDFs are temporary inputs and are removed after conversion. No PDFs are
stored in the project. The full manufacturer text retains its original copyright
and is **not redistributed on GitHub or in package builds**; see
[third-party notices](THIRD_PARTY_NOTICES.md). Your generated `.md` files remain
inside `src/e4433b_mcp/manuals/`, usable with ordinary `grep`/`rg` and MCP search.

The server works without the manual download; the catalog reports availability
and text tools explain how to install missing manuals. Once imported, no network
is needed. Sources, editions, page numbering and conversion limitations are in
[the manual index](src/e4433b_mcp/manuals/README.md).

## Tools

| Tool | Purpose |
| --- | --- |
| `list_adapters` | Enumerate USB adapters without connecting. |
| `get_status` | Read identity, options and the full signal-path configuration. |
| `read_errors` | Return and consume the error queue without silently clearing it. |
| `set_rf` | Set carrier/level; preserve modulation and RF state. |
| `set_rf_output` | Explicit RF output enable/disable. |
| `list_waveforms` | List volatile ARB waveforms. |
| `play_waveform` | Restore continuous I/Q playback of an existing waveform. |
| `configure_am_tone` | Configure ordinary analog sine AM. |
| `set_am_depth` | Change active analog AM depth. |
| `upload_am_wav` | Convert mono 16-bit PCM WAV, upload separate I/Q planes and verify bytes. |
| `inspect_waveform` | Read I/Q hashes and sample ranges. |
| `disconnect` | Release the adapter and optionally return front-panel control. |
| `list_manuals` | List manual editions, sources, coverage and local availability. |
| `search_manuals` | Search Markdown and return page references. |
| `read_manual_pages` | Read 1–5 source pages as Markdown. |
| `scpi_query` | Send one expert ASCII query and read exactly one response. |
| `scpi_write` | Send one expert ASCII non-query without extra commands. |

Static resources: `e4433b://guide`, `e4433b://commands`, `e4433b://manuals`.
Templates expose complete manuals and individual pages. Prefer typed controls for
supported tasks; use expert SCPI after checking model and option applicability.
ASCII commands must be shorter than 128 bytes and cannot contain batches/newlines.
Binary transfers use the dedicated block transport.

## RF and transfer behavior

- Configuration/playback tools leave RF **off** unless `rf_on=true` is explicit.
  `set_rf` preserves the existing RF state. `disconnect` does not change RF state.
- Expert tools execute exactly the requested command. They add no RF mute, reset,
  error drain or retry. Verify writes using the documented query and `read_errors`.
- One persistent serial connection avoids resetting the Nano per query. Whole
  operations are serialized; a process lease prevents competing clients.
- `++auto 0` plus explicit query/read pairs avoids extra reads. On the verified
  firmware, options are read with `DIAG:INFO:OPT?`, not `*OPT?`.
- E443xB UND uploads use **separate ARBI/ARBQ planes, offset-14-bit big-endian
  samples**, escaped 96-byte chunks and final-only EOI. This differs from newer
  interleaved waveform formats. Interrupted uploads can leave partial files.
- Typed configuration failures attempt RF off. A lost connection cannot guarantee
  physical output state. Writes are never automatically retried.
- Uploaded voice AM depth is encoded in its I/Q samples; the analog AM depth menu
  does not change it. Instrument readback is distinct from a scope measurement.

See [operating notes](src/e4433b_mcp/guide.md),
[command provenance](src/e4433b_mcp/commands.md),
[bench validation](docs/validation.md), and
[source-level comparisons](docs/comparison.md).

## Development

```sh
./setup
uv run pytest
uv run ruff check .
uv run python scripts/check_mcp.py
```

Tests run without hardware or original manual downloads. An additional integration
test checks full manuals when installed. For a read-only live check, release any
other client and use `uv run python scripts/check_mcp.py --hardware`; it reads
status/catalog and disconnects without enabling RF or clearing errors.

MIT licensed code. Manufacturer documentation is separately owned.
