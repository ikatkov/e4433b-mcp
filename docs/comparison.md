# Existing-project comparison — 27 September 2026

## Scope and evidence

Searched for E4433B, E4432B, Agilent ESG, and AR488 MCP implementations. No
standalone E4433B-specific MCP was identified in those searches. This is a
bounded search result, not proof that none exists.

Reviewed source, not just README feature lists:

1. **mcpyvisa 2026.2.25**, with **pyvisa-ar488 2026.2.25**: downloaded the published
   source distributions from PyPI, inspected instrument manager, MCP tools,
   driver registry, direct/bridge transports, VISA session code, and tests.
   [Project](https://pypi.org/project/mcpyvisa/2026.2.25/),
   [AR488 backend](https://pypi.org/project/pyvisa-ar488/2026.2.25/).
2. **GPIBUtils-NG**, Git revision
   `a74c0150184a378e728cdb8e1356bab4794d10c0`: inspected MCP tool registry/protocol,
   E4436B and E4438C instrument definitions, E4436B driver, AR488/Prologix
   providers, project target, and repository test layout.
   [Pinned repository](https://github.com/TGoodhew/GPIBUtils-NG/tree/a74c0150184a378e728cdb8e1356bab4794d10c0).

These alternatives were not installed against the user's instrument. Findings
below distinguish source inspection from live bench validation.

## Comparison

| Requirement | mcpyvisa + pyvisa-ar488 | GPIBUtils-NG | This implementation |
| --- | --- | --- | --- |
| Local Mac deployment | Python, stdio, no need for Windows UI | MCP project targets .NET Framework `net472` | Python, local stdio, same SDK release as working scope server |
| AR488 transport | Implemented serial/TCP backend | AR488 **and Prologix providers are stubs**, `IsAvailable=false`, `Open` throws | Uses the bench-tested AR488 0.55.22 connection |
| E4433B-specific driver | Not in eight-model PyMeasure registry | E4433B appears as E4436B alias; base driver limited to identity/CW/power/output | Exact `ESG-D4000B` identity, installed UND option check, typed RF/AM/ARB methods |
| Query/write separation | Separate MCP tools; queries use VISA query | Separate generic query/write/read tools | Separate expert query/write tools; rejects `*OPT?` locally |
| Serialization | InstrumentManager holds an async lock per backend around each operation | MCP dispatcher uses sequential blocking request loop; opens sessions per operation | Thread lock around whole profiles/transfers; process lease and exclusive serial connection |
| Binary voice upload through this adapter | Published session path decodes bytes as ASCII with replacement; reads re-encode line responses | Native VISA byte capabilities exist, but no functioning AR488 transport | Raw definite-length blocks, escaped 96-byte chunks, EOS/EOI control, byte readback |
| Correct E443xB waveform format | No E4433B voice workflow located in inspected release | E4436B definition focuses on UN8/202; E4438C is a different generation | Separate ARBI/ARBQ, big-endian offset-14-bit, marker/sequencer bit awareness |
| Recover front-panel changes | Agent must assemble model commands or add a driver | Generic tools/database require agent orchestration | One playback profile restores I/Q, clock, trigger, offsets, crest mode, ALC, competing paths and blanking |
| Documentation for the next agent | Resources/prompts explain generic SCPI and adapter use | Instrument database includes command provenance and examples | Concise MCP resources plus exact manufacturer references and hardware caveats |
| Broader bench capabilities | Multiple backends, many instruments, PyMeasure integration | Large instrument DB, provider abstraction, SRQ handling, HP-GL capture, simulations | Deliberately limited to this generator; separate existing MCP handles scope |

## Specific source findings

### mcpyvisa / pyvisa-ar488

- `mcpyvisa/instrument_manager.py`: `query` and `write` acquire the backend's
  `asyncio.Lock` and use `asyncio.to_thread`. This is a useful pattern; our
  lock covers complete multi-command operations as well as individual calls.
- `mcpyvisa/pymeasure_registry.py`: the eight mapped drivers are HP 33120A,
  34401A, 3478A, 8657B, Agilent 4284A, and Keithley 2000, 2400, 6517B.
  No E4433B driver is mapped. Generic SCPI access would still be usable for
  ordinary ASCII commands after validating adapter initialization.
- `pyvisa_ar488/sessions.py`, `AR488InstrSession.write`: binary input is
  decoded with ASCII and replacement. `read` receives a string, adds a newline,
  and encodes it as ASCII. This cannot preserve arbitrary waveform bytes.
  It is a concrete blocker for using that release unchanged for voice upload.
- `pyvisa_ar488/direct_transport.py`: initializes with a 0.5-second startup wait
  and line-oriented commands/reads. Our Nano required a longer startup wait;
  our binary upload also needs specific parser pacing and EOI behavior.
- `pyvisa_ar488/bridge_transport.py` has useful explicit handling of pending
  commands and atomic query dispatch through a shared bridge, but still exposes
  a string-oriented interface. That is not the same as a binary-safe AR488
  transfer path.

**Reuse decision:** good candidate for a future multi-instrument bench server.
For this task, a wrapper alone would not fix binary transfers: the underlying
backend would need extension and an E4433B driver would still be required.
The smaller existing, bench-tested transport is the better immediate base.

### GPIBUtils-NG

- [Ar488GpibProvider.cs](https://github.com/TGoodhew/GPIBUtils-NG/blob/a74c0150184a378e728cdb8e1356bab4794d10c0/src/GpibUtils.Visa/Providers/Ar488GpibProvider.cs)
  explicitly implements availability as false and throws on `Open`.
  [PrologixGpibProvider.cs](https://github.com/TGoodhew/GPIBUtils-NG/blob/a74c0150184a378e728cdb8e1356bab4794d10c0/src/GpibUtils.Visa/Providers/PrologixGpibProvider.cs)
  does the same. Provider names in a feature list therefore do not establish a
  working connection for this bench.
- [E4436B definition](https://github.com/TGoodhew/GPIBUtils-NG/blob/a74c0150184a378e728cdb8e1356bab4794d10c0/src/GpibUtils.Mcp/data/instruments/E4436B.json)
  includes E4433B in aliases. It explicitly documents missing base-instrument
  SCPI references in that project's manual library. Its identity regex matches
  `E443[0-9]B`, which does not directly match our unit's actual `ESG-D4000B` response.
- [AgilentE4436B.cs](https://github.com/TGoodhew/GPIBUtils-NG/blob/a74c0150184a378e728cdb8e1356bab4794d10c0/src/GpibUtils.Instruments.SignalSources/AgilentE4436B.cs)
  implements basic CW controls and says its mnemonics were carried over from
  the E4438C and require bench confirmation. Its initialization clears/resets
  the instrument; our status/connect path deliberately preserves settings.
- [GpibTools.cs](https://github.com/TGoodhew/GPIBUtils-NG/blob/a74c0150184a378e728cdb8e1356bab4794d10c0/src/GpibUtils.Mcp/Tools/GpibTools.cs)
  exposes generic query/write/read and instrument-database tools. The database
  is useful context, but is not itself a complete, typed E4433B voice workflow.
- The project has MCP/database tests and broader simulation work. That is
  valuable architecture, but does not establish physical E4433B/AR488 validation.

**Reuse decision:** adopt the idea of explicit model metadata and command
provenance. Do not port the .NET suite or treat the E4438C definitions as a
verified E4433B driver. For a future VISA-based Windows bench, reassess it.

## Resulting design

Use Python + the official MCP SDK, a small AR488 transport, and a typed E4433B
driver. Keep the transport separate so a real VISA backend can be added later.
Provide MCP resources for operating notes and searchable local Markdown manuals for new
features, then record exact commands and verify them. Future agents should call
tools rather than reconstruct the transport and modulation setup each time.

No third-party implementation code was copied into this server. The comparison
informed the design and uncovered compatibility gaps that README-only research
would have missed.
