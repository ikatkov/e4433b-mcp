# E4433B operating guide

This server targets an E4433B with AR488 0.55.22, GPIB address 30, USB serial
115200 baud. Actual identity: `ESG-D4000B`, firmware B.03.86. Installed options on
the verified unit: 1E5, UN8, UN9, UND. Never assume an E4438C command works here.

## First call

Use `get_status(full=True)` to see the whole signal path. Status never presets
the generator or clears errors. `read_errors` consumes and returns the error
queue. It is not possible to inspect that queue without consuming its entries.

If the serial adapter is busy, finish/disconnect the other MCP session before
trying again. Port discovery selects the sole CH340 adapter and verifies the
AR488 response, generator model, and configured serial number. Multiple CH340
devices require an explicit E4433B_PORT; never probe them by sending random SCPI.

## Restore the voice demo

1. `list_waveforms` and confirm `VOICE_T12` exists. ARBI storage is volatile:
   power-off can remove it. This tool does not automatically re-upload missing files.
2. If absent, use `upload_am_wav` with the local file
   `data/test-one-two.wav` (supply your own WAV, using its absolute path),
   name `VOICE_T12`, depth `0.5`. Upload leaves RF off and verifies the bytes.
3. `play_waveform(name="VOICE_T12", sample_rate_hz=16000,
   frequency_hz=750000, level_dbm=-10, rf_on=True)` when output is requested.
4. Use the scope MCP for electrical verification. Confirm every scope setting
   by readback: on this Rigol, write-only calls sometimes failed to take effect;
   combining the write with `;*OPC?` and reading the response worked.

This clip repeats every 2.4095 seconds. Its positive I envelope and zero Q produce
conventional AM. The analog AM menu is off because I/Q is doing the modulation.
AM Depth does not change the uploaded voice. Generate a new named waveform with
a different depth to change it. The I/Q amplitude scaling means −10 dBm on the
display is not the measured carrier power; do not claim calibrated modulation
depth or RF level from the settings alone.

`play_waveform` restores internal I/Q and internal ARB clock, 16 kHz for this
clip, continuous trigger, modulation on, normal crest mode, no burst/marker
blanking, competing modulation off, ALC off, and a one-time power search.
It leaves RF off unless `rf_on=True` was specified.

## Ordinary front-panel AM depth control

Use `configure_am_tone` for the built-in sine tone, then `set_am_depth` for
analog AM path 1. This replaces voice playback but preserves its stored samples.
The E4433B also supports external analog modulation, but this server's initial
typed tool set does not configure it. Search the original Markdown manuals and
use the expert query/write tools for unsupported features, or extend the driver.

## Errors and verification

- −420 means the instrument was asked to talk without a complete response ready.
  Avoid unsupported queries, extra reads, and incorrect message termination.
- On this unit, use `DIAG:INFO:OPT?`; the earlier `*OPT?` attempt failed.
- Upper two bits of I/Q words contain marker/internal sequencing information.
  A changed raw Q hash after playback can still have identical lower 14-bit
  audio. This was observed on the actual unit; do not overwrite the waveform
  solely because a reserved bit changed.
- The local uploader uses 96-byte chunks to stay below the adapter's parser
  limit, escapes CR/LF/ESC/+ and holds EOI until the block is complete.
- Uploads may leave partial files if interrupted. RF is left off; inspect before
  explicitly retrying with overwrite=True. No silent retries or blanket reset.
- `disconnect` returns front-panel control and frees the port without changing RF.
