# Validation — 27 September 2026

## Offline and MCP protocol

- **49 tests passed during the original bench session**, plus Ruff. Tests cover transport framing/escaping, query/write
  separation, final-only EOI, binary truncation, identity checks, process lease,
  serialization, failure cleanup, waveform encoding, profile readback, analog/IQ
  separation, and MCP discovery without hardware.
- Regression coverage verifies that ARB enable resetting high-crest mode is
  corrected, expert tools issue exactly one command, and invalid expert commands
  are rejected before hardware access.
- All four Markdown manuals have sequential source page boundaries, matching
  hashes and at least 95% nonempty pages (originals include blank pages).
  Search, pagination, page bounds and path-traversal rejection were tested.
- Actual stdio MCP handshake discovers **17 tools, 3 static resources and manual
  resource templates**. Manual search, page reads, full-text and page resources
  were fetched through a real MCP client. No runtime internet or PDF reader needed.
- The bench client used serial identity checking, automatic CH340 port
  discovery, GPIB 30, and a 900-second tool timeout.

## Standalone publication checks

- 50 tests passed with locally imported manuals; 49 passed and one manual-corpus
  test was skipped before import, matching a fresh public checkout.
- All four manuals were fetched and converted successfully by the public importer.
- The stable launcher passed a real stdio handshake with 17 tools and all manual
  resources. Python, dependencies, manuals and demo data reside inside the checkout.
- No symlink resolves outside the project directory. Public archives exclude
  generated manufacturer texts, environments, caches and local bench data.

## Live E4433B tests

After reconnection, the instrument responds as:
`Hewlett-Packard, ESG-D4000B, SERIAL_REDACTED, B.03.86`.
Options: 1E5, UN8, UN9, UND. AR488 0.55.22 at `/dev/cu.usbserial-210`.
This successful session supersedes the earlier disconnected-instrument failure.

- Status and waveform catalog succeeded through the MCP.
- Analog AM configuration at 750 kHz, −10 dBm setting, 1 kHz rate was read back;
  depth was changed from 50% to 30%, with no instrument errors.
- The MCP uploaded `test-one-two.wav` as `VOICE_T12`: 38,552 samples at 16 kHz,
  approximately 2.4095 seconds, 50% encoded peak depth. Both 77,104-byte I/Q
  planes were read back and matched exactly. Raw local logs are not published.
- Existing-waveform playback restored internal I/Q and clock, continuous mode,
  master modulation, ALC off, no competing analog modulation, no burst/blanking,
  neutral offsets, and 750 kHz / −10 dBm settings.
- A real firmware side effect was found: `RAD:ARB ON` re-enabled high-crest mode.
  The driver now disables it after ARB enable and verifies the final state. The
  updated profile passed on hardware; verified by full readback.
- Expert `scpi_query("FREQ?")` and `scpi_write("DM:EXT:HICR:STAT OFF")` were
  exercised through the updated stdio server, followed by an empty error queue.
- Final RF-off readback succeeded and `disconnect` returned local front-panel
  control. The voice waveform and playback configuration remain in memory.

## Independent oscilloscope checks

Rigol DS1104Z, CH1 direct connection with user-confirmed external 50-ohm
termination. The scope was controlled through its MCP.

- Tone capture: 120,000 samples at approximately 10 MSa/s. FFT carrier peak
  **750,000 Hz**; fitted Hilbert-envelope AM depth **29.26%** for a 30% setting.
  Envelope fit R² = 0.99838. See `scope-tone-validation.json`, with the
  original capture filename (raw capture is not distributed). This is a bench check, not a traceable calibration.
- Voice: peak-detect acquisition at 200 ms/div showed the changing speech
  envelope over its continuous carrier, approximately 172 mV peak-to-peak.
  See `scope-voice.png`. Frequency statistics at this slow timebase can measure
  envelope/aliasing; use the fast tone capture for the carrier measurement.
- A write-plus-`*OPC?` and readback were used for scope settings because plain
  write-only calls sometimes did not apply them reliably.

The scope observations demonstrate carrier and modulation, not decoded audio
intelligibility. The original WAV and byte-exact transfer establish which audio
was loaded. Obscure commands and all option-specific manual entries have not
been individually exercised on hardware.

## Repeat a read-only connection check

First release any existing MCP connection with `disconnect`, then run:

```sh
.venv/bin/python scripts/check_mcp.py --hardware
```

This checks protocol/manual access, status and catalog; it does not enable RF,
clear errors or alter waveforms. Live configuration/upload and scope measurements
are separate tests. Newly added tools load when the MCP connection is restarted
or a new Codex session launches the server.
