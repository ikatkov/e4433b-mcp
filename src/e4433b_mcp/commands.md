# Command provenance

Primary manufacturer documents (original Agilent manuals hosted by mirrors):

- [E4400-90324, ESG Programming Guide, April 2002](https://www.testunlimited.com/pdf/an/E4400-90324.pdf).
- [E4400-90328, Dual ARB Option UND/UN5 User's and Programming Guide](https://docs.alltest.net/manual/Alltest-HP-Agilent-Keysight-E4437B-Manual.pdf).
- [ESG E44xxB User's Guide](https://maximinstruments.com/pdf_files/AGILENT_E4433B_User%27s_Guide.pdf).

| Feature | Command family | Reference |
| --- | --- | --- |
| Identity | `*IDN?` | Common commands; observed on B.03.86 |
| Installed options | `DIAG:INFO:OPT?` | Diagnostic subsystem; observed on B.03.86 |
| Frequency/mode/offset/reference | `FREQ`, `FREQ:MODE`, `FREQ:OFFS`, `FREQ:MULT`, `FREQ:REF:STAT` | E4400-90324 Frequency subsystem |
| Output/level | `OUTP`, `POW`, `POW:MODE`, `POW:ATT:AUTO` | E4400-90324 Output/Power subsystems |
| ALC/power search | `POW:ALC:STAT`, `POW:ALC:SEAR`, `POW:ALC:SEAR:REF` | E4400-90324 pp. 2-52–2-53 |
| I/Q and burst | `DM:SOUR`, `DM:STAT`, `DM:IQAD:STAT`, `DM:EXT:HICR:STAT`, `BURS:STAT` | E4400-90324 pp. 2-19–2-21 |
| Analog AM | `AM:SOUR`, `AM:DEPTH`, `AM:INT:FREQ`, `AM:INT:FUNC:SHAP`, `AM:STAT` | E4400-90324 pp. 2-7–2-10 |
| Competing modulation | `AM2:STAT`, `FM1/2:STAT`, `PM1/2:STAT`, `PULM:STAT` | Corresponding E4400-90324 subsystems |
| Master modulation | `OUTP:MOD:STAT` | E4400-90324 Output subsystem |
| ARB catalog | `MMEM:CAT? "ARBI:"` | E4400-90324 pp. 2-37–2-38 |
| ARB playback/clock/trigger/filter/blanking | `RAD:ARB:*` | E4400-90328 ch. 5, Dual ARB subsystem |
| Waveform data | `MMEM:DATA "ARBI:name",#...`, separate `ARBQ:name`; `MMEM:DATA?` | E4400-90328 waveform download examples |
| Error queue | `SYST:ERR?` | E4400-90324 System subsystem |

E443xB waveform words are big-endian 16-bit containers with unsigned offset-14-bit
samples: 8192 is zero, 0 is negative full scale, 16383 positive full scale.
Bits 14–15 contain markers/sequencing. I/Q are separate files, not the newer
interleaved signed-16-bit format. See E4400-90328 p. 4-6.

The original text is included in the [Markdown manual library](manuals/README.md)
and exposed through `list_manuals`, `search_manuals`, `read_manual_pages`, and MCP
resources. For an unimplemented feature or a driver bug, use `scpi_query` or
`scpi_write` after reading the relevant passage and checking installed options.
They serialize access with normal tools, issue exactly one command, and add no
error query or RF change. Follow writes with documented readback and `read_errors`.
Binary responses require the block transport, not the expert ASCII query tool.

Live B.03.86 validation found that `RAD:ARB ON` turns high-crest mode back on.
The voice profile therefore sets `DM:EXT:HICR:STAT OFF` after enabling ARB and
verifies it in the final readback, before claiming playback restoration succeeded.
